import { parseArgs } from 'node:util';
import { resolve } from 'node:path';
import { Store } from './store.mjs';
import { TaskState } from './state.mjs';
import { scan } from './indexer.mjs';
import { buildContext } from './context.mjs';
import { runAgent } from './agent.mjs';
import { runTests, testSummary } from './testing.mjs';
import { ROOT, readJson, jsonFile, taskCheck } from './util.mjs';

const { values, positionals } = parseArgs({ allowPositionals: true, options: {
  project: { type: 'string', default: resolve(ROOT, 'sample') }, task: { type: 'string' },
  out: { type: 'string' }, db: { type: 'string' }, namespace: { type: 'string', default: 'sdd-demo' },
  state: { type: 'string' }, trace: { type: 'string' },
} });
const command = positionals[0];
if (!['import', 'context', 'state', 'checkpoint', 'agent', 'test'].includes(command)) {
  console.log('Usage: node src/cli.mjs import|context|state|checkpoint|agent|test [--project DIR] [--task FILE] [--db DIR] [--namespace ID] [--out FILE] [--trace FILE] [--state JSON_FILE]');
  process.exit(command ? 1 : 0);
}
const projectRoot = resolve(values.project);
const memory = new TaskState({ namespace: values.namespace });
let store;
try {
  const snapshot = await scan(projectRoot);
  const task = taskCheck(await readJson(values.task ?? resolve(projectRoot, 'task.json')));
  let result;
  if (command === 'import' || command === 'context' || command === 'agent') store = await new Store({ path: values.db }).open();
  if (command === 'import') result = await store.import(snapshot);
  if (command === 'context') result = await buildContext(store, memory, projectRoot, task);
  if (command === 'state') result = await memory.load(snapshot.project, task.id);
  if (command === 'checkpoint') {
    if (!values.state) throw new Error('checkpoint requires --state FILE');
    const changes = await readJson(values.state);
    if (!Array.isArray(changes.completed) || !Array.isArray(changes.pending) || !Array.isArray(changes.validations)) throw new Error('State needs completed, pending and validations arrays');
    result = await memory.save(snapshot.project, task.id, changes);
  }
  if (command === 'agent') {
    const context = await buildContext(store, memory, projectRoot, task);
    const output = resolve(values.out ?? resolve(ROOT, '.runtime/agent-' + Date.now()));
    await jsonFile(resolve(output, 'context.json'), context);
    result = await runAgent(context, projectRoot, output);
    await memory.save(snapshot.project, task.id, { completed: ['import sources', 'generate context', 'MiniMax code modification'],
      pending: ['reimport changed code', 'run tests'], model_result: result });
  }
  if (command === 'test') {
    const target = await runTests(projectRoot, task.target_tests);
    const regression = await runTests(projectRoot, task.regression_tests);
    result = { target, regression, passed: target.exit_code === 0 && regression.exit_code === 0 };
    await memory.save(snapshot.project, task.id, {
      completed: result.passed ? ['implementation verified'] : ['tests executed'], pending: result.passed ? [] : ['fix failing tests'],
      validations: [{ target: testSummary(target), regression: testSummary(regression), passed: result.passed }],
      validated_fingerprint: result.passed ? snapshot.fingerprint : null });
    if (!result.passed) process.exitCode = 1;
  }
  if (values.out && command !== 'agent') await jsonFile(resolve(values.out), result);
  console.log(JSON.stringify(result, null, 2));
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
} finally {
  if (values.trace) await jsonFile(resolve(values.trace), { database: store?.trace ?? [], powercontext: memory.trace });
  await store?.close();
}
