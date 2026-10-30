import test from 'node:test';
import assert from 'node:assert/strict';
import { prepareSource, splitText } from '../shared/text';
import { quality, median } from '../shared/metrics';
import { importSchema, searchSchema, nameSchema } from '../server/validation';
import { MODEL_KEY } from '../shared/config';
import { SerialQueue } from '../server/store';

test('overlapping Unicode chunks preserve every character and stay bounded', () => {
  const text = '😀这是中文。'.repeat(100);
  const chunks = splitText(text);
  assert.ok(chunks.length > 1);
  for (const c of chunks) { assert.ok(Array.from(c).length <= 180); assert.ok(!c.includes('\uFFFD')); }
  let rebuilt = chunks[0];
  for (const c of chunks.slice(1)) rebuilt += Array.from(c).slice(30).join('');
  assert.equal(rebuilt, text);
  assert.throws(() => splitText(text, 20, 20));
});
test('content IDs are stable, and changed content gets a new source', async () => {
  const a = await prepareSource('a.txt', '正文\r\n第二段');
  const b = await prepareSource('a.txt', '正文\n第二段');
  const c = await prepareSource('a.txt', '正文\n新内容');
  assert.deepEqual(a, b); assert.notEqual(a.source.id, c.source.id);
  await assert.rejects(prepareSource('empty', ' '));
});
test('document-level Recall and nDCG do not reward duplicate chunks', () => {
  assert.deepEqual(quality(['a', 'a', 'b'], ['a', 'b'], 2), { recall: 1, ndcg: 1 });
  assert.equal(quality(['x', 'a'], ['a'], 1).recall, 0);
  assert.equal(quality(['x', 'a'], ['a'], 2).ndcg, 1 / Math.log2(3));
  assert.equal(median([100, 1, 4, 2]), 3); assert.equal(median([]), null);
});
test('API rejects missing, non-finite, zero and wrong-dimension vectors and incompatible model', () => {
  const valid = Array(512).fill(0); valid[0] = 1;
  const body = { text: '测试', modelKey: MODEL_KEY, vector: valid };
  assert.ok(searchSchema.safeParse(body).success);
  for (const vector of [undefined, [1], Array(512).fill(0), valid.map((v, i) => i ? v : NaN)])
    assert.ok(!searchSchema.safeParse({ ...body, vector }).success);
  assert.ok(!searchSchema.safeParse({ ...body, modelKey: 'other' }).success);
  assert.ok(!searchSchema.safeParse({ ...body, k: 200 }).success);
  assert.ok(!importSchema.safeParse({ modelKey: MODEL_KEY, chunks: [] }).success);
  assert.ok(!nameSchema.safeParse('kb_a; DROP TABLE x').success);
});
test('shared SDK connection operations cannot interleave, even after failure', async () => {
  const queue = new SerialQueue(), order: number[] = [];
  const first = queue.run(async () => { order.push(1); await new Promise(resolve => setTimeout(resolve, 20)); order.push(2); throw new Error('expected'); });
  const second = queue.run(async () => { order.push(3); return 42; });
  await assert.rejects(first); assert.equal(await second, 42); assert.deepEqual(order, [1, 2, 3]);
});
