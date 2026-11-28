// Fresh, bounded browser proof for new camera scenes; no real-device FPS claim.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readFileSync,writeFileSync,mkdirSync} from 'node:fs';
import {resolve,dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {serve} from '../motion-library/verify/serve.mjs';
const root=resolve(dirname(fileURLToPath(import.meta.url)),'..');
const req=createRequire(resolve(process.env.MOTION_PLAYWRIGHT_PACKAGE??resolve(root,'motion-library/chromium-stack'),'package.json'));
const playwright=req('playwright'),version=req('playwright/package.json').version;
assert.equal(version,JSON.parse(readFileSync(resolve(root,'motion-library/chromium-stack/package.json'))).devDependencies.playwright);
const browserName=process.env.MOTION_BROWSER??'chromium';
assert(['chromium','firefox','webkit'].includes(browserName));
const server=await serve(root),browser=await playwright[browserName].launch(browserName==='chromium'&&process.env.MOTION_CHROMIUM_EXECUTABLE?{executablePath:process.env.MOTION_CHROMIUM_EXECUTABLE}:{});
const errors=[],external=[],cases=[];
try{
 for(const viewport of [{width:390,height:844},{width:1280,height:720}]){
  const page=await browser.newPage({viewport});
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',route=>{if(new URL(route.request().url()).origin!==server.origin){external.push(route.request().url());return route.abort();}return route.continue();});
  await page.goto(server.origin+'/motion-studio/index.html');
  const rows=await page.evaluate(async({viewport})=>{
   const catalog=await import('/motion-library/expansion/nextgen-camera.mjs');
   const {createMotionSystem}=await import('/packages/motion-sdk/index.mjs');
   const rows=[];
   const hash=async data=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',data))).map(x=>x.toString(16).padStart(2,'0')).join('');
   for(const definition of catalog.definitions){
    const sdk=createMotionSystem();sdk.registerCatalog(catalog);
    const container=document.createElement('div');document.body.append(container);
    const clip=sdk.create(definition.id,{container,...viewport,pixelRatio:1,reducedMotion:'full'});
    const frame=async t=>{clip.render(t);const pixels=clip.canvas.getContext('2d').getImageData(0,0,viewport.width,viewport.height).data;let drawn=0;for(let i=0;i<pixels.length;i+=4)if(pixels[i]!==8||pixels[i+1]!==17||pixels[i+2]!==31)drawn++;return {sha256:await hash(pixels),drawn_pixels:drawn};};
    const a=await frame(.1),b=await frame(.5),c=await frame(.9),repeat=await frame(.5);
    clip.configure({reducedMotion:'reduce'});const reducedA=await frame(.1),reducedB=await frame(.9);
    clip.configure({rtl:true,reducedMotion:'full'});const rtl=await frame(.5);
    const benchmark=clip.benchmark({frames:45,budget_ms:25});
    const png=clip.export('png');const svg=clip.export('svg');
    clip.play();await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));clip.pause();const paused=clip.progress;
    await new Promise(r=>requestAnimationFrame(r));const pauseStable=paused===clip.progress;
    clip.resume();await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));clip.reverse();clip.stop();const stopped=clip.progress===0;
    clip.destroy();const cleanup=container.children.length===0&&sdk.getCapabilities().live_instances===0;container.remove();
    const checks={drawn:[a,b,c].every(x=>x.drawn_pixels>100),changes:a.sha256!==b.sha256&&b.sha256!==c.sha256,deterministic:b.sha256===repeat.sha256,reduced_motion:reducedA.sha256===reducedB.sha256,rtl:b.sha256!==rtl.sha256,exports:png.startsWith('data:image/png')&&svg.includes('<svg'),pause:pauseStable,stop:stopped,cleanup,cpu_budget:benchmark.within_cpu_budget};
    rows.push({id:definition.id,viewport,checks,frames:[a,b,c],benchmark});
   }
   return rows;
  },{viewport});
  cases.push(...rows);await page.close();
 }
 assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
 for(const row of cases)assert(Object.values(row.checks).every(v=>v===true),JSON.stringify(row));
 const sources=['motion-library/expansion/nextgen-camera.mjs','packages/motion-sdk/index.mjs','tests/test_nextgen_camera_browser.mjs','motion-library/chromium-stack/package.json','motion-library/chromium-stack/package-lock.json'];
 const inputs=Object.fromEntries(sources.map(p=>[p,createHash('sha256').update(readFileSync(resolve(root,p))).digest('hex')]));
 const receipt={schema_version:1,status:'passed',recorded_at_utc:new Date().toISOString(),browser:browserName,browser_version:browser.version(),playwright_version:version,platform:process.platform,inputs,cases,page_errors:errors.length,external_requests:external.length,production_fps_verified:false,real_devices_verified:false,gpu_runtime_verified:false};
 const output=process.env.NEXTGEN_CAMERA_RECEIPT;
 if(output){mkdirSync(dirname(resolve(output)),{recursive:true});writeFileSync(output,JSON.stringify(receipt,null,2)+'\n');}
 console.log(JSON.stringify({status:'passed',browser:browserName,cases:cases.length,max_p95_ms:Math.max(...cases.map(c=>c.benchmark.p95_ms)),receipt:output??null}));
}finally{await browser.close();await server.close();}
