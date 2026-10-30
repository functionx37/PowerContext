import type { Chunk, Source } from './config';

export async function sha256(text: string): Promise<string> {
  const bytes = new TextEncoder().encode(text);
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  return Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, '0')).join('');
}

// Bound both Chinese characters and English wordpieces; the worker additionally caps tokens.
export function splitText(text: string, size = 180, overlap = 30): string[] {
  if (size <= overlap || overlap < 0) throw new Error('分块大小必须大于重叠大小');
  const chars = Array.from(text.replace(/\r\n?/g, '\n').trim());
  const chunks: string[] = [];
  for (let start = 0; start < chars.length;) {
    let end = Math.min(start + size, chars.length);
    if (end < chars.length) {
      const window = chars.slice(start, end).join('');
      const match = [...window.matchAll(/[。！？.!?\n]/g)].at(-1);
      if (match && match.index! > size * 0.55) end = start + Array.from(window.slice(0, match.index! + 1)).length;
    }
    const part = chars.slice(start, end).join('').trim();
    if (part) chunks.push(part);
    if (end === chars.length) break;
    start = end - overlap;
  }
  return chunks;
}

export async function prepareSource(title: string, text: string): Promise<{ source: Source; chunks: Chunk[] }> {
  const normalized = text.replace(/\r\n?/g, '\n').trim();
  if (!normalized) throw new Error(`${title} 是空文档`);
  const sourceId = await sha256(`${title}\n${normalized}`);
  const chunks = await Promise.all(splitText(normalized).map(async (part, index) => ({
    id: await sha256(`${sourceId}:${index}:${part}`), sourceId, title, text: part, index,
  })));
  return { source: { id: sourceId, title, text: normalized }, chunks };
}
