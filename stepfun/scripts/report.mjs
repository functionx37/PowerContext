import { readFile, writeFile } from 'node:fs/promises';
const path = process.argv[2];
if (!path) throw new Error('Usage: npm run report -- reports/benchmark-xxx.json');
const r = JSON.parse(await readFile(path, 'utf8'));
if (r.schema !== 1 || !r.configurations) throw new Error('不是本应用生成的评测报告');
const fmt = (n, digits = 2) => n == null ? '未测' : n.toFixed(digits);
const lines = ['# 浏览器实测报告', '', `时间：${r.measuredAt}`, `浏览器：${r.userAgent}`, `CPU 逻辑线程：${r.hardwareConcurrency}；内存提示：${r.deviceMemoryGB ?? '未知'} GB`,
  `数据库：${JSON.stringify(r.database)}`, `模型：${r.model.id}@${r.model.revision}`, `语料 SHA-256：${r.corpusSha256}`, `查询 SHA-256：${r.queriesSha256}`,
  `${r.sourceCount} 篇文档 / ${r.chunkCount} 块 / ${r.queryCount} 个查询 / ${r.trials} 轮`, '', r.notes, '',
  '|配置|加载 ms|首次推理 ms|块/秒|写入 ms|刷新 ms|检索 ms|端到端 ms|Recall@5|nDCG@5|',
  '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|'];
for (const c of r.configurations) {
  if (c.status !== 'complete') { lines.push(`|${c.label}|未完成：${String(c.error || c.status).replaceAll('|', '/')}|||||||||`); continue; }
  const s = c.summary;
  lines.push(`|${c.label}|${fmt(c.load.loadMs)}|${fmt(c.firstInferenceMs)}|${fmt(s.chunksPerSecond)}|${fmt(s.writeMs)}|${fmt(s.refreshMs)}|${fmt(s.searchMs)}|${fmt(s.endToEndMs)}|${fmt(s.recallAt5, 4)}|${fmt(s.ndcgAt5, 4)}|`);
}
const baseline = r.configurations.find(c => c.dtype === 'fp32' && c.batch === 8 && c.status === 'complete');
if (baseline) for (const c of r.configurations.filter(c => c.dtype !== 'fp32' && c.status === 'complete')) {
  lines.push('', `${c.label} 相对 FP32 批量基线：Recall@5 变化 ${fmt((c.summary.recallAt5 - baseline.summary.recallAt5) * 100)} 个百分点；nDCG@5 变化 ${fmt((c.summary.ndcgAt5 - baseline.summary.ndcgAt5) * 100)} 个百分点。`);
}
lines.push('', '单项对比：FP32 逐条→FP32 批量同时改变批大小和刷新策略，是组合优化；FP32 批量→INT8 WASM 仅改变精度。FP16 WebGPU 同时改变精度与后端，只作为部署方案比较。', '', '这是一组小规模验收语料，结果不能外推到所有中文知识库。首次模型网络下载由下载清单单独记录，加载时间不包含下载脚本耗时。');
const medians = r.configurations.filter(c => c.status === 'complete').map(c => c.summary.endToEndMs);
if (medians.length && medians.every(n => n > 900 && n < 1100)) lines.push('',
  '计时限制：本次各配置端到端中位数均聚集在约 1000 ms，可能受到内置浏览器绘制回调节流影响（推断）。数值保留原样，不用于证明模型或检索的延迟改善。请在前台 Chrome/Edge 复测。模型冷网络下载完整时长未记录，清单仅报告实际文件字节和哈希。');
await writeFile('reports/BENCHMARK.md', lines.join('\n') + '\n');
console.log('Written reports/BENCHMARK.md');
