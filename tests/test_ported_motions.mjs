// The Universal Motion SDK motions ported from earlier branches (docs/evidence/ported-motions.json):
// each module defines exactly its listed ids, every motion states a valid digital meaning (the one the
// browser receipt recorded), none duplicates a native, withdrawn or camera id, and each draws
// deterministic, changing, mirrored and reduced-motion-safe frames through the SDK.
// Run: node --test tests/test_ported_motions.mjs
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { createMotionSystem, validateScene } from '../packages/motion-sdk/index.mjs';
import { brief, validMeaning } from '../packages/motion-engines/tools/build_registry.mjs';

const root = new URL('../', import.meta.url);
const json = (path) => JSON.parse(readFileSync(new URL(path, root), 'utf8'));
const manifest = json('docs/evidence/ported-motions.json');
const receipt = json('docs/evidence/ported-motions-chromium.json');
const policy = json('governance/policies/motion-purpose.json');
const native = new Set(json('packages/motion-engines/registry.json').motions.map((row) => row.id));
const withdrawn = new Set(policy.registries['native-engine'].withdrawn_ids);
const camera = new Set(policy.registries['nextgen-camera'].legacy_ids);
const asked = new Set(brief.map((row) => row.id));
const modules = new Map(await Promise.all(manifest.groups.map(async (group) => [group.source, await import(new URL(group.source, root))])));
const signature = (scene) => JSON.stringify(scene.primitives.map(({ fill, stroke, opacity, text, ...geometry }) => geometry));

test('each ported module defines exactly its listed motions, and no id is ported twice', () => {
  const seen = new Set();
  assert.ok(manifest.groups.length > 0);
  for (const group of manifest.groups) {
    const ids = modules.get(group.source).definitions.map((row) => row.id);
    assert.deepEqual(ids, group.ids, group.source);
    for (const id of ids) {
      assert.ok(!seen.has(id), `${id} is ported twice`);
      seen.add(id);
    }
    for (const id of Object.keys(group.left_out)) assert.ok(!ids.includes(id), `${id} is left out but still defined`);
  }
});

test('a ported motion is a brief name that is not native, withdrawn or a camera scene', () => {
  for (const group of manifest.groups) {
    for (const id of group.ids) {
      assert.ok(asked.has(id), `${id} is not in the brief`);
      assert.ok(!native.has(id), `${id} is already a native engine motion on HEAD`);
      assert.ok(!withdrawn.has(id), `${id} was withdrawn by the owner`);
      assert.ok(!camera.has(id), `${id} is a pinned camera scene`);
    }
    for (const [id, reason] of Object.entries(group.left_out)) {
      if (reason.startsWith('superseded')) assert.ok(native.has(id), `${id} is said to be superseded but is not native`);
      if (reason.startsWith('withdrawn')) assert.ok(withdrawn.has(id), `${id} is said to be withdrawn but is not`);
    }
  }
  for (const id of Object.keys(manifest.not_ported)) assert.ok(!manifest.groups.some((group) => group.ids.includes(id)), id);
});

test('every ported motion states the digital meaning its browser receipt recorded', () => {
  for (const group of manifest.groups) {
    const recorded = new Map(receipt.groups[group.source].motions.map((row) => [row.id, row.meaning]));
    for (const definition of modules.get(group.source).definitions) {
      assert.ok(validMeaning(definition.meaning), `${definition.id} has no valid meaning`);
      assert.match(definition.meaning.ar, /[؀-ۿ]/);
      assert.ok(Object.isFrozen(definition.meaning), definition.id);
      assert.deepEqual({ ...definition.meaning }, recorded.get(definition.id), `${definition.id}: meaning differs from the receipt`);
    }
  }
  assert.equal(validMeaning({ en: 'An English sentence only.', ar: 'English again, no Arabic.' }), false);
  assert.equal(validMeaning({ en: 'Too short', ar: 'قصير' }), false);
});

test('ported motions draw deterministic, changing, mirrored and reduced-motion-safe frames', () => {
  const width = 390, height = 844;
  for (const group of manifest.groups) {
    const catalog = modules.get(group.source);
    const sdk = createMotionSystem();
    sdk.registerCatalog(catalog);
    const geometry = new Set();
    for (const { id } of catalog.definitions) {
      const clip = sdk.create(id, { width, height, reducedMotion: 'full' });
      const scenes = [0.1, 0.5, 0.9].map((t) => validateScene(clip.render(t)));
      assert.equal(new Set(scenes.map(signature)).size, 3, `${id} does not change`);
      assert.deepEqual(clip.render(0.5), scenes[1], `${id} is not deterministic`);
      const key = scenes.map(signature).join('\n');
      assert.ok(!geometry.has(key), `${id} draws the same frames as another motion`);
      geometry.add(key);
      clip.configure({ reducedMotion: 'reduce' });
      assert.deepEqual(clip.render(0.1), clip.render(0.9), `${id}: reduced motion must be one still frame`);
      clip.configure({ reducedMotion: 'full', rtl: true });
      const mirrored = clip.render(0.5);
      assert.equal(mirrored.primitives.length, scenes[1].primitives.length, id);
      assert.notDeepEqual(mirrored.primitives, scenes[1].primitives, `${id} is not mirrored`);
      assert.match(clip.export('svg', 0.5), /<svg/);
      clip.destroy();
    }
    assert.equal(sdk.getCapabilities().live_instances, 0);
    assert.throws(() => catalog.sampleMotion('not-a-ported-motion', 0.5, {}));
    assert.throws(() => catalog.sampleMotion(catalog.definitions[0].id, Number.NaN, {}));
  }
});
