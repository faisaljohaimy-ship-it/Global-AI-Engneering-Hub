import { existsSync, lstatSync, mkdirSync } from 'node:fs';
import { isAbsolute, resolve, sep } from 'node:path';

const defaults = Object.freeze({ frames: 30, frameBudgetMs: 20, width: 1280, height: 720, out: null });
export function validateOptions(options = {}) {
  const unknown = Object.keys(options).filter((key) => !Object.hasOwn(defaults, key));
  if (unknown.length) throw new Error('Unknown Chromium probe option');
  const result = { ...defaults, ...options };
  for (const [key, minimum, maximum] of [['frames', 12, 120], ['width', 320, 1920], ['height', 320, 1080]]) {
    if (!Number.isSafeInteger(result[key]) || result[key] < minimum || result[key] > maximum) {
      throw new Error(`${key} must be a bounded integer (${minimum}..${maximum})`);
    }
  }
  if (!Number.isFinite(result.frameBudgetMs) || result.frameBudgetMs < 1 || result.frameBudgetMs > 100) {
    throw new Error('frameBudgetMs must be finite and between 1 and 100');
  }
  if (result.out !== null && (typeof result.out !== 'string' || !result.out)) throw new Error('Invalid output path');
  return result;
}

export function parseArgs(args) {
  const parsed = {};
  const keys = { '--frames': 'frames', '--frame-budget-ms': 'frameBudgetMs', '--width': 'width', '--height': 'height', '--out': 'out' };
  for (let index = 0; index < args.length; index += 2) {
    const key = keys[args[index]];
    const value = args[index + 1];
    if (!key || value === undefined || Object.hasOwn(parsed, key)) throw new Error('Unknown, duplicate or incomplete probe argument');
    parsed[key] = key === 'out' ? value : Number(value);
  }
  return validateOptions(parsed);
}

export function prepareOutputDirectory(input) {
  if (input === null) return null;
  if (!isAbsolute(input) || input.split(/[\\/]/).some((part) => part === '..' || part === '.git' || part.startsWith('.env'))) {
    throw new Error('Output must be a new absolute directory under /tmp or /workspace');
  }
  const path = resolve(input);
  if (!['/tmp', '/workspace'].some((root) => path.startsWith(root + sep))) throw new Error('Output is outside approved writable roots');
  let current = sep;
  for (const part of path.split(sep).filter(Boolean)) {
    current = resolve(current, part);
    if (existsSync(current) && lstatSync(current).isSymbolicLink()) throw new Error('Symlink output paths are refused');
  }
  if (existsSync(path)) throw new Error('Output directory already exists; preserve previous evidence');
  // Deliberately do not create missing parents or overwrite a project directory.
  mkdirSync(path, { recursive: false, mode: 0o700 });
  return path;
}

export async function withDeadline(promise, milliseconds) {
  if (!Number.isFinite(milliseconds) || milliseconds < 1 || milliseconds > 60000) throw new Error('Invalid probe deadline');
  let timer;
  try {
    return await Promise.race([promise, new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error('Native rendering probe exceeded its deadline')), milliseconds);
    })]);
  } finally { clearTimeout(timer); }
}
