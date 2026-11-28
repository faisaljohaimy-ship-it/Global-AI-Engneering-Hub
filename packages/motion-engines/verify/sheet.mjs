#!/usr/bin/env node
// Contact sheet for looking at motions: three moments of each, side by side, in one PNG.
// The harness proves a motion works; only eyes can tell whether it looks right.
//
//   node packages/motion-engines/verify/sheet.mjs --module quantum --out /tmp/quantum.png [--direction rtl]
import { createRequire } from 'node:module';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { serve } from './serve.mjs';
import { scan } from '../tools/build_registry.mjs';

const sdk = resolve(fileURLToPath(new URL('..', import.meta.url)));
const option = (name) => {
  const index = process.argv.indexOf(`--${name}`);
  return index > 0 ? process.argv[index + 1] : undefined;
};
const out = option('out');
const entries = await scan({ module: option('module'), id: option('id') });
if (!out || !entries.length) {
  console.error('Usage: sheet.mjs --out FILE.png [--module key | --id id] [--direction rtl]');
  process.exit(2);
}
const { chromium } = createRequire(import.meta.url)('playwright');
const server = await serve(sdk);
const browser = await chromium.launch({ args: ['--enable-unsafe-webgpu', '--enable-features=Vulkan,WebGPU', '--use-webgpu-adapter=swiftshader', '--ignore-gpu-blocklist'] });
try {
  const page = await browser.newPage({ viewport: { width: 3 * 324 + 8, height: 400 }, deviceScaleFactor: 1 });
  await page.goto(`${server.origin}/verify/harness.html`);
  await page.waitForFunction(() => window.h);
  await page.evaluate(async ({ ids, direction }) => {
    const { createMotion } = await import('../core/api.mjs');
    const scan = await Promise.all(ids.map((id) => window.h.load(id)));
    document.body.style.cssText = 'margin:0;padding:4px;background:#111;display:grid;grid-template-columns:repeat(3,320px);grid-auto-rows:min-content;align-content:start;gap:4px;font:11px system-ui;color:#ddd;';
    document.body.replaceChildren();
    for (const id of ids) {
      const label = document.createElement('div');
      label.style.cssText = 'grid-column:1/-1;padding-top:4px;';
      label.textContent = id;
      document.body.append(label);
      for (const progress of [0.2, 0.5, 0.85]) {
        const cell = document.createElement('div');
        cell.style.cssText = 'width:320px;height:180px;';
        document.body.append(cell);
        const definition = scan[ids.indexOf(id)];
        const instance = await createMotion(definition, { container: cell, width: 320, height: 180, pixelRatio: 1, quality: 'high', direction, reducedMotion: false, gpu: definition.engine === 'webgpu-wgsl' ? 'readback' : 'auto' });
        instance.render({ progress });
        await instance.settled();
        const canvas = cell.querySelector('canvas');
        if (canvas && cell.querySelectorAll('canvas').length === 1 && instance.capture()) {
          // Keep the picture and free the WebGL context: a page may hold only a few at once.
          const image = new Image();
          image.src = canvas.toDataURL();
          await image.decode();
          instance.destroy();
          cell.append(image);
        }
      }
    }
  }, { ids: entries.map((entry) => entry.id), direction: option('direction') ?? 'ltr' });
  await page.evaluate(() => new Promise((painted) => requestAnimationFrame(() => requestAnimationFrame(painted))));
  await page.screenshot({ path: out, fullPage: true });
  console.log(`${entries.length} motions -> ${out}`);
} finally {
  await browser.close();
  server.close();
}
