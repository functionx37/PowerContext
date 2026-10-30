import type { Backend, DType } from '../shared/config';
export interface Runtime { backend: 'wasm' | 'webgpu'; dtype: DType; reason: string }
export interface LoadResult extends Runtime { loadMs: number; reused: boolean }
export interface EmbedResult extends Runtime { vectors: number[][]; embeddingMs: number }
export class Embedder {
  private worker = new Worker(new URL('./embedding.worker.ts', import.meta.url), { type: 'module' });
  private sequence = 0;
  private pending = new Map<number, { resolve: (value: any) => void; reject: (error: Error) => void }>();
  constructor(onStatus: (message: any) => void) {
    this.worker.onmessage = ({ data }) => {
      if (data.event) return onStatus(data);
      const request = this.pending.get(data.id);
      if (!request) return;
      this.pending.delete(data.id);
      if (data.error) request.reject(new Error(data.error)); else request.resolve(data.result);
    };
    this.worker.onerror = event => {
      for (const p of this.pending.values()) p.reject(new Error(event.message));
      this.pending.clear();
    };
  }
  private call<T>(data: object): Promise<T> {
    return new Promise((resolve, reject) => {
      const id = ++this.sequence; this.pending.set(id, { resolve, reject }); this.worker.postMessage({ id, ...data });
    });
  }
  load(options: { backend: Backend; dtype: DType; strict?: boolean }) {
    return this.call<LoadResult>({ op: 'load', options: { ...options,
      simulateNoGPU: new URLSearchParams(location.search).get('webgpu') === 'off' } });
  }
  embed(texts: string[], query = false) { return this.call<EmbedResult>({ op: 'embed', texts, query }); }
  dispose() {
    this.worker.terminate();
    for (const p of this.pending.values()) p.reject(new Error('推理任务已取消'));
    this.pending.clear();
  }
}
