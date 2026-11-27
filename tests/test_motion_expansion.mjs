import assert from 'node:assert/strict';
import test from 'node:test';
import {createHash} from 'node:crypto';
import {readFileSync,existsSync} from 'node:fs';
import {definitions,getDefinition,sampleMotion,sampleScene,getCapabilities,structuralSignature,MAX_PRIMITIVES,MAX_POINTS} from '../motion-library/expansion/catalog.mjs';
import {examples,exampleFor} from '../motion-library/expansion/examples.mjs';

const hash=value=>createHash('sha256').update(JSON.stringify(value)).digest('hex');
const visibleGeometry = scene=>scene.primitives.map(p=>Object.fromEntries(Object.entries(p).filter(([key])=>!['fill','stroke','lineWidth','opacity'].includes(key))));
const validate = scene=>{
 assert(scene.primitives.length>0&&scene.primitives.length<=MAX_PRIMITIVES);
 assert.equal(scene.meta.engine,'canvas2d');
 for(const p of scene.primitives){
  assert(['circle','line','rect','polyline','text'].includes(p.type));
  for(const [key,value] of Object.entries(p)){
   if(typeof value==='number')assert(Number.isFinite(value),`${scene.meta.id}: ${key} not finite`);
  }
  if(p.type==='polyline'){
   assert(p.points.length>0&&p.points.length<=MAX_POINTS);
   for(const q of p.points)assert(Number.isFinite(q.x)&&Number.isFinite(q.y));
  }
  for(const key of ['r','radius','width','height','lineWidth','size'])if(key in p)assert(p[key]>=0,`${scene.meta.id}: negative ${key}`);
  if('opacity' in p)assert(p.opacity>=0&&p.opacity<=1,scene.meta.id);
 }
};

test('400 original recipes are 20 categories, 200 base mechanisms and 200 coupled compositions',()=>{
 assert.equal(definitions.length,400);assert.equal(new Set(definitions.map(d=>d.id)).size,400);
 const groups=Map.groupBy(definitions,d=>d.category_id);
 assert.equal(groups.size,20);
 for(const [category,rows]of groups){
  assert.equal(rows.length,20,category);
  assert.equal(rows.filter(d=>d.tier==='basic').length,10,category);
  assert.equal(rows.filter(d=>d.tier==='advanced').length,10,category);
 }
 assert.equal(getCapabilities().basic,200);assert.equal(getCapabilities().advanced,200);
 assert.equal(getCapabilities().gpu_required,false);
});

test('metadata is complete, bilingual, source-resolvable and does not preclaim runtime evidence',()=>{
 for(const d of definitions){
  assert.match(d.id,/^[a-z0-9-]{1,64}$/);assert.match(d.name_ar,/[\u0600-\u06ff]/);
  assert.match(d.name_en,/[A-Za-z]/);assert(d.mechanism.length>50);
  assert(existsSync(new URL('../'+d.source.module,import.meta.url)),d.id);
  assert.equal(d.engine,'canvas2d');assert.equal(d.license,'MIT');
  assert.equal(d.runtime_status,'pending-browser-evidence');
  assert.equal(d.operational_evidence.status,'requires-current-receipt');
  assert.equal(d.gpu.required,false);assert(d.mobile.compatible);assert(d.direction.rtl);
  assert.equal(d.reduced_motion.mode,'static-poster');
  assert(d.interactive_preview.endsWith('?motion='+d.id));
  assert(d.integration_example.endsWith('#'+d.id));
  assert.equal(d.automated_test,'tests/test_motion_expansion.mjs');assert(d.performance_benchmark);
  assert(Object.isFrozen(d));assert(Object.isFrozen(d.parameters));
 }
});

test('mechanism source graphs and style-stripped sampled geometry are unique',()=>{
 const graph=new Map(),geometries=new Map();
 for(const d of definitions){
  const key=structuralSignature(d.id);assert(!graph.has(key),`${d.id} duplicates ${graph.get(key)}`);graph.set(key,d.id);
  const signature=hash([.17,.5,.83].map(t=>visibleGeometry(sampleMotion(d,t))));
  assert(!geometries.has(signature),`${d.id} changes style only from ${geometries.get(signature)}`);
  geometries.set(signature,d.id);
  if(d.tier==='advanced'){
   assert.equal(d.composition.source_count,2);assert(d.composition.coupling);
   assert.notEqual(d.composition.secondary_family,d.category_id);
  }
 }
});

test('all 400 recipes produce bounded deterministic changing scenes in desktop and mobile dimensions',()=>{
 for(const d of definitions){
  for(const size of [{width:640,height:360},{width:390,height:844}]){
   const frames=[0,.17,.5,.83,1].map(t=>sampleMotion(d,t,size));
   frames.forEach(validate);
   assert.deepEqual(frames[2],sampleMotion(d,.5,size));
   assert(new Set(frames.map(scene=>hash(scene.primitives))).size>1,d.id+' is static in animated mode');
  }
 }
});

test('every reduced-motion alternative is a stable poster across all requested timestamps',()=>{
 for(const d of definitions){
  const a=sampleMotion(d,0,{reducedMotion:true}),b=sampleMotion(d,.5,{reducedMotion:true}),c=sampleMotion(d,1,{reducedMotion:true});
  validate(a);assert.deepEqual(a,b,d.id);assert.deepEqual(b,c,d.id);assert.equal(a.meta.progress,.65);
 }
});

test('RTL mirrors every primitive without reversing text and without mutating canonical metadata',()=>{
 for(const d of definitions){
  const a=sampleMotion(d,.37),b=sampleMotion(d,.37,{rtl:true});
  assert.equal(a.primitives.length,b.primitives.length);
  a.primitives.forEach((p,i)=>{
   const q=b.primitives[i];
   const near=(x,y)=>assert(Math.abs(x-y)<1e-8,d.id);
   if(p.type==='line'){near(p.x1+q.x1,640);near(p.x2+q.x2,640);near(p.y1,q.y1);}
   else if(p.type==='polyline')p.points.forEach((v,k)=>{near(v.x+q.points[k].x,640);near(v.y,q.points[k].y);});
   else if(p.type==='rect'){near(p.x+q.x+p.width,640);near(p.y,q.y);near(p.rotation||0,-(q.rotation||0));}
   else{near(p.x+q.x,640);near(p.y,q.y);if(p.type==='text')assert.equal(p.text,q.text);}
  });
 }
});

test('duration/color/quality variants never create new component identities and seed is bounded deterministic variation',()=>{
 const d=definitions[0],s=structuralSignature(d.id);
 assert.deepEqual(sampleMotion(d,-1),sampleMotion(d,0));assert.deepEqual(sampleScene(d,2),sampleMotion(d,1));
 assert.notEqual(hash(sampleMotion(d,.4,{seed:1}).primitives),hash(sampleMotion(d,.4,{seed:2}).primitives));
 assert.deepEqual(sampleMotion(d,.4,{seed:2}),sampleMotion(d,.4,{seed:2}));
 assert.equal(structuralSignature(d.id),s);
 assert.equal(definitions.length,400);
});

test('invalid options, non-finite times and unknown IDs fail closed; caller objects cannot inject code',()=>{
 for(const id of ['missing','../secrets','',null])assert.throws(()=>getDefinition(id));
 for(const t of [NaN,Infinity,-Infinity,'0.5'])assert.throws(()=>sampleMotion(definitions[0],t));
 for(const options of [null,[],{width:NaN},{width:0},{height:8192},{detail:1},{detail:1.5},{intensity:2},{seed:-1},{rtl:'yes'},{reducedMotion:1},{interaction:{x:Infinity}},{interaction:{y:2}}])assert.throws(()=>sampleMotion(definitions[0],.5,options));
 assert.deepEqual(sampleMotion({...definitions[0],build:()=>{throw new Error('injected');}},.5),sampleMotion(definitions[0],.5));
});

test('all integration examples execute against the same canonical sampler',()=>{
 assert.equal(Object.keys(examples).length,400);
 for(const d of definitions){assert.deepEqual(exampleFor(d.id).sample(.4),sampleMotion(d,.4));assert(exampleFor(d.id).usage.includes(d.id));}
 assert.throws(()=>exampleFor('__proto__'));
});

test('machine-readable definitions are regenerated from authored executable recipes',()=>{
 const doc=JSON.parse(readFileSync(new URL('../motion-library/expansion/definitions.json',import.meta.url)));
 assert.deepEqual(doc.definitions,definitions);assert.equal(doc.capabilities.components,400);
});
