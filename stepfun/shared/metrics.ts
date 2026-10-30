export function median(values: number[]): number | null {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const m = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[m] : (sorted[m - 1] + sorted[m]) / 2;
}
export function quality(ranked: string[], relevant: string[], k: number) {
  const truth = new Set(relevant);
  const top = [...new Set(ranked)].slice(0, k);
  const found = top.filter(id => truth.has(id)).length;
  const dcg = top.reduce((sum, id, i) => sum + (truth.has(id) ? 1 / Math.log2(i + 2) : 0), 0);
  const ideal = Array.from({ length: Math.min(k, truth.size) }, (_, i) => 1 / Math.log2(i + 2)).reduce((a, b) => a + b, 0);
  return { recall: truth.size ? found / truth.size : 0, ndcg: ideal ? dcg / ideal : 0 };
}
