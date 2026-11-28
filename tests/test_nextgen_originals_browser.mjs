// Verify the actual original catalog in an isolated, fresh browser context.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readFileSync, writeFileSync, mkdirSync} from 'node:fs';
import {resolve, dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {serve} from '../motion-library/verify/serve.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const catalogPath = 'motion-library/expansion/nextgen-catalog.mjs';
const manifestPath = 'docs/evidence/nextgen-local-motion-inventory.json';
const packagePath = 'motion-library/chromium-stack';
const load = name => JSON.parse(readFileSync(resolve(root, name), 'utf8'));
const manifest = load(manifestPath);
const required = manifest.catalogs.flatMap(catalog => catalog.ids).sort();
const require = createRequire(resolve(root, packagePath, 'package.json'));
const playwright = require('playwright');
const version = require('playwright/package.json').version;
assert.equal(version, load(packagePath + '/package.json').devDependencies.playwright);

const browserName = process.env.MOTION_BROWSER ?? 'chromium';
const profiles = [{width: 390, height: 844}, {width: 1280, height: 720}];
assert(['chromium', 'firefox', 'webkit'].includes(browserName));
const server = await serve(root);
let browser;
const errors = [], external = [], cases = [];
try {
  browser = await playwright[browserName].launch();
  for (const viewport of profiles) {
    const page = await browser.newPage({viewport, deviceScaleFactor: 1});
    try {
      page.on('pageerror', error => errors.push(error.message));
      await page.route('**/*', route => {
        const url = new URL(route.request().url());
        if (url.origin !== server.origin) {
          external.push(url.origin);
          return route.abort();
        }
        if (url.pathname === '/nextgen-runtime') {
          return route.fulfill({contentType: 'text/html', body: '<!doctype html><html lang="en"><body></body></html>'});
        }
        return route.continue();
      });
      await page.goto(server.origin + '/nextgen-runtime');
      const rows = await page.evaluate(async ({viewport, catalogPath}) => {
        const catalog = await import('/' + catalogPath);
        const {createMotionSystem} = await import('/packages/motion-sdk/index.mjs');
        const system = createMotionSystem();
        system.registerCatalog(catalog);
        const rows = [];
        for (const definition of catalog.definitions) {
          const container = document.body.appendChild(document.createElement('div'));
          const canvas = container.appendChild(document.createElement('canvas'));
          // Readback-heavy QA needs a stable raster path. WebKit can switch its
          // backing store after initial reads, perturbing antialiased edge bytes.
          canvas.getContext('2d', {willReadFrequently: true});
          const clip = system.create(definition.id, {
            canvas, ...viewport, pixelRatio: 1, reducedMotion: 'full',
          });
          const frame = async progress => {
            clip.render(progress);
            const context = clip.canvas.getContext('2d');
            const pixels = context.getImageData(0, 0, viewport.width, viewport.height).data;
            let drawnPixels = 0;
            for (let i = 0; i < pixels.length; i += 4) {
              if (pixels[i] !== 8 || pixels[i + 1] !== 17 || pixels[i + 2] !== 31) drawnPixels++;
            }
            const digest = await crypto.subtle.digest('SHA-256', pixels);
            const sha256 = Array.from(new Uint8Array(digest), byte =>
              byte.toString(16).padStart(2, '0')).join('');
            return {sha256, drawn_pixels: drawnPixels};
          };
          const frames = [await frame(.1), await frame(.5), await frame(.9)];
          const repeated = await frame(.5);
          clip.configure({reducedMotion: 'reduce'});
          const reducedA = await frame(.1), reducedB = await frame(.9);
          clip.configure({rtl: true, reducedMotion: 'full'});
          const rtl = await frame(.5);
          const benchmark = clip.benchmark({frames: 45, budget_ms: 25});
          const png = clip.export('png'), svg = clip.export('svg');
          clip.play();
          await new Promise(requestAnimationFrame);
          clip.pause();
          const paused = clip.progress;
          await new Promise(requestAnimationFrame);
          const pause = paused === clip.progress;
          clip.resume();
          await new Promise(requestAnimationFrame);
          clip.reverse();
          clip.stop();
          const stop = clip.progress === 0;
          clip.destroy();
          const cleanup = container.firstChild === canvas && canvas.width === 300 && canvas.height === 150
            && system.getCapabilities().live_instances === 0;
          container.remove();
          const checks = {
            drawn: frames.every(frame => frame.drawn_pixels > 100),
            changes: new Set(frames.map(frame => frame.sha256)).size === 3,
            deterministic: frames[1].sha256 === repeated.sha256,
            reduced_motion: reducedA.sha256 === reducedB.sha256,
            rtl: frames[1].sha256 !== rtl.sha256,
            exports: png.startsWith('data:image/png') && svg.includes('<svg'),
            pause, stop, cleanup, cpu_budget: benchmark.within_cpu_budget,
          };
          rows.push({id: definition.id, viewport, checks, frames, benchmark});
        }
        return rows;
      }, {viewport, catalogPath});
      assert.deepEqual(rows.map(row => row.id).sort(), required);
      cases.push(...rows);
    } finally {
      await page.close();
    }
  }
  assert.deepEqual(errors, []);
  assert.deepEqual(external, []);
  const failures = cases.flatMap(row => Object.entries(row.checks)
    .filter(([, value]) => value !== true)
    .map(([check]) => ({id: row.id, viewport: row.viewport.width, check, p95_ms: row.benchmark.p95_ms})));
  assert.deepEqual(failures, [], 'Original motion checks failed');
  const sources = [manifestPath, catalogPath, ...manifest.catalogs.map(catalog => catalog.source),
    'packages/motion-sdk/index.mjs', 'tests/test_nextgen_originals_browser.mjs',
    'motion-library/verify/serve.mjs', packagePath + '/package.json', packagePath + '/package-lock.json'];
  const inputs = Object.fromEntries(sources.map(name =>
    [name, createHash('sha256').update(readFileSync(resolve(root, name))).digest('hex')]));
  const receipt = {
    schema_version: 2, status: 'passed', recorded_at_utc: new Date().toISOString(),
    browser: browserName, browser_version: browser.version(), playwright_version: version,
    platform: process.platform, inputs, cases, page_errors: errors.length, external_requests: external.length,
    production_fps_verified: false, real_devices_verified: false, gpu_runtime_verified: false,
  };
  const output = process.env.NEXTGEN_CAMERA_RECEIPT;
  if (output) {
    mkdirSync(dirname(resolve(output)), {recursive: true, mode: 0o700});
    writeFileSync(output, JSON.stringify(receipt, null, 2) + '\n', {flag: 'wx', mode: 0o600});
  }
  console.log(JSON.stringify({status: receipt.status, browser: browserName, identities: required.length,
    cases: cases.length, max_p95_ms: Math.max(...cases.map(row => row.benchmark.p95_ms))}));
} finally {
  if (browser) await browser.close();
  await server.close();
}
