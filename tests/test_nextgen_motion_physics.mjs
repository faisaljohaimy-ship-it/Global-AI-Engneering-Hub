import assert from 'node:assert/strict';
import test from 'node:test';
import * as catalog from '../motion-library/expansion/nextgen-motion-physics.mjs';
import {createMotionSystem, validateScene} from '../packages/motion-sdk/index.mjs';

const viewport = {width: 390, height: 844};
const byId = new Map(catalog.definitions.map(row => [row.id, row]));
const scene = (id, t, options = {}) => catalog.sampleMotion(id, t, {...viewport, ...options});

function points(primitive) {
  if (primitive.type === 'polyline') return primitive.points.map(({x, y}) => [x, y]);
  if (primitive.type === 'line') return [[primitive.x1, primitive.y1], [primitive.x2, primitive.y2]];
  return [[primitive.x, primitive.y]];
}

test('the twenty owner identities are distinct and each has bounded deterministic accessible frames', () => {
  const ids = catalog.definitions.map(row => row.id);
  assert.equal(ids.length, 20);
  assert.equal(new Set(ids).size, 20);
  assert.equal(ids.filter(id => id.startsWith('twin-')).length, 10);
  assert.equal(ids.filter(id => id.startsWith('physics-')).length, 10);
  const middleFrames = new Set();
  const sdk = createMotionSystem();
  sdk.registerCatalog(catalog);
  for (const id of ids) {
    const definition = byId.get(id);
    assert.match(definition.name_ar, /[\u0600-\u06ff]/u);
    assert.equal(definition.license, 'MIT');
    const clip = sdk.create(id, {...viewport, reducedMotion: 'full'});
    const frames = [0, .1, .5, .9, 1].map(progress => clip.render(progress));
    const content = frames.map(frame => JSON.stringify(frame.primitives));
    assert.equal(new Set(content.slice(1, 4)).size, 3, id);
    assert.deepEqual(clip.render(.5), frames[2], id);
    middleFrames.add(content[2]);
    for (const frame of frames) {
      validateScene(frame);
      assert(frame.primitives.length >= 2 && frame.primitives.length <= 150, id);
      for (const primitive of frame.primitives) {
        for (const [x, y] of points(primitive)) {
          assert(x >= 0 && x <= viewport.width && y >= 0 && y <= viewport.height, id);
        }
      }
    }
    clip.configure({reducedMotion: 'full', rtl: true});
    const mirrored = clip.render(.5);
    assert.notDeepEqual(mirrored.primitives, frames[2].primitives, id);
    assert.equal(mirrored.primitives.length, frames[2].primitives.length, id);
    for (let i = 0; i < mirrored.primitives.length; i++) {
      points(mirrored.primitives[i]).forEach(([x, y], j) => {
        const [originalX, originalY] = points(frames[2].primitives[i])[j];
        assert(Math.abs(x + originalX - viewport.width) < 1e-9, id);
        assert.equal(y, originalY, id);
      });
    }
    clip.configure({reducedMotion: 'reduce'});
    assert.deepEqual(clip.render(.1), clip.render(.9), id);
    assert.match(clip.export('svg'), /^<svg /, id);
    clip.destroy();
  }
  assert.equal(middleFrames.size, ids.length);
  assert.equal(sdk.getCapabilities().live_instances, 0);
});

test('pinned cloth keeps anchors exact and lattice distances bounded under wind', () => {
  const id = 'physics-cloth-simulation';
  const first = scene(id, .1);
  const last = scene(id, .9);
  assert.deepEqual(first.primitives.slice(-9), last.primitives.slice(-9));
  assert.notDeepEqual(first.primitives.slice(0, -9), last.primitives.slice(0, -9));
  for (const primitive of last.primitives.slice(0, -9)) {
    assert.equal(primitive.type, 'line');
    const length = Math.hypot(primitive.x1 - primitive.x2, primitive.y1 - primitive.y2);
    assert(Math.abs(length - .074 * viewport.width) < .11 * .074 * viewport.width);
  }
});

test('rigid disks meet at their surfaces and separate after the impulse', () => {
  const id = 'physics-rigid-collision';
  const gap = time => {
    const [a, b] = scene(id, time).primitives.filter(row => row.type === 'circle');
    return b.x - a.x - a.r - b.r;
  };
  const contact = (.68 - .2 - .085 - .098) / (.43 + .26);
  assert(gap(.1) > 20);
  assert(Math.abs(gap(contact)) < 1e-9);
  assert(gap(.9) > 20);
});

test('Voronoi vertices satisfy the owning site’s distance inequality', () => {
  const primitives = scene('physics-voronoi-structure', .45).primitives;
  const regions = primitives.filter(row => row.type === 'polyline');
  const sites = primitives.filter(row => row.type === 'circle');
  assert.equal(regions.length, sites.length);
  const distance = (a, b) => (a.x - b.x) ** 2 + (a.y - b.y) ** 2;
  regions.forEach((region, i) => {
    for (const corner of region.points) for (const site of sites) {
      assert(distance(corner, sites[i]) <= distance(corner, site) + 1e-7);
    }
  });
});

test('twin scan and construction materialize more generated geometry with time', () => {
  for (const id of ['twin-terrain-reconstruction', 'twin-construction', 'physics-geometry-growth']) {
    const quantities = [.1, .5, .9].map(time => scene(id, time).primitives.length);
    assert(quantities[0] < quantities[1] && quantities[1] < quantities[2], id);
  }
  assert.throws(() => scene('invalid', 0), RangeError);
  assert.throws(() => scene('twin-construction', NaN), RangeError);
  assert.throws(() => scene('twin-construction', 0, {width: 0}), RangeError);
});
