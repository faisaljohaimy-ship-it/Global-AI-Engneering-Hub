#!/usr/bin/env node
// Runtime evidence for hub motion. Every css and waapi component in components.json is
// played in a real browser engine, once from the CSS the Python compiler emits and once
// through the JavaScript runtime, and the values the engine computed are recorded. The
// Motion Lab is then driven like a user would: every component is selected and played.
// Playwright is a tool of the machine running this script, not a dependency of the hub:
//
//   node motion-library/verify/browser.mjs            verify, print a summary
//   node motion-library/verify/browser.mjs --write    also rewrite the evidence file

import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { serve } from './serve.mjs';

const library = resolve(fileURLToPath(new URL('..', import.meta.url)));
const repository = resolve(library, '..');
const evidencePath = join(library, 'evidence', 'chromium.json');
const digest = (data) => createHash('sha256').update(data).digest('hex');
const labFiles = ['index.html', 'styles.css', 'motions.css', 'app.mjs'];

let playwright;
try {
  playwright = createRequire(import.meta.url)('playwright');
} catch {
  console.error('Playwright with Chromium is required to produce browser evidence.');
  process.exit(2);
}

const manifest = JSON.parse(readFileSync(join(library, 'components.json'), 'utf8'));
const specs = manifest.components.filter((row) => row.engine === 'css' || row.engine === 'waapi').map((row) => {
  const path = join(library, row.spec);
  const css = execFileSync('python3', [join(library, 'compile.py'), path], { encoding: 'utf8' });
  return { engine: row.engine, source: `motion-library/${row.spec}`, css, spec: JSON.parse(readFileSync(path, 'utf8')) };
});
const server = await serve(repository);

// Runs in the page: the animation is paused and moved to exact times, and every value
// is read back from the engine's computed style.
function inspectSpec({ spec, css, reduced }) {
  const hub = window.hub;
  const stage = document.getElementById('stage');
  stage.replaceChildren();
  document.getElementById('compiled').textContent = css;
  const names = [...new Set(spec.keyframes.flatMap((frame) => Object.keys(frame).filter((key) => key !== 'offset')))];
  const make = (dir = 'ltr') => {
    const wrap = document.createElement('div');
    wrap.dir = dir;
    const element = document.createElement('div');
    element.className = 'box';
    wrap.append(element);
    stage.append(wrap);
    return element;
  };
  const read = (element, keys = names) => Object.fromEntries(keys.map((key) => [key, getComputedStyle(element).getPropertyValue(key)]));
  const reference = (declarations) => {
    const element = make();
    const keys = Object.keys(declarations).filter((key) => key !== 'offset');
    for (const key of keys) element.style.setProperty(key, String(declarations[key]));
    const values = read(element, keys);
    element.parentElement.remove();
    return values;
  };
  const number = /-?\d*\.?\d+(?:e-?\d+)?/g;
  const near = (a, b) => {
    const left = (a.match(number) || []).map(Number);
    const right = (b.match(number) || []).map(Number);
    return a.replace(number, '#') === b.replace(number, '#') && left.length === right.length
      && left.every((value, index) => Math.abs(value - right[index]) <= 0.001 + 0.001 * Math.abs(right[index]));
  };
  const matches = (actual, expected) => Object.keys(expected).every((key) => near(actual[key], expected[key]));
  const checks = {};
  const reducedState = reference(spec.reduced_motion);
  const atRest = (element) => matches(read(element, Object.keys(reducedState)), reducedState);
  const className = 'hub-motion-' + spec.id;

  if (reduced) {
    const directions = spec.rtl_mirror ? ['ltr', 'rtl'] : ['ltr'];
    checks.reducedMotionDisablesAnimation = directions.every((dir) => {
      const element = make(dir);
      element.classList.add(className);
      return getComputedStyle(element).animationName === 'none' && element.getAnimations().length === 0 && atRest(element);
    });
    const target = make();
    checks.runtimeHonoursMediaQuery = hub.play(target, spec) === null && atRest(target);
    return { checks };
  }

  const element = make();
  element.classList.add(className);
  const animation = element.getAnimations()[0];
  const at = (player, target, time) => {
    player.currentTime = time;
    return read(target);
  };
  checks.cssAnimationCreated = Boolean(animation) && animation.animationName === 'hub-' + spec.id;
  if (!checks.cssAnimationCreated) return { checks };
  const timing = animation.effect.getTiming();
  const intervals = animation.effect.getKeyframes().slice(0, -1);
  checks.timingMatchesSpec = timing.duration === spec.duration_ms && timing.fill === 'both'
    && intervals.length === spec.keyframes.length - 1 && intervals.every((frame) => frame.easing === spec.easing);
  animation.pause();
  const duration = spec.duration_ms;
  const start = at(animation, element, 0);
  const end = at(animation, element, duration);
  const middle = at(animation, element, duration / 2);
  checks.startMatchesFirstKeyframe = matches(start, reference(spec.keyframes[0]));
  checks.endMatchesLastKeyframe = matches(end, reference(spec.keyframes.at(-1)));
  const between = [0.1, 0.25, 0.5, 0.75, 0.9].map((progress) => at(animation, element, progress * duration));
  const moving = names.filter((key) => start[key] !== end[key]);
  checks.interpolatesBetweenEnds = moving.every((key) => between.some((sample) => sample[key] !== start[key] && sample[key] !== end[key]));

  // Interior keyframes are checked exactly wherever eased progress lands on their offset.
  const interior = spec.keyframes.slice(1, -1).filter((frame) => spec.easing === 'linear' || (spec.easing === 'ease-in-out' && frame.offset === 0.5));
  if (interior.length) {
    checks.interiorKeyframesExact = interior.every((frame) => matches(at(animation, element, frame.offset * duration), reference(frame)));
  }
  // The runtime's easing maths is compared with the engine's own timing function.
  const [first, last] = [spec.keyframes[0], spec.keyframes.at(-1)];
  if (spec.keyframes.length === 2 && typeof first.opacity === 'number' && typeof last.opacity === 'number') {
    checks.easingMatchesEngine = [0.2, 0.5, 0.8].every((progress) => {
      const expected = first.opacity + (last.opacity - first.opacity) * hub.ease(spec.easing, progress);
      return Math.abs(Number(at(animation, element, progress * duration).opacity) - expected) < 0.005;
    });
  }
  const measured = { start, middle, end };
  const sampleTimes = [0, 0.25, 0.5, 0.75, 1].map((progress) => progress * duration);
  const played = make();
  const player = hub.play(played, spec, { reducedMotion: false });
  player.pause();
  checks.runtimeMatchesCompiledCss = sampleTimes.every((time) => matches(at(player, played, time), at(animation, element, time)));
  const still = make();
  checks.runtimeReducedState = hub.play(still, spec, { reducedMotion: true }) === null && atRest(still);

  if (spec.rtl_mirror) {
    const travel = (value) => Number((value.match(/matrix\(([^)]+)\)/) || ['', '1,0,0,1,0,0'])[1].split(',')[4]);
    const mirrored = make('rtl');
    mirrored.classList.add(className);
    const mirroredAnimation = mirrored.getAnimations()[0];
    mirroredAnimation.pause();
    const ltr = travel(at(animation, element, 0).transform);
    const rtl = travel(at(mirroredAnimation, mirrored, 0).transform);
    checks.compiledCssMirrorsUnderRtl = mirroredAnimation.animationName === `hub-${spec.id}-rtl` && ltr !== 0 && Math.abs(ltr + rtl) < 0.02;
    const mirroredPlayed = make('rtl');
    const mirroredPlayer = hub.play(mirroredPlayed, spec, { reducedMotion: false });
    mirroredPlayer.pause();
    checks.runtimeMirrorsLikeCompiledCss = sampleTimes.every((time) => matches(at(mirroredPlayer, mirroredPlayed, time), at(mirroredAnimation, mirrored, time)));
    measured.horizontalTravelPx = { ltr, rtl };
  }
  return { checks, measured };
}

async function inspectBehaviours(slideUp) {
  const hub = window.hub;
  const stage = document.getElementById('stage');
  stage.replaceChildren();
  const results = {};

  const list = document.createElement('ul');
  for (let index = 0; index < 4; index += 1) list.append(document.createElement('li'));
  stage.append(list);
  const players = hub.stagger(list.children, slideUp, { each: 40, reducedMotion: false });
  hub.seek(players, 150);
  const opacities = Array.from(list.children, (item) => Number(getComputedStyle(item).opacity));
  results.stagger = {
    checks: {
      delaysEvenlySpaced: players.map((item) => item.effect.getTiming().delay).join() === '0,40,80,120',
      laterItemsTrailEarlierOnes: opacities.every((value, index) => index === 0 || value < opacities[index - 1]),
      reducedMotionSkipsAnimation: hub.stagger(list.children, slideUp, { reducedMotion: true }).every((item) => item === null),
    },
    measured: { opacitiesAt150ms: opacities },
  };

  const text = 'مَرْحَبًا بِالعَالَم';
  const line = document.createElement('p');
  line.dir = 'rtl';
  line.lang = 'ar';
  stage.append(line);
  const parts = hub.graphemes(text, 'ar');
  let wholeGraphemes = true;
  for (let count = 0; count <= parts.length; count += 1) {
    hub.renderTypewriter(line, text, count / parts.length, 'ar');
    wholeGraphemes &&= line.textContent === parts.slice(0, count).join('');
  }
  const words = hub.segments(text, 'ar', 'word');
  let byWord = words.length === 3;
  for (let count = 0; count <= words.length; count += 1) {
    hub.renderTypewriter(line, text, count / words.length, 'ar', 'word');
    byWord &&= line.textContent === words.slice(0, count).join('');
  }
  let drawn = [];
  await hub.run((progress) => { hub.renderTypewriter(line, text, progress, 'ar'); drawn.push(progress); }, 80, { reducedMotion: false });
  const animated = drawn.length > 1 && drawn.at(-1) === 1 && line.textContent === text;
  drawn = [];
  await hub.run((progress) => drawn.push(progress), 80, { reducedMotion: true });
  results.typewriterAt = {
    checks: {
      cutsOnlyBetweenGraphemes: wholeGraphemes && parts.length < Array.from(text).length,
      fullTextStaysAccessible: line.getAttribute('aria-label') === text,
      rightToLeftLayout: getComputedStyle(line).direction === 'rtl',
      animationEndsOnFullText: animated,
      reducedMotionRendersFinalStateOnce: drawn.join() === '1',
      wordUnitKeepsJoinedWordsWhole: byWord,
    },
    measured: { graphemes: parts.length, codePoints: Array.from(text).length },
  };

  const figure = document.createElement('span');
  stage.append(figure);
  const shown = (progress, options) => { hub.renderCounter(figure, 0, 2500, progress, options); return figure.textContent; };
  results.counterValueAt = {
    checks: {
      endpointsExact: shown(0, {}) === '0' && shown(1, {}) === '2,500',
      linearMidpoint: shown(0.5, { easing: 'linear' }) === '1,250',
      easedMidpointAheadOfLinear: hub.counterValueAt(0, 2500, 0.5) > 1250,
      arabicIndicDigits: shown(1, { locale: 'ar-SA' }) === '٢٬٥٠٠',
    },
    measured: { easeOutMidpoint: hub.counterValueAt(0, 2500, 0.5) },
  };
  return results;
}

// Runs in the Motion Lab after Play: compares the lab's own animation with the
// specification played beside it, at five moments.
async function compareLabWithSpec(specPath) {
  const hub = await import('/motion-library/runtime/hub-motion.mjs');
  const spec = await (await fetch(specPath)).json();
  const stage = document.getElementById('stage');
  const targets = stage.querySelectorAll('#preview span').length ? [...stage.querySelectorAll('#preview span')] : [document.getElementById('preview')];
  const target = targets[0];
  const player = target.getAnimations()[0];
  if (!player) return { playing: false };
  const names = [...new Set(spec.keyframes.flatMap((frame) => Object.keys(frame).filter((key) => key !== 'offset')))];
  const twin = target.cloneNode(true);
  twin.removeAttribute('id');
  twin.className = target.className.split(' ').filter((name) => !name.startsWith('run-')).join(' ');
  target.after(twin);
  const reference = hub.play(twin, spec, { reducedMotion: false });
  const delay = player.effect.getTiming().delay;
  player.pause();
  reference.pause();
  const number = /-?\d*\.?\d+(?:e-?\d+)?/g;
  const near = (a, b) => {
    const left = (a.match(number) || []).map(Number);
    const right = (b.match(number) || []).map(Number);
    return a.replace(number, '#') === b.replace(number, '#') && left.length === right.length
      && left.every((value, index) => Math.abs(value - right[index]) <= 0.001 + 0.001 * Math.abs(right[index]));
  };
  let worst = 0;
  const same = [0, 0.25, 0.5, 0.75, 1].every((progress) => {
    player.currentTime = delay + progress * spec.duration_ms;
    reference.currentTime = progress * spec.duration_ms;
    return names.every((name) => {
      const [a, b] = [getComputedStyle(target).getPropertyValue(name), getComputedStyle(twin).getPropertyValue(name)];
      if (name === 'opacity') worst = Math.max(worst, Math.abs(Number(a) - Number(b)));
      return near(a, b);
    });
  });
  twin.remove();
  player.cancel();
  return { playing: true, matchesSpecification: same, largestOpacityDifference: Number(worst.toFixed(4)) };
}

const browser = await playwright.chromium.launch();
const results = [];
let engine;
try {
  const page = await browser.newPage({ viewport: { width: 800, height: 600 } });
  const problems = [];
  page.on('pageerror', (error) => problems.push(String(error)));
  await page.goto(`${server.origin}/motion-library/verify/harness.html`);
  await page.waitForFunction(() => window.hub);
  for (const { spec, css, source, engine: componentEngine } of specs) {
    await page.emulateMedia({ reducedMotion: 'no-preference' });
    const motion = await page.evaluate(inspectSpec, { spec, css, reduced: false });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    const still = await page.evaluate(inspectSpec, { spec, css, reduced: true });
    const checks = { ...motion.checks, ...still.checks };
    results.push({ id: spec.id, kind: 'spec', engine: componentEngine, source, css_sha256: digest(css), pass: Object.values(checks).every(Boolean), checks, measured: motion.measured });
  }
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  const slideUp = specs.find((item) => item.spec.id === 'ui-slide-up');
  await page.evaluate((css) => { document.getElementById('compiled').textContent = css; }, slideUp.css);
  const behaviours = await page.evaluate(inspectBehaviours, slideUp.spec);
  for (const [name, { checks, measured }] of Object.entries(behaviours)) {
    results.push({ id: `runtime-${name}`, kind: 'runtime', implementation: `motion-library/runtime/hub-motion.mjs#${name}`, pass: Object.values(checks).every(Boolean), checks, measured });
  }
  // Decoding a screenshot in the harness page tells a drawn canvas from a blank one.
  const colours = (png) => page.evaluate(async (data) => {
    const image = new Image();
    image.src = 'data:image/png;base64,' + data;
    await image.decode();
    const canvas = document.createElement('canvas');
    [canvas.width, canvas.height] = [image.width, image.height];
    const context = canvas.getContext('2d');
    context.drawImage(image, 0, 0);
    const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
    const seen = new Set();
    for (let index = 0; index < pixels.length; index += 4 * 97) seen.add(`${pixels[index]},${pixels[index + 1]},${pixels[index + 2]}`);
    return seen.size;
  }, png.toString('base64'));

  // The Motion Lab, driven through its own controls.
  const lab = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  lab.on('pageerror', (error) => problems.push('lab: ' + String(error)));
  await lab.emulateMedia({ reducedMotion: 'no-preference' });
  await lab.goto(`${server.origin}/motion-lab/index.html`);
  await lab.waitForFunction(() => document.documentElement.dataset.labReady === 'true', null, { timeout: 15000 });
  const counts = await lab.evaluate(() => Object.fromEntries(['indexedCount', 'implementedCount', 'testedCount', 'usedCount'].map((id) => [id, Number(document.getElementById(id).textContent)])));
  const choose = async (id, direction = 'ltr', mode = 'full') => {
    await lab.selectOption('#direction', direction);
    await lab.selectOption('#motionMode', mode);
    await lab.click(`#motionList button[data-id="${id}"]`);
    await lab.click('#play');
    await lab.evaluate(() => new Promise((painted) => requestAnimationFrame(() => requestAnimationFrame(painted))));
    return lab.evaluate(() => document.getElementById('previewNote')?.textContent ?? '');
  };
  const played = {};
  for (const row of manifest.components) {
    const note = await choose(row.id);
    const entry = { engine: row.engine, startedWithoutError: !/fail/i.test(note) };
    if (row.engine === 'css' || row.engine === 'waapi') {
      Object.assign(entry, await lab.evaluate(compareLabWithSpec, `/motion-library/${row.spec}`));
    } else if (await lab.locator('#stage canvas').count()) {
      await lab.waitForTimeout(250);
      entry.canvasColours = await colours(await lab.locator('#stage canvas').screenshot({ type: 'png' }));
      entry.drawsOnCanvas = entry.canvasColours > 2;
    } else {
      // The cross-dissolve adapter drives two DOM layers; it must finish on the incoming one.
      await lab.waitForTimeout(JSON.parse(readFileSync(join(library, row.spec), 'utf8')).duration_ms + 300);
      entry.layerOpacities = await lab.evaluate(() => Array.from(document.querySelectorAll('#stage .dissolve-layer'), (layer) => Number(layer.style.opacity)));
      entry.reachesEndState = entry.layerOpacities.join() === '0,1';
    }
    played[row.id] = entry;
  }
  await choose('ui-fade-in', 'ltr', 'reduce');
  const reducedInLab = await lab.evaluate(() => {
    const preview = document.getElementById('preview');
    return preview.getAnimations().length === 0 && getComputedStyle(preview).opacity === '1';
  });
  const travelIn = async (direction) => {
    await choose('ui-slide-inline-start', direction);
    return lab.evaluate(() => {
      const preview = document.getElementById('preview');
      const player = preview.getAnimations()[0];
      player.pause();
      player.currentTime = 0;
      return Number((getComputedStyle(preview).transform.match(/matrix\(([^)]+)\)/) || ['', '1,0,0,1,0,0'])[1].split(',')[4]);
    });
  };
  const labTravel = { ltr: await travelIn('ltr'), rtl: await travelIn('rtl') };
  const rows = Object.values(played);
  const labChecks = {
    loadsWithoutPageErrors: problems.filter((problem) => problem.startsWith('lab:')).length === 0,
    countsMatchManifest: counts.indexedCount === manifest.catalog_total && [counts.implementedCount, counts.testedCount, counts.usedCount].every((value) => value === manifest.components.length),
    everyComponentStartsWithoutError: rows.every((row) => row.startedWithoutError),
    everyCssAndWaapiComponentAnimates: rows.filter((row) => 'playing' in row).every((row) => row.playing),
    everyCanvasComponentDraws: rows.filter((row) => 'drawsOnCanvas' in row).every((row) => row.drawsOnCanvas),
    adapterLayersReachEndState: rows.filter((row) => 'reachesEndState' in row).every((row) => row.reachesEndState),
    cssComponentsMatchTheirSpecification: rows.filter((row) => row.engine === 'css').every((row) => row.matchesSpecification),
    reducedModeAppliesEndStateWithoutAnimation: reducedInLab,
    inlineTravelMirrorsUnderRtl: labTravel.ltr !== 0 && Math.abs(labTravel.ltr + labTravel.rtl) < 0.02,
  };
  results.push({
    id: 'motion-lab', kind: 'lab', pass: Object.values(labChecks).every(Boolean), checks: labChecks,
    measured: { counts, horizontalTravelPx: labTravel, components: played },
    findings: Object.entries(played).filter(([, row]) => row.engine === 'waapi' && row.matchesSpecification === false)
      .map(([id, row]) => `${id}: the lab eases the whole animation where the compiled CSS eases each keyframe interval (largest opacity difference ${row.largestOpacityDifference}).`),
  });
  for (const row of manifest.components.filter((item) => item.engine === 'glsl-webgl')) {
    const shader = JSON.parse(readFileSync(join(library, row.spec), 'utf8')).shader;
    const checks = { labLoads: labChecks.loadsWithoutPageErrors, shaderCompilesAndLinks: played[row.id].startedWithoutError, drawsOnCanvas: played[row.id].drawsOnCanvas };
    results.push({ id: row.id, kind: 'lab-engine', engine: row.engine, source: `motion-library/${shader}`, source_sha256: digest(readFileSync(join(library, shader))), pass: Object.values(checks).every(Boolean), checks, measured: { canvasColours: played[row.id].canvasColours } });
  }
  if (problems.length) results.push({ id: 'page-errors', kind: 'harness', pass: false, checks: { noPageErrors: false }, measured: { problems } });
  engine = { browser: 'chromium', version: browser.version(), playwright: createRequire(import.meta.url)('playwright/package.json').version, platform: process.platform };
} finally {
  await browser.close();
  server.close();
}

const failed = results.filter((result) => !result.pass);
const evidence = {
  schema_version: 1,
  notes: 'Generated by motion-library/verify/browser.mjs. Values were read from the engine, not asserted by hand. A result stays valid only while its css_sha256 or source_sha256 and the hashes below match the files in the repository.',
  generated_on: new Date().toISOString().slice(0, 10),
  engine,
  inputs: {
    runtime_sha256: digest(readFileSync(join(library, 'runtime', 'hub-motion.mjs'))),
    core_sha256: digest(readFileSync(join(library, 'runtime', 'core.mjs'))),
    lab_sha256: digest(Buffer.concat(labFiles.map((name) => readFileSync(join(repository, 'motion-lab', name))))),
  },
  summary: { passed: results.length - failed.length, failed: failed.length },
  results,
};
if (process.argv.includes('--write')) writeFileSync(evidencePath, JSON.stringify(evidence, null, 2) + '\n');
for (const result of failed) console.error(`FAIL ${result.id}: ${Object.entries(result.checks).filter(([, ok]) => !ok).map(([name]) => name).join(', ')}`);
for (const finding of results.flatMap((result) => result.findings ?? [])) console.log(`FINDING ${finding}`);
console.log(`${engine.browser} ${engine.version}: ${evidence.summary.passed} passed, ${evidence.summary.failed} failed`);
process.exit(failed.length ? 1 : 0);
