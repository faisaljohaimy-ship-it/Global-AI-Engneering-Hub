import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import * as catalog from '../motion-library/expansion/nextgen-motion-systems.mjs';
import {createMotionSystem, validateScene} from '../packages/motion-sdk/index.mjs';

const inventory = JSON.parse(readFileSync(new URL(
  '../docs/evidence/nextgen-cinematic-inventory.json',import.meta.url)));
const requested = inventory.motions
  .filter(row => (row.number >= 41 && row.number <= 50) || (row.number >= 161 && row.number <= 170))
  .map(row => row.id);
const times = [.1,.5,.9];

function bareGeometry(primitives) {
  return primitives.filter(item => item.type !== 'text').map(({
    fill,stroke,lineWidth,opacity,...geometry
  }) => geometry);
}
function mirrored(actual, original, width) {
  const coordinate = (left,right) => assert(Math.abs(left + right - width) < 1e-8);
  assert.equal(actual.type,original.type);
  switch (actual.type) {
    case 'line':
      coordinate(actual.x1,original.x1);
      coordinate(actual.x2,original.x2);
      break;
    case 'polyline':
      actual.points.forEach((point,i)=>coordinate(point.x,original.points[i].x));
      break;
    case 'rect':
      coordinate(actual.x, original.x + original.width);
      break;
    default:
      coordinate(actual.x,original.x);
  }
}

test('the neural and network catalogs fill the twenty specified original identities', () => {
  assert.deepEqual(catalog.definitions.map(row=>row.id),requested);
  assert.equal(new Set(catalog.definitions.map(row=>row.mechanism)).size,requested.length);
  for (const entry of catalog.definitions) {
    assert.match(entry.name_ar,/\p{Script=Arabic}/u);
    assert.equal(entry.license,'MIT');
    assert.equal(entry.engine,'canvas2d');
    assert.equal(entry.runtime_status,'requires-current-source-bound-proof');
    assert(entry.name_en.length > 8);
  }
});

for (const definition of catalog.definitions) {
  test(`${definition.id} renders changing, distinct geometry and supports SDK options`, () => {
    for (const [width,height] of [[390,844],[1280,720]]) {
      const frames=times.map(t=>validateScene(catalog.sampleMotion(definition.id,t,{width,height})));
      assert.equal(new Set(frames.map(frame=>JSON.stringify(bareGeometry(frame.primitives)))).size,3);
      assert(frames.every(frame=>frame.primitives.length >= 6 && frame.primitives.length <= 130));
    }
    const sdk=createMotionSystem();
    sdk.registerCatalog(catalog);
    const width=390;
    const clip=sdk.create(definition.id,{width,height:844,reducedMotion:'full'});
    const middle=clip.render(.5);
    assert.deepEqual(middle,clip.render(.5));
    clip.configure({rtl:true});
    const rtl=clip.render(.5);
    assert.equal(rtl.primitives.length,middle.primitives.length);
    rtl.primitives.forEach((item,i)=>mirrored(item,middle.primitives[i],width));
    clip.configure({reducedMotion:'reduce'});
    assert.deepEqual(clip.render(.1),clip.render(.9));
    assert.match(clip.export('svg'),/<svg/);
    clip.destroy();
    assert.equal(sdk.getCapabilities().live_instances,0);
  });
}
test('the mechanisms have distinct style-independent geometry, including within each family', () => {
  const signatures=catalog.definitions.map(({id})=>JSON.stringify(times.map(t=>
    bareGeometry(catalog.sampleMotion(id,t).primitives))));
  assert.equal(new Set(signatures).size,catalog.definitions.length);
});
test('grid routing computes a shortest contiguous path around blocked tiles', () => {
  const scene=catalog.sampleMotion('networks-signal-routing',.5,{width:400,height:400});
  const path=scene.primitives.find(item=>item.type==='polyline').points.map(({x,y})=>
    Math.round((y/400-.22)/.114)*6+Math.round((x/400-.15)/.133));
  assert.equal(path[0],0);
  assert.equal(path.at(-1),29);
  assert.equal(path.length,10);
  const blocked=new Set([7,8,9,15,21]);
  path.forEach((tile,i)=>{
    assert(!blocked.has(tile));
    if (i === 0) return;
    const last=path[i-1];
    assert.equal(Math.abs(tile%6-last%6)+Math.abs(Math.floor(tile/6)-Math.floor(last/6)),1);
  });
});
test('distributed system reports acknowledgements only after the messages return', () => {
  const acknowledgment = t => catalog.sampleMotion('networks-distributed-system',t).primitives.at(-1).text;
  assert.equal(acknowledgment(.1),'ACK 0/3');
  assert.equal(acknowledgment(.7),'ACK 1/3');
  assert.equal(acknowledgment(.9),'ACK 2/3');
  assert.equal(acknowledgment(1),'ACK 3/3');
});
test('the sampler rejects invalid timing, dimensions and direction flags', () => {
  const id='networks-signal-routing';
  for (const args of [['unknown',0], [id,NaN], [id,1,{width:0}], [id,.1,{intensity:2}], [id,.5,{rtl:'ltr'}]]) {
    assert.throws(()=>catalog.sampleMotion(...args),RangeError);
  }
});
