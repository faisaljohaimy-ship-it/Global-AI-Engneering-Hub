import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import * as catalog from '../motion-library/expansion/nextgen-motion-particles.mjs';
import {createMotionSystem, validateScene} from '../packages/motion-sdk/index.mjs';

test('the nine reviewed CPU particle identities map to the original brief', () => {
  const inventory = JSON.parse(readFileSync(new URL('../docs/evidence/nextgen-cinematic-inventory.json', import.meta.url)));
  const requested = inventory.motions.filter(({number}) => number >= 62 && number <= 70);
  assert.deepEqual(catalog.definitions.map(({id, name_en}) => [id, name_en]),
    requested.map(({id, name}) => [id, name]));
  assert(catalog.definitions.every(({engine}) => engine === 'canvas2d'));
  assert.throws(() => catalog.sampleMotion('particles-gpu-swarm', .5), RangeError);
});

test('each particle mechanism has distinct geometry and correctly mirrors or freezes', () => {
  const sdk = createMotionSystem();
  sdk.registerCatalog(catalog);
  for (const [width, height] of [[390, 844], [1280, 720]]) {
    const mechanisms = new Set();
    for (const {id} of catalog.definitions) {
      const clip = sdk.create(id, {width, height, reducedMotion: 'full'});
      const frames = [.1, .5, .9].map((time) => validateScene(clip.render(time)));
      assert(frames.every((frame) => frame.primitives.length >= 64), id);
      const geometry = frames.map((frame) => JSON.stringify(frame.primitives.map(
        ({fill, stroke, opacity, ...placement}) => placement
      )));
      assert.equal(new Set(geometry).size, 3, id);
      mechanisms.add(geometry.join('\n'));
      assert.deepEqual(frames[1], clip.render(.5), id);
      assert.match(clip.export('svg'), /<svg/, id);

      clip.configure({rtl: true});
      const mirrored = clip.render(.5);
      assert.notDeepEqual(frames[1].primitives, mirrored.primitives, id);
      mirrored.primitives.forEach((primitive, index) => {
        const original = frames[1].primitives[index];
        const x = primitive.type === 'line' ? primitive.x1 + original.x1 : primitive.x + original.x;
        assert(Math.abs(x - width) < 1e-6, id);
      });
      clip.configure({reducedMotion: 'reduce'});
      assert.deepEqual(clip.render(.1), clip.render(.9), id);
      clip.destroy();
    }
    assert.equal(mechanisms.size, catalog.definitions.length);
  }
  assert.equal(sdk.getCapabilities().live_instances, 0);
});

test('signed input moves field sources and rejects invalid input', () => {
  for (const id of ['particles-attraction-field', 'particles-repulsion-field']) {
    const left = {interaction: {x: -.6, y: .3}};
    const right = {interaction: {x: .6, y: -.3}};
    const a = catalog.sampleMotion(id, .6, left);
    const b = catalog.sampleMotion(id, .6, right);
    assert(b.primitives.at(-1).x > a.primitives.at(-1).x);
    assert.notDeepEqual(a.primitives[0], b.primitives[0]);
    assert.deepEqual(catalog.sampleMotion(id, .6, {...left, reducedMotion: true}),
      catalog.sampleMotion(id, .6, {...right, reducedMotion: true}));
  }
  assert.throws(() => catalog.sampleMotion('particles-attraction-field', .5,
    {interaction: {x: 4, y: 0}}), RangeError);
  assert.throws(() => catalog.sampleMotion('particles-attraction-field', Infinity), RangeError);
});
