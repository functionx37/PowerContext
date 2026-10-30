// The immutable Hugging Face revision is filled from the verified model manifest.
export const MODEL = {
  id: 'Xenova/bge-small-zh-v1.5',
  revision: '75c43b069aac4d136ba6bc1122f995fedcfd2781',
  dimension: 512,
  pooling: 'cls' as const,
  queryPrefix: '为这个句子生成表示以用于检索相关文章：',
};
export const MODEL_KEY = `${MODEL.id}@${MODEL.revision}:cls:l2:512:chunk180-v1`;
export type DType = 'fp32' | 'fp16' | 'q8';
export type Backend = 'auto' | 'webgpu' | 'wasm';
export interface Chunk { id: string; sourceId: string; title: string; text: string; index: number }
export interface Source { id: string; title: string; text: string }
export interface CollectionInfo { name: string; title: string; count: number; modelKey: string }
export interface SearchHit { id: string; text: string; title: string; sourceId: string; index: number; value: number | null }
