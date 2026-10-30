// HTTP + real seekdb integration contract. Unit vectors are test fixtures only;
// application / performance evaluation vectors always come from the browser.
import 'dotenv/config';
import assert from 'node:assert/strict';
import { writeFile } from 'node:fs/promises';
import { prepareSource } from '../shared/text';
import { MODEL_KEY } from '../shared/config';
const base = process.env.APP_URL ?? `http://localhost:${process.env.PORT ?? 3000}`;
async function request(path: string, body?: unknown, method?: string) {
  const response = await fetch(`${base}/api${path}`, { method: method ?? (body ? 'POST' : 'GET'),
    headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined });
  if (response.status === 204) return undefined;
  const data = await response.json();
  if (!response.ok) throw new Error(data.error); return data;
}
const health = await request('/health'); assert.ok(health.ready, health.error);
const owned: string[] = [];
try {
  const a = await request('/collections', { title: '可清理集成测试 A' }); owned.push(a.name);
  const b = await request('/collections', { title: '可清理集成测试 B' }); owned.push(b.name);
  const p = await prepareSource('test.txt', '索引刷新支持新写入的文档立即进行向量检索。');
  const vector = Array(512).fill(0); vector[0] = 1;
  const input = { modelKey: MODEL_KEY, chunks: p.chunks.map(c => ({ ...c, vector })), sources: [p.source] };
  assert.equal((await request(`/collections/${a.name}/chunks`, input)).inserted, 1);
  assert.equal((await request(`/collections/${a.name}/chunks`, input)).skipped, 1);
  assert.equal((await request(`/collections/${a.name}/refresh`, {})).count, 1);
  const query = { text: '索引刷新', vector, modelKey: MODEL_KEY, k: 5, mode: 'hybrid' };
  const [hitA, hitB] = await Promise.all([request(`/collections/${a.name}/search`, query), request(`/collections/${b.name}/search`, query)]);
  assert.equal(hitA.hits[0]?.id, p.chunks[0].id); assert.equal(hitB.hits.length, 0);
  assert.equal((await request(`/collections/${a.name}/sources/${p.source.id}`)).text, p.source.text);
  assert.equal((await request('/collections')).find((c: any) => c.name === a.name)?.count, 1);
  const invalid = await fetch(`${base}/api/collections/${a.name}/search`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...query, vector: [1] }),
  });
  assert.equal(invalid.status, 400);
  const report = { measuredAt: new Date().toISOString(), passed: true, database: health.database,
    checks: ['create', 'write', 'idempotency', 'refresh', 'DB hybrid search', 'concurrent collection isolation', 'original source', 'persistent catalog', 'reject invalid vector'] };
  await writeFile('reports/db-smoke.json', JSON.stringify(report, null, 2)); console.log(JSON.stringify(report, null, 2));
} finally { for (const name of owned) await request(`/collections/${name}`, undefined, 'DELETE'); }
