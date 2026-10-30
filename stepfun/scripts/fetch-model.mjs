// Download only public model artifacts. No inference takes place in Node.
import { mkdir, writeFile, readFile, rename, stat } from 'node:fs/promises';
import { createWriteStream, createReadStream } from 'node:fs';
import { Readable } from 'node:stream';
import { pipeline } from 'node:stream/promises';
import { createHash } from 'node:crypto';
import { resolve, dirname } from 'node:path';
const id = 'Xenova/bge-small-zh-v1.5';
const revision = '75c43b069aac4d136ba6bc1122f995fedcfd2781';
const host = (process.env.HF_ENDPOINT || 'https://huggingface.co').replace(/\/$/, '');
const root = resolve('public/models');
const onnx = {
  'onnx/model.onnx': [94851877, '69a0b846f4f116b5e6aabf9546ea6754d02264f3211a13a1bd69b31b8040749a'],
  'onnx/model_quantized.onnx': [24010842, '15b717c382bcb518ba457b93ea6850ede7f4f1cd8937454aa06972366cd19bcc'],
  'onnx/model_fp16.onnx': [47497427, '60d0fe5eb8d4e251d4b24dff010a2625c10a013503f0d09f625e8a9b0311315f'],
};
const files = ['config.json', 'tokenizer.json', 'tokenizer_config.json', 'special_tokens_map.json', ...Object.keys(onnx)];
async function hash(path) {
  const h = createHash('sha256');
  for await (const chunk of createReadStream(path)) h.update(chunk);
  return h.digest('hex');
}
const entries = [];
for (const file of files) {
  const path = resolve(root, id, file);
  await mkdir(dirname(path), { recursive: true });
  const expected = onnx[file];
  let valid = false;
  try { valid = expected ? (await stat(path)).size === expected[0] && await hash(path) === expected[1] : !!JSON.parse(await readFile(path, 'utf8')); } catch {}
  if (!valid) {
    console.log(`Downloading ${file} (${host})`);
    let resumeAt = 0;
    if (expected) { try { resumeAt = (await stat(`${path}.part`)).size; } catch {} }
    if (resumeAt >= (expected?.[0] ?? Infinity)) resumeAt = 0;
    let response;
    for (let attempt = 0; attempt < 4; attempt++) {
      response = await fetch(`${host}/${id}/resolve/${revision}/${file}`, {
        headers: resumeAt ? { Range: `bytes=${resumeAt}-` } : {}, signal: AbortSignal.timeout(300000),
      });
      if (![429, 503].includes(response.status) || attempt === 3) break;
      await response.body?.cancel();
      console.log(`Rate limited; retry ${attempt + 1}/3 in ${(attempt + 1) * 15}s`);
      await new Promise(resolve => setTimeout(resolve, (attempt + 1) * 15000));
    }
    if (!response.ok || !response.body) throw new Error(`${file}: HTTP ${response.status}`);
    const append = response.status === 206 && response.headers.get('content-range')?.startsWith(`bytes ${resumeAt}-`);
    if (response.status === 206 && !append) throw new Error(`${file}: unexpected Content-Range`);
    await pipeline(Readable.fromWeb(response.body), createWriteStream(`${path}.part`, { flags: append ? 'a' : 'w' }));
    if (expected && ((await stat(`${path}.part`)).size !== expected[0] || await hash(`${path}.part`) !== expected[1]))
      throw new Error(`${file}: SHA-256 / length mismatch`);
    if (!expected) JSON.parse(await readFile(`${path}.part`, 'utf8'));
    await rename(`${path}.part`, path);
  }
  entries.push({ file, bytes: (await stat(path)).size, sha256: await hash(path) });
}
const bytes = Object.fromEntries(entries.map(x => [x.file, x.bytes]));
const manifest = { id, revision, measuredAt: new Date().toISOString(), downloadHost: host, files: entries,
  weightsCompression: { fp16: bytes['onnx/model.onnx'] / bytes['onnx/model_fp16.onnx'], q8: bytes['onnx/model.onnx'] / bytes['onnx/model_quantized.onnx'] } };
await mkdir('reports', { recursive: true });
await writeFile(resolve(root, 'manifest.json'), JSON.stringify(manifest, null, 2));
await writeFile('reports/model-manifest.json', JSON.stringify(manifest, null, 2));
console.log('Model artifacts verified. Manifest: reports/model-manifest.json');
