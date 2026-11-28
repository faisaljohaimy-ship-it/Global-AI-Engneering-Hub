// L08 native engine motions, batch of 2026-11-28: every new motion is original, carries a digital
// meaning in both languages, is in the brief under its own number and name, and is operational only
// with passing browser evidence for its exact source. Run: node --test tests/test_native_motions_digital.mjs
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { brief, build, coreHash, scan, validMeaning } from '../packages/motion-engines/tools/build_registry.mjs';
import { BASELINE_ENGINE_MOTIONS, NEXTGEN_CAMERA_IDS, TARGET, WITHDRAWN, inventory } from '../packages/motion-engines/tools/native_inventory.mjs';
import { defineMotion } from '../packages/motion-engines/core/define.mjs';

const root = new URL('../', import.meta.url);
const read = (path) => readFileSync(new URL(path, root), 'utf8');
const registry = JSON.parse(read('packages/motion-engines/registry.json'));
const evidence = JSON.parse(read('packages/motion-engines/evidence/chromium.json'));
const recorded = JSON.parse(readFileSync(TARGET, 'utf8'));
const rows = new Map(evidence.results.map((row) => [row.id, row]));
const added = registry.motions.filter((entry) => entry.meaning);
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

test('new motion sources are pure functions of time: no clocks, randomness, timers, listeners or CSS animation', () => {
  for (const entry of added) {
    const source = read(entry.source);
    for (const pattern of FORBIDDEN) assert.doesNotMatch(source, pattern, `${entry.id} uses ${pattern}`);
    assert.doesNotMatch(source, /^\s*import .* from '(?!\.\.\/\.\.\/(core|engines|shaders)\/)/m, `${entry.id} imports from outside the SDK`);
    assert.doesNotMatch(source, /copyright|shadertoy|licen[cs]ed under/i, `${entry.id} carries third-party text`);
  }
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
