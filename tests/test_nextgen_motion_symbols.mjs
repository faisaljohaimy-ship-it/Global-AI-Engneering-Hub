import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import * as catalog from '../motion-library/expansion/nextgen-motion-symbols.mjs';
import {createMotionSystem,validateScene} from '../packages/motion-sdk/index.mjs';

const brief = JSON.parse(readFileSync(new URL('../docs/evidence/nextgen-cinematic-inventory.json',import.meta.url)));
const originalNumbers = [81,82,83,84,85,86,87,89,90,141,142,143,144,145,146,147,148,149,150];
const times = [.1, .5, .9];

const geometry = primitives => primitives.map(({fill,stroke,opacity,lineWidth,...shape}) => shape);

test('symbol catalog covers the requested original typography and icon identities',()=>{
  assert.deepEqual(catalog.definitions.map(row=>row.id),
    brief.motions.filter(row=>originalNumbers.includes(row.number)).map(row=>row.id));
  assert.equal(new Set(catalog.definitions.map(row=>row.mechanism)).size,originalNumbers.length);
  for(const row of catalog.definitions) {
    assert.match(row.name_ar,/\p{Script=Arabic}/u);
    assert.equal(row.license,'MIT');
    assert.equal(row.engine,'canvas2d');
    assert.equal(row.runtime_status,'requires-current-source-bound-proof');
  }
});

for(const {id} of catalog.definitions) {
  test(`${id} draws unique timed geometry with deterministic RTL and reduced motion`,()=>{
    const sdk=createMotionSystem();
    sdk.registerCatalog(catalog);
    for(const [width,height] of [[390,844],[1280,720]]) {
      const clip=sdk.create(id,{width,height,reducedMotion:'full'});
      const frames=times.map(t=>validateScene(clip.render(t)));
      assert.equal(new Set(frames.map(frame=>JSON.stringify(geometry(frame.primitives)))).size,3);
      assert(frames.every(frame=>frame.primitives.length>=2&&frame.primitives.length<=155));
      assert.deepEqual(clip.render(.5),frames[1]);
      clip.configure({rtl:true});
      assert.notDeepEqual(clip.render(.5).primitives,frames[1].primitives);
      assert.match(clip.export('svg'),/<svg/);
      clip.configure({rtl:false,reducedMotion:'reduce'});
      assert.deepEqual(clip.render(.1),clip.render(.9));
      clip.destroy();
      assert.equal(sdk.getCapabilities().live_instances,0);
    }
  });
}

test('mechanisms have distinct scene geometry across both original families',()=>{
  const shapes=catalog.definitions.map(({id})=>JSON.stringify(times.map(t=>geometry(catalog.sampleMotion(id,t).primitives))));
  assert.equal(new Set(shapes).size,shapes.length);
});

test('interactive icon yaw, pitch and morph respond to a pointer during full motion',()=>{
  for(const id of ['icons-reactive-rotation','icons-morphing']) {
    const still = catalog.sampleMotion(id,.5);
    const moved = catalog.sampleMotion(id,.5,{interaction:{x:.7,y:-.8}});
    assert.notDeepEqual(geometry(moved.primitives),geometry(still.primitives));
    const poster = catalog.sampleMotion(id,.5,{reducedMotion:true});
    assert.deepEqual(poster,catalog.sampleMotion(id,.5,{reducedMotion:true,interaction:{x:.7,y:-.8}}));
  }
});

test('vector lettering uses real width and weight changes without reversing Arabic stroke order',()=>{
  const id='typography-variable-font';
  const low=catalog.sampleMotion(id,.1).primitives[0];
  const high=catalog.sampleMotion(id,.5).primitives[0];
  assert(high.lineWidth>low.lineWidth);
  assert(high.points[2].x-high.points[1].x>low.points[2].x-low.points[1].x);
  for(const rtl of [true,false]) {
    const [outline]=catalog.sampleMotion('typography-calligraphy-path',.5,{rtl}).primitives;
    assert(outline.points[0].x>outline.points.at(-1).x);
  }
});

test('reject invalid dimensions, timing, and pointer input without invoking the sampler',()=>{
  const id='icons-reactive-rotation';
  for(const input of [['missing',1], [id,Infinity], [id,.5,{width:1}], [id,.5,{rtl:1}],
    [id,.5,{interaction:{x:2,y:0}}], [id,.5,{interaction:null}]]) assert.throws(()=>catalog.sampleMotion(...input),RangeError);
});
