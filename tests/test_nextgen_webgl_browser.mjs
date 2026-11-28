// Fresh local WebGL2 shader and point rendering proof. No hardware/FPS claim.
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {mkdirSync, readFileSync, writeFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {serve} from '../motion-library/verify/serve.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const bridge = resolve(process.env.MOTION_PLAYWRIGHT_PACKAGE ?? resolve(root, 'motion-library/chromium-stack'),
  'package.json');
const require = createRequire(bridge);
const playwright = require('playwright');
const playwrightVersion = require('playwright/package.json').version;
const lockScope = JSON.parse(readFileSync(resolve(root, 'motion-library/chromium-stack/package.json')));
assert.equal(playwrightVersion, lockScope.devDependencies.playwright);

const browserName = process.env.MOTION_BROWSER ?? 'chromium';
assert(['chromium', 'firefox', 'webkit'].includes(browserName), 'Unknown browser');
const launchOptions = browserName === 'chromium'
  ? {args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
     executablePath: process.env.MOTION_CHROMIUM_EXECUTABLE}
  : browserName === 'firefox'
    ? {headless: process.env.MOTION_WEBGL_HEADED !== '1',
       firefoxUserPrefs: {'webgl.force-enabled': true}}
    : {};
const server = await serve(root);
const errors = [], external = [], cases = [];
let browser;
try {
  browser = await playwright[browserName].launch(launchOptions);
  for (const viewport of [{width: 390, height: 844}, {width: 1280, height: 720}]) {
    const page = await browser.newPage({viewport, deviceScaleFactor: 1});
    page.on('pageerror', (error) => errors.push(error.message));
    await page.route('**/*', (route) => {
      if (new URL(route.request().url()).origin !== server.origin) {
        external.push(route.request().url());
        return route.abort();
      }
      return route.continue();
    });
    await page.goto(server.origin + '/motion-library/chromium-stack/harness.html');
    const observations = await page.evaluate(async ({width, height}) => {
      const {createMotion, definitions} = await import('/motion-library/expansion/nextgen-motion-webgl.mjs');
      const canvas = document.createElement('canvas');
      canvas.width = 120;
      canvas.height = 90;
      canvas.setAttribute('style', 'display: block');
      document.body.replaceChildren(canvas);
      const hash = async (bytes) => Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)),
        (entry) => entry.toString(16).padStart(2, '0')).join('');
      const rows = [];
      for (const definition of definitions) {
        const motion = createMotion(canvas, definition.id, {width, height});
        const runtime = motion.runtimeInfo();
        const sample = async (progress) => {
          motion.render(progress);
          const rgba = motion.readPixels();
          let drawn = 0, opaque = 0;
          for (let offset = 0; offset < rgba.length; offset += 4) {
            if (rgba[offset] !== 8 || rgba[offset + 1] !== 17 || rgba[offset + 2] !== 31) drawn++;
            if (rgba[offset + 3] === 255) opaque++;
          }
          return {sha256: await hash(rgba), drawn_pixels: drawn, opaque_pixels: opaque};
        };
        const frames = [];
        for (const progress of [.1, .5, .9]) frames.push(await sample(progress));
        const same = await sample(.5);
        const png = canvas.toDataURL('image/png');
        motion.configure({reducedMotion: true});
        const posterStart = await sample(.1), posterEnd = await sample(.9);
        motion.configure({reducedMotion: false, rtl: true});
        const rtl = await sample(.5);
        motion.configure({reducedMotion: false, rtl: false});
        const benchmark = motion.benchmark({frames: 24, budget_ms: 25});
        let duplicate_canvas_rejected = false;
        try { createMotion(canvas, definition.id, {width, height}); }
        catch (error) { duplicate_canvas_rejected = /active motion/.test(error.message); }
        motion.destroy();
        let destroyedRead = '';
        try { motion.readPixels(); }
        catch (error) { destroyedRead = error.message; }
        const surface = {width: canvas.width, height: canvas.height, style: canvas.getAttribute('style')};
        const checks = {
          actual_webgl2: runtime.engine === 'webgl2' && runtime.renderers.includes('webgl2'),
          drawn: frames.every((frame) => frame.drawn_pixels > 100),
          opaque: frames.every((frame) => frame.opaque_pixels === runtime.source_framebuffer.width * runtime.source_framebuffer.height),
          changes: new Set(frames.map((frame) => frame.sha256)).size === 3,
          deterministic: frames[1].sha256 === same.sha256,
          reduced_motion: posterStart.sha256 === posterEnd.sha256,
          rtl: frames[1].sha256 !== rtl.sha256,
          png: png.startsWith('data:image/png'),
          duplicate_canvas_rejected,
          cleanup: /destroyed/.test(destroyedRead) && surface.width === 120 && surface.height === 90
            && surface.style === 'display: block',
          bounded_framebuffer: runtime.source_framebuffer.width * runtime.source_framebuffer.height <= 131072,
          budget: benchmark.within_cpu_budget,
        };
        rows.push({id: definition.id, viewport: {width, height}, runtime, checks, frames, benchmark,
          cleanup_evidence: {surface, destroyed_read_rejected: /destroyed/.test(destroyedRead)}});
        // Separate the next synchronous p95 sample from the current measured frame loop.
        await new Promise((resolve) => requestAnimationFrame(resolve));
      }
      canvas.remove();
      return rows;
    }, viewport);
    cases.push(...observations);
    await page.close();
  }
  assert.equal(cases.length, 24);
  assert.equal(new Set(cases.map(({id, viewport}) => id + ':' + viewport.width)).size, 24);
  assert.deepEqual(errors, []);
  assert.deepEqual(external, []);
  for (const row of cases) {
    const failed = Object.keys(row.checks).filter((key) => !row.checks[key]);
    assert.deepEqual(failed, [], row.id + ' at ' + row.viewport.width + ': ' + JSON.stringify({
      benchmark: row.benchmark, cleanup: row.cleanup_evidence,
    }));
  }

  const inputs = Object.fromEntries([
    'motion-library/expansion/nextgen-motion-webgl.mjs',
    'tests/test_nextgen_webgl_browser.mjs',
    'motion-library/chromium-stack/harness.html',
    'motion-library/chromium-stack/package.json',
    'motion-library/chromium-stack/package-lock.json',
    'motion-library/verify/serve.mjs',
  ].map((path) => [path, createHash('sha256').update(readFileSync(resolve(root, path))).digest('hex')]));
  const receipt = {
    schema_version: 1, status: 'passed', recorded_at_utc: new Date().toISOString(),
    browser: browserName, browser_version: browser.version(), playwright_version: playwrightVersion,
    runtime: 'webgl2', platform: process.platform, inputs, cases,
    page_errors: errors.length, external_requests: external.length,
    hardware_verified: false, production_fps_verified: false, real_devices_verified: false,
  };
  const output = process.env.NEXTGEN_WEBGL_RECEIPT;
  if (output) {
    mkdirSync(dirname(resolve(output)), {recursive: true});
    writeFileSync(output, JSON.stringify(receipt, null, 2) + '\n', {mode: 0o600});
  }
  console.log(JSON.stringify({status: 'passed', browser: browserName, browser_version: browser.version(),
    cases: cases.length, max_p95_ms: Math.max(...cases.map((row) => row.benchmark.p95_ms)),
    renderer: cases[0].runtime.renderer, receipt: output ?? null}));
} finally {
  if (browser) await browser.close();
  await server.close();
}
