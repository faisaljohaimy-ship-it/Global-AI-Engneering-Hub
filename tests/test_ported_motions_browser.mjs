// Browser proof for the Universal Motion SDK motions ported from earlier branches
// (docs/evidence/ported-motions.json). Each motion is drawn by the real SDK in headless Chromium,
// one motion at a time, at 390x844 and 1280x720, and must pass the checks the nextgen camera scenes
// pass on HEAD: drawn, changes, deterministic, reduced_motion, rtl, exports, pause, stop, cleanup,
// cpu_budget. No real device, production frame rate or GPU acceleration is claimed.
//
//   node tests/test_ported_motions_browser.mjs                      prove every ported group
//   node tests/test_ported_motions_browser.mjs --source <module>    prove one group
//   node tests/test_ported_motions_browser.mjs --source <module> --write
//        and replace that group's entry in docs/evidence/ported-motions-chromium.json
//
// Playwright is found as packages/motion-engines/tools/playwright.mjs finds it
// (MOTION_PLAYWRIGHT_PACKAGE, else Node resolution); its version is recorded next to the reviewed pin
// of motion-library/chromium-stack/package.json, and a mismatch is recorded, not hidden.
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { serve } from '../motion-library/verify/serve.mjs';
import { loadPlaywright } from '../packages/motion-engines/tools/playwright.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const MANIFEST = 'docs/evidence/ported-motions.json';
const RECEIPT = 'docs/evidence/ported-motions-chromium.json';
const INPUTS = ['packages/motion-sdk/index.mjs', 'tests/test_ported_motions_browser.mjs', 'motion-library/verify/serve.mjs'];
const VIEWPORTS = [{ width: 390, height: 844 }, { width: 1280, height: 720 }];
const read = (path) => readFileSync(resolve(root, path));
const sha256 = (data) => createHash('sha256').update(data).digest('hex');

const args = process.argv.slice(2);
const write = args.includes('--write');
const wanted = args.flatMap((arg, i) => (arg === '--source' ? [args[i + 1]] : []));
const manifest = JSON.parse(read(MANIFEST));
const groups = manifest.groups.filter((group) => !wanted.length || wanted.includes(group.source));
assert.ok(groups.length, `no ported group matches ${wanted.join(', ')}`);
assert.equal(groups.length, new Set(groups.map((group) => group.source)).size);

const { playwright, version } = loadPlaywright();
const pinned = JSON.parse(read('motion-library/chromium-stack/package.json')).devDependencies.playwright;
const server = await serve(root);
const browser = await playwright.chromium.launch();
const results = {};
try {
  for (const group of groups) {
    const errors = [], external = [], cases = [];
    let motions;
    for (const viewport of VIEWPORTS) {
      const page = await browser.newPage({ viewport, deviceScaleFactor: 1 });
      try {
        page.on('pageerror', (error) => errors.push(error.message));
        await page.route('**/*', (route) => {
          const url = new URL(route.request().url());
          if (url.origin !== server.origin) { external.push(url.origin); return route.abort(); }
          if (url.pathname === '/ported-motions') return route.fulfill({ contentType: 'text/html', body: '<!doctype html><html lang="en"><body></body></html>' });
          return route.continue();
        });
        await page.goto(`${server.origin}/ported-motions`);
        const out = await page.evaluate(async ({ source, viewport }) => {
          const catalog = await import(`/${source}`);
          const { createMotionSystem } = await import('/packages/motion-sdk/index.mjs');
          const hash = async (data) => Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', data)), (b) => b.toString(16).padStart(2, '0')).join('');
          const rows = [];
          // One motion at a time: each gets a fresh SDK system and is destroyed before the next starts.
          for (const definition of catalog.definitions) {
            const system = createMotionSystem();
            system.registerCatalog(catalog);
            const container = document.body.appendChild(document.createElement('div'));
            const canvas = container.appendChild(document.createElement('canvas'));
            canvas.getContext('2d', { willReadFrequently: true });
            const clip = system.create(definition.id, { canvas, ...viewport, pixelRatio: 1, reducedMotion: 'full' });
            const frame = async (progress) => {
              clip.render(progress);
              const pixels = clip.canvas.getContext('2d').getImageData(0, 0, viewport.width, viewport.height).data;
              let drawn = 0;
              for (let i = 0; i < pixels.length; i += 4) if (pixels[i] !== 8 || pixels[i + 1] !== 17 || pixels[i + 2] !== 31) drawn++;
              return { sha256: await hash(pixels), drawn_pixels: drawn };
            };
            const frames = [await frame(0.1), await frame(0.5), await frame(0.9)];
            const repeated = await frame(0.5);
            clip.configure({ reducedMotion: 'reduce' });
            const reducedA = await frame(0.1), reducedB = await frame(0.9);
            clip.configure({ rtl: true, reducedMotion: 'full' });
            const rtl = await frame(0.5);
            const benchmark = clip.benchmark({ frames: 45, budget_ms: 25 });
            const png = clip.export('png'), svg = clip.export('svg');
            clip.play();
            await new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)));
            clip.pause();
            const paused = clip.progress;
            await new Promise(requestAnimationFrame);
            const pause = paused === clip.progress;
            clip.resume();
            await new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)));
            clip.reverse();
            clip.stop();
            const stop = clip.progress === 0;
            clip.destroy();
            const cleanup = container.firstChild === canvas && canvas.width === 300 && canvas.height === 150
              && system.getCapabilities().live_instances === 0;
            container.remove();
            const checks = {
              drawn: frames.every((f) => f.drawn_pixels > 100),
              changes: new Set(frames.map((f) => f.sha256)).size === 3,
              deterministic: frames[1].sha256 === repeated.sha256,
              reduced_motion: reducedA.sha256 === reducedB.sha256,
              rtl: frames[1].sha256 !== rtl.sha256,
              exports: png.startsWith('data:image/png') && svg.includes('<svg'),
              pause, stop, cleanup, cpu_budget: benchmark.within_cpu_budget,
            };
            rows.push({ id: definition.id, viewport, checks, frames, benchmark });
          }
          const motions = catalog.definitions.map(({ id, name_en, name_ar, engine, meaning }) => ({ id, name_en, name_ar, engine, meaning: meaning ?? null }));
          return { rows, motions };
        }, { source: group.source, viewport });
        cases.push(...out.rows);
        motions = out.motions;
      } finally {
        await page.close();
      }
    }
    assert.deepEqual(motions.map((m) => m.id), group.ids, `${group.source}: the module's motions are not the manifest's ids`);
    const failures = cases.flatMap((row) => Object.entries(row.checks).filter(([, ok]) => ok !== true)
      .map(([check]) => ({ id: row.id, viewport: row.viewport.width, check, p95_ms: row.benchmark.p95_ms })));
    results[group.source] = {
      status: failures.length || errors.length || external.length ? 'failed' : 'passed',
      recorded_at_utc: new Date().toISOString(),
      browser: 'chromium', browser_version: browser.version(), playwright_version: version,
      reviewed_playwright_pin: pinned, toolchain_matches_reviewed_pin: version === pinned,
      platform: process.platform,
      source_sha256: sha256(read(group.source)),
      inputs: Object.fromEntries(INPUTS.map((path) => [path, sha256(read(path))])),
      motions, cases, failures,
      page_errors: errors.length, external_requests: external.length,
      production_fps_verified: false, real_devices_verified: false, gpu_runtime_verified: false,
    };
    console.log(JSON.stringify({ source: group.source, status: results[group.source].status, motions: motions.length, cases: cases.length,
      failures, page_errors: errors, external_requests: external.length, max_p95_ms: Math.max(...cases.map((row) => row.benchmark.p95_ms)) }));
  }
} finally {
  await browser.close();
  server.close();
}

const failed = Object.entries(results).filter(([, group]) => group.status !== 'passed').map(([source]) => source);
if (write) {
  assert.deepEqual(failed, [], 'a failing group is reported, never written as evidence');
  const path = resolve(root, RECEIPT);
  const receipt = existsSync(path) ? JSON.parse(readFileSync(path, 'utf8')) : {
    schema_version: 1,
    what: 'Chromium proof of the Universal Motion SDK motions ported from earlier branches. Each group is bound to the SHA-256 of its module and of the SDK, this script and the static server; a changed file voids that group until it is proven again.',
    produced_by: 'node tests/test_ported_motions_browser.mjs --source <module> --write',
    boundary: 'SwiftShader/CPU Canvas2D in headless Chromium on a shared host. No real device, production frame rate, GPU acceleration, Firefox or WebKit run is claimed.',
    groups: {},
  };
  for (const [source, group] of Object.entries(results)) receipt.groups[source] = group;
  receipt.groups = Object.fromEntries(Object.entries(receipt.groups).sort(([a], [b]) => a.localeCompare(b)));
  writeFileSync(path, `${JSON.stringify(receipt, null, 1)}\n`);
  console.log(`wrote ${RECEIPT}`);
}
if (failed.length) {
  console.error(`failed: ${failed.join(', ')}`);
  process.exitCode = 1;
}
