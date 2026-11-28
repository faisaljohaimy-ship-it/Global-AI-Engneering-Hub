#!/usr/bin/env node
// Browser evidence for the Motion SDK. Every motion is created in a real browser and
// has to prove, frame by frame, that it draws, moves, repeats exactly, obeys its
// controls, honours reduced motion and reading direction, and cleans up after itself.
// A motion that fails any check is not operational.
//
//   node packages/motion-engines/verify/browser.mjs [--browser chromium|firefox|webkit] [--module key] [--id id] [--write] [--timeout seconds]
//
// Playwright is a tool of the machine running this script, not a dependency of the SDK.
import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { serve } from './serve.mjs';
import { coreHash, scan } from '../tools/build_registry.mjs';

const sdk = resolve(fileURLToPath(new URL('..', import.meta.url)));
const option = (name) => {
  const index = process.argv.indexOf(`--${name}`);
  return index > 0 ? process.argv[index + 1] : undefined;
};
const browserName = option('browser') ?? 'chromium';
const selected = (await scan({ module: option('module'), id: option('id') }))
  .map((item) => ({ id: item.id, engine: item.definition.engine, source_sha256: item.digest, category: { key: item.module } }));
if (!selected.length) {
  console.error('No motion matches.');
  process.exit(2);
}

let playwright;
try {
  playwright = createRequire(import.meta.url)('playwright');
} catch {
  console.error('Playwright is required to produce browser evidence.');
  process.exit(2);
}
const launch = browserName === 'chromium'
  ? { args: ['--enable-unsafe-webgpu', '--enable-features=Vulkan,WebGPU', '--use-webgpu-adapter=swiftshader', '--ignore-gpu-blocklist', '--enable-precise-memory-info', '--js-flags=--expose-gc'] }
  : {};
const TIMEOUT_MS = Number(option('timeout') ?? 300) * 1000;
const server = await serve(sdk);
const browser = await playwright[browserName].launch(launch);
const NONBLANK = (facts) => facts.distinct >= 6 && facts.spread >= 0.01;
const ALT = ['#101828', '#ff2d55', '#00e5a8', '#ffd60a', '#7c3aed'];

async function inspect(page, entry) {
  const id = entry.id;
  const checks = {};
  const measured = {};
  const h = (method, ...args) => page.evaluate(([name, values]) => window.h[name](...values), [method, args]);
  let serial = 0;
  // WGSL motions are checked through the readback presentation, which shows the real
  // WebGPU output even where the browser cannot put a WebGPU canvas on screen.
  const wgsl = entry.engine === 'webgpu-wgsl';
  const make = async (options = {}) => {
    serial += 1;
    const key = `k${serial}`;
    const info = await h('create', key, id, { ...(wgsl ? { gpu: 'readback' } : {}), ...options });
    return { key, info };
  };
  const frame = async (key, at, label) => {
    const facts = await h('frame', key, at, label);
    if (facts.mode === 'pixels') return facts;
    // DOM, SVG and layered pictures are read from a screenshot. A capture taken straight
    // after a change can show an unfinished frame, so wait for two animation frames and
    // accept a capture only when the next one is identical.
    await page.evaluate(() => new Promise((painted) => requestAnimationFrame(() => requestAnimationFrame(painted))));
    const stage = page.locator(`#stage-${key}`);
    let png = await stage.screenshot({ type: 'png' });
    for (let attempt = 0; attempt < 4; attempt += 1) {
      const next = await stage.screenshot({ type: 'png' });
      if (next.equals(png)) break;
      png = next;
    }
    return h('png', label, png.toString('base64'));
  };
  await h('reset');
  const heapBefore = await h('heap');
  const drop = (...items) => Promise.all(items.map((item) => h('drop', item.key)));

  // 1. It draws, it changes over time, and the same moment always gives the same frame.
  const main = await make();
  const { kind, still, rtl, params, camera, duration, text, interactive } = main.info.definition;
  const moments = [0.1, 0.35, 0.6, 0.85];
  const facts = [];
  for (const moment of moments) facts.push(await frame(main.key, { progress: moment }, `m${moment}`));
  const stillFacts = await frame(main.key, { progress: still }, 'still');
  checks.draws = NONBLANK(stillFacts);
  const changes = [];
  for (let index = 1; index < moments.length; index += 1) changes.push(await h('diff', `m${moments[index - 1]}`, `m${moments[index]}`));
  checks.changesOverTime = new Set(facts.map((item) => item.hash)).size >= 3 && Math.max(...changes) >= 0.002;
  const again = await frame(main.key, { progress: 0.35 }, 'again');
  const twin = await make();
  const twinFacts = await frame(twin.key, { progress: 0.35 }, 'twin');
  checks.sameFrameForSameMoment = again.hash === facts[1].hash && twinFacts.hash === facts[1].hash;
  await drop(twin);
  measured.frames = { distinctColours: stillFacts.distinct, spread: Number(stillFacts.spread.toFixed(4)), largestChange: Number(Math.max(...changes).toFixed(4)), readback: facts[0].mode };
  measured.signature = facts.map((item) => item.hash).join('-');

  // 2. Colours, parameters, camera settings, duration and easing are real controls.
  const reference = await frame(main.key, { progress: 0.6 }, 'ref');
  const coloured = await make({ colors: ALT });
  checks.coloursChangeTheFrame = (await frame(coloured.key, { progress: 0.6 }, 'coloured')).hash !== reference.hash;
  await drop(coloured);
  const inert = [];
  const sampleAt = [0.6, 0.35, 0.85];
  const references = {};
  for (const moment of sampleAt) references[moment] = (await frame(main.key, { progress: moment }, 'p')).hash;
  for (const [group, schema] of [['params', params], ['camera', camera]]) {
    for (const [name, spec] of Object.entries(schema)) {
      let effect = false;
      for (const value of [spec.min, spec.max]) {
        if (effect || value === spec.default) continue;
        const variant = await make({ [group]: { [name]: value } });
        for (const moment of sampleAt) {
          if ((await frame(variant.key, { progress: moment }, 'v')).hash !== references[moment]) {
            effect = true;
            break;
          }
        }
        await drop(variant);
      }
      if (!effect) inert.push(`${group}.${name}`);
    }
  }
  checks.everyParameterChangesTheFrame = inert.length === 0;
  if (inert.length) measured.inertParameters = inert;
  if (text) {
    // Every declared string is a real control: replacing it changes the picture.
    // A string may be on screen for only part of the timeline, so more moments are tried.
    const unread = [];
    for (const key of Object.keys(text.en)) {
      const variant = await make({ text: { [key]: 'Qx 2049' } });
      let effect = false;
      for (const moment of [...sampleAt, 0.1, 0.5, 0.2, 0.75, 0.95, 0.03]) {
        references[moment] ??= (await frame(main.key, { progress: moment }, 'p')).hash;
        if ((await frame(variant.key, { progress: moment }, 'v')).hash !== references[moment]) {
          effect = true;
          break;
        }
      }
      await drop(variant);
      if (!effect) unread.push(key);
    }
    checks.everyTextChangesTheFrame = unread.length === 0;
    if (unread.length) measured.unreadText = unread;
  }
  if (interactive) {
    // Live input changes the picture, and handing control back restores the scripted frame exactly.
    const before = await frame(main.key, { progress: still }, 'i0');
    await h('input', main.key, interactive.sample);
    const during = await frame(main.key, { progress: still }, 'i1');
    await h('input', main.key, null);
    const after = await frame(main.key, { progress: still }, 'i2');
    checks.inputChangesTheFrame = during.hash !== before.hash && NONBLANK(during);
    checks.releasingInputRestoresTheFrame = after.hash === before.hash;
  }

  const normal = await make({ virtual: true });
  const slow = await make({ virtual: true, duration: duration * 2 });
  await h('call', normal.key, 'play');
  await h('call', slow.key, 'play');
  const half = (await h('advance', normal.key, duration / 2)).time / duration;
  const quarter = (await h('advance', slow.key, duration / 2)).time / (duration * 2);
  checks.durationSetsTheSpeed = Math.abs(half - 0.5) < 0.06 && Math.abs(quarter - 0.25) < 0.06;
  // The same instant looks different at half speed: the duration control reaches the picture.
  await h('call', slow.key, 'pause');
  let slower = false;
  for (const moment of sampleAt) slower ||= (await frame(slow.key, { time: moment * duration }, 'slow')).hash !== references[moment];
  checks.durationChangesTheFrame = slower;
  await drop(normal, slow);
  const easedAt = kind === 'loop' ? { time: 200 } : { progress: 0.3 };
  const linear = await make({ easing: 'linear' });
  const easedIn = await make({ easing: 'ease-in' });
  checks.easingChangesTheFrame = (await frame(linear.key, easedAt, 'e1')).hash !== (await frame(easedIn.key, easedAt, 'e2')).hash;
  await drop(linear, easedIn);

  // 3. Transport: play, pause, resume, reverse, stop, and the end of a one-shot.
  const transport = await make({ virtual: true });
  const played = await h('call', transport.key, 'play');
  const moving = await h('advance', transport.key, duration * 0.4);
  await h('call', transport.key, 'pause');
  const held = await h('advance', transport.key, duration * 0.3);
  await h('call', transport.key, 'resume');
  const resumed = await h('advance', transport.key, duration * 0.1);
  await h('call', transport.key, 'reverse');
  const reversed = await h('advance', transport.key, duration * 0.2);
  const stopped = await h('call', transport.key, 'stop');
  checks.transportWorks = played.state === 'playing' && moving.time > duration * 0.3 && held.state === 'paused' && Math.abs(held.time - moving.time) < 1
    && resumed.time > held.time && reversed.time < resumed.time && stopped.state === 'idle' && stopped.time === 0 && stopped.pending === 0;
  if (kind === 'oneshot') {
    await h('call', transport.key, 'play');
    const ended = await h('advance', transport.key, duration + 200);
    checks.oneShotFinishes = ended.state === 'finished' && Math.abs(ended.time - duration) < 1 && ended.pending === 0;
  }

  // 4. Reduced motion: one still frame, drawn once, and nothing scheduled.
  const calm = await make({ virtual: true, reducedMotion: true });
  await h('call', calm.key, 'play');
  const rested = await h('advance', calm.key, 800);
  const calmFacts = await frame(calm.key, { progress: still }, 'calm');
  checks.reducedMotionIsOneStillFrame = rested.state === 'still' && rested.pending === 0 && calm.info.framesDrawn === 1 && rested.framesDrawn === 1 && NONBLANK(calmFacts);
  await drop(calm);

  // 5. Reading direction.
  const ltrInstance = await make({ direction: 'ltr' });
  const ltr = await frame(ltrInstance.key, { progress: 0.35 }, 'ltr');
  const rtlInstance = await make({ direction: 'rtl' });
  const rightToLeft = await frame(rtlInstance.key, { progress: 0.35 }, 'rtl');
  if (rtl === 'neutral') checks.directionNeutral = ltr.hash === rightToLeft.hash;
  else if (rtl === 'mirror') {
    checks.mirrorsUnderRtl = ltr.hash !== rightToLeft.hash && Math.abs(ltr.centroidX + rightToLeft.centroidX - 1) < 0.08;
    measured.centroidX = { ltr: Number(ltr.centroidX.toFixed(3)), rtl: Number(rightToLeft.centroidX.toFixed(3)) };
  } else checks.rendersArabicRightToLeft = rtlInstance.info.direction === 'rtl' && rtlInstance.info.locale === 'ar' && NONBLANK(rightToLeft) && ltr.hash !== rightToLeft.hash;

  await drop(ltrInstance, rtlInstance);

  // 6. Lower quality costs fewer pixels and still draws; frames export; destroy releases everything.
  // A phone held upright: a tall, narrow frame must still be filled with a picture.
  const phone = await make({ width: 180, height: 320 });
  const portrait = await frame(phone.key, { progress: still }, 'portrait');
  checks.drawsInPortrait = NONBLANK(portrait) && portrait.width === 180 && portrait.height === 320;
  await drop(phone);
  const tuned = await make();
  const high = (await h('info', tuned.key)).pixels;
  const low = await h('optimize', tuned.key, { tier: 'low' });
  checks.lowerQualityStillDraws = low.tier === 'low' && low.pixels < high && NONBLANK(await frame(tuned.key, { progress: still }, 'low'));
  await drop(tuned);
  const exported = await h('exportFrames', main.key, { frames: 2, fps: 10 });
  checks.exportsFrames = exported.supported ? exported.sizes.length === 2 && exported.sizes.every((size) => size > 100) : typeof exported.reason === 'string';
  measured.export = exported.supported ? 'in-page' : 'cli-renderer';
  measured.benchmark = await h('benchmark', main.key, { frames: 24 });
  measured.fallback = main.info.fallback;
  if (wgsl) {
    measured.webgpu = main.info.fallback ? `not available here (${main.info.fallback}); the fallback was checked instead` : `WGSL verified through ${main.info.present} presentation`;
    // The fallback is a second implementation and has to draw and move on its own.
    const plain = await make({ gpu: 'off' });
    const first = await frame(plain.key, { progress: 0.35 }, 'f1');
    const later = await frame(plain.key, { progress: 0.6 }, 'f2');
    checks.fallbackDrawsAndMoves = plain.info.fallback === 'webgpu-off' && NONBLANK(first) && first.hash !== later.hash;
    await drop(plain);
    // Shown straight on a WebGPU canvas: either that works here, or the device is lost and
    // the motion carries on with its fallback. Both are acceptable; a blank frame is not.
    const direct = await make({ gpu: 'auto' });
    await page.waitForTimeout(1500);
    const now = await h('info', direct.key);
    const shown = await frame(direct.key, { progress: still }, 'direct');
    checks.survivesWithoutWebgpuCanvas = NONBLANK(shown);
    measured.canvasPresentation = now.fallback ? `device lost here; recovered with the fallback (${now.fallback})` : 'works here';
    await drop(direct);
  }
  const destroyed = await h('destroy', transport.key);
  checks.destroyReleasesEverything = destroyed.children === 0 && destroyed.refuses && destroyed.pending === 0;
  await h('reset');
  const settledHeap = await h('heap');
  if (settledHeap !== null) {
    // A leak shows as growth that repeats: create, draw and destroy the motion several
    // times and compare the collected heap before and after.
    const cycles = 6;
    for (let cycle = 0; cycle < cycles; cycle += 1) {
      const again = await make();
      await frame(again.key, { progress: 0.5 }, 'leak');
      await drop(again);
    }
    await h('reset');
    const grown = ((await h('heap')) - settledHeap) / 1048576 / cycles;
    measured.heapGrowthPerInstanceMB = Number(grown.toFixed(3));
    measured.heapAfterAllChecksMB = Number(((settledHeap - heapBefore) / 1048576).toFixed(2));
    checks.releasesMemory = grown < 0.5;
  }
  return { checks, measured };
}

const results = [];
const problems = [];
let engine;
try {
  const context = await browser.newContext({ viewport: { width: 640, height: 400 }, deviceScaleFactor: 1 });
  let page;
  let module;
  for (const entry of selected) {
    if (entry.category.key !== module) {
      await page?.close();
      page = await context.newPage();
      page.on('pageerror', (error) => problems.push(`${entry.category.key}: ${String(error).slice(0, 300)}`));
      await page.emulateMedia({ reducedMotion: 'no-preference' });
      await page.goto(`${server.origin}/verify/harness.html`);
      await page.waitForFunction(() => window.h);
      module = entry.category.key;
    }
    const before = problems.length;
    let outcome;
    try {
      outcome = await Promise.race([
        inspect(page, entry),
        new Promise((_, reject) => setTimeout(() => reject(new Error(`timed out after ${TIMEOUT_MS / 1000} s`)), TIMEOUT_MS)),
      ]);
    } catch (error) {
      outcome = { checks: { ranWithoutError: false }, measured: { error: String(error.message ?? error).slice(0, 400) } };
      module = null;
    }
    if (problems.length > before) outcome.checks.noPageErrors = false;
    const pass = Object.values(outcome.checks).every(Boolean);
    results.push({ id: entry.id, module: entry.category.key, engine: entry.engine, source_sha256: entry.source_sha256, pass, ...outcome });
    if (!pass) console.error(`FAIL ${entry.id}: ${Object.entries(outcome.checks).filter(([, ok]) => !ok).map(([name]) => name).join(', ')}${outcome.measured.error ? ' — ' + outcome.measured.error : ''}${outcome.measured.inertParameters ? ' — inert: ' + outcome.measured.inertParameters.join(', ') : ''}`);
  }
  const probe = await context.newPage();
  await probe.goto(`${server.origin}/verify/harness.html`);
  const renderer = await probe.evaluate(() => {
    const gl = document.createElement('canvas').getContext('webgl2');
    const extension = gl && gl.getExtension('WEBGL_debug_renderer_info');
    return { webgl2: Boolean(gl), webgpu: Boolean(navigator.gpu), renderer: extension ? gl.getParameter(extension.UNMASKED_RENDERER_WEBGL) : 'unknown' };
  });
  engine = { browser: browserName, version: browser.version(), playwright: createRequire(import.meta.url)('playwright/package.json').version, platform: process.platform, ...renderer };
} finally {
  await browser.close();
  server.close();
}

// No two motions may be the same picture under two names.
const seen = new Map();
for (const result of results.filter((item) => item.measured.signature)) {
  const other = seen.get(result.measured.signature);
  if (other) {
    result.checks.uniqueFrames = false;
    result.pass = false;
    console.error(`FAIL ${result.id}: draws the same frames as ${other}`);
  } else seen.set(result.measured.signature, result.id);
}
const failed = results.filter((result) => !result.pass);
if (process.argv.includes('--write')) {
  const path = join(sdk, 'evidence', `${browserName}.json`);
  const partial = Boolean(option('module') || option('id'));
  let kept = [];
  if (partial) {
    try {
      const previous = JSON.parse(readFileSync(path, 'utf8'));
      if (previous.inputs.core_sha256 === coreHash()) kept = previous.results.filter((row) => !results.some((result) => result.id === row.id));
    } catch {
      kept = [];
    }
  }
  const all = [...kept, ...results].sort((a, b) => a.id.localeCompare(b.id));
  writeFileSync(path, JSON.stringify({
    schema_version: 1,
    notes: 'Generated by packages/motion-engines/verify/browser.mjs at 320x180, quality high, device pixel ratio 1. A row is valid only while source_sha256 matches the motion file and core_sha256 matches the SDK core.',
    generated_on: new Date().toISOString().slice(0, 10),
    engine,
    inputs: { core_sha256: coreHash() },
    summary: { passed: all.filter((row) => row.pass).length, failed: all.filter((row) => !row.pass).length },
    results: all,
  }, null, 1) + '\n');
}
for (const problem of problems.slice(0, 8)) console.error(`PAGE ERROR ${problem}`);
console.log(`${engine.browser} ${engine.version} (${digest(results)}): ${results.length - failed.length} passed, ${failed.length} failed`);
process.exit(failed.length ? 1 : 0);

function digest(rows) {
  return createHash('sha256').update(rows.map((row) => row.id + row.measured.signature).join()).digest('hex').slice(0, 8);
}
