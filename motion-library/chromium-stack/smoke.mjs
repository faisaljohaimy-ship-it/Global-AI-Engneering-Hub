#!/usr/bin/env node
import { createServer } from 'node:http';
import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { inspectNative } from './native-probes.mjs';
import { parseArgs, prepareOutputDirectory, validateOptions, withDeadline } from './options.mjs';

const here = fileURLToPath(new URL('.', import.meta.url));
const sha256 = (bytes) => createHash('sha256').update(bytes).digest('hex');
export async function runProbe(input = {}) {
  const options = validateOptions(input);
  const out = prepareOutputDirectory(options.out);
  const require = createRequire(import.meta.url);
  const { chromium } = require('playwright');
  const html = readFileSync(new URL('harness.html', import.meta.url));
  const server = createServer((request, response) => {
    if (!['/', '/harness.html'].includes(request.url)) { response.writeHead(404).end(); return; }
    response.writeHead(200, { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store' }).end(html);
  });
  await new Promise((ready, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', ready); });
  const origin = `http://127.0.0.1:${server.address().port}`;
  let browser;
  try {
    browser = await chromium.launch();
    const cases = [];
    const settings = [
      { id: 'desktop-ltr', width: options.width, height: options.height, dir: 'ltr', reduced: false },
      { id: 'mobile-rtl', width: 390, height: 844, dir: 'rtl', reduced: false },
      { id: 'mobile-reduced-rtl', width: 390, height: 844, dir: 'rtl', reduced: true }
    ];
    for (const setting of settings) {
      const context = await browser.newContext({ viewport: { width: setting.width, height: setting.height }, reducedMotion: setting.reduced ? 'reduce' : 'no-preference', deviceScaleFactor: 1 });
      const external = [], errors = [];
      await context.route('**/*', (route) => {
        if (new URL(route.request().url()).origin !== origin) { external.push('external request blocked'); return route.abort(); }
        return route.continue();
      });
      try {
        const page = await context.newPage();
        page.on('pageerror', (error) => errors.push(error.message));
        page.setDefaultTimeout(30000);
        await page.goto(origin + '/harness.html');
        await page.evaluate((dir) => { document.documentElement.dir = dir; document.documentElement.lang = dir === 'rtl' ? 'ar' : 'en'; }, setting.dir);
        const result = await withDeadline(page.evaluate(inspectNative, { frames: options.frames, frameBudgetMs: options.frameBudgetMs }), 30000);
        if (errors.length || external.length) throw new Error('Browser error or unexpected external request');
        const row = { id: setting.id, status: 'passed', ...result, page_errors: 0, external_requests: 0 };
        if (out) {
          const bytes = await page.screenshot({ path: resolve(out, setting.id + '.png') });
          row.screenshot_sha256 = sha256(bytes);
        }
        cases.push(row);
      } finally { await context.close(); }
    }
    const performancePassed = cases.every((row) => row.benchmark.within_configured_budget);
    const report = {
      schema_version: 1, status: performancePassed ? 'passed' : 'failed-performance-budget', functional_status: 'passed',
      performance_budget: { status: performancePassed ? 'passed' : 'failed', frame_budget_ms: options.frameBudgetMs },
      scope: 'isolated native Chromium stack; no third-party motion engines activated',
      recorded_at_utc: new Date().toISOString(), browser: { engine: 'chromium', version: browser.version(), mode: 'headless' },
      toolchain: { node: process.versions.node, playwright: require('playwright/package.json').version },
      provenance: { recovered_branch_head: 'd7d28e41912305ef7c418035490f8ab7fbc51a8d', original_18_latest_dependencies_installed: false, unrelated_741_14_patch_recovered: false },
      inputs: Object.fromEntries(['package.json', 'package-lock.json', 'options.mjs', 'native-probes.mjs', 'smoke.mjs', 'harness.html'].map((path) => [path, sha256(readFileSync(resolve(here, path)))])),
      cases, functional_rendering_cases: cases.length, webgpu_rendering_cases: 0,
      limitations: ['No production field metrics or physical mobile/Safari hardware was measured.', 'WebGPU API/adapter presence is availability only, never rendering evidence.', 'WebGL may use a software renderer; inspect each case.', 'A benchmark result applies only to this bounded lab workload.'],
      network: { bind: '127.0.0.1', external_requests: 0, authenticated_profiles: false }
    };
    if (out) writeFileSync(resolve(out, 'report.json'), JSON.stringify(report, null, 2) + '\n', { flag: 'wx', mode: 0o600 });
    return report;
  } finally {
    if (browser) await browser.close();
    server.closeAllConnections();
    await new Promise((done) => server.close(done));
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  try {
    const report = await runProbe(parseArgs(process.argv.slice(2)));
    console.log(JSON.stringify(report, null, 2));
    if (report.status !== 'passed') process.exitCode = 1;
  } catch (error) {
    console.error('Chromium stack failed: ' + error.message);
    process.exitCode = 1;
  }
}
