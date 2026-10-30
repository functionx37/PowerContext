import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { hash, sourcePath, readJson } from './util.mjs';

export async function scan(projectRoot) {
  const manifest = await readJson(resolve(projectRoot, 'project.json'));
  if (!/^[a-zA-Z0-9_-]{1,64}$/.test(manifest.id)) throw new Error('Invalid project id');
  if (!Array.isArray(manifest.sources) || !manifest.sources.length) throw new Error('No sources');
  const docs = [], files = [], paths = new Set();
  for (const source of manifest.sources) {
    if (paths.has(source.path)) throw new Error('Duplicate source path');
    paths.add(source.path);
    if (!['spec', 'code', 'test', 'data'].includes(source.kind)) throw new Error('Invalid source kind');
    if (!Array.isArray(source.symbols) || source.symbols.some(s => !/^[a-zA-Z0-9_$.-]+$/.test(s))) throw new Error('Invalid source symbols');
    const body = (await readFile(await sourcePath(projectRoot, source.path), 'utf8')).replace(/\r\n/g, '\n');
    if (Buffer.byteLength(body) > 256000) throw new Error('Source exceeds 256KB');
    files.push({ path: source.path, sha256: hash(body) });
    const lines = body.split('\n');
    const starts = source.kind === 'spec'
      ? lines.flatMap((line, i) => /^## (R-[0-9]+)\b/.test(line) ? [i] : []) : [0];
    if (!starts.length) throw new Error('Spec must contain ## R-NNN headings');
    for (let i = 0; i < starts.length; i++) {
      const start = starts[i], end = i + 1 < starts.length ? starts[i + 1] : lines.length;
      const text = lines.slice(start, end).join('\n');
      const specId = source.kind === 'spec' ? /^## (R-[0-9]+)/.exec(lines[start])[1] : '';
      docs.push({ source_id: source.path + (specId ? '#' + specId : ''), path: source.path, kind: source.kind,
        spec_id: specId, symbols: '|' + source.symbols.join('|') + '|', start_line: start + 1, end_line: end,
        body: text, sha256: hash(text) });
    }
  }
  if (new Set(docs.map(d => d.source_id)).size !== docs.length) throw new Error('Duplicate source ID');
  return { project: manifest.id, manifest, files, docs, fingerprint: hash(JSON.stringify({ manifest, files })) };
}
