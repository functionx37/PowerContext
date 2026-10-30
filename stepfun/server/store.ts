import { SeekdbClient, Schema, FulltextIndexConfig, VectorIndexConfig } from 'seekdb';
import { resolve } from 'node:path';
import { mkdirSync } from 'node:fs';
import { MODEL, MODEL_KEY, type CollectionInfo } from '../shared/config';
import { importSchema, searchSchema, nameSchema } from './validation';
import type { z } from 'zod';

// One connection owns SQL session variables used by hybridSearch. Serialize ALL
// database operations, including across collections, so concurrent HTTP clients
// cannot overwrite @search_parm between GET_SQL and execution.
export class SerialQueue {
  private tail: Promise<unknown> = Promise.resolve();
  run<T>(operation: () => Promise<T>): Promise<T> {
    const next = this.tail.then(operation, operation);
    this.tail = next.catch(() => undefined);
    return next;
  }
}

export class Store {
  client: SeekdbClient;
  queue = new SerialQueue();
  version = '';
  mode = process.env.SEEKDB_MODE ?? 'embedded';
  constructor() {
    const path = resolve(process.env.SEEKDB_PATH ?? '.data/seekdb');
    if (this.mode === 'embedded') mkdirSync(path, { recursive: true });
    process.env.SEEKDB_BINDINGS_CACHE_DIR ??= resolve('.data/bindings');
    this.client = new SeekdbClient(this.mode === 'embedded'
      ? { path, database: process.env.SEEKDB_DATABASE ?? 'stepfun' }
      : { host: process.env.SEEKDB_HOST ?? '127.0.0.1', port: Number(process.env.SEEKDB_PORT ?? 2881),
          user: process.env.SEEKDB_USER ?? 'root', password: process.env.SEEKDB_PASSWORD ?? '',
          database: process.env.SEEKDB_DATABASE ?? 'stepfun', queryTimeout: 60000 });
  }
  async init() {
    // SDK 1.4 no longer auto-creates the selected database on connection.
    // Database management uses its separate administrative connection.
    const database = process.env.SEEKDB_DATABASE ?? 'stepfun';
    const databases = await this.client.listDatabases();
    if (!databases.some(d => d.name === database)) await this.client.createDatabase(database);
    const rows = await this.client.execute('SELECT VERSION() AS version');
    this.version = String(rows?.[0]?.version ?? 'unknown');
    await this.client.execute(`CREATE TABLE IF NOT EXISTS atlas_catalog (
      name VARCHAR(64) PRIMARY KEY, title VARCHAR(256) NOT NULL, model_key VARCHAR(256) NOT NULL)`);
    await this.client.execute(`CREATE TABLE IF NOT EXISTS atlas_sources (
      collection_name VARCHAR(64) NOT NULL, source_id VARCHAR(64) NOT NULL,
      title VARCHAR(256) NOT NULL, body LONGTEXT NOT NULL,
      PRIMARY KEY(collection_name, source_id))`);
  }
  async get(name: string) {
    nameSchema.parse(name);
    const row = await this.client.execute('SELECT model_key FROM atlas_catalog WHERE name = ?', [name]);
    if (!row?.length) throw Object.assign(new Error('知识库不存在，请重新选择'), { status: 404 });
    if (row[0].model_key !== MODEL_KEY) throw new Error('知识库模型版本不兼容，请创建新知识库');
    return this.client.getCollection({ name, embeddingFunction: null });
  }
  async list(): Promise<CollectionInfo[]> {
    const rows = await this.client.execute('SELECT name, title, model_key FROM atlas_catalog ORDER BY name');
    const result: CollectionInfo[] = [];
    for (const r of rows ?? []) {
      const collection = await this.client.getCollection({ name: r.name, embeddingFunction: null });
      result.push({ name: r.name, title: r.title, modelKey: r.model_key, count: Number(await collection.count()) });
    }
    return result;
  }
  async create(name: string, title: string) {
    nameSchema.parse(name);
    const collection = await this.client.createCollection({ name,
      schema: new Schema({
        fulltextIndex: new FulltextIndexConfig('ik', { ik_mode: 'smart' }),
        vectorIndex: new VectorIndexConfig({ embeddingFunction: null,
          hnsw: { dimension: MODEL.dimension, distance: 'cosine', m: 16, ef_construction: 200 } }),
      }),
    });
    try {
      await this.client.execute('INSERT INTO atlas_catalog (name, title, model_key) VALUES (?, ?, ?)', [name, title, MODEL_KEY]);
    } catch (e) { await this.client.deleteCollection(name); throw e; }
    return { name: collection.name, title, count: 0, modelKey: MODEL_KEY };
  }
  async write(name: string, input: z.infer<typeof importSchema>) {
    const collection = await this.get(name);
    for (const source of input.sources) {
      await this.client.execute('REPLACE INTO atlas_sources (collection_name, source_id, title, body) VALUES (?, ?, ?, ?)',
        [name, source.id, source.title, source.text]);
    }
    const unique = [...new Map(input.chunks.map(c => [c.id, c])).values()];
    const existing = new Set((await collection.get({ ids: unique.map(c => c.id), include: [] })).ids);
    const fresh = unique.filter(c => !existing.has(c.id));
    // SQL insert is atomic per HTTP batch. Retrying an interrupted import skips
    // already committed deterministic IDs; no per-row SDK upsert round-trips.
    if (fresh.length) await collection.add({
      ids: fresh.map(c => c.id), documents: fresh.map(c => c.text), embeddings: fresh.map(c => c.vector),
      metadatas: fresh.map(c => ({ title: c.title, sourceId: c.sourceId, chunkId: c.id, index: c.index })),
    });
    return { inserted: fresh.length, skipped: unique.length - fresh.length };
  }
  async refresh(name: string) {
    const collection = await this.get(name);
    // Do not use the SDK's version-gated best-effort no-op: old versions must
    // return an actionable failure rather than falsely report an index refresh.
    await this.client.execute('CALL dbms_index_manager.refresh()');
    return { count: Number(await collection.count()), refreshed: true };
  }
  async search(name: string, input: z.infer<typeof searchSchema>) {
    const c = await this.get(name);
    const include = ['documents', 'metadatas', 'distances'] as const;
    const candidates = Math.max(30, input.k * 4);
    const result = input.mode === 'semantic'
      ? await c.query({ queryEmbeddings: [input.vector], nResults: input.k, include })
      : await c.hybridSearch({
          query: { whereDocument: { $contains: input.keywords || input.text }, nResults: candidates },
          knn: { queryEmbeddings: [input.vector], nResults: candidates },
          rank: { rrf: { rankConstant: 60, rankWindowSize: candidates } }, nResults: input.k, include,
        });
    return result.ids[0].map((id, i) => ({ id, text: result.documents?.[0]?.[i] ?? '',
      title: String(result.metadatas?.[0]?.[i]?.title ?? ''),
      sourceId: String(result.metadatas?.[0]?.[i]?.sourceId ?? ''),
      index: Number(result.metadatas?.[0]?.[i]?.index ?? 0), value: result.distances?.[0]?.[i] ?? null }));
  }
  async source(name: string, id: string) {
    await this.get(name);
    const rows = await this.client.execute('SELECT title, body FROM atlas_sources WHERE collection_name = ? AND source_id = ?', [name, id]);
    if (!rows?.length) throw Object.assign(new Error('原文不存在'), { status: 404 });
    return { title: rows[0].title, text: rows[0].body };
  }
  async remove(name: string) {
    await this.get(name);
    await this.client.deleteCollection(name);
    await this.client.execute('DELETE FROM atlas_sources WHERE collection_name = ?', [name]);
    await this.client.execute('DELETE FROM atlas_catalog WHERE name = ?', [name]);
  }
  close() { return this.client.close(); }
}
