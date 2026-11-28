#!/usr/bin/env node
// Builds registry.mjs (id -> lazy import) and registry.json (the
// metadata record of every motion) from the motion modules themselves, so that the
// record cannot drift from the code. Operational status comes only from evidence.
// A motion that states no digital meaning is refused unless its id is one of the legacy ids
// pinned in governance/policies/motion-purpose.json, and a withdrawn id is refused outright.
//
//   node packages/motion-engines/tools/build_registry.mjs           rewrite both files
//   node packages/motion-engines/tools/build_registry.mjs --check   exit 1 if either is out of date
import { createHash } from 'node:crypto';
import { existsSync, readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { MODULES } from '../core/define.mjs';
import { EASINGS } from '../core/easing.mjs';

const sdk = resolve(fileURLToPath(new URL('..', import.meta.url)));
const sha256 = (data) => createHash('sha256').update(data).digest('hex');
const version = JSON.parse(readFileSync(join(sdk, 'package.json'), 'utf8')).version;
/** The motions that were asked for by name: tools/brief.json. */
export const brief = JSON.parse(readFileSync(join(sdk, 'tools', 'brief.json'), 'utf8')).motions;
const asked = new Map(brief.map((row) => [row.id, row]));

/** The owner's purposeful-motion policy: the one place the legacy and withdrawn ids are listed. */
export const PURPOSE_POLICY = 'governance/policies/motion-purpose.json';
/** The motions that existed before the rule. The legacy list may only shrink, so it is never longer than this. */
const LEGACY_CEILING = 34;

/** What the registry needs from the policy: { legacy, withdrawn, minChars, maxChars }. Nothing is built without it. */
export function purposePolicy(root = resolve(sdk, '..', '..')) {
  const path = join(root, PURPOSE_POLICY);
  if (!existsSync(path)) throw new Error(`${PURPOSE_POLICY} is missing: motions are not registered without the purposeful-motion policy`);
  const policy = JSON.parse(readFileSync(path, 'utf8'));
  const native = policy.registries?.['native-engine'];
  const ids = (list) => Array.isArray(list) && list.every((id) => typeof id === 'string' && id) && new Set(list).size === list.length;
  if (!native || !ids(native.legacy_ids) || !ids(native.withdrawn_ids)) throw new Error(`${PURPOSE_POLICY}: registries.native-engine needs legacy_ids and withdrawn_ids`);
  if (native.legacy_ids.length > LEGACY_CEILING) throw new Error(`${PURPOSE_POLICY}: legacy_ids may only shrink from the ${LEGACY_CEILING} motions that existed before the rule`);
  const { min_chars: low, max_chars: high } = policy.meaning ?? {};
  if (!Number.isInteger(low) || !Number.isInteger(high)) throw new Error(`${PURPOSE_POLICY}: meaning needs min_chars and max_chars`);
  // The policy may tighten the limits of a meaning; it cannot loosen them past 12 and 240 characters.
  return Object.freeze({ legacy: new Set(native.legacy_ids), withdrawn: new Set(native.withdrawn_ids), minChars: Math.max(12, low), maxChars: Math.min(240, high) });
}
const purpose = purposePolicy();

/** One hash over the files every motion depends on: evidence is void when any of them changes. */
export function coreHash() {
  const files = ['core', 'engines', 'shaders'].flatMap((dir) => readdirSync(join(sdk, dir)).filter((name) => name.endsWith('.mjs')).sort().map((name) => `${dir}/${name}`));
  return sha256(files.map((file) => `${file}\n${readFileSync(join(sdk, file), 'utf8')}`).join('\n'));
}

const evidenceFor = (browser) => {
  const path = join(sdk, 'evidence', `${browser}.json`);
  if (!existsSync(path)) return { current: false, rows: new Map() };
  const evidence = JSON.parse(readFileSync(path, 'utf8'));
  return { current: evidence.inputs?.core_sha256 === coreHash(), rows: new Map(evidence.results.map((row) => [row.id, row])), engine: evidence.engine };
};

const GPU = { none: 'None: drawn on the CPU.', webgl2: 'WebGL2 (any GPU from about 2017, or software rendering).', webgpu: 'WebGPU when available; falls back to WebGL2.' };
const CPU = { low: 'Light: suitable for phones at full quality.', medium: 'Moderate: full quality on laptops, medium tier on phones.', high: 'Heavy: full quality needs a discrete or recent integrated GPU; the governor lowers the tier elsewhere.' };

/**
 * The digital meaning of a motion: what it stands for in a digital service, in one sentence
 * per language (for example "Records from many systems converge into one platform").
 * Every motion must carry one (owner direction of 2026-11-28); scan() makes the only exception,
 * for the legacy ids pinned in the policy. The limits come from the policy's `meaning` block.
 */
export function validMeaning(meaning) {
  const sentence = (value) => typeof value === 'string' && value.trim().length >= purpose.minChars && value.length <= purpose.maxChars;
  return Boolean(meaning) && typeof meaning === 'object' && Object.keys(meaning).sort().join() === 'ar,en'
    && sentence(meaning.en) && sentence(meaning.ar) && /[\u0600-\u06ff]/.test(meaning.ar);
}

/** Every motion module on disk, read straight from the files: { id, module, file, path, digest, definition }. */
export async function scan({ module: only, id: wanted } = {}) {
  const found = [];
  for (const module of Object.keys(MODULES)) {
    const dir = join(sdk, 'motions', module);
    if ((only && only !== module) || !existsSync(dir)) continue;
    for (const file of readdirSync(dir).filter((name) => name.endsWith('.mjs')).sort()) {
      const path = join(dir, file);
      const expected = `${module}-${file.slice(0, -4)}`;
      if (wanted && wanted !== expected) continue;
      if (purpose.withdrawn.has(expected)) throw new Error(`${expected}: withdrawn in ${PURPOSE_POLICY} because its meaning was only decorative; a withdrawn motion is not registered again`);
      const definition = (await import(pathToFileURL(path).href)).default;
      if (!definition || definition.id !== expected) throw new Error(`${module}/${file} must default-export the motion with id ${expected}`);
      if (definition.module !== module) throw new Error(`${expected}: module must be '${module}'`);
      const request = asked.get(expected);
      if (request && (definition.number !== request.number || definition.name.en !== request.name)) throw new Error(`${expected}: number and name.en must match tools/brief.json (${request.number}, ${request.name})`);
      if (!request && definition.number <= brief.length) throw new Error(`${expected}: numbers up to ${brief.length} belong to tools/brief.json`);
      if (definition.meaning === undefined) {
        if (!purpose.legacy.has(expected)) throw new Error(`${expected}: a motion must state its digital meaning (meaning.en and meaning.ar); only the legacy ids pinned in ${PURPOSE_POLICY} may lack one`);
      } else if (!validMeaning(definition.meaning)) throw new Error(`${expected}: meaning needs one English and one Arabic sentence (en, ar) saying what the motion means digitally`);
      found.push({ id: expected, module, file, path, digest: sha256(readFileSync(path, 'utf8')), definition });
    }
  }
  return found.sort((a, b) => a.definition.number - b.definition.number);
}

export async function build() {
  const chromium = evidenceFor('chromium');
  const others = Object.fromEntries(['firefox', 'webkit'].map((browser) => [browser, evidenceFor(browser)]));
  const entries = [];
  {
    for (const { module, file, path, digest, definition } of await scan()) {
      const row = chromium.rows.get(definition.id);
      const current = Boolean(row) && chromium.current && row.source_sha256 === digest;
      const verified = (evidence) => {
        const item = evidence.rows.get(definition.id);
        return item && evidence.current && item.source_sha256 === digest ? (item.pass ? 'verified' : 'failing') : 'not-run';
      };
      entries.push({
        id: definition.id,
        number: definition.number,
        name: definition.name,
        summary: definition.summary,
        meaning: definition.meaning ?? null,
        category: { key: module, letter: MODULES[module].letter, en: MODULES[module].en, ar: MODULES[module].ar },
        engine: definition.engine,
        kind: definition.kind,
        tags: definition.tags,
        source: `packages/motion-engines/motions/${module}/${file}`,
        source_sha256: digest,
        source_bytes: statSync(path).size,
        preview: `motion-studio/engines.html#${definition.id}`,
        controls: {
          duration: { default: definition.duration, min: 100, max: 120000, unit: 'ms' },
          easing: { default: definition.easing, options: EASINGS },
          colors: definition.colors,
          parameters: definition.params,
          camera: definition.camera,
          text: definition.text ?? null,
          input: definition.interactive ? definition.interactive.note : null,
        },
        shader_source: Boolean(definition.setup.shader),
        requirements: { gpu: definition.requirements.gpu, gpu_note: GPU[definition.requirements.gpu], cost: definition.requirements.cost, cpu_note: CPU[definition.requirements.cost] },
        compatibility: {
          mobile: definition.requirements.cost === 'high' ? 'Runs at the low or medium tier; not measured on a phone.' : 'Expected at full quality; not measured on a phone.',
          browsers: { chromium: verified(chromium), firefox: verified(others.firefox), webkit: verified(others.webkit) },
          rtl: definition.rtl,
        },
        reduced_motion: `One still frame at ${Math.round(definition.still * 100)}% of the timeline; nothing is scheduled or animated.`,
        benchmark: current && row.measured?.benchmark ? { ...row.measured.benchmark, viewport: '320x180', environment: `${chromium.engine.browser} ${chromium.engine.version}, ${chromium.engine.renderer}` } : null,
        test: `node packages/motion-engines/verify/browser.mjs --id ${definition.id}`,
        license: 'Original work of the repository owner. No third-party code or assets. The repository has no blanket licence: reuse outside the owner\'s projects needs the owner\'s permission.',
        usage: `import { motion } from 'packages/motion-engines/index.mjs';\nconst instance = await motion.create('${definition.id}', { container });\nmotion.play(instance);`,
        integration: `python3 hub.py register PROJECT --revision HUB_SHA --capability engine-motion:${definition.id} --apply`,
        status: current ? (row.pass ? 'operational' : 'failing') : 'implemented-unverified',
        evidence: current ? `packages/motion-engines/evidence/chromium.json#${definition.id}` : null,
      });
    }
  }
  entries.sort((a, b) => a.number - b.number);
  const ids = entries.map((entry) => entry.id);
  const numbers = entries.map((entry) => entry.number);
  if (new Set(ids).size !== ids.length || new Set(numbers).size !== numbers.length) throw new Error('Motion ids and numbers must be unique');
  const loaders = entries.map((entry) => `  '${entry.id}': () => import('./${entry.source.slice('packages/motion-engines/'.length)}'),`).join('\n');
  const module = `// Generated by tools/build_registry.mjs from the motion modules. Do not edit.\nexport const loaders = Object.freeze({\n${loaders}\n});\n`;
  const counts = (key) => entries.reduce((totals, entry) => ({ ...totals, [key(entry)]: (totals[key(entry)] ?? 0) + 1 }), {});
  const document = {
    schema_version: 1,
    sdk_version: version,
    notes: 'Generated by packages/motion-engines/tools/build_registry.mjs. A motion is operational only while browser evidence exists for its exact source and for the exact core it runs on.',
    counts: { motions: entries.length, by_status: counts((entry) => entry.status), by_engine: counts((entry) => entry.engine), by_module: counts((entry) => entry.category.key), with_digital_meaning: entries.filter((entry) => entry.meaning).length },
    brief: {
      requested: brief.length,
      implemented: brief.filter((row) => ids.includes(row.id)).length,
      operational: brief.filter((row) => entries.some((entry) => entry.id === row.id && entry.status === 'operational')).length,
      not_implemented: brief.filter((row) => !ids.includes(row.id)).map((row) => row.id),
    },
    motions: entries,
  };
  return { module, json: JSON.stringify(document, null, 2) + '\n', document };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const { module, json, document } = await build();
  const targets = [[join(sdk, 'registry.mjs'), module], [join(sdk, 'registry.json'), json]];
  if (process.argv.includes('--check')) {
    const stale = targets.filter(([path, text]) => !existsSync(path) || readFileSync(path, 'utf8') !== text).map(([path]) => path.slice(sdk.length + 1));
    if (stale.length) {
      console.error(`Out of date: ${stale.join(', ')}. Run node packages/motion-engines/tools/build_registry.mjs.`);
      process.exit(1);
    }
  } else for (const [path, text] of targets) writeFileSync(path, text);
  console.log(JSON.stringify({ ...document.counts, brief: { ...document.brief, not_implemented: document.brief.not_implemented.length } }));
}
