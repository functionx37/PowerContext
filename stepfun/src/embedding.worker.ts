import { env, pipeline, type FeatureExtractionPipeline } from '@huggingface/transformers';
import { MODEL, type Backend, type DType } from '../shared/config';

env.allowLocalModels = true;
env.allowRemoteModels = false;
env.localModelPath = '/models/';
env.useBrowserCache = true;
// Single-threaded WASM also works without cross-origin isolation. A dedicated
// worker keeps tokenization / fallback inference away from the UI thread.
if (env.backends.onnx.wasm) env.backends.onnx.wasm.numThreads = 1;
let extractor: FeatureExtractionPipeline | null = null;
let actual: { backend: 'webgpu' | 'wasm'; dtype: DType; reason: string };
let currentKey = '';
let strict = false;
function status(message: unknown) { self.postMessage({ event: 'status', ...message as object }); }

async function create(backend: 'webgpu' | 'wasm', dtype: DType) {
  // These literal device/dtype choices determine the ONNX execution provider
  // and downloaded artifact. No automatic server embedding is ever available.
  const result = await pipeline('feature-extraction', MODEL.id, {
    revision: MODEL.revision, device: backend, dtype, local_files_only: true,
    progress_callback: info => status({ progress: info }),
  });
  result.tokenizer.model_max_length = 256;
  return result;
}

async function load(options: { backend: Backend; dtype: DType; strict?: boolean; simulateNoGPU?: boolean }) {
  const key = JSON.stringify(options);
  if (extractor && key === currentKey) return { ...actual, loadMs: 0, reused: true };
  await extractor?.dispose(); extractor = null; currentKey = ''; strict = !!options.strict;
  const started = performance.now();
  let backend: 'webgpu' | 'wasm' = 'wasm', dtype = options.dtype, reason = '';
  const gpu = options.simulateNoGPU ? undefined : (self.navigator as unknown as { gpu?: { requestAdapter(): Promise<{ features: Set<string> } | null> } }).gpu;
  if (options.backend !== 'wasm') {
    let adapter = null;
    try { adapter = await gpu?.requestAdapter(); } catch { /* normal unavailable path */ }
    if (adapter && (dtype !== 'fp16' || adapter.features.has('shader-f16'))) backend = 'webgpu';
    else {
      reason = adapter ? 'GPU 不支持 FP16，已降级至 WASM / INT8' : options.simulateNoGPU
        ? '测试模式：WebGPU 不可用，已自动降级至 WASM / INT8' : 'WebGPU 不可用，已降级至 WASM';
      if (strict) throw new Error(reason);
    }
  } else reason = '已手动选择 WASM';
  if (backend === 'wasm' && dtype === 'fp16') dtype = 'q8';
  try { extractor = await create(backend, dtype) as FeatureExtractionPipeline; }
  catch (error) {
    if (backend === 'wasm' || strict) throw error;
    backend = 'wasm'; dtype = options.dtype === 'fp32' ? 'fp32' : 'q8';
    reason = `WebGPU 初始化失败，已降级至 WASM：${String(error)}`;
    extractor = await create(backend, dtype) as FeatureExtractionPipeline;
  }
  actual = { backend, dtype, reason }; currentKey = key;
  status({ runtime: actual });
  return { ...actual, loadMs: performance.now() - started, reused: false };
}

async function embed(texts: string[], query: boolean) {
  if (!extractor) throw new Error('请先加载模型；运行 npm run model:fetch 获取本地权重');
  const started = performance.now();
  const inputs = texts.map(t => query ? MODEL.queryPrefix + t : t);
  let tensor;
  try { tensor = await extractor(inputs, { pooling: MODEL.pooling, normalize: true }); }
  catch (error) {
    if (actual.backend === 'wasm' || strict) throw error;
    await extractor.dispose();
    actual = { backend: 'wasm', dtype: actual.dtype === 'fp32' ? 'fp32' : 'q8', reason: `WebGPU 推理失败，已切换 WASM：${String(error)}` };
    extractor = await create(actual.backend, actual.dtype) as FeatureExtractionPipeline;
    status({ runtime: actual });
    tensor = await extractor(inputs, { pooling: MODEL.pooling, normalize: true });
  }
  return { vectors: tensor.tolist() as number[][], embeddingMs: performance.now() - started, ...actual };
}
let tail = Promise.resolve();
self.onmessage = ({ data }) => {
  tail = tail.then(async () => {
    try {
      const result = data.op === 'load' ? await load(data.options) : await embed(data.texts, !!data.query);
      self.postMessage({ id: data.id, result });
    } catch (error) { self.postMessage({ id: data.id, error: error instanceof Error ? error.message : String(error) }); }
  });
};

