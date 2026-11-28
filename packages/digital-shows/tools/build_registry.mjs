// Writes registry.json from kit.mjs: scene ids, parameter schemas, meanings, themes, and the
// SHA-256 of the kit and of every font file, so the pipeline can refuse a kit or a font that
// changed without its registry.   node packages/digital-shows/tools/build_registry.mjs [--check]
// SPDX-License-Identifier: MIT
import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { buildRegistry } from '../kit.mjs';

const here = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const sha256 = (file) => createHash('sha256').update(readFileSync(resolve(here, file))).digest('hex');

export function registryDocument() {
  const registry = buildRegistry();
  registry.kit_sha256 = sha256('kit.mjs');
  registry.fonts.notice_sha256 = sha256(`fonts/${registry.fonts.notice}`);
  for (const font of registry.fonts.files) font.sha256 = sha256(`fonts/${font.file}`);
  return `${JSON.stringify(registry, null, 1)}\n`;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const target = resolve(here, 'registry.json'), text = registryDocument();
  if (process.argv.includes('--check')) {
    if (readFileSync(target, 'utf8') !== text) { process.stderr.write('registry.json is stale: run node packages/digital-shows/tools/build_registry.mjs\n'); process.exit(1); }
    process.stdout.write('registry.json is current\n');
  } else {
    writeFileSync(target, text);
    process.stdout.write(`wrote ${target}\n`);
  }
}
