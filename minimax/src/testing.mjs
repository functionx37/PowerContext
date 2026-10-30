import { spawnSync } from 'node:child_process';
import { resolve } from 'node:path';
import { scan } from './indexer.mjs';
import { hash, sourcePath } from './util.mjs';
import { readFile } from 'node:fs/promises';

export function testSummary(result) {
  const { log, ...metadata } = result;
  return { ...metadata, log_sha256: hash(log) };
}

export async function runTests(projectRoot, files) {
  for (const file of files) await sourcePath(projectRoot, file);
  const snapshot = await scan(projectRoot);
  const args = ['--test', '--test-reporter=tap', ...files];
  const result = spawnSync(process.execPath, args, { cwd: projectRoot, encoding: 'utf8', timeout: 30000 });
  if (result.error || result.status === null) throw new Error('Test process could not run: ' + result.error?.message);
  const log = result.stdout + result.stderr;
  const passed = Number(/^# pass (\d+)/m.exec(log)?.[1]);
  const failed = Number(/^# fail (\d+)/m.exec(log)?.[1]);
  const skipped = Number(/^# skipped (\d+)/m.exec(log)?.[1]);
  return { command: ['node', ...args], code_version: snapshot.fingerprint, test_files: await Promise.all(files.map(async path =>
    ({ path, sha256: hash(await readFile(resolve(projectRoot, path))) }))), exit_code: result.status,
    passed, failed, skipped, log, at: new Date().toISOString() };
}
