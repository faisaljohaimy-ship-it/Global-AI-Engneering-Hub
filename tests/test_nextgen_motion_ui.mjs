import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import * as catalog from '../motion-library/expansion/nextgen-motion-ui.mjs';
import {createMotionSystem, validateScene} from '../packages/motion-sdk/index.mjs';

const inventory = JSON.parse(readFileSync(new URL('../docs/evidence/nextgen-cinematic-inventory.json', import.meta.url)));
const stripped = (scene) => JSON.stringify(scene.primitives.map(({stroke, fill, opacity, text, ...shape}) => shape));
const testSizes = [[390, 844], [1280, 720]];
const times = [0.1, 0.5, 0.9];

test('the hologram and dashboard pack covers all twenty original brief identities once', () => {
  const expected = inventory.motions
    .filter((row) => ['hologram', 'dashboard'].includes(row.module) && !row.pr16_source)
    .map((row) => row.id);
  assert.equal(expected.length, 20);
  assert.deepEqual(catalog.definitions.map(({id}) => id), expected);
  for (const row of catalog.definitions) {
    assert(row.name_en);
    assert.match(row.name_ar, /\p{Script=Arabic}/u);
    assert.equal(row.engine, 'canvas2d');
    assert.match(row.runtime_status, /proof/);
  }
});

test('all scene geometries change distinctly at three times on mobile and desktop', () => {
  const sdk = createMotionSystem();
  sdk.registerCatalog(catalog);
  for (const [width, height] of testSizes) {
    const unique = new Set();
    for (const {id} of catalog.definitions) {
      const clip = sdk.create(id, {width, height, reducedMotion: 'full'});
      const frames = times.map((t) => validateScene(clip.render(t)));
      assert.equal(new Set(frames.map(stripped)).size, times.length, id);
      const trajectory = frames.map(stripped).join('\n');
      assert(!unique.has(trajectory), id);
      unique.add(trajectory);
      assert.deepEqual(clip.render(0.5), frames[1]);
      assert.match(clip.export('svg', 0.5), /<svg/);
      clip.destroy();
    }
  }
  assert.equal(sdk.getCapabilities().live_instances, 0);
});

test('reduced motion ignores animation and pointer input, while RTL mirrors the geometry', () => {
  const width = 390;
  for (const {id} of catalog.definitions) {
    const ltr = catalog.sampleMotion(id, 0.5, {width}).primitives;
    const rtl = catalog.sampleMotion(id, 0.5, {width, rtl: true}).primitives;
    assert.notDeepEqual(ltr, rtl, id);
    const mirror = (left, right, offset = 0) => {
      assert(Math.abs(left.x + right.x + offset - width) < 1e-8, id);
      assert.equal(left.y, right.y);
    };
    ltr.forEach((shape, index) => {
      const reflected = rtl[index];
      if (shape.type === 'polyline') shape.points.forEach((point, i) => mirror(point, reflected.points[i]));
      else mirror(shape, reflected, shape.width);
      if (shape.type === 'text') assert.equal(shape.text, reflected.text);
    });
    const rest = (time, x) => catalog.sampleMotion(id, time, {width, reducedMotion: true, interaction: {x, y: 0}});
    assert.deepEqual(rest(0, -1), rest(1, 1), id);
  }
});

test('scan boundary never exposes highlighted geometry ahead of the scanner', () => {
  const scan = (t) => catalog.sampleMotion('hologram-scanline-reveal', t).primitives;
  const checked = (t) => {
    const shapes = scan(t);
    const scanner = shapes.at(-1).points[0].x;
    const highlighted = shapes.filter((shape) => shape.type === 'polyline' && (shape.stroke === '#67e8f9' || shape.stroke === '#a78bfa'));
    for (const path of highlighted) for (const point of path.points) assert(point.x <= scanner + 1e-8);
    return scanner;
  };
  assert(checked(0.15) < checked(0.85));
});

test('projected hologram follows pointer inputs without time advancing', () => {
  const rotate = (x, y) => catalog.sampleMotion('hologram-interactive-rotation', 0.5, {interaction: {x, y}});
  const origin = stripped(rotate(0, 0));
  assert.notEqual(origin, stripped(rotate(1, 0)));
  assert.notEqual(origin, stripped(rotate(0, 1)));
});

test('time series cursor tracks the partial line endpoint', () => {
  const trace = (t) => {
    const scene = catalog.sampleMotion('dashboard-time-series-reveal', t);
    const [line, cursor, marker, sample] = scene.primitives.slice(-4);
    assert.equal(line.points.at(-1).x, cursor.points[0].x);
    assert.equal(line.points.at(-1).x, marker.x);
    assert.equal(line.points.at(-1).y, marker.y);
    return {x: marker.x, sample: Number(sample.text)};
  };
  const early = trace(0.1), later = trace(0.8);
  assert(later.x > early.x);
  assert(later.sample > early.sample);
});

test('Sankey links conserve widths at both pairs of source and destination nodes', () => {
  const frame = catalog.sampleMotion('dashboard-sankey-flow', 1);
  const flows = frame.primitives.slice(-12, -4).filter((_, index) => index % 2 === 1);
  const nodes = frame.primitives.slice(-4);
  const total = (a, b) => flows[a].lineWidth + flows[b].lineWidth;
  assert(Math.abs(total(0, 1) - nodes[0].height) < 1e-8);
  assert(Math.abs(total(2, 3) - nodes[1].height) < 1e-8);
  assert(Math.abs(total(0, 2) - nodes[2].height) < 1e-8);
  assert(Math.abs(total(1, 3) - nodes[3].height) < 1e-8);
});

test('unknown IDs and out-of-domain sampling options are rejected', () => {
  const name = 'dashboard-kpi-flow';
  for (const [id, t, options] of [
    ['unknown', 0, {}], [name, NaN, {}], [name, 0.5, {height: 0}],
    [name, 0.5, {interaction: {x: 0, y: 2}}], [name, 0.5, {intensity: Infinity}],
    [name, 0.5, {rtl: 1}], [name, 0.5, {reducedMotion: 'full'}],
  ]) assert.throws(() => catalog.sampleMotion(id, t, options), RangeError);
});
