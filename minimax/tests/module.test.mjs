import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdir, mkdtemp, cp, writeFile, readFile, rm } from 'node:fs/promises';
import { resolve } from 'node:path';
import { ROOT, sourcePath, taskCheck, readJson } from '../src/util.mjs';
import { scan } from '../src/indexer.mjs';
import { parseProposal } from '../src/agent.mjs';
import { buildContext } from '../src/context.mjs';

test('source traversal and absolute paths are rejected', async () => {
  await assert.rejects(sourcePath(resolve(ROOT, 'sample'), '../package.json'), /escapes/);
  await assert.rejects(sourcePath(resolve(ROOT, 'sample'), resolve(ROOT, 'package.json')), /relative/);
});
test('agent refuses test edits and duplicate edits', () => {
  assert.throws(() => parseProposal(JSON.stringify({ summary: 'x', files: [{ path: 'tests/a.mjs', content: 'x' }] }), ['src/a.mjs']), /invalid file/);
  assert.throws(() => parseProposal(JSON.stringify({ summary: 'x', files: [{ path: 'src/a.mjs', content: 'x' }, { path: 'src/a.mjs', content: 'y' }] }), ['src/a.mjs']), /invalid file/);
});
test('task query shape is validated before database access', () => {
  assert.throws(() => taskCheck({ id: 'x' }), /description/);
});
test('source hashes and line ranges follow actual spec changes', async () => {
  await mkdir(resolve(ROOT, '.runtime'), { recursive: true });
  const dir = await mkdtemp(resolve(ROOT, '.runtime/unit-'));
  try {
    await cp(resolve(ROOT, 'sample'), dir, { recursive: true });
    const before = await scan(dir);
    const path = resolve(dir, 'specs/tickets.md');
    await writeFile(path, (await readFile(path, 'utf8')).replace('默认排除', '现在必须默认排除'));
    const after = await scan(dir);
    assert.notEqual(before.fingerprint, after.fingerprint);
    const doc = after.docs.find(d => d.spec_id === 'R-001');
    const lines = (await readFile(path, 'utf8')).split('\n');
    assert.equal(doc.body, lines.slice(doc.start_line - 1, doc.end_line).join('\n'));
    assert.ok(doc.body.includes('现在必须默认排除'));
  } finally { await rm(dir, { recursive: true, force: true }); }
});
test('context refuses stale imports and absent required sources', async () => {
  const project = resolve(ROOT, 'sample');
  const snapshot = await scan(project);
  const task = await readJson(resolve(project, 'task.json'));
  await assert.rejects(buildContext({ active: async () => ({ fingerprint: 'old' }) }, {}, project, task), /Sources changed/);
  await assert.rejects(buildContext({ active: async () => ({ fingerprint: snapshot.fingerprint }), retrieve: async () => [] }, {}, project, task), /Missing required/);
});
