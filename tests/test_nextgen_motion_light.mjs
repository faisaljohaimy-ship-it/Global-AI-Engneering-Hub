import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import * as catalog from '../motion-library/expansion/nextgen-motion-light.mjs';
import {createMotionSystem, validateScene} from '../packages/motion-sdk/index.mjs';

const inventory = JSON.parse(readFileSync(new URL(
  '../docs/evidence/nextgen-cinematic-inventory.json', import.meta.url)));

test('lighting and product definitions cover the exact 20 remaining brief identities', () => {
  const target = inventory.motions.filter((row) => ['lighting', 'product'].includes(row.module));
  assert.equal(target.length, 20);
  const expected = new Map(target.map((row) => [row.id, row.name]));
  assert.equal(catalog.definitions.length, expected.size);
  for (const definition of catalog.definitions) {
    assert.equal(definition.name_en, expected.get(definition.id));
    assert.match(definition.name_ar, /\p{Script=Arabic}/u);
    assert.equal(definition.engine, 'canvas2d');
    assert.equal(definition.license, 'MIT');
    assert.equal(definition.runtime_status, 'requires-current-source-bound-proof');
    expected.delete(definition.id);
  }
  assert.equal(expected.size, 0);
});

function geometry(primitive) {
  const {fill, stroke, opacity, ...shape} = primitive;
  return shape;
}

test('all 20 mechanisms produce distinct changing geometry, accessible posters and RTL', () => {
  const trajectories = new Set();
  for (const definition of catalog.definitions) {
    for (const [width, height] of [[390, 844], [1280, 720]]) {
      const options = {width, height};
      const frames = [.1, .5, .9].map((progress) => catalog.sampleMotion(definition, progress, options));
      const shapes = frames.map((frame) => JSON.stringify(frame.primitives.map(geometry)));
      assert.equal(new Set(shapes).size, 3, definition.id);
      assert.deepEqual(frames[1], catalog.sampleMotion(definition.id, .5, options));
      for (const frame of frames) {
        validateScene(frame);
        assert.equal(frame.background, '#08111f');
        assert(frame.primitives.length > 3, definition.id);
      }
      if (width === 390) trajectories.add(JSON.stringify(shapes));
      const first = catalog.sampleMotion(definition.id, .1, {...options, reducedMotion: true});
      const last = catalog.sampleMotion(definition.id, .9, {...options, reducedMotion: true});
      assert.deepEqual(first, last, definition.id);
      const mirrored = catalog.sampleMotion(definition.id, .5, {...options, rtl: true});
      assert.notDeepEqual(frames[1].primitives, mirrored.primitives, definition.id);
      assert.equal(mirrored.primitives.length, frames[1].primitives.length);
      frames[1].primitives.forEach((primitive, index) => {
        const pair = mirrored.primitives[index];
        const check = (coordinate, partner) => assert(Math.abs(coordinate + partner - width) < 1e-9);
        if (primitive.type === 'line') {
          check(primitive.x1, pair.x1);
          check(primitive.x2, pair.x2);
        } else if (primitive.type === 'polyline') {
          primitive.points.forEach((point, vertex) => check(point.x, pair.points[vertex].x));
        } else if (primitive.type === 'rect') {
          check(primitive.x + primitive.width / 2, pair.x + pair.width / 2);
          assert.equal(pair.rotation || 0, -primitive.rotation || 0);
        } else {
          check(primitive.x, pair.x);
        }
      });
    }
  }
  assert.equal(trajectories.size, 20);
});

test('actual SDK registration enables all scenes, vector export and lifecycle cleanup', () => {
  const sdk = createMotionSystem();
  sdk.registerCatalog(catalog);
  for (const {id} of catalog.definitions) {
    const clip = sdk.create(id, {width: 390, height: 844, reducedMotion: 'full'});
    const scene = clip.render(.5);
    assert.equal(scene.meta.id, id);
    assert.match(clip.export('svg'), /^<svg\b/);
    assert.equal(clip.benchmark({frames: 8}).production_fps_verified, false);
    clip.destroy();
    assert.throws(() => clip.render(.5), /destroyed/);
  }
  assert.equal(sdk.getCapabilities().live_instances, 0);
});

test('feature explosion responds to pointer input and fixes reduced-motion interaction', () => {
  const id = 'product-feature-explosion';
  const inputA = {x: -.8, y: .9};
  const inputB = {x: .75, y: -.65};
  assert.notDeepEqual(catalog.sampleMotion(id, .55, {interaction: inputA}),
    catalog.sampleMotion(id, .55, {interaction: inputB}));
  assert.deepEqual(catalog.sampleMotion(id, .1, {reducedMotion: true, interaction: inputA}),
    catalog.sampleMotion(id, .9, {reducedMotion: true, interaction: inputB}));
});

test('sampler rejects unsafe values before constructing primitives', () => {
  const id = 'lighting-bloom-reveal';
  for (const [name, progress, options] of [
    ['unknown', .2, {}],
    [id, Infinity, {}],
    [id, .5, {intensity: 1.5}],
    [id, .5, {width: -1}],
    [id, .5, {rtl: 'yes'}],
    [id, .5, {interaction: {x: 2, y: 0}}],
  ]) {
    assert.throws(() => catalog.sampleMotion(name, progress, options), RangeError);
  }
});
