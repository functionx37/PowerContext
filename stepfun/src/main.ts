import './style.css';
import { api } from './api';
import { Embedder, type Runtime } from './embedding';
import { benchmark } from './benchmark';
import { corpus } from '../shared/corpus';
import { prepareSource } from '../shared/text';
import { MODEL_KEY, type CollectionInfo, type Backend, type DType, type SearchHit } from '../shared/config';

const icons = {
  search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4.5 4.5"/>',
  book: '<path d="M4 4h6a3 3 0 0 1 3 3v14a4 4 0 0 0-4-3H4z"/><path d="M13 7a3 3 0 0 1 3-3h5v14h-4a4 4 0 0 0-4 3"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  arrow: '<path d="M5 12h14m-6-6 6 6-6 6"/>',
  upload: '<path d="M12 16V3m-5 5 5-5 5 5M4 15v5h16v-5"/>',
  chip: '<rect x="6" y="6" width="12" height="12" rx="3"/><path d="M10 2v4m4-4v4m-4 12v4m4-4v4M2 10h4m-4 4h4m12-4h4m-4 4h4"/>',
  chart: '<path d="M4 3v17h17M8 15v-4m5 4V7m5 8V4"/>',
  file: '<path d="M6 3h8l4 4v14H6zM14 3v5h5M9 12h6m-6 4h6"/>',
  shield: '<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6z"/><path d="m8 12 3 3 5-6"/>',
};
const icon = (name: keyof typeof icons, cls = '') => `<svg class="icon ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name]}</svg>`;
const escape = (value: unknown) => String(value).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]!));
const $ = <T extends HTMLElement = HTMLElement>(selector: string) => document.querySelector<T>(selector)!;
let collections: CollectionInfo[] = [], active = localStorage.getItem('atlas.collection') ?? '';
let runtime: Runtime | undefined, busy = false, epoch = 0, tab = 'search', cancelled = false;
let report: any, logs: any[] = [];
let engine = new Embedder(onStatus);

$('#app').innerHTML = `
  <aside class="sidebar">
    <a class="brand" href="/" aria-label="知屿首页"><span class="brand-mark">${icon('book')}</span><span>知屿<span class="brand-en">LOCAL ATLAS</span></span></a>
    <div class="space-label">个人工作空间 <span>LOCAL</span></div>
    <nav aria-label="主导航"><button class="nav-button selected" id="nav-search">${icon('search')}知识检索<span>↗</span></button><button class="nav-button" id="nav-benchmark">${icon('chart')}性能实验室</button></nav>
    <div class="section-label">我的知识库<button class="icon-button" id="add-collection" aria-label="新建知识库">${icon('plus')}</button></div>
    <div id="collections" class="collection-list"><span class="muted">正在连接…</span></div>
    <div class="sidebar-bottom"><div class="local-note">${icon('shield')}<div>计算留在你的设备<span>模型推理无需云端 API</span></div></div><div class="powered">POWERED BY <b>seekdb</b> × STEP<span>01 / 本地优先</span></div></div>
  </aside>
  <div class="workspace">
    <header><div class="breadcrumb">工作空间 <span>/</span> <b id="breadcrumb">知识检索</b></div><div class="connection"><span class="dot" id="db-dot"></span><span id="db-state">连接 seekdb 中</span><button id="reconnect" class="text-button">重试</button></div></header>
    <main>
      <div class="page-top"><div><div class="eyebrow" id="eyebrow">YOUR KNOWLEDGE, CONNECTED</div><h1 id="page-title">让知识，自然相连<span>。</span></h1><p id="page-subtitle">导入你的资料，用自己的语言找到答案。</p></div><button class="primary" id="open-import">${icon('plus')}导入文档</button></div>
      <div class="notice" id="notice" role="status" hidden></div>
      <section id="search-view">
        <form id="search-form" class="search-panel">
          <div class="search-input-wrap">${icon('search')}<input id="query" aria-label="搜索问题" placeholder="想了解什么？试着用一句话描述…" maxlength="1000" autocomplete="off"><button class="search-submit" aria-label="搜索" type="submit">${icon('arrow')}</button></div>
          <div class="search-options"><div class="segmented" aria-label="检索方式"><button type="button" class="active" data-mode="hybrid">混合检索</button><button type="button" data-mode="semantic">语义检索</button></div><label class="top-k">结果数 <select id="top-k" aria-label="结果数量"><option>5</option><option>10</option><option>20</option></select></label><span class="search-hint">Enter 搜索 ↵</span></div>
          <details class="keyword-details"><summary>指定关键词（可选）</summary><input id="keywords" maxlength="500" placeholder="为空时使用完整问题进行全文检索" aria-label="全文检索关键词"></details>
        </form>
        <div class="content-grid"><div class="results-column"><div class="results-heading"><h2 id="results-title">从这里开始探索</h2><span id="results-meta">你的知识，触手可及</span></div><div id="results"></div></div>
          <aside class="insight-column"><section class="runtime-card"><div class="card-heading">${icon('chip')}端侧推理<span class="tiny-badge" id="backend-badge">未加载</span></div><div class="model-name">BGE-small-zh<span>512 维 · 中文语义模型</span></div><div class="runtime-config"><label>精度<select id="dtype"><option value="fp16">FP16 · 默认</option><option value="q8">INT8 · 更小</option><option value="fp32">FP32 · 基线</option></select></label><label>推理后端<select id="backend"><option value="auto">自动 · WebGPU 优先</option><option value="wasm">WASM · 强制降级</option><option value="webgpu">WebGPU · 优先</option></select></label></div><button id="load-model" class="secondary full">加载本地模型</button><div id="model-status" class="model-status">首次使用前运行 npm run model:fetch</div><div class="runtime-divider"></div><div class="runtime-foot"><span>推理位置</span><b>当前浏览器</b></div><div class="runtime-foot"><span>检索与存储</span><b>seekdb</b></div></section>
          <section class="tips-card"><span class="tiny-label">HOW IT WORKS</span><h3>从资料到发现，只需三步</h3><ol><li><span>01</span><div>收集资料<p>导入 TXT、Markdown 或粘贴文本</p></div></li><li><span>02</span><div>本地向量化<p>在浏览器中理解文本的含义</p></div></li><li><span>03</span><div>发现关联<p>seekdb 融合关键词与语义</p></div></li></ol><p class="privacy-note">原文与向量会写入你配置的 seekdb；模型计算在本机完成。</p></section></aside>
        </div>
      </section>
      <section id="benchmark-view" hidden><div class="experiment-intro"><div><span class="tiny-label">MEASURE, DON'T GUESS</span><h2>在真实数据上，比较每一次优化。</h2><p>固定 18 篇中文资料、12 个查询、3 轮实验。所有向量在当前浏览器计算，所有检索由 seekdb 执行。</p></div><div class="benchmark-actions"><button id="run-benchmark" class="primary">${icon('chart')}运行完整评测</button><button id="cancel-benchmark" class="secondary" hidden>取消评测</button><button id="export-report" class="secondary">导出原始报告</button></div></div><div class="bench-progress" hidden><div id="bench-message"></div><progress id="bench-progress" max="100" value="0"></progress></div><div id="benchmark-results" class="benchmark-results"><div class="empty-small">尚未运行。评测将创建临时知识库，完成后自动清理。WebGPU 不可用时会如实记录原因。</div></div><p class="muted experiment-note">FP32 逐条与批量配置用于对比批处理和刷新策略；FP32 与 INT8 的批量配置用于对比精度。首次模型加载、首次推理与后续查询分开记录。</p></section>
      <footer><span>知屿 · 让每一份知识都有回响</span><span>浏览器本地推理 <i>→</i> seekdb 混合检索</span><button id="export-logs" class="text-button">导出运行日志</button></footer>
    </main>
  </div>
  <dialog id="import-dialog"><form method="dialog" class="dialog-top"><h2>把资料带到知屿</h2><button class="icon-button" aria-label="关闭">✕</button></form><p class="muted">文档将在浏览器内分块、向量化，然后写入当前知识库。</p><label class="dropzone" id="dropzone">${icon('upload')}<strong>选择文件，或拖放到这里</strong><span>TXT / MD · UTF-8 · 每份最多 2 MB</span><input type="file" id="files" accept=".txt,.md,.markdown,text/plain,text/markdown" multiple></label><div id="file-list"></div><div class="or"><span>也可以直接粘贴</span></div><input id="document-title" placeholder="文档标题" maxlength="100" aria-label="文档标题"><textarea id="document-text" placeholder="把值得记住的内容放在这里…" aria-label="文档内容" rows="5"></textarea><div class="import-bottom"><label>批大小 <select id="batch-size"><option>8</option><option>1</option><option>4</option><option>16</option></select></label><button id="start-import" class="primary">${icon('upload')}开始导入</button></div><div id="import-progress" role="status"></div></dialog>
  <dialog id="collection-dialog"><form id="collection-form"><div class="dialog-top"><h2>新建知识库</h2><button type="button" class="icon-button" id="close-collection" aria-label="关闭">✕</button></div><p class="muted">每个知识库独立存储和检索。</p><input id="collection-title" required maxlength="80" placeholder="例如：产品与研究" aria-label="知识库名称"><button type="submit" class="primary full">创建知识库</button></form></dialog>
  <dialog id="source-dialog"><form method="dialog" class="dialog-top"><h2 id="source-title">原文</h2><button class="icon-button" aria-label="关闭">✕</button></form><pre id="source-text"></pre></dialog>
`;

let searchMode = 'hybrid', pickedFiles: File[] = [];
function notify(message: string, error = false) { const n = $('#notice'); n.textContent = message; n.classList.toggle('error', error); n.hidden = false; }
function log(kind: string, values: object) { logs.push({ at: new Date().toISOString(), kind, ...values }); if (logs.length > 2000) logs.shift(); }
function onStatus(message: any) {
  if (message.runtime) {
    runtime = message.runtime; $('#backend-badge').textContent = `${runtime!.backend.toUpperCase()} / ${runtime!.dtype === 'q8' ? 'INT8' : runtime!.dtype.toUpperCase()}`;
    $('#model-status').textContent = runtime!.reason || '模型已就绪，计算在当前浏览器执行';
  } else if (message.progress?.status === 'progress') {
    $('#model-status').textContent = `读取模型 ${Math.round(message.progress.progress ?? 0)}%`;
  }
}
function setBusy(value: boolean) {
  busy = value;
  document.querySelectorAll<HTMLButtonElement | HTMLInputElement | HTMLSelectElement>('#open-import, #add-collection, #load-model, #dtype, #backend, #query, #top-k, #keywords, #run-benchmark, #start-import, #files, #document-title, #document-text, #batch-size, #collection-form button[type=submit], .search-submit, [data-collection], [data-mode]').forEach(el => el.disabled = value);
  $('#load-model').classList.toggle('loading', value);
}
function selected() { if (!active) throw new Error('请先创建知识库'); return active; }
async function loadModel() {
  const result = await engine.load({ backend: ($('#backend') as HTMLSelectElement).value as Backend, dtype: ($('#dtype') as HTMLSelectElement).value as DType });
  onStatus({ runtime: result }); log('model-load', result); return result;
}
function renderCollections() {
  $('#collections').innerHTML = collections.length ? collections.map(c => `<button data-collection="${c.name}" class="collection-button ${c.name === active ? 'selected' : ''}">${icon('book')}<span>${escape(c.title)}</span><b>${c.count}</b></button>`).join('') : '<p class="muted">还没有知识库<br>点击 + 创建一个</p>';
  document.querySelectorAll<HTMLButtonElement>('[data-collection]').forEach(button => {
    button.disabled = busy; button.onclick = () => { active = button.dataset.collection!; epoch++; localStorage.setItem('atlas.collection', active); renderCollections(); renderEmpty(); };
  });
}
function renderEmpty() {
  $('#results-title').textContent = '从这里开始探索'; $('#results-meta').textContent = collections.find(c => c.name === active)?.title ?? '你的知识，触手可及';
  const count = collections.find(c => c.name === active)?.count ?? 0;
  $('#results').innerHTML = `<div class="welcome-card"><div class="atlas-illustration"><span class="orbit one"></span><span class="orbit two"></span><span class="illustration-file first">${icon('file')}</span><span class="illustration-file second">${icon('file')}</span><span class="illustration-core">${icon('search')}</span><span class="spark s1">+</span><span class="spark s2">✧</span></div><span class="tiny-label">A LITTLE KNOWLEDGE GOES A LONG WAY</span><h2>${count ? '你的下一次发现，从一个问题开始' : '为你的想法，建一座知识小岛'}</h2><p>${count ? `当前知识库已有 ${count} 个片段。输入问题，发现资料之间的联系。` : '笔记、研究、灵感碎片——把它们放在一起，<br>让每次搜索都能找到新的连接。'}</p><button id="sample-import" class="secondary">${icon('book')}${count ? '追加示例资料' : '试用 18 篇示例资料'}${icon('arrow')}</button><div class="example-queries"><span>试着问问</span><button data-example="如何让刚刚写入的资料马上可以被查询到？">新资料如何立即可检索？ ↗</button><button data-example="如何结合关键词和语义搜索？">混合检索如何工作？ ↗</button></div></div><div class="method-row"><div>${icon('shield')}<span>端侧计算</span></div><div>${icon('chip')}<span>量化模型</span></div><div>${icon('search')}<span>数据库内融合</span></div></div>`;
  $('#sample-import').onclick = () => { if (!busy) void runImport(corpus); };
  document.querySelectorAll<HTMLButtonElement>('[data-example]').forEach(b => b.onclick = () => { ($('#query') as HTMLInputElement).value = b.dataset.example!; $('#query').focus(); });
}
async function refreshCollections() {
  collections = await api<CollectionInfo[]>('/collections');
  if (!collections.some(c => c.name === active)) active = collections[0]?.name ?? '';
  localStorage.setItem('atlas.collection', active); renderCollections();
}
async function startup() {
  try {
    const health = await api('/health');
    $('#db-dot').classList.toggle('online', health.ready);
    $('#db-state').textContent = health.ready ? `seekdb · ${health.database.mode === 'embedded' ? '嵌入式' : '本地服务'}` : 'seekdb 未就绪';
    $('#reconnect').hidden = health.ready;
    if (!health.ready) { notify(`数据库尚未就绪。${health.error || '首次连接可能需要下载嵌入式组件，请稍后点击重试。'}`, true); renderCollections(); return; }
    $('#notice').hidden = true;
    await refreshCollections();
    if (!collections.length) { const c = await api<CollectionInfo>('/collections', { title: '我的知识小岛' }); active = c.name; await refreshCollections(); }
    renderEmpty();
  } catch (error) { notify(String(error), true); }
}

async function runImport(documents: { title: string; text: string }[]) {
  if (busy) return;
  if (!active) return notify('请先创建知识库', true);
  const name = selected(), route = `/collections/${name}`, capturedEpoch = epoch;
  setBusy(true); const start = performance.now();
  let imported = 0, skipped = 0, embeddingMs = 0, writeMs = 0;
  const update = (message: string) => { $('#import-progress').textContent = message; notify(message); };
  try {
    update('正在读取文档并加载本地模型…'); await loadModel();
    const prepared = await Promise.all(documents.map(s => prepareSource(s.title, s.text)));
    const chunks = prepared.flatMap(s => s.chunks).sort((a, b) => a.text.length - b.text.length);
    const batch = Number(($('#batch-size') as HTMLSelectElement).value);
    for (let i = 0; i < chunks.length; i += batch) {
      const slice = chunks.slice(i, i + batch);
      update(`正在本地向量化 ${Math.min(i + batch, chunks.length)} / ${chunks.length} 个片段…`);
      const embedded = await engine.embed(slice.map(c => c.text)); embeddingMs += embedded.embeddingMs;
      const result = await api(`${route}/chunks`, { modelKey: MODEL_KEY,
        chunks: slice.map((c, j) => ({ ...c, vector: embedded.vectors[j] })),
        sources: i === 0 ? prepared.map(s => s.source) : [],
      });
      imported += result.inserted; skipped += result.skipped; writeMs += result.writeMs;
    }
    update('写入完成，正在刷新 seekdb 索引…');
    const refreshed = await api(`${route}/refresh`, {});
    const timing = { documents: documents.length, chunks: chunks.length, inserted: imported, skipped, embeddingMs, writeMs, refreshMs: refreshed.refreshMs, totalMs: performance.now() - start, runtime };
    log('import', timing); await refreshCollections();
    if (capturedEpoch === epoch) renderEmpty();
    update(`已导入 ${imported} 个新片段，跳过 ${skipped} 个已有片段。索引刷新完成，可以开始检索。`);
    ($('#import-dialog') as HTMLDialogElement).close(); pickedFiles = []; $('#file-list').textContent = '';
    ($('#document-text') as HTMLTextAreaElement).value = ''; ($('#files') as HTMLInputElement).value = '';
  } catch (error) { notify(`导入未完成：${error instanceof Error ? error.message : error}。已写入的批次可安全重试，完成后需刷新索引。`, true); $('#import-progress').textContent = String(error); log('import-error', { error: String(error), inserted: imported }); }
  finally { setBusy(false); }
}
$('#start-import').onclick = async () => {
  try {
    const documents = [];
    for (const file of pickedFiles) {
      if (file.size > 2_000_000) throw new Error(`${file.name} 超过 2 MB`);
      const text = new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer());
      documents.push({ title: file.name, text });
    }
    const text = ($('#document-text') as HTMLTextAreaElement).value.trim();
    if (text) documents.push({ title: ($('#document-title') as HTMLInputElement).value.trim() || '未命名文档', text });
    if (!documents.length) throw new Error('请选择文件或粘贴文本');
    if (documents.length > 100 || documents.reduce((s, d) => s + d.text.length, 0) > 2_000_000) throw new Error('单次最多 100 份文档，总计 200 万字符');
    await runImport(documents);
  } catch (e) { $('#import-progress').textContent = e instanceof Error ? e.message : String(e); }
};
function pick(files: File[]) {
  if (files.some(f => !/\.(txt|md|markdown)$/i.test(f.name))) { $('#import-progress').textContent = '仅支持 TXT 与 Markdown 文件'; return; }
  pickedFiles = files; $('#file-list').textContent = files.map(f => f.name).join(' · ');
}
$('#files').onchange = () => pick(Array.from(($('#files') as HTMLInputElement).files ?? []));
$('#dropzone').ondragover = e => { e.preventDefault(); };
$('#dropzone').ondrop = e => { e.preventDefault(); if (!busy) pick(Array.from(e.dataTransfer?.files ?? [])); };
$('#open-import').onclick = () => { if (!active) return notify('请先创建知识库', true); ($('#import-dialog') as HTMLDialogElement).showModal(); };
$('#add-collection').onclick = () => ($('#collection-dialog') as HTMLDialogElement).showModal();
$('#close-collection').onclick = () => ($('#collection-dialog') as HTMLDialogElement).close();
$('#collection-form').onsubmit = async e => {
  e.preventDefault(); if (busy) return;
  try { setBusy(true); const c = await api<CollectionInfo>('/collections', { title: ($('#collection-title') as HTMLInputElement).value }); active = c.name; epoch++; await refreshCollections(); renderEmpty(); ($('#collection-dialog') as HTMLDialogElement).close(); }
  catch (e) { notify(String(e), true); } finally { setBusy(false); }
};
document.querySelectorAll<HTMLButtonElement>('[data-mode]').forEach(b => b.onclick = () => {
  searchMode = b.dataset.mode!; document.querySelectorAll('[data-mode]').forEach(el => el.classList.toggle('active', el === b));
});
$('#search-form').onsubmit = async e => {
  e.preventDefault(); if (busy) return;
  const text = ($('#query') as HTMLInputElement).value.trim(); if (!text) return $('#query').focus();
  if (!active) return notify('请先创建知识库', true);
  const capturedEpoch = epoch, name = selected(), start = performance.now(); setBusy(true);
  try {
    notify('正在当前浏览器理解你的问题…'); await loadModel();
    const embedded = await engine.embed([text], true);
    const result = await api(`/collections/${name}/search`, { text, vector: embedded.vectors[0], modelKey: MODEL_KEY,
      keywords: ($('#keywords') as HTMLInputElement).value, mode: searchMode, k: Number(($('#top-k') as HTMLSelectElement).value) });
    if (capturedEpoch !== epoch) return;
    renderHits(result.hits, name); await new Promise(resolve => requestAnimationFrame(resolve));
    const totalMs = performance.now() - start;
    $('#results-title').textContent = `找到 ${result.hits.length} 条相关内容`;
    $('#results-meta').textContent = `向量化 ${embedded.embeddingMs.toFixed(0)} ms · 检索 ${result.searchMs.toFixed(0)} ms · 总计 ${totalMs.toFixed(0)} ms`;
    $('#notice').hidden = true; log('query', { collection: name, mode: searchMode, queryEmbeddingMs: embedded.embeddingMs, searchMs: result.searchMs, endToEndMs: totalMs, runtime });
  } catch (e) { notify(e instanceof Error ? e.message : String(e), true); }
  finally { setBusy(false); }
};
function renderHits(hits: SearchHit[], name: string) {
  $('#results').innerHTML = hits.length ? hits.map((h, i) => `<article class="result-card"><div class="result-top"><span class="rank">${String(i + 1).padStart(2, '0')}</span><span class="result-source">${icon('file')}${escape(h.title)}</span><span class="result-type">${searchMode === 'hybrid' ? '混合匹配' : '语义匹配'}</span></div><h3>${escape(h.title.replace(/\.(txt|md|markdown)$/i, ''))}</h3><p>${escape(h.text)}</p><div class="result-bottom"><span>片段 ${h.index + 1} · ${searchMode === 'semantic' ? `余弦距离 ${h.value?.toFixed(4) ?? '—'}` : `数据库融合排序 #${i + 1}`}</span><button class="text-button" data-source="${escape(h.sourceId)}">查看原文 ↗</button></div></article>`).join('') : '<div class="empty-small">当前知识库没有匹配内容。先导入资料并完成索引刷新，再试试其他表达。</div>';
  document.querySelectorAll<HTMLButtonElement>('[data-source]').forEach(b => b.onclick = async () => {
    try { const source = await api(`/collections/${name}/sources/${b.dataset.source}`); $('#source-title').textContent = source.title; $('#source-text').textContent = source.text; ($('#source-dialog') as HTMLDialogElement).showModal(); }
    catch (e) { notify(String(e), true); }
  });
}
$('#load-model').onclick = async () => { if (busy) return; setBusy(true); try { await loadModel(); notify('模型已就绪'); } catch (e) { notify(`模型加载失败：${e}。请先执行 npm run model:fetch。`, true); } finally { setBusy(false); } };
$('#reconnect').onclick = async () => { try { await api('/reconnect', {}); await startup(); } catch (e) { notify(String(e), true); } };
function switchTab(next: string) {
  tab = next; $('#search-view').hidden = tab !== 'search'; $('#benchmark-view').hidden = tab !== 'benchmark';
  $('#nav-search').classList.toggle('selected', tab === 'search'); $('#nav-benchmark').classList.toggle('selected', tab === 'benchmark');
  $('#breadcrumb').textContent = tab === 'search' ? '知识检索' : '性能实验室';
  $('#page-title').innerHTML = tab === 'search' ? '让知识，自然相连<span>。</span>' : '更轻、更快，有据可依<span>。</span>';
  $('#page-subtitle').textContent = tab === 'search' ? '导入你的资料，用自己的语言找到答案。' : '用同一组问题，衡量端侧推理与混合检索的每一处改进。';
  $('#open-import').hidden = tab !== 'search';
}
$('#nav-search').onclick = () => switchTab('search'); $('#nav-benchmark').onclick = () => switchTab('benchmark');
function download(name: string, value: unknown) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: 'application/json' }));
  const a = document.createElement('a'); a.href = url; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function renderReport(value: any) {
  report = value;
  const fmt = (n: number | null | undefined, places = 1) => n == null ? '—' : n.toFixed(places);
  $('#benchmark-results').innerHTML = `<div class="table-scroll"><table><thead><tr><th>实验配置</th><th>片段 / 秒</th><th>写入 / 刷新 ms</th><th>检索 ms</th><th>端到端 ms</th><th>Recall@5</th><th>nDCG@5</th></tr></thead><tbody>${value.configurations.map((c: any) => `<tr><td><b>${escape(c.label)}</b><span class="table-status">${c.status === 'complete' ? '完成 · 中位数' : c.status === 'running' ? '运行中' : escape(c.error)}</span></td><td>${fmt(c.summary?.chunksPerSecond)}</td><td>${fmt(c.summary?.writeMs)} / ${fmt(c.summary?.refreshMs)}</td><td>${fmt(c.summary?.searchMs)}</td><td>${fmt(c.summary?.endToEndMs)}</td><td>${fmt(c.summary?.recallAt5, 3)}</td><td>${fmt(c.summary?.ndcgAt5, 3)}</td></tr>`).join('')}</tbody></table></div>`;
}
$('#run-benchmark').onclick = async () => {
  if (busy) return; setBusy(true); cancelled = false; $('#cancel-benchmark').hidden = false; $('.bench-progress').hidden = false;
  engine.dispose();
  try {
    await benchmark({ onStatus, cancelled: () => cancelled,
      onProgress: (message, percent) => { $('#bench-message').textContent = message; ($('#bench-progress') as HTMLProgressElement).value = percent; },
      onPartial: renderReport,
    });
    notify('评测完成。可以导出原始报告，生成技术说明中的实测表。');
  } catch (e) { notify(String(e), true); }
  finally { engine = new Embedder(onStatus); runtime = undefined; $('#backend-badge').textContent = '未加载'; $('#model-status').textContent = '实验实例已释放，请重新加载日常检索模型'; $('#cancel-benchmark').hidden = true; setBusy(false); await refreshCollections(); }
};
$('#cancel-benchmark').onclick = () => { cancelled = true; $('#bench-message').textContent = '将在当前推理或数据库请求完成后取消并清理…'; };
$('#export-report').onclick = () => report ? download(`benchmark-${Date.now()}.json`, report) : notify('请先运行评测', true);
$('#export-logs').onclick = () => download(`atlas-runtime-${Date.now()}.json`, { userAgent: navigator.userAgent, modelKey: MODEL_KEY, logs });
renderEmpty(); void startup();
