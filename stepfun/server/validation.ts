import { z } from 'zod';
import { MODEL, MODEL_KEY } from '../shared/config';
export const nameSchema = z.string().regex(/^kb_[a-z0-9_]{1,60}$/);
export const vectorSchema = z.array(z.number().finite()).length(MODEL.dimension).refine(v => {
  const norm = Math.sqrt(v.reduce((s, n) => s + n * n, 0));
  return norm > 0.9 && norm < 1.1;
}, '必须提供浏览器生成的归一化向量');
export const importSchema = z.object({
  modelKey: z.literal(MODEL_KEY),
  chunks: z.array(z.object({
    id: z.string().regex(/^[a-f0-9]{64}$/), sourceId: z.string().regex(/^[a-f0-9]{64}$/),
    title: z.string().min(1).max(256), text: z.string().min(1).max(2000),
    index: z.number().int().min(0), vector: vectorSchema,
  })).min(1).max(64),
  sources: z.array(z.object({
    id: z.string().regex(/^[a-f0-9]{64}$/), title: z.string().min(1).max(256),
    text: z.string().min(1).max(2_000_000),
  })).max(100).default([]),
});
export const searchSchema = z.object({
  modelKey: z.literal(MODEL_KEY), text: z.string().trim().min(1).max(1000),
  keywords: z.string().trim().max(500).optional(), vector: vectorSchema,
  mode: z.enum(['hybrid', 'semantic']).default('hybrid'), k: z.number().int().min(1).max(20).default(5),
});
