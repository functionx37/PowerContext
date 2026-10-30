import { createHash } from 'node:crypto';
import { readFile, writeFile, mkdir, realpath } from 'node:fs/promises';
import { resolve, relative, dirname, isAbsolute, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import dotenv from 'dotenv';

export const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
dotenv.config({ path: resolve(ROOT, '.env') });
export const hash = text => createHash('sha256').update(text).digest('hex');
export const readJson = async path => JSON.parse(await readFile(path, 'utf8'));
export async function jsonFile(path, value) {
  await mkdir(dirname(path), { recursive: true });
  await writeFile(path, JSON.stringify(value, null, 2) + '\n', 'utf8');
}
export async function sourcePath(root, path) {
  if (typeof path !== 'string' || !path || isAbsolute(path) || path.includes('\\')) throw new Error('Source must use a relative POSIX path');
  const base = await realpath(root);
  const target = await realpath(resolve(base, path));
  const rel = relative(base, target);
  if (rel.startsWith('..' + sep) || rel === '..' || isAbsolute(rel)) throw new Error('Source escapes project root');
  return target;
}
export function taskCheck(task) {
  for (const field of ['id', 'description']) if (typeof task[field] !== 'string' || !task[field].trim()) throw new Error(`Task needs ${field}`);
  for (const field of ['symbols', 'terms', 'spec_ids', 'required_sources', 'editable', 'target_tests', 'regression_tests']) {
    if (!Array.isArray(task[field]) || !task[field].length || task[field].some(x => typeof x !== 'string' || !x)) throw new Error(`Task needs nonempty ${field}`);
  }
  if (task.terms.length > 20 || task.symbols.length > 20 || task.spec_ids.length > 40) throw new Error('Task query too large');
  return task;
}
