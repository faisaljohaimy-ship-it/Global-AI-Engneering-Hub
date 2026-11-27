import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { serve } from '../motion-library/verify/serve.mjs';

const repository = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const components = JSON.parse(readFileSync(resolve(repository, 'motion-library/components.json'), 'utf8')).components;
const playwright = createRequire(new URL('../motion-library/verify/package.json', import.meta.url))('playwright');
const executablePath = process.env.MOTION_CHROMIUM_EXECUTABLE;
const server = await serve(repository);
const browser = await playwright.chromium.launch(executablePath ? { executablePath } : {});

try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const pageErrors = [];
  const failedRequests = [];
  const externalRequests = [];
  page.on('pageerror', (error) => pageErrors.push(String(error)));
  page.on('requestfailed', (request) => failedRequests.push(request.url()));
  page.on('request', (request) => {
    const url = new URL(request.url());
    if (url.protocol !== 'data:' && !['127.0.0.1', 'localhost'].includes(url.hostname)) externalRequests.push(request.url());
  });
  await page.goto(`${server.origin}/motion-lab/index.html`);
  await page.waitForFunction(() => document.documentElement.dataset.labReady === 'true');

  const listed = await page.locator('#motionList .catalog-button').count();
  assert.equal(listed, 142);
  const initial = await page.evaluate(() => structuredClone(window.__motionLabReport));
  assert.deepEqual(
    { indexed: initial.indexed, implemented: initial.implemented, tested: initial.tested, used: initial.used },
    { indexed: 142, implemented: 30, tested: 30, used: 30 },
  );

  for (const component of components) {
    await page.locator(`#motionList [data-id="${component.id}"]`).click();
    // The shader stays explicitly pending engine-runtime evidence. Its reduced state
    // still exercises the Lab control without promoting a WebGL claim here.
    await page.locator('#motionMode').selectOption(component.id === 'spatial-fresnel-rim' ? 'reduce' : 'full');
    await page.locator('#play').click();
    await page.waitForTimeout(35);
    const error = await page.evaluate(() => window.__motionLabReport.error);
    assert.equal(error, null, `${component.id} failed in Motion Lab: ${error}`);
    await page.locator('#stop').click();
    const active = await page.evaluate(() => document.getAnimations().filter((animation) => animation.playState === 'running').length);
    assert.equal(active, 0, `${component.id} kept animating after Stop`);
  }

  assert.deepEqual(pageErrors, []);
  assert.deepEqual(failedRequests, []);
  assert.deepEqual(externalRequests, []);
  console.log(`Motion Lab: ${listed} indexed, ${components.length} executable controls passed`);
} finally {
  await browser.close();
  server.close();
}
