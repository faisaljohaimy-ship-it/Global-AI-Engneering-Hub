import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import * as catalog from '../motion-library/expansion/nextgen-motion-scenes.mjs';
import {createMotionSystem, validateScene} from '../packages/motion-sdk/index.mjs';

const inventory = JSON.parse(readFileSync(new URL('../docs/evidence/nextgen-cinematic-inventory.json', import.meta.url)));
const brief = inventory.motions.filter((row) => ['transitions', 'story'].includes(row.module));

test('catalog implements exactly the named transition and story brief', () => {
  assert.equal(brief.length, 20);
  assert.deepEqual(catalog.definitions.map(({id, name_en}) => [id, name_en]),
    brief.map((row) => [row.id, row.name]));
  for (const entry of catalog.definitions) {
    assert(entry.name_ar);
    assert.equal(entry.engine, 'canvas2d');
    assert.equal(entry.runtime_status, 'requires-current-source-bound-proof');
  }
});

test('each motion changes geometry, is distinct, seekable and stable with reduced motion', () => {
  const sdk = createMotionSystem();
  sdk.registerCatalog(catalog);
  for (const [width, height] of [[390, 844], [1280, 720]]) {
    const motionGeometries = new Set();
    for (const {id} of catalog.definitions) {
      const clip = sdk.create(id, {width, height, reducedMotion: 'full'});
      const times = [.1, .5, .9];
      const samples = times.map((time) => validateScene(clip.render(time)));
      const geometries = samples.map(({primitives}) => JSON.stringify(primitives.map(
        ({fill, stroke, opacity, ...geometry}) => geometry
      )));
      assert.equal(new Set(geometries).size, times.length, id);
      motionGeometries.add(geometries.join('\n'));
      assert.deepEqual(samples[1], clip.render(.5), id);
      assert.match(clip.export('svg'), /<svg/, id);

      clip.configure({rtl: true});
      const rtl = clip.render(.5);
      assert.notDeepEqual(rtl.primitives, samples[1].primitives, id);
      assert.equal(rtl.primitives.length, samples[1].primitives.length, id);
      rtl.primitives.forEach((item, index) => {
        const original = samples[1].primitives[index];
        const mirrored = item.type === 'line' ? item.x1 + original.x1
          : item.type === 'polyline' ? item.points[0].x + original.points[0].x
          : item.x + original.x + (item.width ?? 0);
        assert(Math.abs(mirrored - width) < 1e-6, id);
      });

      clip.configure({reducedMotion: 'reduce'});
      assert.deepEqual(clip.render(.1), clip.render(.9), id);
      clip.destroy();
    }
    assert.equal(motionGeometries.size, catalog.definitions.length);
  }
  assert.equal(sdk.getCapabilities().live_instances, 0);
});

test('pointer input affects interactive scenes with reduced motion override', () => {
  for (const id of ['transitions-curtain-reveal', 'story-milestone-journey']) {
    const left = {interaction: {x: -.85, y: 0}};
    const right = {interaction: {x: .85, y: 0}};
    assert.notDeepEqual(catalog.sampleMotion(id, .5, left), catalog.sampleMotion(id, .5, right));
    assert.deepEqual(catalog.sampleMotion(id, .5, {...left, reducedMotion: true}),
      catalog.sampleMotion(id, .5, {...right, reducedMotion: true}));
  }
});

test('refuses invalid motion inputs', () => {
  for (const changed of [{width: 0}, {height: Infinity}, {intensity: 2}, {rtl: 'yes'},
    {interaction: {x: 2, y: 0}}, {reducedMotion: 'yes'}]) {
    assert.throws(() => catalog.sampleMotion('story-kpi-storytelling', .5, changed), RangeError);
  }
  assert.throws(() => catalog.sampleMotion('missing', .5), RangeError);
  assert.throws(() => catalog.sampleMotion('story-kpi-storytelling', NaN), RangeError);
});
