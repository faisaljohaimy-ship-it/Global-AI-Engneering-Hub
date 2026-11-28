import assert from 'node:assert/strict';
import test from 'node:test';
import * as catalog from '../motion-library/expansion/nextgen-camera.mjs';
import {createMotionSystem,validateScene} from '../packages/motion-sdk/index.mjs';
for(const definition of catalog.definitions){
  test(`${definition.id}: real projection, deterministic time, SDK lifecycle and accessibility`,()=>{
    const sdk=createMotionSystem();sdk.registerCatalog(catalog);
    const clip=sdk.create(definition.id,{width:390,height:844,reducedMotion:'full'});
    const first=clip.render(.1),later=clip.render(.8);
    assert.notDeepEqual(first.primitives,later.primitives);assert.deepEqual(later,clip.render(.8));
    assert(first.primitives.length>10);validateScene(first);
    for(const p of first.primitives)for(const k of ['x1','x2'])assert(p[k]>=-.00001&&p[k]<=390.00001);
    clip.configure({reducedMotion:'reduce'});assert.deepEqual(clip.render(.1),clip.render(.9));
    clip.configure({reducedMotion:'full',rtl:true});const rtl=clip.render(.1);
    assert.notDeepEqual(first.primitives,rtl.primitives);assert.equal(rtl.primitives.length,first.primitives.length);
    first.primitives.forEach((p,i)=>assert(Math.abs(p.x1+rtl.primitives[i].x1-390)<1e-6));
    assert.match(clip.export('svg'),/<svg/);assert.equal(clip.benchmark({frames:20}).production_fps_verified,false);
    clip.destroy();assert.equal(sdk.getCapabilities().live_instances,0);assert.throws(()=>clip.render(.1));
  });
}
test('rejects unknown cameras, unsafe dimensions, non-finite progress and flags',()=>{
  for(const [id,t,o]of [['unknown',0,{}],['camera-drone-approach',NaN,{}],['camera-drone-approach',0,{width:0}],['camera-drone-approach',0,{rtl:'yes'}]])assert.throws(()=>catalog.sampleMotion(id,t,o));
});
