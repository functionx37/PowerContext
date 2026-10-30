import 'dotenv/config';
import express from 'express';
import { resolve } from 'node:path';
import { z, ZodError } from 'zod';
import { Store } from './store';
import { importSchema, searchSchema } from './validation';
import { MODEL, MODEL_KEY } from '../shared/config';
import { Console } from 'node:console';
import { createWriteStream, mkdirSync } from 'node:fs';

const announce = console.log.bind(console);
// The upstream Windows embedded engine redirects/closes process descriptors.
// Keep Vite's later HMR logs away from those descriptors; otherwise a source
// update can raise an unhandled EBADF and stop the HTTP server.
if (process.platform === 'win32' && (process.env.SEEKDB_MODE ?? 'embedded') === 'embedded') {
  mkdirSync('.data', { recursive: true });
  const output = createWriteStream('.data/application.log', { flags: 'a' });
  globalThis.console = new Console({ stdout: output, stderr: output });
  for (const stream of [process.stdout, process.stderr]) stream.on('error', error => {
    const code = (error as NodeJS.ErrnoException).code;
    if (code !== 'EBADF' && code !== 'EPIPE') throw error;
  });
}

const app = express();
app.disable('x-powered-by');
app.use(express.json({ limit: '12mb' }));
// Only same-origin browser calls may mutate this loopback personal service.
app.use('/api', (req, res, next) => {
  if (req.headers['sec-fetch-site'] === 'cross-site') return res.status(403).json({ error: '仅允许同源请求' });
  const origin = req.headers.origin;
  if (origin && origin !== `http://${req.headers.host}` && origin !== `https://${req.headers.host}`)
    return res.status(403).json({ error: '不允许跨来源请求' });
  res.setHeader('Cache-Control', 'no-store');
  next();
});
let store: Store | undefined;
let initError = '';
let initializing: Promise<void> | undefined;
async function connect() {
  if (initializing) return initializing;
  initializing = (async () => {
    try { const next = new Store(); await next.init(); store = next; initError = ''; }
    catch (e) { initError = e instanceof Error ? e.message : String(e); }
  })().finally(() => { initializing = undefined; });
  return initializing;
}
function db() {
  if (!store) throw Object.assign(new Error(`seekdb 未连接：${initError || '正在连接'}。检查 .env；可使用 Docker server 方案。`), { status: 503 });
  return store;
}
app.get('/api/health', (_req, res) => res.json({ ready: !!store, error: initError,
  database: store ? { mode: store.mode, version: store.version } : null, model: MODEL, modelKey: MODEL_KEY }));
app.post('/api/reconnect', async (_req, res) => { if (!store) await connect(); res.json({ ready: !!store, error: initError }); });
app.get('/api/collections', async (_req, res) => { const s = db(); res.json(await s.queue.run(() => s.list())); });
app.post('/api/collections', async (req, res) => {
  const { title } = z.object({ title: z.string().trim().min(1).max(80) }).parse(req.body);
  const s = db(); const name = `kb_${crypto.randomUUID().replaceAll('-', '')}`;
  res.status(201).json(await s.queue.run(() => s.create(name, title)));
});
app.post('/api/collections/:name/chunks', async (req, res) => {
  const body = importSchema.parse(req.body), s = db(), started = performance.now();
  const result = await s.queue.run(() => s.write(req.params.name, body));
  res.json({ ...result, writeMs: performance.now() - started });
});
app.post('/api/collections/:name/refresh', async (req, res) => {
  const s = db(), started = performance.now();
  res.json({ ...await s.queue.run(() => s.refresh(req.params.name)), refreshMs: performance.now() - started });
});
app.post('/api/collections/:name/search', async (req, res) => {
  const body = searchSchema.parse(req.body), s = db(), started = performance.now();
  const hits = await s.queue.run(() => s.search(req.params.name, body));
  res.json({ hits, searchMs: performance.now() - started, mode: body.mode });
});
app.get('/api/collections/:name/sources/:id', async (req, res) => {
  const s = db(); res.json(await s.queue.run(() => s.source(req.params.name, req.params.id)));
});
app.delete('/api/collections/:name', async (req, res) => {
  const s = db(); await s.queue.run(() => s.remove(req.params.name)); res.status(204).end();
});
app.use('/api', (_req, res) => res.status(404).json({ error: '接口不存在' }));
app.use((error: Error & { status?: number; type?: string }, _req: express.Request, res: express.Response, _next: express.NextFunction) => {
  res.status(error instanceof ZodError ? 400 : error.status ?? 500).json({
    error: error instanceof ZodError ? error.issues.map(i => `${i.path.join('.')}: ${i.message}`).join('; ') : error.message,
  });
});
if (process.argv.includes('--production')) {
  app.use(express.static(resolve('dist')));
  app.get('/{*path}', (_req, res) => res.sendFile(resolve('dist/index.html')));
} else {
  const { createServer } = await import('vite');
  const vite = await createServer({ server: { middlewareMode: true }, appType: 'spa' });
  app.use(vite.middlewares);
}
const port = Number(process.env.PORT ?? 3000);
const server = app.listen(port, process.env.HOST ?? '127.0.0.1', () => {
  announce(`知屿 Local: http://localhost:${port}`);
  void connect();
});
async function shutdown() { server.close(); if (store) await store.queue.run(() => store!.close()); process.exit(0); }
process.on('SIGINT', shutdown); process.on('SIGTERM', shutdown);
