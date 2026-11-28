import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import * as catalog from '../motion-library/expansion/nextgen-originals.mjs';
import {createMotionSystem, validateScene} from '../packages/motion-sdk/index.mjs';

const inventory = JSON.parse(readFileSync(new URL('../docs/evidence/nextgen-cinematic-inventory.json', import.meta.url)));
const selected = inventory.motions.filter((row) => ['camera', 'micro'].includes(row.module) && !row.pr16_source);
const expected = {
  camera: ['dolly-in', 'dolly-out', 'orbital-sweep', 'crane-reveal', 'focus-pull', 'parallax-tracking', 'spatial-roll'],
  micro: ['button-compression', 'liquid-button', 'cursor-distortion', 'hover-elevation', 'toggle-transformation', 'input-focus', 'elastic-selection', 'navigation-morph', 'success-feedback'],
};
const frames = [0.1, 0.5, 0.9];
const sizes = [[390, 844], [1280, 720]];
const signature = (scene) => JSON.stringify(scene.primitives.map(({fill, stroke, opacity, text, ...geometry}) => geometry));
const near = (a, b) => assert(Math.abs(a - b) < 1e-6, `${a} should equal ${b}`);

test('originals cover the seven camera identities and nine interaction identities', () => {
  const ids = Object.entries(expected).flatMap(([category, names]) => names.map((name) => `${category}-${name}`));
  assert.deepEqual(catalog.definitions.map((row) => row.id), ids);
  const ownerIds = new Set(selected.map((row) => row.id));
  for (const item of catalog.definitions) {
    assert(ownerIds.has(item.id), item.id);
    assert(item.name_en && /\p{Script=Arabic}/u.test(item.name_ar));
    assert.match(item.runtime_status, /proof/);
  }
});

test('camera and control paths produce distinct deterministic geometry through the SDK', () => {
  const sdk = createMotionSystem();
  sdk.registerCatalog(catalog);
  const paths = new Set();
  for (const [width, height] of sizes) {
    for (const {id} of catalog.definitions) {
      const clip = sdk.create(id, {width, height, reducedMotion: 'full'});
      const scenes = frames.map((time) => validateScene(clip.render(time)));
      const signatures = scenes.map(signature);
      assert.equal(new Set(signatures).size, frames.length, `static geometry: ${id}`);
      const key = signatures.join('\n');
      assert(!paths.has(key), `duplicate geometry: ${id}`);
      paths.add(key);
      assert.deepEqual(clip.render(0.5), scenes[1]);
      assert.match(clip.export('svg', 0.5), /<svg/);
      clip.destroy();
    }
  }
  assert.equal(sdk.getCapabilities().live_instances, 0);
});

test('all posters are stable and RTL mirrors geometry without reversing labels', () => {
  const width = 390, height = 844;
  for (const {id} of catalog.definitions) {
    const options = {width, height};
    const ltr = catalog.sampleMotion(id, 0.5, options).primitives;
    const rtl = catalog.sampleMotion(id, 0.5, {...options, rtl: true}).primitives;
    assert.notDeepEqual(ltr, rtl, id);
    assert.equal(ltr.length, rtl.length, id);
    ltr.forEach((left, index) => {
      const right = rtl[index];
      if (left.type === 'line') {
        near(left.x1 + right.x1, width);
        near(left.x2 + right.x2, width);
        near(left.y1, right.y1);
        near(left.y2, right.y2);
      } else if (left.type === 'polyline') {
        assert.equal(left.points.length, right.points.length);
        left.points.forEach((point, i) => {
          near(point.x + right.points[i].x, width);
          near(point.y, right.points[i].y);
        });
      } else {
        near(left.x + right.x + (left.width ?? 0), width);
        near(left.y, right.y);
        if (left.type === 'text') assert.equal(left.text, right.text);
      }
    });
    assert.deepEqual(
      catalog.sampleMotion(id, 0.05, {...options, reducedMotion: true, interaction: {x: -1, y: 1}}),
      catalog.sampleMotion(id, 0.95, {...options, reducedMotion: true, interaction: {x: 1, y: -1}}),
      id,
    );
  }
});

test('dolly direction, parallax ratios, and focus transfer have distinct camera semantics', () => {
  const width = 640, height = 360;
  const sample = (id, t) => catalog.sampleMotion(`camera-${id}`, t, {width, height});
  const span = (frame) => {
    const subject = frame.primitives.filter((p) => p.stroke === '#67e8f9');
    const xs = subject.flatMap(({x1, x2}) => [x1, x2]);
    return Math.max(...xs) - Math.min(...xs);
  };
  assert(span(sample('dolly-in', 0.9)) > span(sample('dolly-in', 0.1)));
  assert(span(sample('dolly-out', 0.9)) < span(sample('dolly-out', 0.1)));
  const anchor = (frame, stroke) => frame.primitives.find((p) => p.stroke === stroke).x1;
  const a = sample('parallax-tracking', 0.1), b = sample('parallax-tracking', 0.9);
  const shift = (stroke) => Math.abs(anchor(b, stroke) - anchor(a, stroke));
  assert(shift('#67e8f9') > shift('#a78bfa') && shift('#a78bfa') > shift('#6ee7b7'));
  const sharpness = (frame, stroke) => frame.primitives.find((p) => p.type === 'circle' && p.stroke === stroke).opacity;
  const nearFrame = sample('focus-pull', 0.05), farFrame = sample('focus-pull', 0.95);
  assert.deepEqual(nearFrame.meta.camera, farFrame.meta.camera);
  assert(sharpness(nearFrame, '#67e8f9') > sharpness(farFrame, '#67e8f9'));
  assert(sharpness(nearFrame, '#a78bfa') < sharpness(farFrame, '#a78bfa'));
});

test('interactive controls respond to pointer input within a fixed frame', () => {
  for (const id of ['micro-cursor-distortion', 'micro-hover-elevation']) {
    const a = catalog.sampleMotion(id, 0.5, {interaction: {x: 0, y: 0}});
    const b = catalog.sampleMotion(id, 0.5, {interaction: {x: 1, y: 0.4}});
    assert.notEqual(signature(a), signature(b));
  }
});

test('invalid identity, viewport, time, pointer, and direction fail closed', () => {
  const id = 'camera-dolly-in';
  for (const [name, progress, options] of [
    ['micro-random', 0.5, {}], [id, NaN, {}], [id, 0.5, {width: 0}],
    [id, 0.5, {interaction: {x: 2, y: 0}}], [id, 0.5, {rtl: 'yes'}],
    [id, 0.5, {reducedMotion: 'auto'}], [id, 0.5, {intensity: Infinity}],
  ]) assert.throws(() => catalog.sampleMotion(name, progress, options), RangeError);
});
