// Runtime proof for the actual registered expansion, not a candidate catalog count.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {writeFileSync, mkdirSync, readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {serve} from '../motion-library/verify/serve.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const packageDirectory = process.env.MOTION_PLAYWRIGHT_PACKAGE ?? resolve(root, 'motion-library/verify');
const require = createRequire(resolve(packageDirectory, 'package.json'));
const playwright = require('playwright');
const playwrightVersion = require('playwright/package.json').version;
const expectedVersion = JSON.parse(readFileSync(resolve(root,'motion-library/verify/package.json'),'utf8')).devDependencies.playwright;
assert.equal(playwrightVersion,expectedVersion,'Use the exact reviewed motion verifier lockfile, not an ambient global Playwright');
const server = await serve(root);
const browserName = process.env.MOTION_BROWSER ?? 'chromium';
assert(['chromium','firefox','webkit'].includes(browserName),'Select an installed Playwright engine');
const browser = await playwright[browserName].launch(browserName === 'chromium' && process.env.MOTION_CHROMIUM_EXECUTABLE ? {executablePath: process.env.MOTION_CHROMIUM_EXECUTABLE} : {});
const results = [], allErrors = [], failures = [], external = [];
const evidenceDirectory = process.env.MOTION_STUDIO_EVIDENCE;
try {
  for (const viewport of [{width: 390,height: 844},{width: 1280,height: 900}]) {
    const context = await browser.newContext({viewport, reducedMotion: 'no-preference'});
    const page = await context.newPage();
    page.on('pageerror', (error) => allErrors.push(String(error)));
    page.on('requestfailed', (request) => failures.push(request.url()));
    page.on('response', (response) => { if (response.url().startsWith(server.origin) && response.status() >= 400) failures.push(`${response.status()} ${response.url()}`); });
    page.on('request', (request) => {
      const url = new URL(request.url());
      if (!['data:','blob:'].includes(url.protocol) && url.origin !== server.origin) external.push(request.url());
    });
    await page.goto(`${server.origin}/motion-studio/index.html`);
    await page.waitForFunction(() => document.documentElement.dataset.studioReady === 'true');
    const waapi = await page.evaluate(async () => {
      const {createMotionSystem} = await import('/packages/motion-sdk/index.mjs');
      const local=createMotionSystem(),target=document.createElement('div');
      target.style.cssText='position:fixed;width:20px;height:20px;background:#fff;inset-inline-start:0;inset-block-start:0';
      document.body.append(target);
      const clip=local.create({id:'browser-waapi-proof',engine:'waapi',duration_ms:1000,keyframes:[{offset:0,opacity:0},{offset:1,opacity:1}]},{target,reducedMotion:'full'});
      clip.render(.25);const quarter=Number(getComputedStyle(target).opacity);
      clip.render(.75);const threeQuarter=Number(getComputedStyle(target).opacity);
      clip.play();await new Promise((resolve)=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));clip.pause();
      const progressed=clip.progress>.75;
      clip.reverse().render(.5);const half=Number(getComputedStyle(target).opacity);
      clip.destroy();const cancelled=target.getAnimations().length===0;target.remove();
      return {quarter,threeQuarter,half,progressed,cancelled,optional_engines_installed:false};
    });
    assert(Math.abs(waapi.quarter-.25)<.01);assert(Math.abs(waapi.threeQuarter-.75)<.01);assert(Math.abs(waapi.half-.5)<.01);
    assert.equal(waapi.progressed,true);assert.equal(waapi.cancelled,true);
    const definitions = await page.evaluate(() => window.__motionStudio.definitions());
    assert.equal(definitions.length, 400, 'Exactly400new implemented definitions must be registered');
    assert.equal(new Set(definitions.map((row) => row.id)).size,400);
    assert.equal(await page.locator('#recipe-count').textContent(),'400');
    assert.equal(await page.locator('#catalog-list button').count(),30,'Catalog is paged, not400DOM previews');
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth+2),false,'No horizontal overflow');

    // Exercise end-user controls, seeking and locale/preferences before the full matrix.
    await page.locator('#reduced').selectOption('full');
    await page.locator('#play').click();
    await page.waitForFunction(() => window.__motionStudio.snapshot().progress > .01);
    await page.locator('#pause').click();
    const paused = await page.evaluate(() => window.__motionStudio.snapshot());
    await page.waitForTimeout(50);
    assert.equal((await page.evaluate(() => window.__motionStudio.snapshot())).progress,paused.progress);
    await page.locator('#resume').click();
    await page.waitForFunction((value) => window.__motionStudio.snapshot().progress > value,paused.progress);
    await page.locator('#reverse').click();
    await page.locator('#stop').click();
    assert.equal((await page.evaluate(() => window.__motionStudio.snapshot())).progress,0);
    await page.locator('#language').selectOption(viewport.width < 500 ? 'ar' : 'en');
    await page.locator('#direction').selectOption(viewport.width < 500 ? 'rtl' : 'ltr');
    await page.locator('#profile').selectOption(viewport.width < 500 ? 'mobile' : 'balanced');
    await page.locator('#intensity').fill('75');
    await page.locator('#intensity').dispatchEvent('input');
    await page.locator('#benchmark').click();
    assert.match(await page.locator('#operation-result').textContent(),/P95/);
    const [download] = await Promise.all([page.waitForEvent('download'),page.locator('#export-svg').click()]);
    assert(download.suggestedFilename().endsWith('.svg'));
    await page.locator('#search').fill('unlikely-query-with-no-match');
    assert.equal(await page.locator('#catalog-list button').count(),0);
    await page.locator('#search').fill('');
    await page.locator('#next').click();
    assert.match(await page.locator('#page-label').textContent(),/^2\s/);
    await page.locator('#previous').click();

    // Every ID is actually drawn on Canvas2D at3timeline positions; pixel output
    // and scene counts are recorded separately from sampling CPU measurements.
    const rows = await page.evaluate(() => {
      const api = window.__motionStudio;
      const digest = (data) => {
        let hash = 2166136261;
        for (let index=0;index<data.length;index+=4) {
          hash ^= data[index];hash = Math.imul(hash,16777619);
          hash ^= data[index+1];hash = Math.imul(hash,16777619);
          hash ^= data[index+2];hash = Math.imul(hash,16777619);
        }
        return (hash>>>0).toString(16).padStart(8,'0');
      };
      return api.definitions().map((definition) => {
        api.select(definition.id);
        const frames = [.17,.5,.83].map((progress) => {
          const start = performance.now(),scene = api.preview(progress),ms = performance.now()-start;
          const canvas = document.querySelector('#stage canvas');
          const pixels = canvas.getContext('2d').getImageData(0,0,canvas.width,canvas.height).data;
          let changed=0;
          for (let index=0;index<pixels.length;index+=4) {
            if (pixels[index]!==pixels[0]||pixels[index+1]!==pixels[1]||pixels[index+2]!==pixels[2])changed++;
          }
          if (!scene.primitives.length || !changed || api.snapshot().canvas_count!==1 || api.snapshot().live_instances!==1) throw new Error('Blank/leaking render: '+definition.id);
          return {progress,primitives:scene.primitives.length,changed_pixels:changed,pixel_fnv32:digest(pixels),sampling_and_draw_ms:ms};
        });
        const benchmark = api.benchmark(12);
        if (benchmark.production_fps_verified!==false || !Number.isFinite(benchmark.p95_ms))throw new Error('Invalid benchmark: '+definition.id);
        return {id:definition.id,frames,benchmark};
      });
    });
    assert.equal(rows.length,400);
    for (const row of rows) assert(row.frames.every((frame) => frame.changed_pixels > 0));

    // Reduced motion is a stable poster in the real browser for every recipe.
    await page.locator('#reduced').selectOption('reduce');
    const reduced = await page.evaluate(() => window.__motionStudio.definitions().map((definition) => {
      const api=window.__motionStudio;api.select(definition.id);
      const a=api.preview(.1),b=api.preview(.9);
      if (JSON.stringify(a.primitives)!==JSON.stringify(b.primitives))throw new Error('Reduced motion changes with time: '+definition.id);
      return {id:definition.id,primitives:a.primitives.length,stable:true};
    }));
    await page.locator('#play').click();
    assert.equal((await page.evaluate(() => window.__motionStudio.snapshot())).state,'finished');
    await page.locator('#theme').click();
    assert.equal(await page.evaluate(() => document.documentElement.dataset.theme),'light');
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth+2),false);
    if (evidenceDirectory) {
      mkdirSync(evidenceDirectory,{recursive:true});
      await page.screenshot({path:resolve(evidenceDirectory,`studio-${viewport.width}.png`),fullPage:true});
    }
    results.push({viewport,language:viewport.width<500?'ar':'en',direction:viewport.width<500?'rtl':'ltr',rendered_definitions:rows.length,frames_per_definition:3,waapi_adapter:waapi,results:rows,reduced_motion:reduced,errors:[]});
    await context.close();
  }
  assert.deepEqual(allErrors,[]);assert.deepEqual(failures,[]);assert.deepEqual(external,[]);
  const sourceFiles = ['packages/motion-sdk/index.mjs','motion-studio/index.html','motion-studio/studio.mjs','motion-studio/styles.css','motion-library/expansion/catalog.mjs','motion-library/expansion/definitions.json','motion-library/expansion/families.mjs','motion-library/expansion/systems.mjs','motion-library/expansion/geometry.mjs','tests/test_motion_studio_browser.mjs'];
  const source_sha256 = Object.fromEntries(sourceFiles.map((path)=>[path,createHash('sha256').update(readFileSync(resolve(root,path))).digest('hex')]));
  const report={schema_version:1,status:'passed',recorded_at_utc:new Date().toISOString(),sdk_version:'1.0.0',engine:`${browserName}-canvas2d`,browser:browser.version(),playwright_version:playwrightVersion,node_version:process.version,source_sha256,new_definitions_rendered:400,viewport_profiles:2,frame_samples:2400,reduced_motion_cases:800,production_fps_verified:false,gpu_runtime_verified:false,results};
  if (evidenceDirectory) writeFileSync(resolve(evidenceDirectory,'motion-studio-runtime.json'),JSON.stringify(report,null,2)+'\n');
  console.log(JSON.stringify({status:'passed',definitions:400,viewport_profiles:2,frame_samples:2400,reduced_motion_cases:800,browserName,browser:browser.version(),production_fps_verified:false}));
} finally {
  await browser.close();server.close();
}
