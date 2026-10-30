import { scan } from './indexer.mjs';
import { taskCheck } from './util.mjs';

export async function buildContext(store, memory, projectRoot, task) {
  taskCheck(task);
  const current = await scan(projectRoot);
  const active = await store.active(current.project);
  if (!active) throw new Error('Project has not been imported. Run import first.');
  if (active.fingerprint !== current.fingerprint) throw new Error('Sources changed. Reimport before generating context.');
  const sources = await store.retrieve(active.import_id, task);
  const found = new Set(sources.map(s => s.source_id));
  const missing = task.required_sources.filter(id => !found.has(id));
  if (missing.length) throw new Error('Missing required context sources: ' + missing.join(', '));
  const progress = await memory.load(current.project, task.id);
  const validationCurrent = progress.state.validated_fingerprint === current.fingerprint;
  return { schema: 'sdd-context-v1', project: current.project, task, corpus: active,
    database: { engine: store.version, selection: 'SQL spec IDs + symbol relations + literal keyword matching' },
    sources, progress: { ...progress, validation_current: validationCurrent },
    next_action: validationCurrent && progress.state.pending.length === 0 ? 'Review recorded successful validation' :
      progress.state.revision ? 'Resume pending work; rerun validation when source fingerprint changed' : 'Implement task, then run target and regression tests' };
}
