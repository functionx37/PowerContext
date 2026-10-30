import { Embedder } from './embedding';
import { api } from './api';
import { corpus, queries } from '../shared/corpus';
import { prepareSource, sha256 } from '../shared/text';
import { quality, median } from '../shared/metrics';
import { MODEL, MODEL_KEY, type Backend, type DType, type CollectionInfo } from '../shared/config';

export const experiments: { label: string; backend: Backend; dtype: DType; batch: number; refreshEveryBatch: boolean }[] = [
  { label: 'FP32 · WASM · 逐条', backend: 'wasm', dtype: 'fp32', batch: 1, refreshEveryBatch: true },
  { label: 'FP32 · WASM · 批量', backend: 'wasm', dtype: 'fp32', batch: 8, refreshEveryBatch: false },
  { label: 'INT8 · WASM · 批量', backend: 'wasm', dtype: 'q8', batch: 8, refreshEveryBatch: false },
  { label: 'FP16 · WebGPU · 批量', backend: 'webgpu', dtype: 'fp16', batch: 8, refreshEveryBatch: false },
];
export async function benchmark(options: {
  onProgress: (message: string, percent: number) => void;
  onStatus: (message: any) => void;
  cancelled: () => boolean;
  onPartial: (report: any) => void;
}) {
  const health = await api('/health');
  if (!health.ready) throw new Error('seekdb 尚未连接，无法进行真实评测');
  const modelManifest = await fetch('/models/manifest.json').then(r => r.ok ? r.json() : null);
  const dataset = await Promise.all(corpus.map(s => prepareSource(s.title, s.text)));
  const chunks = dataset.flatMap(s => s.chunks).sort((a, b) => a.text.length - b.text.length);
  const report: any = {
    schema: 1, measuredAt: new Date().toISOString(), userAgent: navigator.userAgent,
    hardwareConcurrency: navigator.hardwareConcurrency, deviceMemoryGB: (navigator as any).deviceMemory ?? null,
    secureContext: isSecureContext, model: MODEL, runtime: 'Transformers.js 3.8.1 / ONNX Runtime Web', database: health.database,
    corpusSha256: await sha256(JSON.stringify(corpus)), queriesSha256: await sha256(JSON.stringify(queries)),
    sourceCount: corpus.length, chunkCount: chunks.length, queryCount: queries.length, trials: 3, k: 5,
    modelManifest, notes: '本机静态权重；加载时间含缓存读取及 session 创建，不含 model:fetch 网络下载。WASM 单线程。首次推理单列；后续查询按提交至浏览器绘制回调计时。',
    configurations: [],
  };
  const check = () => { if (options.cancelled()) throw new Error('评测已取消；已完成的原始记录可以导出'); };
  for (let ci = 0; ci < experiments.length; ci++) {
    check(); const config = experiments[ci];
    const record: any = { ...config, status: 'running', imports: [], queries: [] };
    report.configurations.push(record);
    const engine = new Embedder(options.onStatus);
    let collection: CollectionInfo | undefined;
    try {
      options.onProgress(`加载 ${config.label}`, ci / experiments.length * 100);
      const load = await engine.load({ backend: config.backend, dtype: config.dtype, strict: true });
      record.load = load;
      const warmupStart = performance.now(); await engine.embed(['这是首次推理，用于单独记录预热开销。']);
      record.firstInferenceMs = performance.now() - warmupStart;
      for (let trial = 0; trial < 3; trial++) {
        check();
        collection = await api<CollectionInfo>('/collections', { title: `评测 ${config.label} #${trial + 1}` });
        const route = `/collections/${collection.name}`;
        let embeddingMs = 0, writeMs = 0, refreshMs = 0;
        const importStart = performance.now();
        for (let i = 0; i < chunks.length; i += config.batch) {
          check(); const batch = chunks.slice(i, i + config.batch);
          const embedded = await engine.embed(batch.map(c => c.text)); embeddingMs += embedded.embeddingMs;
          const written = await api(`${route}/chunks`, { modelKey: MODEL_KEY,
            chunks: batch.map((c, j) => ({ ...c, vector: embedded.vectors[j] })),
            sources: i === 0 ? dataset.map(s => s.source) : [],
          });
          writeMs += written.writeMs;
          if (config.refreshEveryBatch) refreshMs += (await api(`${route}/refresh`, {})).refreshMs;
        }
        if (!config.refreshEveryBatch) refreshMs += (await api(`${route}/refresh`, {})).refreshMs;
        record.imports.push({ trial, embeddingMs, writeMs, refreshMs,
          totalMs: performance.now() - importStart, chunksPerSecond: chunks.length / embeddingMs * 1000 });
        for (let qi = 0; qi < queries.length; qi++) {
          check(); const query = queries[qi], start = performance.now();
          const embedded = await engine.embed([query.text], true);
          const found = await api(`${route}/search`, { modelKey: MODEL_KEY, text: query.text,
            vector: embedded.vectors[0], mode: 'hybrid', k: 5 });
          // Browser rendering opportunity, not just fetch completion.
          await new Promise(resolve => requestAnimationFrame(resolve));
          record.queries.push({ trial, query: query.text, firstQueryInTrial: qi === 0,
            queryEmbeddingMs: embedded.embeddingMs, searchMs: found.searchMs,
            endToEndMs: performance.now() - start, rankedTitles: found.hits.map((h: any) => h.title),
            ...quality(found.hits.map((h: any) => h.title), query.relevant, 5) });
          options.onProgress(`${config.label} · 第 ${trial + 1}/3 轮 · 查询 ${qi + 1}/${queries.length}`,
            (ci + (trial + (qi + 1) / queries.length) / 3) / experiments.length * 100);
        }
        await api(route, undefined, 'DELETE'); collection = undefined;
        options.onPartial(report);
      }
      record.status = 'complete';
      const warm = record.queries.filter((q: any) => !q.firstQueryInTrial);
      record.summary = {
        chunksPerSecond: median(record.imports.map((r: any) => r.chunksPerSecond)),
        embeddingMs: median(record.imports.map((r: any) => r.embeddingMs)),
        writeMs: median(record.imports.map((r: any) => r.writeMs)),
        refreshMs: median(record.imports.map((r: any) => r.refreshMs)),
        searchMs: median(warm.map((q: any) => q.searchMs)),
        endToEndMs: median(warm.map((q: any) => q.endToEndMs)),
        recallAt5: record.queries.reduce((s: number, q: any) => s + q.recall, 0) / record.queries.length,
        ndcgAt5: record.queries.reduce((s: number, q: any) => s + q.ndcg, 0) / record.queries.length,
      };
    } catch (e) {
      record.status = 'unavailable'; record.error = e instanceof Error ? e.message : String(e);
      if (options.cancelled()) { options.onPartial(report); throw e; }
    } finally {
      engine.dispose();
      if (collection) {
        try { await api(`/collections/${collection.name}`, undefined, 'DELETE'); }
        catch (e) { record.cleanupError = String(e); }
      }
      options.onPartial(report);
    }
  }
  options.onProgress('评测完成；不可用的后端保留错误原因', 100);
  return report;
}
