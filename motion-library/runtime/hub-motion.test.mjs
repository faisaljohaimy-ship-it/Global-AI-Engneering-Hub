import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { test } from 'node:test';
import {
  counterValueAt, cubicBezier, ease, formatCounter, graphemes, segments, staggerDelays, toKeyframes, typewriterAt, validateSpec,
} from './hub-motion.mjs';

const specsDir = new URL('../specs/', import.meta.url);
const specs = readdirSync(specsDir).filter((name) => name.endsWith('.json'))
  .map((name) => JSON.parse(readFileSync(new URL(name, specsDir), 'utf8')));
const fadeIn = () => structuredClone(specs.find((spec) => spec.id === 'ui-fade-in'));

test('every committed specification is accepted', () => {
  assert.ok(specs.length >= 23);
  for (const spec of specs) assert.equal(validateSpec(spec), spec);
  assert.equal(new Set(specs.map((spec) => spec.id)).size, specs.length);
});

test('the runtime rejects what the Python compiler rejects', () => {
  const unordered = fadeIn();
  unordered.keyframes[0].offset = 1;
  assert.throws(() => validateSpec(unordered), /ordered/);
  const injected = fadeIn();
  injected.keyframes[0].opacity = '0; color: red';
  assert.throws(() => validateSpec(injected), /Unsafe/);
  const property = fadeIn();
  property.keyframes[0].width = '10px';
  assert.throws(() => validateSpec(property), /Unsupported or empty/);
  assert.throws(() => validateSpec({ ...fadeIn(), id: 'Bad Id' }), /Invalid motion id/);
  assert.throws(() => validateSpec({ ...fadeIn(), duration_ms: 0 }), /duration_ms/);
  assert.throws(() => validateSpec({ ...fadeIn(), easing: 'steps(2)' }), /easing/);
  assert.throws(() => validateSpec({ ...fadeIn(), reduced_motion: {} }), /reduced_motion/);
});

test('easing curves match the CSS definitions', () => {
  for (const name of ['linear', 'ease', 'ease-in', 'ease-out', 'ease-in-out']) {
    assert.equal(ease(name, 0), 0);
    assert.equal(ease(name, 1), 1);
    let previous = 0;
    for (let step = 1; step <= 100; step += 1) {
      const value = ease(name, step / 100);
      assert.ok(value >= previous - 1e-9, `${name} must not go backwards`);
      previous = value;
    }
  }
  assert.ok(Math.abs(ease('linear', 0.37) - 0.37) < 1e-9);
  assert.ok(Math.abs(ease('ease-in-out', 0.5) - 0.5) < 1e-9);
  assert.ok(Math.abs(ease('ease', 0.5) - 0.8024) < 5e-4);
  assert.ok(ease('ease-out', 0.5) > 0.5 && ease('ease-in', 0.5) < 0.5);
  // Independent reference: scan the parametric curve finely and interpolate at x.
  const [x1, y1, x2, y2] = [0.25, 0.1, 0.25, 1];
  const point = (a, b, t) => 3 * a * t * (1 - t) ** 2 + 3 * b * t * t * (1 - t) + t ** 3;
  const curve = cubicBezier(x1, y1, x2, y2);
  for (const x of [0.1, 0.25, 0.4, 0.6, 0.75, 0.9]) {
    let t = 0;
    while (point(x1, x2, t) < x) t += 1e-5;
    assert.ok(Math.abs(curve(x) - point(y1, y2, t)) < 1e-3, `ease at ${x}`);
  }
});

test('keyframes are converted for Element.animate', () => {
  const frames = toKeyframes({ easing: 'ease-out', keyframes: [{ offset: 0, 'background-color': 'red', opacity: 0 }, { offset: 1, opacity: 1 }] });
  assert.deepEqual(frames[0], { offset: 0, easing: 'ease-out', backgroundColor: 'red', opacity: '0' });
});

test('typewriter cuts only between graphemes, including Arabic marks', () => {
  const arabic = 'مَرْحَبًا بِالعَالَم';
  const parts = graphemes(arabic, 'ar');
  assert.ok(parts.length < Array.from(arabic).length, 'combining marks stay attached to their letter');
  for (let count = 0; count <= parts.length; count += 1) {
    assert.equal(typewriterAt(arabic, count / parts.length, 'ar'), parts.slice(0, count).join(''));
  }
  const words = segments(arabic, 'ar', 'word');
  assert.deepEqual(words, ['مَرْحَبًا', ' ', 'بِالعَالَم']);
  assert.equal(typewriterAt(arabic, 1 / 3, 'ar', 'word'), 'مَرْحَبًا');
  assert.equal(typewriterAt(arabic, 1, 'ar', 'word'), arabic);
  assert.equal(graphemes('👨‍👩‍👧').length, 1);
  assert.equal(typewriterAt('abc', -1), '');
  assert.equal(typewriterAt('abc', 2), 'abc');
});

test('counter values are deterministic and localised', () => {
  assert.equal(counterValueAt(0, 500, 0), 0);
  assert.equal(counterValueAt(0, 500, 1), 500);
  assert.equal(counterValueAt(10, 20, 0.5, 'linear'), 15);
  assert.ok(counterValueAt(0, 100, 0.5) > 50, 'ease-out is ahead of linear at the midpoint');
  assert.equal(formatCounter(1234.4), '1,234');
  assert.equal(formatCounter(1234, { locale: 'ar-SA' }), '١٬٢٣٤');
});

test('stagger delays are evenly spaced', () => {
  assert.deepEqual(staggerDelays(4, 30), [0, 30, 60, 90]);
  assert.deepEqual(staggerDelays(3, 40, 100), [100, 140, 180]);
  assert.deepEqual(staggerDelays(0), []);
});
