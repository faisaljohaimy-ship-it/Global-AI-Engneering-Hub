// Unit tests for the parts that need no browser: the definition contract, easing,
// springs, seeded randomness, text handling, quality tiers and the governor.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createGovernor, deviceTier, pickTier, TIERS } from '../core/capabilities.mjs';
import { createVirtualClock } from '../core/clock.mjs';
import { defineMotion, ENGINES, MODULES } from '../core/define.mjs';
import { ease, EASINGS } from '../core/easing.mjs';
import { settleTime, spring, wobble } from '../core/spring.mjs';
import { graphemes, isArabic, units, words } from '../core/text.mjs';
import { clamp, hexToRgb, mulberry32, pingPong, rgba, smoothstep, stage } from '../core/util.mjs';
import { resolveOptions } from '../core/api.mjs';
import { safeDeclarations } from '../adapters/behaviour.mjs';

const valid = () => ({
  id: 'quantum-test-motion', number: 901, module: 'quantum', name: { en: 'Test', ar: 'اختبار' },
  summary: { en: 'A test.', ar: 'اختبار.' }, engine: 'canvas2d', kind: 'loop', duration: 2000, easing: 'ease-out',
  colors: ['#000000', '#ffffff', '#ff0000'],
  params: { a: { default: 1, min: 0, max: 2, step: 0.1, label: { en: 'A', ar: 'أ' } }, b: { default: 3, min: 1, max: 5, step: 1, label: { en: 'B', ar: 'ب' } } },
  rtl: 'neutral', requirements: { gpu: 'none', cost: 'low' }, still: 0.5, tags: ['test'], setup: () => ({ render() {} }),
});

test('there are twenty modules and seven engines', () => {
  assert.equal(Object.keys(MODULES).length, 20);
  assert.deepEqual([...new Set(Object.values(MODULES).map((module) => module.letter))].join(''), 'ABCDEFGHIJKLMNOPQRST');
  assert.equal(ENGINES.length, 7);
});

test('a complete definition is accepted and frozen', () => {
  const motion = defineMotion(valid());
  assert.equal(motion.id, 'quantum-test-motion');
  assert.throws(() => { motion.id = 'x'; }, TypeError);
});

test('each missing or wrong field is refused', () => {
  const cases = {
    'id without module prefix': (d) => { d.id = 'test-motion'; },
    'unknown module': (d) => { d.module = 'nope'; },
    'no Arabic name': (d) => { d.name.ar = 'Test'; },
    'no Arabic summary': (d) => { d.summary.ar = 'A test.'; },
    'unknown engine': (d) => { d.engine = 'flash'; },
    'unknown kind': (d) => { d.kind = 'forever'; },
    'duration out of range': (d) => { d.duration = 50; },
    'unknown easing': (d) => { d.easing = 'bouncy'; },
    'two colours only': (d) => { d.colors = ['#000', '#fff']; },
    'a colour that is not hex': (d) => { d.colors[1] = 'red'; },
    'one parameter only': (d) => { delete d.params.b; },
    'default outside its range': (d) => { d.params.a.default = 9; },
    'parameter without Arabic label': (d) => { delete d.params.a.label.ar; },
    'unknown direction mode': (d) => { d.rtl = 'flip'; },
    'unknown gpu requirement': (d) => { d.requirements.gpu = 'cuda'; },
    'still outside 0..1': (d) => { d.still = 1.5; },
    'no tags': (d) => { d.tags = []; },
    'no setup': (d) => { delete d.setup; },
    'text with different keys': (d) => { d.text = { en: { a: 'x' }, ar: { b: 'س' } }; },
    'text without Arabic': (d) => { d.text = { en: { a: 'x' }, ar: { a: 'x' } }; },
    'interactive without sample': (d) => { d.interactive = { note: { en: 'x', ar: 'س' } }; },
  };
  for (const [name, breakIt] of Object.entries(cases)) {
    const definition = valid();
    breakIt(definition);
    assert.throws(() => defineMotion(definition), TypeError, name);
  }
});

test('options are validated and clamped, and unknown ones are refused', () => {
  const motion = defineMotion({ ...valid(), text: { en: { title: 'Hello' }, ar: { title: 'مرحبا' } } });
  const settings = resolveOptions(motion, { params: { a: 99 }, colors: ['#111111'], direction: 'rtl' });
  assert.equal(settings.params.a, 2);
  assert.equal(settings.params.b, 3);
  assert.deepEqual(settings.colors, ['#111111', '#ffffff', '#ff0000']);
  assert.equal(settings.text.title, 'مرحبا');
  assert.equal(resolveOptions(motion, { locale: 'en' }).text.title, 'Hello');
  assert.equal(resolveOptions(motion, { text: { title: 'Custom' } }).text.title, 'Custom');
  assert.throws(() => resolveOptions(motion, { params: { nope: 1 } }), /Unknown parameter/);
  assert.throws(() => resolveOptions(motion, { text: { nope: 'x' } }), /Unknown text/);
  assert.throws(() => resolveOptions(motion, { duration: 5 }), /duration/);
  assert.throws(() => resolveOptions(motion, { easing: 'nope' }), /easing/);
  assert.throws(() => resolveOptions(motion, { colors: ['blue'] }), /Colours/);
  assert.throws(() => resolveOptions(motion, { quality: 'ultra' }), /quality/);
  assert.throws(() => resolveOptions(motion, { gpu: 'always' }), /gpu/);
});

test('every easing starts at 0, ends at 1 and matches the CSS curves at known points', () => {
  for (const name of EASINGS) {
    assert.equal(ease(name, 0), 0, name);
    assert.equal(ease(name, 1), 1, name);
  }
  assert.equal(ease('linear', 0.3), 0.3);
  // Reference values found independently by scanning the Bezier parameter.
  const reference = (x1, y1, x2, y2, x) => {
    let best = 0;
    let gap = Infinity;
    for (let step = 0; step <= 200000; step += 1) {
      const t = step / 200000;
      const at = 3 * (1 - t) ** 2 * t * x1 + 3 * (1 - t) * t * t * x2 + t ** 3;
      if (Math.abs(at - x) < gap) [gap, best] = [Math.abs(at - x), t];
    }
    return 3 * (1 - best) ** 2 * best * y1 + 3 * (1 - best) * best * best * y2 + best ** 3;
  };
  assert.ok(Math.abs(ease('ease-in-out', 0.25) - reference(0.42, 0, 0.58, 1, 0.25)) < 1e-4);
  assert.ok(Math.abs(ease('ease', 0.6) - reference(0.25, 0.1, 0.25, 1, 0.6)) < 1e-4);
  assert.ok(ease('ease-out-back', 0.7) > 1, 'back easing overshoots');
  assert.throws(() => ease('nope', 0.5), RangeError);
});

test('springs are closed-form: they start at rest, settle at the target and ring when underdamped', () => {
  assert.equal(spring(0), 0);
  assert.ok(Math.abs(spring(5) - 1) < 1e-6);
  const samples = Array.from({ length: 200 }, (_, index) => spring(index / 100, { frequency: 3, damping: 0.3 }));
  assert.ok(Math.max(...samples) > 1.05, 'an underdamped spring overshoots');
  assert.ok(Math.max(...Array.from({ length: 200 }, (_, index) => spring(index / 100, { damping: 1 }))) <= 1 + 1e-9, 'a critically damped spring does not');
  assert.ok(Math.abs(spring(settleTime({ frequency: 3, damping: 0.5 }) * 1.5, { frequency: 3, damping: 0.5 }) - 1) < 0.002);
  assert.equal(wobble(0), 0);
  assert.ok(Math.abs(wobble(4)) < 1e-4);
});

test('the same seed gives the same sequence, and helpers behave at their edges', () => {
  const [a, b, c] = [mulberry32(7), mulberry32(7), mulberry32(8)];
  const first = [a(), a(), a()];
  assert.deepEqual(first, [b(), b(), b()]);
  assert.notDeepEqual(first, [c(), c(), c()]);
  assert.ok(first.every((value) => value >= 0 && value < 1));
  assert.deepEqual(hexToRgb('#fff'), [1, 1, 1]);
  assert.throws(() => hexToRgb('fff'), RangeError);
  assert.equal(rgba([1, 0, 0.5], 0.5), 'rgba(255, 0, 128, 0.5)');
  assert.equal(clamp(5), 1);
  assert.equal(smoothstep(0, 1, 0.5), 0.5);
  assert.equal(stage(0.5, 0.25, 0.75), 0.5);
  assert.equal(pingPong(0.25), 0.5);
  assert.equal(pingPong(1.5), 1);
});

test('Arabic is moved by the word, other scripts by the grapheme', () => {
  assert.ok(isArabic('هندسة'));
  assert.ok(!isArabic('Engineering'));
  assert.deepEqual(words('  هندسة   تتحرك '), ['هندسة', 'تتحرك']);
  assert.deepEqual(units('هندسة تتحرك', 'ar').map((unit) => unit.text), ['هندسة', 'تتحرك']);
  assert.deepEqual(units('Go on', 'en').map((unit) => unit.text), ['G', 'o', 'o', 'n']);
  assert.equal(graphemes('éa', 'en').length, 2, 'a combining mark stays with its letter');
  assert.equal(graphemes('👨‍👩‍👧', 'en').length, 1, 'a joined emoji is one unit');
});

test('device tiers follow memory, cores, pointer and data saving', () => {
  assert.equal(deviceTier({ deviceMemory: 8, cores: 8 }), 'high');
  assert.equal(deviceTier({ deviceMemory: 4, cores: 8 }), 'medium');
  assert.equal(deviceTier({ deviceMemory: 2, cores: 8 }), 'low');
  assert.equal(deviceTier({ deviceMemory: 8, cores: 8, saveData: true }), 'low');
  assert.equal(deviceTier({ deviceMemory: 8, cores: 8, webgl2: false }), 'low');
  assert.equal(deviceTier({ deviceMemory: 8, cores: 8, coarsePointer: true, viewport: { width: 390, height: 844 } }), 'medium');
  assert.equal(deviceTier({}), 'high', 'unknown values count as capable');
  assert.equal(pickTier({ tier: 'medium' }, 'high'), 'low', 'a costly motion starts one step lower');
  assert.equal(pickTier({ tier: 'high' }, 'high'), 'high');
  assert.deepEqual(Object.keys(TIERS), ['high', 'medium', 'low']);
});

test('the governor lowers quality when frames run slow, raises it again, and never goes above its start', () => {
  const governor = createGovernor({ start: 'high', targetMs: 20, window: 4 });
  const feed = (ms, times) => Array.from({ length: times }, () => governor.sample(ms)).filter(Boolean);
  assert.deepEqual(feed(40, 4), ['medium']);
  assert.deepEqual(feed(40, 4), ['low']);
  assert.deepEqual(feed(40, 8), [], 'low is the floor: the motion keeps running');
  assert.deepEqual(feed(5, 12), ['medium'], 'three calm windows raise it one step');
  assert.deepEqual(feed(5, 12), ['high']);
  assert.deepEqual(feed(5, 24), [], 'never above the starting tier');
  assert.deepEqual(feed(18, 12), [], 'within budget: no change');
});

test('the virtual clock runs callbacks one step at a time and can cancel them', () => {
  const clock = createVirtualClock(10);
  const seen = [];
  const loop = (now) => {
    seen.push(now);
    if (seen.length < 3) clock.request(loop);
  };
  clock.request(loop);
  const cancelled = clock.request(() => seen.push('never'));
  clock.cancel(cancelled);
  clock.advance(100);
  assert.deepEqual(seen, [10, 20, 30]);
  assert.equal(clock.pending, 0);
});

test('a behaviour may only set visual properties, and never a url or markup', () => {
  assert.deepEqual(safeDeclarations({ transform: 'scale(1.1)', opacity: 0.5, '--glow': '#fff', position: 'fixed', background: 'url(x)', filter: 'url(#a)', boxShadow: '0 0 4px red;color:red' }),
    { transform: 'scale(1.1)', opacity: '0.5', '--glow': '#fff' });
});
