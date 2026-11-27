import { chromium } from 'playwright';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
const require = createRequire(import.meta.url);
const manifest = JSON.parse(readFileSync(new URL('./package.json', import.meta.url)));
for (const name of Object.keys(manifest.dependencies)) {
  try { require.resolve(name); console.log('resolved', name); }
  catch { console.warn('entry resolution requires review', name); }
}
const browser = await chromium.launch({headless:true});
try {
 const page = await browser.newPage({reducedMotion:'reduce'});
 await page.setContent('<style>@keyframes fade{from{opacity:0}to{opacity:1}} #card{animation:fade 100ms both} @media(prefers-reduced-motion:reduce){#card{animation:none}}</style><div id="card">Motion</div>');
 const result = await page.evaluate(async()=>{
  const card=document.querySelector('#card');
  const anim=card.animate([{opacity:0},{opacity:1}],{duration:100});
  anim.finish(); await anim.finished;
  return {waapi:typeof card.animate==='function', reducedMotion:matchMedia('(prefers-reduced-motion: reduce)').matches, webgl:!!document.createElement('canvas').getContext('webgl2'), webgpu:!!navigator.gpu, css:getComputedStyle(card).animationName==='none'};
 });
 console.log(JSON.stringify(result));
 if(!result.waapi || !result.reducedMotion || !result.css) throw Error('Motion smoke failed');
} finally {await browser.close();}
