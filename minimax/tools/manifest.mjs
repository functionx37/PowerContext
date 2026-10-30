import { readdir, readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { ROOT, hash, jsonFile } from '../src/util.mjs';

const files = [];
async function visit(relative) {
  for (const entry of await readdir(resolve(ROOT, relative), { withFileTypes: true })) {
    const path = relative ? relative + '/' + entry.name : entry.name;
    if (entry.isDirectory()) await visit(path);
    else if (entry.isFile()) files.push({ path, sha256: hash(await readFile(resolve(ROOT, path))) });
  }
}
for (const directory of ['src', 'tools', 'sample', 'tests', 'docs']) await visit(directory);
for (const path of ['README.md', 'package.json', 'package-lock.json', 'requirements.txt', 'requirements-lock-windows.txt', '.env.example', '.npmrc', '.gitignore', 'evidence/before/tickets.mjs', 'evidence/README.md']) {
  files.push({ path, sha256: hash(await readFile(resolve(ROOT, path))) });
}
await jsonFile(resolve(ROOT, 'evidence/source-manifest.json'), files.sort((a, b) => a.path.localeCompare(b.path)));
console.log(`Recorded ${files.length} source/document hashes.`);
