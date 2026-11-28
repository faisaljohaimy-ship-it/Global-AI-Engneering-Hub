// L08 native engine motions, batch of 2026-11-28: every new motion is original, carries a digital
// meaning in both languages, is in the brief under its own number and name, and is operational only
// with passing browser evidence for its exact source. Run: node --test tests/test_native_motions_digital.mjs
// The purposeful-motion policy (governance/policies/motion-purpose.json) is checked here too: only the
// pinned legacy motions may lack a meaning, and no covered motion source uses unseeded randomness.
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { test } from 'node:test';
import { PURPOSE_POLICY, brief, build, coreHash, purposePolicy, scan, validMeaning } from '../packages/motion-engines/tools/build_registry.mjs';
import { definitions as cameraScenes } from '../motion-library/expansion/nextgen-camera.mjs';
import { BASELINE_ENGINE_MOTIONS, NEXTGEN_CAMERA_IDS, TARGET, WITHDRAWN, inventory } from '../packages/motion-engines/tools/native_inventory.mjs';
import { defineMotion } from '../packages/motion-engines/core/define.mjs';

const root = new URL('../', import.meta.url);
const read = (path) => readFileSync(new URL(path, root), 'utf8');
const registry = JSON.parse(read('packages/motion-engines/registry.json'));
const evidence = JSON.parse(read('packages/motion-engines/evidence/chromium.json'));
const recorded = JSON.parse(readFileSync(TARGET, 'utf8'));
const rows = new Map(evidence.results.map((row) => [row.id, row]));
const policy = JSON.parse(read(PURPOSE_POLICY));
const legacy = new Set(policy.registries['native-engine'].legacy_ids);
// A motion belongs to the batch because it is not a pinned legacy motion, never because it happens to
// carry a meaning: a new motion without one is then caught by the tests below instead of being skipped.
const added = registry.motions.filter((entry) => !legacy.has(entry.id));
const FORBIDDEN = [/Math\.random/, /Date\.now/, /performance\.now/, /requestAnimationFrame/, /setTimeout/, /setInterval/, /addEventListener/, /\burl\(/, /transition\s*:/, /animation\s*:/, /will-change/, /translateZ/];

test('the batch adds at least 25 motions and every one is operational', () => {
  assert.ok(added.length >= 25, `only ${added.length} new motions`);
  assert.equal(added.length, recorded.motions.length);
  for (const entry of added) assert.equal(entry.status, 'operational', entry.id);
});

test('every new motion states a digital meaning in English and Arabic', () => {
  for (const entry of added) {
    assert.ok(validMeaning(entry.meaning), `${entry.id} has no valid meaning`);
    assert.match(entry.meaning.ar, /[؀-ۿ]/);
  }
});

test('only the pinned legacy motions lack a meaning, and the pinned lists cannot grow', () => {
  const without = registry.motions.filter((entry) => !validMeaning(entry.meaning)).map((entry) => entry.id);
  assert.deepEqual(without.sort(), [...legacy].sort(), 'a motion without a meaning must be a pinned legacy id, and a pinned id must still lack one');
  for (const entry of registry.motions) assert.equal(entry.meaning === null, legacy.has(entry.id), entry.id);
  assert.ok(legacy.size <= BASELINE_ENGINE_MOTIONS, 'legacy_ids may only shrink');
  assert.deepEqual([...purposePolicy().legacy].sort(), [...legacy].sort(), 'the registry builder reads the same list');
  const withdrawn = policy.registries['native-engine'].withdrawn_ids;
  for (const id of WITHDRAWN) assert.ok(withdrawn.includes(id), `${id} must stay withdrawn in the policy`);
  for (const id of withdrawn) assert.ok(!registry.motions.some((entry) => entry.id === id) && !legacy.has(id), `${id} is withdrawn`);
  // The camera scenes have no meaning field at all: every scene the module defines is pinned, and nothing else is.
  const scenes = cameraScenes.map((scene) => scene.id).sort();
  assert.deepEqual(scenes, [...policy.registries['nextgen-camera'].legacy_ids].sort());
  assert.ok(scenes.every((id) => NEXTGEN_CAMERA_IDS.includes(id)), 'the camera list may only shrink');
  assert.ok(cameraScenes.every((scene) => scene.meaning === undefined), 'a camera scene that states a meaning needs a policy change, not a pin');
});

test('every new motion is a brief name under its own number, and none duplicates a nextgen camera scene', async () => {
  const asked = new Map(brief.map((row) => [row.id, row]));
  for (const entry of added) {
    const row = asked.get(entry.id);
    assert.ok(row, `${entry.id} is not in the brief`);
    assert.equal(entry.number, row.number);
    assert.equal(entry.name.en, row.name);
    assert.ok(!NEXTGEN_CAMERA_IDS.includes(entry.id), `${entry.id} duplicates a nextgen camera scene`);
    assert.ok(!WITHDRAWN.includes(entry.id), `${entry.id} was withdrawn`);
  }
  const ids = (await scan()).map((item) => item.id);
  for (const id of WITHDRAWN) assert.ok(!ids.includes(id), `${id} was withdrawn but its file is still there`);
});

test('each new motion passed every browser check for its exact source on the current core', () => {
  assert.equal(evidence.inputs.core_sha256, coreHash());
  for (const entry of added) {
    const row = rows.get(entry.id);
    assert.ok(row, `${entry.id} has no evidence`);
    assert.equal(row.source_sha256, entry.source_sha256, `${entry.id} evidence is for another source`);
    assert.ok(row.pass && Object.values(row.checks).every(Boolean), `${entry.id} failed a check`);
    for (const check of ['draws', 'changesOverTime', 'sameFrameForSameMoment', 'reducedMotionIsOneStillFrame', 'drawsInPortrait', 'lowerQualityStillDraws', 'destroyReleasesEverything']) {
      assert.equal(row.checks[check], true, `${entry.id} lacks ${check}`);
    }
    assert.ok(Object.keys(row.checks).length >= 16, `${entry.id} was not fully checked`);
    assert.ok(row.measured.benchmark.averageMs < 16, `${entry.id} is slower than one frame at 60 fps on software rendering`);
  }
});

test('the recorded proof hashes are the ones in the browser evidence', () => {
  for (const motion of recorded.motions) {
    const row = rows.get(motion.id);
    assert.equal(motion.proof.frame_signature, row.measured.signature, motion.id);
    assert.equal(motion.source_sha256, row.source_sha256, motion.id);
    assert.equal(motion.proof.checks_passed, motion.proof.checks_total, motion.id);
  }
});

test('no two motions, old or new, draw the same frames', () => {
  const signatures = evidence.results.filter((row) => row.pass).map((row) => row.measured.signature);
  assert.equal(new Set(signatures).size, signatures.length);
  assert.equal(new Set(registry.motions.map((entry) => entry.name.en)).size, registry.motions.length);
});

test('motion sources, old and new, are pure functions of time: no clocks, randomness, timers, listeners or CSS animation', () => {
  assert.equal(registry.motions.length, added.length + legacy.size);
  for (const entry of registry.motions) {
    const source = read(entry.source);
    for (const pattern of FORBIDDEN) assert.doesNotMatch(source, pattern, `${entry.id} uses ${pattern}`);
  }
  for (const entry of added) {
    const source = read(entry.source);
    assert.doesNotMatch(source, /^\s*import .* from '(?!\.\.\/\.\.\/(core|engines|shaders)\/)/m, `${entry.id} imports from outside the SDK`);
    assert.doesNotMatch(source, /copyright|shadertoy|licen[cs]ed under/i, `${entry.id} carries third-party text`);
  }
});

// The policy's source scan, exactly as engineering_os/motion_policy.py runs it: every .mjs file under the
// roots of a source set, `//` comment lines left out, each pattern of each forbidden group.
const code = (text) => text.split('\n').map((line) => (line.trimStart().startsWith('//') ? '' : line)).join('\n');
const group = (name) => policy.sources.patterns[name].map((pattern) => new RegExp(pattern));
function sourceFiles(roots) {
  const walk = (path, descend) => (statSync(new URL(path, root)).isDirectory()
    ? readdirSync(new URL(`${path}/`, root), { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name)).flatMap((item) => (
      item.isDirectory() ? (descend ? walk(`${path}/${item.name}`, true) : []) : (item.name.endsWith('.mjs') ? [`${path}/${item.name}`] : [])))
    : [path]);
  return roots.flatMap((entry) => walk(entry.path, entry.recursive));
}

test('no covered motion source draws from unseeded randomness or seeds itself from a clock', () => {
  const scanned = new Map();
  for (const [name, set] of Object.entries(policy.sources.sets)) {
    const files = sourceFiles(set.roots);
    scanned.set(name, files);
    for (const file of files) {
      const text = code(read(file));
      for (const forbidden of set.forbidden) for (const pattern of group(forbidden)) assert.doesNotMatch(text, pattern, `${file} (${name} sources): ${forbidden}`);
    }
  }
  // Every native motion, the 400-recipe generator, the camera scenes and the show kit are pure sources.
  const pure = scanned.get('pure');
  for (const entry of registry.motions) assert.ok(pure.includes(entry.source), `${entry.source} is not scanned`);
  for (const file of ['motion-library/expansion/catalog.mjs', 'motion-library/expansion/nextgen-camera.mjs', 'packages/digital-shows/kit.mjs']) assert.ok(pure.includes(file), file);
  for (const forbidden of ['unseeded-randomness', 'wall-clock', 'timer']) assert.ok(policy.sources.sets.pure.forbidden.includes(forbidden), forbidden);
  // The playback code may read a clock for the timeline, never randomness and never a clock as a seed.
  for (const file of ['packages/motion-engines/core/api.mjs', 'packages/motion-engines/core/clock.mjs', 'packages/motion-sdk/index.mjs']) assert.ok(scanned.get('runtime').includes(file), file);
  for (const forbidden of ['unseeded-randomness', 'clock-as-seed']) assert.ok(policy.sources.sets.runtime.forbidden.includes(forbidden), forbidden);
});

test('the randomness patterns refuse Math.random, crypto and a clock seed, and allow a seeded generator', () => {
  const hit = (name, line) => group(name).some((pattern) => pattern.test(code(line)));
  for (const line of ['const jitter = Math.random();', 'const pick = Math\n  .random() * 4;', 'crypto.getRandomValues(bytes);', 'const id = crypto.randomUUID();']) {
    assert.ok(hit('unseeded-randomness', line), line);
  }
  for (const line of ['const seed = Date.now();', 'const next = mulberry32(performance.now());', 'const next = seeded(Date.now() >>> 0);', 'options.seed = new Date().getTime();']) {
    assert.ok(hit('clock-as-seed', line) && hit('wall-clock', line), line);
  }
  // Seeded and therefore repeatable: the same seed draws the same frames (the policy states this).
  for (const line of ['const next = mulberry32((settings.seed + Math.imul(salt + 1, 0x9e3779b1)) >>> 0);', 'const rand = ctx.random(7);', 'const next = seeded(977 + c.seed);', 'const n = noise(i, seed);']) {
    for (const name of Object.keys(policy.sources.patterns)) assert.ok(!hit(name, line), `${line} must be allowed (${name})`);
  }
  assert.match(policy.sources.seeded_randomness.en, /seeded/);
  assert.match(policy.sources.seeded_randomness.ar, /[؀-ۿ]/);
  // A comment line is not code; anything else is, including a block comment.
  assert.ok(!hit('unseeded-randomness', '  // no Math.random here'));
  assert.ok(hit('unseeded-randomness', '/* Math.random */'));
});

test('the inventory count is truthful: 34 engine motions and 3 camera scenes before, plus this batch', async () => {
  const fresh = await inventory();
  assert.deepEqual(JSON.parse(JSON.stringify(fresh)), recorded, 'run node packages/motion-engines/tools/native_inventory.mjs');
  const { counts } = recorded;
  assert.equal(counts.baseline.total, BASELINE_ENGINE_MOTIONS + NEXTGEN_CAMERA_IDS.length);
  assert.equal(counts.baseline.total, 37);
  assert.equal(counts.native_engine_motions, BASELINE_ENGINE_MOTIONS + counts.added_this_batch);
  assert.equal(counts.native_total, 37 + counts.added_this_batch);
  assert.equal(counts.remaining_to_target, 200 - counts.native_total);
  assert.equal(recorded.remaining_brief_ids.length, counts.remaining_to_target);
  assert.equal(recorded.gpu_hardware_claimed, false);
  assert.match(recorded.browser.renderer, /SwiftShader/);
  assert.equal(registry.counts.with_digital_meaning, counts.added_this_batch);
});

test('the registry is rebuilt from the files and stays in step with them', async () => {
  const { json } = await build();
  assert.equal(read('packages/motion-engines/registry.json'), json);
});

// Negative cases: the contract refuses what does not fit.

test('a meaning must be one English and one Arabic sentence and nothing else', () => {
  const good = { en: 'Records from many systems merge into one.', ar: 'سجلاتٌ من أنظمةٍ كثيرة تندمج في سجلٍّ واحد.' };
  assert.ok(validMeaning(good));
  for (const bad of [null, 'text', {}, { en: good.en }, { ar: good.ar }, { en: good.en, ar: 'English only here, no Arabic' }, { en: 'short', ar: good.ar }, { ...good, fr: 'en plus' }, { en: good.en, ar: 'ق'.repeat(300) }]) {
    assert.equal(validMeaning(bad), false, JSON.stringify(bad));
  }
});

test('defineMotion refuses a new motion with a broken definition', async () => {
  const { default: motion } = await import('../packages/motion-engines/motions/story/transformation-journey.mjs');
  const base = { ...motion };
  assert.doesNotThrow(() => defineMotion(base));
  const broken = [
    { name: { en: 'Digital Transformation Journey', ar: 'Digital' } },
    { params: { only: base.params.fields } },
    { rtl: 'sideways' },
    { colors: ['#000', '#fff'] },
    { kind: 'forever' },
    { setup: null },
    { id: 'story-transformation-journey!' },
  ];
  for (const change of broken) assert.throws(() => defineMotion({ ...base, ...change }), TypeError, JSON.stringify(Object.keys(change)));
});

test('evidence for another source or another core does not make a motion operational', () => {
  const entry = added[0];
  const row = rows.get(entry.id);
  const proven = (candidate, core) => core === coreHash() && candidate.pass && candidate.source_sha256 === entry.source_sha256;
  assert.ok(proven(row, evidence.inputs.core_sha256));
  assert.equal(proven({ ...row, source_sha256: '0'.repeat(64) }, evidence.inputs.core_sha256), false);
  assert.equal(proven(row, 'f'.repeat(64)), false);
  assert.equal(proven({ ...row, pass: false }, evidence.inputs.core_sha256), false);
});
