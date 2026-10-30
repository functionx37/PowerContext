import { SeekdbClient } from 'seekdb';
import { randomUUID } from 'node:crypto';
import { mkdir, readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { ROOT } from './util.mjs';

export class Store {
  constructor(options = {}) {
    this.trace = [];
    this.options = options;
  }
  async open() {
    const path = resolve(this.options.path ?? process.env.SEEKDB_PATH ?? resolve(ROOT, '.runtime/seekdb'));
    process.env.SEEKDB_BINDINGS_CACHE_DIR ??= resolve(ROOT, '.runtime/bindings');
    const mode = process.env.SEEKDB_MODE ?? 'server';
    let endpoint = {};
    if (mode === 'server' && !process.env.SEEKDB_HOST) {
      try {
        endpoint = JSON.parse(await readFile(process.env.SEEKDB_CONNECTION_FILE ?? resolve(ROOT, '.runtime/connection.json'), 'utf8')).seekdb;
      } catch { throw new Error('Start tools/services.py or configure SEEKDB_HOST/PORT/USER/PASSWORD'); }
    }
    const database = process.env.SEEKDB_DATABASE ?? 'sdd_context';
    if (!/^[a-zA-Z0-9_]{1,64}$/.test(database)) throw new Error('Invalid database name');
    if (!['embedded', 'server'].includes(mode)) throw new Error('SEEKDB_MODE must be embedded or server');
    if (mode === 'embedded') await mkdir(path, { recursive: true });
    const connection = mode === 'embedded' ? { path, database } : {
      host: process.env.SEEKDB_HOST ?? endpoint.host ?? '127.0.0.1', port: Number(process.env.SEEKDB_PORT ?? endpoint.port ?? 2881),
      user: process.env.SEEKDB_USER ?? endpoint.user ?? 'root', password: process.env.SEEKDB_PASSWORD ?? '', database,
      queryTimeout: 30000,
    };
    try {
      // Server mode must bootstrap through an existing database; connecting to
      // the requested database before CREATE DATABASE fails on a clean install.
      const admin = new SeekdbClient(mode === 'embedded' ? connection : { ...connection, database: 'information_schema' });
      try {
        const databases = await admin.listDatabases();
        if (!databases.some(d => d.name === database)) await admin.createDatabase(database);
      } finally { await admin.close(); }
      this.client = new SeekdbClient(connection);
      this.version = (await this.sql('SELECT VERSION() AS version'))[0].version;
      await this.sql(`CREATE TABLE IF NOT EXISTS sdd_imports (
        project VARCHAR(64) PRIMARY KEY, import_id VARCHAR(64) NOT NULL, fingerprint VARCHAR(64) NOT NULL)`);
      await this.sql(`CREATE TABLE IF NOT EXISTS sdd_documents (
        import_id VARCHAR(64) NOT NULL, source_id VARCHAR(256) NOT NULL, path VARCHAR(256) NOT NULL,
        kind VARCHAR(16) NOT NULL, spec_id VARCHAR(32) NOT NULL, symbols TEXT NOT NULL,
        start_line INT NOT NULL, end_line INT NOT NULL, body LONGTEXT NOT NULL, sha256 VARCHAR(64) NOT NULL,
        PRIMARY KEY(import_id, source_id))`);
      return this;
    } catch (e) { await this.close(); throw e; }
  }
  async sql(query, parameters = []) {
    const rows = await this.client.execute(query, parameters);
    this.trace.push({ query, parameters, row_count: Array.isArray(rows) ? rows.length : null,
      source_ids: Array.isArray(rows) ? rows.flatMap(r => r.source_id ? [r.source_id] : []) : [] });
    return rows;
  }
  async active(project) {
    const rows = await this.sql('SELECT import_id, fingerprint FROM sdd_imports WHERE project = ?', [project]);
    return rows[0] ?? null;
  }
  async import(snapshot) {
    const importId = randomUUID();
    // Stage a complete immutable generation. A single pointer write publishes it.
    // Readers never see a partially reimported corpus; old generations may be kept for audit.
    for (const d of snapshot.docs) {
      await this.sql(`INSERT INTO sdd_documents
        (import_id, source_id, path, kind, spec_id, symbols, start_line, end_line, body, sha256)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`, [importId, d.source_id, d.path, d.kind, d.spec_id,
        d.symbols, d.start_line, d.end_line, d.body, d.sha256]);
    }
    await this.sql('REPLACE INTO sdd_imports (project, import_id, fingerprint) VALUES (?, ?, ?)',
      [snapshot.project, importId, snapshot.fingerprint]);
    return { import_id: importId, fingerprint: snapshot.fingerprint, count: snapshot.docs.length };
  }
  async retrieve(importId, task) {
    const marks = task.spec_ids.map(() => '?').join(',');
    const conditions = task.symbols.map(() => 'symbols LIKE ?').concat(task.terms.map(() => 'LOWER(body) LIKE ?'));
    const escapeLike = value => value.replace(/[!%_]/g, char => '!' + char);
    // ESCAPE makes user-supplied '%' and '_' literal, rather than query wildcards.
    const predicates = conditions.map(p => p + " ESCAPE '!'").join(' OR ');
    return this.sql(`SELECT source_id, path, kind, spec_id, symbols, start_line, end_line, body, sha256
      FROM sdd_documents WHERE import_id = ? AND
      ((kind = 'spec' AND spec_id IN (${marks})) OR (kind <> 'spec' AND (${predicates})))
      ORDER BY kind, source_id`, [importId, ...task.spec_ids,
      ...task.symbols.map(s => '%|' + escapeLike(s) + '|%'), ...task.terms.map(t => '%' + escapeLike(t.toLowerCase()) + '%')]);
  }
  async close() { if (this.client) { await this.client.close(); this.client = null; } }
}
