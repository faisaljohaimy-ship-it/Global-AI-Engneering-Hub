#!/usr/bin/env node
// Runtime evidence for hub motion. Plays every specification in a real browser engine,
// once from the CSS the Python compiler emits and once through the JavaScript runtime,
// and records what the engine actually computed. Playwright is a tool of the machine
// running this script, not a dependency of the hub:
//
//   node motion-library/verify/browser.mjs            verify, print a summary
//   node motion-library/verify/browser.mjs --write    also rewrite the evidence file

import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { serve } from './serve.mjs';

const library = resolve(fileURLToPath(new URL('..', import.meta.url)));
const evidencePath = join(library, 'evidence', 'chromium.json');
const digest = (data) => createHash('sha256').update(data).digest('hex');

let playwright;
try {
  playwright = createRequire(import.meta.url)('playwright');
} catch {
  console.error('Playwright with Chromium is required to produce browser evidence.');
  process.exit(2);
}

const server = await serve(library);

const specs = readdirSync(join(library, 'specs')).filter((name) => name.endsWith('.json')).sort().map((name) => {
  const source = `motion-library/specs/${name}`;
  const css = execFileSync('python3', [join(library, 'compile.py'), join(library, 'specs', name)], { encoding: 'utf8' });
  return { source, css, spec: JSON.parse(readFileSync(join(library, 'specs', name), 'utf8')) };
});

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

  if (reduced) {
    const element = make();
    element.classList.add('hub-motion-' + spec.id);
    checks.reducedMotionDisablesAnimation = getComputedStyle(element).animationName === 'none' && element.getAnimations().length === 0;
    checks.reducedMotionEndState = matches(read(element, Object.keys(reducedState)), reducedState);
    const target = make();
    checks.runtimeHonoursMediaQuery = hub.play(target, spec) === null && matches(read(target, Object.keys(reducedState)), reducedState);
    return { checks };
  }

  const element = make();
  element.classList.add('hub-motion-' + spec.id);
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
  if (spec.rtl_mirror === true) {
    const mirrored = make('rtl');
    mirrored.classList.add('hub-motion-' + spec.id);
    const player = mirrored.getAnimations()[0];
    player.pause();
    const travel = (value) => Number((value.match(/matrix\(([^)]+)\)/) || ['', '1,0,0,1,0,0'])[1].split(',')[4]);
    const ltr = travel(at(animation, element, 0).transform);
    const rtl = travel(at(player, mirrored, 0).transform);
    checks.rtlMirrorsInlineTravel = ltr !== 0 && Math.abs(ltr + rtl) < 0.02;
    const runtimeTarget = make('rtl');
    const runtimePlayer = hub.play(runtimeTarget, spec, { reducedMotion: false });
    runtimePlayer.pause();
    const runtimeRtl = travel(at(runtimePlayer, runtimeTarget, 0).transform);
    checks.runtimeMirrorsInlineTravel = Math.abs(runtimeRtl - rtl) < 0.02;
    measured.inlineTravelPx = { ltr, rtl };
  }
  const played = make();
  const player = hub.play(played, spec, { reducedMotion: false });
  player.pause();
  checks.runtimeMatchesCompiledCss = [0, 0.25, 0.5, 0.75, 1].every((progress) => {
    const time = progress * duration;
    return matches(at(player, played, time), at(animation, element, time));
  });
  const still = make();
  checks.runtimeReducedState = hub.play(still, spec, { reducedMotion: true }) === null
    && matches(read(still, Object.keys(reducedState)), reducedState);
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
  results['ui-staggered-list'] = {
    implementation: 'stagger',
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
  results['typography-typewriter'] = {
    implementation: 'typewriterAt',
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
  results['typography-counter-interpolation'] = {
    implementation: 'counterValueAt',
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

function inspectGlsl(fragmentSource) {
  const stage = document.getElementById('stage');
  stage.replaceChildren();
  const canvas = document.createElement('canvas');
  canvas.width = 64;
  canvas.height = 64;
  stage.append(canvas);
  const gl = canvas.getContext('webgl', { alpha: false, antialias: false });
  const checks = { webglContextCreated: Boolean(gl) };
  if (!gl) return { checks, measured: {} };
  const compile = (type, source) => {
    const shader = gl.createShader(type);
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    return shader;
  };
  const vertex = compile(gl.VERTEX_SHADER, 'attribute vec2 a_position; void main(){gl_Position=vec4(a_position,0.0,1.0);}');
  const fragment = compile(gl.FRAGMENT_SHADER, fragmentSource);
  checks.vertexShaderCompiled = gl.getShaderParameter(vertex, gl.COMPILE_STATUS);
  checks.fragmentShaderCompiled = gl.getShaderParameter(fragment, gl.COMPILE_STATUS);
  const program = gl.createProgram();
  gl.attachShader(program, vertex);
  gl.attachShader(program, fragment);
  gl.linkProgram(program);
  checks.programLinked = gl.getProgramParameter(program, gl.LINK_STATUS);
  if (!checks.vertexShaderCompiled || !checks.fragmentShaderCompiled || !checks.programLinked) {
    return { checks, measured: { shaderLog: gl.getShaderInfoLog(fragment), programLog: gl.getProgramInfoLog(program) } };
  }
  const buffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1, 1,-1, -1,1, -1,1, 1,-1, 1,1]), gl.STATIC_DRAW);
  gl.useProgram(program);
  const position = gl.getAttribLocation(program, 'a_position');
  gl.enableVertexAttribArray(position);
  gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);
  gl.uniform2f(gl.getUniformLocation(program, 'u_resolution'), canvas.width, canvas.height);
  const time = gl.getUniformLocation(program, 'u_time');
  const draw = (seconds) => {
    gl.uniform1f(time, seconds);
    gl.drawArrays(gl.TRIANGLES, 0, 6);
    const pixels = new Uint8Array(canvas.width * canvas.height * 4);
    gl.readPixels(0, 0, canvas.width, canvas.height, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
    return pixels;
  };
  const first = draw(0);
  const second = draw(1);
  const colours = new Set();
  for (let index = 0; index < first.length; index += 16) colours.add(first.slice(index, index + 4).join(','));
  checks.drawCompletedWithoutError = gl.getError() === gl.NO_ERROR;
  checks.drawsMultipleColours = colours.size > 2;
  checks.timeChangesPixels = first.some((value, index) => value !== second[index]);
  return { checks, measured: { sampledColours: colours.size } };
}

const executablePath = process.env.MOTION_CHROMIUM_EXECUTABLE;
const browser = await playwright.chromium.launch(executablePath ? { executablePath } : {});
const results = [];
try {
  const page = await browser.newPage({ viewport: { width: 800, height: 600 } });
  const problems = [];
  page.on('pageerror', (error) => problems.push(String(error)));
  await page.goto(`${server.origin}/verify/harness.html`);
  await page.waitForFunction(() => window.hub);
  for (const { spec, css, source } of specs) {
    if (spec.id === 'spatial-fresnel-rim') continue;
    await page.emulateMedia({ reducedMotion: 'no-preference' });
    const motion = await page.evaluate(inspectSpec, { spec, css, reduced: false });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    const still = await page.evaluate(inspectSpec, { spec, css, reduced: true });
    const checks = { ...motion.checks, ...still.checks };
    results.push({ id: spec.id, kind: 'spec', source, css_sha256: digest(css), pass: Object.values(checks).every(Boolean), checks, measured: motion.measured });
  }
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  const slideUp = specs.find((item) => item.spec.id === 'ui-slide-up');
  await page.evaluate((css) => { document.getElementById('compiled').textContent = css; }, slideUp.css);
  const behaviours = await page.evaluate(inspectBehaviours, slideUp.spec);
  for (const [id, { implementation, checks, measured }] of Object.entries(behaviours)) {
    results.push({ id, kind: 'runtime', implementation: `motion-library/runtime/hub-motion.mjs#${implementation}`, pass: Object.values(checks).every(Boolean), checks, measured });
  }
  const shader = 'runtime/glsl/fresnel-rim.frag';
  const shaderSource = readFileSync(join(library, shader), 'utf8');
  const glsl = await page.evaluate(inspectGlsl, shaderSource);
  results.push({
    id: 'spatial-fresnel-rim', kind: 'glsl', engine: 'glsl-webgl',
    source: `motion-library/${shader}`, shader_sha256: digest(shaderSource),
    pass: Object.values(glsl.checks).every(Boolean), checks: glsl.checks, measured: glsl.measured,
  });
  if (problems.length) results.push({ id: 'page-errors', kind: 'harness', pass: false, checks: { noPageErrors: false }, measured: { problems } });
  var engine = { browser: 'chromium', version: browser.version(), playwright: createRequire(import.meta.url)('playwright/package.json').version, platform: process.platform };
} finally {
  await browser.close();
  server.close();
}

const failed = results.filter((result) => !result.pass);
const evidence = {
  schema_version: 1,
  notes: 'Generated by motion-library/verify/browser.mjs. Values were read from the engine, not asserted by hand. A result stays valid only while its CSS/shader digest and the runtime hashes below match the repository.',
  generated_on: new Date().toISOString().slice(0, 10),
  engine,
  inputs: {
    runtime_sha256: digest(readFileSync(join(library, 'runtime', 'hub-motion.mjs'))),
    core_sha256: digest(readFileSync(join(library, 'runtime', 'core.mjs'))),
    base_css_sha256: digest(readFileSync(join(library, 'runtime', 'hub-motion-base.css'))),
  },
  summary: { passed: results.length - failed.length, failed: failed.length },
  results,
};
if (process.argv.includes('--write')) writeFileSync(evidencePath, JSON.stringify(evidence, null, 2) + '\n');
for (const result of failed) console.error(`FAIL ${result.id}: ${Object.entries(result.checks).filter(([, ok]) => !ok).map(([name]) => name).join(', ')}`);
console.log(`${engine.browser} ${engine.version}: ${evidence.summary.passed} passed, ${evidence.summary.failed} failed`);
process.exit(failed.length ? 1 : 0);
