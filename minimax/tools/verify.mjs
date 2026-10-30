import assert from 'node:assert/strict';
import { cp, mkdir, readFile, writeFile, access } from 'node:fs/promises';
import { resolve } from 'node:path';
import { spawn, spawnSync } from 'node:child_process';
import { once } from 'node:events';
import { createServer } from 'node:net';
import { parseArgs } from 'node:util';
import { Store } from '../src/store.mjs';
import { TaskState } from '../src/state.mjs';
import { scan } from '../src/indexer.mjs';
import { buildContext } from '../src/context.mjs';
import { runAgent } from '../src/agent.mjs';
import { runTests, testSummary } from '../src/testing.mjs';
import { ROOT, jsonFile, readJson, hash } from '../src/util.mjs';

const { values } = parseArgs({ options: { live: { type: 'boolean', default: false }, out: { type: 'string' } } });
if (values.live && !process.env.MINIMAX_API_KEY) {
  console.error('MINIMAX_API_KEY is missing. Live verification was not started.');
  process.exit(1);
}
const runId = new Date().toISOString().replace(/[:.]/g, '-') + '-' + process.pid;
const runtime = resolve(ROOT, '.runtime', runId);
const output = resolve(values.out ?? resolve(ROOT, 'evidence', 'local-' + runId));
const project = resolve(runtime, 'project');
const serviceData = resolve(runtime, 'services');
const readyFile = resolve(runtime, 'connection.json');
const python = process.env.PC_PYTHON ?? resolve(ROOT, process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python');
const sleep = ms => new Promise(r => setTimeout(r, ms));
const report = { run_id: runId, started_at: new Date().toISOString(), live_requested: values.live,
  live_model_verified: false, competition_ready: false, checks: {}, versions: { node: process.version, platform: process.platform,
    powercontext: '1.4.1', pylibseekdb: '1.4.0.post2', seekdb_sdk: '1.4.0' } };
let services, store, memory;
const traces = [];

async function freePort() {
  const server = createServer();
  await new Promise((ok, fail) => { server.once('error', fail); server.listen(0, '127.0.0.1', ok); });
  const port = server.address().port;
  await new Promise(ok => server.close(ok));
  return port;
}
async function startServices() {
  const port = await freePort();
  services = spawn(python, ['-u', resolve(ROOT, 'tools/services.py'), '--data-dir', serviceData,
    '--ready-file', readyFile, '--port', String(port)], { cwd: ROOT, stdio: ['ignore', 'pipe', 'pipe'] });
  let log = '';
  services.stdout.on('data', b => { log += b; });
  services.stderr.on('data', b => { log += b; });
  services.on('error', e => { log += e.message; });
  for (let i = 0; i < 240; i++) {
    if (services.exitCode !== null) throw new Error('Services failed: ' + log);
    try {
      const connection = await readJson(readyFile);
      process.env.SEEKDB_CONNECTION_FILE = readyFile;
      process.env.SEEKDB_MODE = 'server';
      // This verifier always owns its fresh local services, regardless of .env settings.
      for (const name of ['SEEKDB_HOST', 'SEEKDB_PORT', 'SEEKDB_USER', 'SEEKDB_PASSWORD', 'POWERCONTEXT_TOKEN']) delete process.env[name];
      process.env.SEEKDB_DATABASE = 'sdd_context';
      process.env.POWERCONTEXT_URL = connection.powercontext_url;
      return { pid: services.pid, endpoint: connection.seekdb, powercontext_url: connection.powercontext_url };
    } catch { await sleep(250); }
  }
  throw new Error('Services startup timed out: ' + log);
}
async function stopServices() {
  if (services && services.exitCode === null) {
    await writeFile(resolve(serviceData, 'stop-request'), '');
    await Promise.race([once(services, 'exit'), sleep(25000).then(() => { throw new Error('Services shutdown timeout'); })]);
  }
  services = null;
}
async function openStore() { store = await new Store().open(); return store; }
async function closeStore(stage) {
  if (store) {
    traces.push({ stage, version: store.version, operations: store.trace.filter(x => /^(SELECT|REPLACE)/.test(x.query.trim())) });
    await store.close(); store = null;
  }
}
function cli(command, name) {
  const destination = resolve(output, name + '.json');
  const result = spawnSync(process.execPath, [resolve(ROOT, 'src/cli.mjs'), command,
    '--project', project, '--namespace', runId, '--out', destination,
    '--trace', resolve(output, name + '-trace.json')], { cwd: ROOT, env: process.env, encoding: 'utf8', timeout: 40000 });
  if (result.status !== 0) throw new Error(`CLI ${command} failed: ${result.stderr || result.error || result.stdout}`);
  return readJson(destination);
}
async function saveTest(name, value) {
  await jsonFile(resolve(output, name + '.json'), value);
  await writeFile(resolve(output, name + '.log'), '$ ' + value.command.join(' ') + '\ncode_version=' + value.code_version +
    '\nexit_code=' + value.exit_code + '\n' + value.log, 'utf8');
}

try {
  await access(python);
  await mkdir(output, { recursive: true });
  await cp(resolve(ROOT, 'sample'), project, { recursive: true });
  const baseline = await readFile(resolve(ROOT, 'evidence/before/tickets.mjs'), 'utf8');
  const delivered = await readFile(resolve(ROOT, 'sample/src/tickets.mjs'), 'utf8');
  await writeFile(resolve(project, 'src/tickets.mjs'), baseline);
  const task = await readJson(resolve(project, 'task.json'));
  console.log('Checking unchanged tests against baseline...');
  const beforeTarget = await runTests(project, task.target_tests);
  const beforeRegression = await runTests(project, task.regression_tests);
  await saveTest('before-target', beforeTarget); await saveTest('before-regression', beforeRegression);
  assert.notEqual(beforeTarget.exit_code, 0);
  assert.ok(beforeTarget.failed > 0 && beforeTarget.passed > 0 && beforeTarget.skipped === 0);
  assert.match(beforeTarget.log, /ERR_ASSERTION/);
  assert.doesNotMatch(beforeTarget.log, /ERR_MODULE_NOT_FOUND|SyntaxError|Cannot find module/);
  assert.equal(beforeRegression.exit_code, 0);
  report.checks.baseline_functional_failure = true;
  report.service_first = await startServices();
  console.log('Importing sources and retrieving real seekdb context...');
  memory = new TaskState({ namespace: runId });
  await openStore();
  const initial = await scan(project);
  report.versions.database = store.version;
  report.initial_import = await store.import(initial);
  const initialContext = await buildContext(store, memory, project, task);
  assert.equal(initialContext.progress.state.revision, 0);
  assert.equal(initialContext.progress.recalled, 0);
  assert.deepEqual(task.required_sources.filter(id => !initialContext.sources.some(s => s.source_id === id)), []);
  await jsonFile(resolve(output, 'context-before.json'), initialContext);
  const checkpoint = await memory.save(initial.project, task.id, {
    completed: ['sources imported', 'context retrieved', 'baseline tests executed'],
    pending: ['implement archive filter', 'run unchanged target and regression tests'],
    validations: [{ stage: 'before', target: testSummary(beforeTarget), regression: testSummary(beforeRegression) }],
    input_fingerprint: initial.fingerprint,
  });
  await closeStore('baseline-context');
  const resumed = await cli('context', 'context-resumed-before');
  assert.equal(resumed.progress.state.revision, checkpoint.revision);
  assert.deepEqual(resumed.progress.state.pending, checkpoint.pending);
  assert.match(resumed.next_action, /Resume/);
  if (values.live) {
    console.log('Requesting real MiniMax modification...');
    report.agent = await runAgent(resumed, project, resolve(output, 'minimax'));
    report.live_model_verified = report.agent.live_model_verified;
    report.implementation_author = 'MiniMax API';
  } else {
    await writeFile(resolve(project, 'src/tickets.mjs'), delivered);
    report.implementation_author = 'Codex reference implementation; no MiniMax API call';
  }
  const after = await readFile(resolve(project, 'src/tickets.mjs'), 'utf8');
  assert.notEqual(hash(baseline), hash(after));
  await writeFile(resolve(output, 'before.mjs'), baseline);
  await writeFile(resolve(output, 'after.mjs'), after);
  const diff = spawnSync('git', ['diff', '--no-index', '--no-prefix', '--', resolve(output, 'before.mjs'), resolve(output, 'after.mjs')], { encoding: 'utf8' });
  assert.equal(diff.status, 1, 'git diff should report a code change');
  await writeFile(resolve(output, 'change.diff'), diff.stdout
    .replace(/^diff --git .*$/m, 'diff --git a/sample/src/tickets.mjs b/sample/src/tickets.mjs')
    .replace(/^--- .*$/m, '--- a/sample/src/tickets.mjs').replace(/^\+\+\+ .*$/m, '+++ b/sample/src/tickets.mjs'));
  console.log('Running target and regression tests after the change...');
  const target = await runTests(project, task.target_tests);
  const regression = await runTests(project, task.regression_tests);
  await saveTest('after-target', target); await saveTest('after-regression', regression);
  assert.equal(target.exit_code, 0); assert.equal(regression.exit_code, 0);
  assert.equal(target.skipped + regression.skipped, 0);
  assert.deepEqual(target.test_files, beforeTarget.test_files);
  assert.deepEqual(regression.test_files, beforeRegression.test_files);
  report.checks.same_tests_before_after = true;
  report.tests = { before: { target: { passed: beforeTarget.passed, failed: beforeTarget.failed }, regression: { passed: beforeRegression.passed } },
    after: { target: { passed: target.passed, failed: target.failed }, regression: { passed: regression.passed, failed: regression.failed } } };
  report.checks.effective_code_change = true;
  await openStore();
  const final = await scan(project);
  await store.import(final);
  await memory.save(final.project, task.id, { completed: ['sources imported', 'context retrieved', 'code modified', 'target and regression passed'],
    pending: [], validations: [{ stage: 'after', target: testSummary(target), regression: testSummary(regression) }], validated_fingerprint: final.fingerprint,
    implementation_author: report.implementation_author });
  await closeStore('after-context');
  await jsonFile(resolve(output, 'powercontext-trace.json'), memory.trace);
  console.log('Restarting both services and context process...');
  await stopServices();
  report.service_restarted = await startServices();
  assert.notEqual(report.service_first.pid, report.service_restarted.pid);
  const recovered = await cli('context', 'context-recovered');
  assert.equal(recovered.progress.recalled, 2);
  assert.equal(recovered.progress.state.revision, 2);
  assert.equal(recovered.progress.validation_current, true);
  assert.deepEqual(recovered.progress.state.pending, []);
  assert.match(recovered.next_action, /successful validation/);
  assert.ok(recovered.progress.state.memory_ref);
  report.checks.state_reused_after_restart = true;
  console.log('Verifying spec reimport and stale-context detection...');
  const specPath = resolve(project, 'specs/tickets.md');
  const oldSpec = await readFile(specPath, 'utf8');
  const clause = '规格更新校验：includeArchived 不改变 status 的错误校验，非法状态仍抛出 RangeError。';
  await writeFile(specPath, oldSpec.replace('## R-002', clause + '\n\n## R-002'));
  await openStore();
  const restartedMemory = new TaskState({ namespace: runId });
  await assert.rejects(buildContext(store, restartedMemory, project, task), /Sources changed/);
  await store.import(await scan(project));
  const updated = await buildContext(store, restartedMemory, project, task);
  assert.ok(updated.sources.find(s => s.spec_id === 'R-001').body.includes(clause));
  assert.notEqual(updated.corpus.import_id, recovered.corpus.import_id);
  assert.equal(updated.progress.validation_current, false);
  await jsonFile(resolve(output, 'context-spec-updated.json'), updated);
  report.checks.context_correct_and_spec_reimported = true;
  report.checks.database_used = traces.some(t => t.operations.some(q => q.source_ids.length >= task.required_sources.length));
  assert.equal(report.checks.database_used, true);
  await closeStore('spec-updated');
  report.checks.runnable_from_empty_state = true;
  report.local_checks_passed = Object.values(report.checks).every(Boolean);
  report.competition_ready = report.local_checks_passed && report.live_model_verified;
  report.remaining = report.live_model_verified ? [] : ['Provide a MiniMax API key and run npm run verify:live; current modification is a reference implementation.'];
} catch (error) {
  report.local_checks_passed = false;
  report.error = { message: error.message, stack: error.stack };
  process.exitCode = 1;
} finally {
  await closeStore('final-cleanup');
  try { await stopServices(); } catch (error) { report.shutdown_error = error.message; process.exitCode = 1; }
  report.finished_at = new Date().toISOString();
  await jsonFile(resolve(output, 'database-trace.json'), traces);
  await jsonFile(resolve(output, 'verification.json'), report);
  console.log(JSON.stringify(report, null, 2));
  console.log('Evidence: ' + output);
}
