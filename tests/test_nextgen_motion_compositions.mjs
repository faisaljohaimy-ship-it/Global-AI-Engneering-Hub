import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import * as catalog from '../motion-library/expansion/nextgen-motion-compositions.mjs';
import {createMotionSystem, validateScene} from '../packages/motion-sdk/index.mjs';

const inventory = JSON.parse(readFileSync(new URL('../docs/evidence/nextgen-cinematic-inventory.json', import.meta.url)));
const geometry = (scene) => JSON.stringify(scene.primitives.map(({fill, stroke, opacity, text, ...shape}) => shape));
const audio = 'compositions-audio-reactive-neural';
const universe = 'compositions-adaptive-universe';
const story = 'compositions-infinite-storytelling';
const sample = (id, time, options) => validateScene(catalog.sampleMotion(id, time, options));

test('composition identities are independently defined members of the owner inventory', () => {
  const assigned = new Set([192, 193, 194, 195, 196, 197, 199]);
  const expected = inventory.motions.filter((entry) => assigned.has(entry.number)).map((entry) => entry.id);
  assert.equal(expected.length, 7);
  assert.deepEqual(catalog.definitions.map((entry) => entry.id), expected);
  for (const row of catalog.definitions) {
    assert.match(row.name_ar, /\p{Script=Arabic}/u);
    assert(row.mechanism);
    assert.match(row.runtime_status, /proof/);
  }
});

test('all compositions vary at three times, export, and honor RTL and reduced motion', () => {
  const sdk = createMotionSystem();
  sdk.registerCatalog(catalog);
  for (const [width, height] of [[390, 844], [1280, 720]]) {
    const trajectories = new Set();
    for (const {id} of catalog.definitions) {
      const options = {width, height};
      const clip = sdk.create(id, {...options, reducedMotion: 'full'});
      const frames = [0.1, 0.5, 0.9].map((time) => clip.render(time));
      const shapes = frames.map(geometry);
      assert.equal(new Set(shapes).size, 3, id);
      const trajectory = shapes.join('\n');
      assert(!trajectories.has(trajectory), id);
      trajectories.add(trajectory);
      assert.deepEqual(clip.render(0.5), frames[1]);
      assert.match(clip.export('svg', 0.5), /<svg/);
      clip.configure({reducedMotion: 'reduce'});
      assert.deepEqual(clip.render(0.1), clip.render(0.9));
      clip.configure({reducedMotion: 'full', rtl: true});
      const reflected = clip.render(0.5);
      assert.notEqual(geometry(reflected), geometry(frames[1]), id);
      for (const [index, left] of frames[1].primitives.entries()) {
        const right = reflected.primitives[index];
        const mirror = (a, b, extent = 0) => {
          assert(Math.abs(a.x + b.x + extent - width) < 1e-6, id);
          assert.equal(a.y, b.y, id);
        };
        if (left.type === 'polyline') left.points.forEach((point, i) => mirror(point, right.points[i]));
        else mirror(left, right, left.width);
        if (left.type === 'text') assert.equal(left.text, right.text);
      }
      clip.destroy();
    }
  }
  assert.equal(sdk.getCapabilities().live_instances, 0);
});

test('audio input resolves the expected spectrum bin and influences geometry', () => {
  const tone = (bin) => Array.from({length: 64}, (_, i) => Math.sin(2 * Math.PI * bin * i / 64) * 0.6);
  const four = sample(audio, 0.5, {pcm_samples: tone(4)});
  const six = sample(audio, 0.5, {pcm_samples: tone(6)});
  assert.equal(four.meta.audio_input, 'supplied-normalized-pcm');
  assert(Math.abs(four.meta.spectrum[3] - 0.6) < 1e-10);
  assert(four.meta.spectrum[5] < 1e-10);
  assert(Math.abs(six.meta.spectrum[5] - 0.6) < 1e-10);
  assert.notEqual(geometry(four), geometry(six));
  assert.equal(sample(audio, 0.5).meta.audio_input, 'synthetic-signal');
  assert.deepEqual(
    sample(audio, 0.1, {pcm_samples: tone(4), reducedMotion: true}),
    sample(audio, 0.9, {pcm_samples: tone(6), reducedMotion: true}),
  );
});

test('star point count is bounded and responds to viewport and detail', () => {
  const small = sample(universe, 0.5, {width: 390, height: 820, detail: 6});
  const large = sample(universe, 0.5, {width: 1280, height: 720, detail: 6});
  const detailed = sample(universe, 0.5, {width: 1280, height: 720, detail: 24});
  assert(small.meta.point_budget < large.meta.point_budget);
  assert(large.meta.point_budget < detailed.meta.point_budget);
  assert(detailed.meta.point_budget <= 132);
  assert.notEqual(geometry(sample(universe, 0.5, {seed: 1})), geometry(sample(universe, 0.5, {seed: 2})));
});

test('story cards return to the same geometry and label order on a complete cycle', () => {
  const start = sample(story, 0), end = sample(story, 1);
  assert.deepEqual(start.primitives, end.primitives);
  assert.notDeepEqual(start.primitives, sample(story, 0.83).primitives);
});

test('invalid identity, dimensions, PCM, seed and detail fail without a frame', () => {
  for (const args of [
    ['unknown', 0.5, {}], [audio, 0.5, {height: 0}], [audio, NaN, {}],
    [audio, 0.5, {pcm_samples: [0.5]}], [audio, 0.5, {pcm_samples: Array(16)}],
    [audio, 0.5, {pcm_samples: Array(16).fill(1.01)}],
    [universe, 0.5, {seed: -1}], [universe, 0.5, {detail: 6.5}],
  ]) assert.throws(() => sample(...args), RangeError);
});
