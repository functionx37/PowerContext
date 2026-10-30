import { hash } from './util.mjs';

const KIND = 'sdd-task-v1';
const PREFIX = 'SDD task checkpoint v1\n';
export class TaskState {
  constructor({ url = process.env.POWERCONTEXT_URL ?? 'http://127.0.0.1:18800', namespace = 'sdd-demo' } = {}) {
    this.url = url.replace(/\/$/, '');
    this.namespace = namespace;
    this.trace = [];
  }
  async request(path, data) {
    const headers = { 'content-type': 'application/json' };
    if (process.env.POWERCONTEXT_TOKEN) headers.authorization = 'Bearer ' + process.env.POWERCONTEXT_TOKEN;
    const response = await fetch(this.url + path, { method: 'POST', headers, body: JSON.stringify(data), signal: AbortSignal.timeout(30000) });
    if (!response.ok) throw new Error(`PowerContext ${path}: HTTP ${response.status}`);
    const value = await response.json();
    this.trace.push({ path, request: data, response: value });
    return value;
  }
  async load(project, taskId) {
    const scope = await this.request('/v1/scopes', { title: `SDD / ${project} / ${taskId}`,
      summary: 'SDD task progress and validation snapshots; one writer per task.',
      idempotency_key: 'sdd-v1-' + hash(JSON.stringify([this.namespace, project, taskId])) });
    let cursor = null;
    const snapshots = [];
    do {
      const page = await this.request('/v1/atomic-memory/list', { scope_id: scope.scope_id, kind: KIND, states: ['active'], limit: 100, cursor });
      for (const item of page.items) {
        if (!item.text.startsWith(PREFIX)) throw new Error('Unexpected task memory format');
        const state = JSON.parse(item.text.slice(PREFIX.length));
        if (!Number.isInteger(state.revision) || state.revision < 1 || state.project !== project || state.task_id !== taskId) throw new Error('Invalid task memory');
        snapshots.push({ ...state, memory_ref: item.artifact });
      }
      cursor = page.next_cursor;
    } while (cursor);
    snapshots.sort((a, b) => a.revision - b.revision);
    if (new Set(snapshots.map(s => s.revision)).size !== snapshots.length) throw new Error('Concurrent task writes detected; use a new namespace');
    return { scope_id: scope.scope_id, state: snapshots.at(-1) ?? { project, task_id: taskId, revision: 0,
      completed: [], pending: ['import sources', 'generate context', 'modify code', 'run tests'], validations: [] }, recalled: snapshots.length };
  }
  async save(project, taskId, changes) {
    const loaded = await this.load(project, taskId);
    const state = { ...loaded.state, ...changes, project, task_id: taskId, revision: loaded.state.revision + 1,
      saved_at: new Date().toISOString() };
    delete state.memory_ref;
    const text = PREFIX + JSON.stringify(state);
    if (Buffer.byteLength(text, 'utf8') > 8192) throw new Error('Task checkpoint exceeds PowerContext 8192-byte limit; store test summaries and log hashes instead of full logs');
    const result = await this.request('/v1/memory/remember', { scope_id: loaded.scope_id, kind: KIND,
      text, reason: 'Persist task progress and test evidence for the next process.' });
    if (!result.records?.length) throw new Error('PowerContext did not return a memory artifact');
    return { ...state, memory_ref: result.records[0].artifact };
  }
}
