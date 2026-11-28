import test from 'node:test';
import assert from 'node:assert/strict';
import {createMotionSystem, drawScene, sceneToSVG, validateScene} from '../packages/motion-sdk/index.mjs';
import {frameSequence} from '../packages/motion-sdk/examples.mjs';

const definition = {id: 'test-orbit', name_ar: 'مدار اختباري', name_en: 'Test orbit', duration_ms: 1000, engine: 'canvas2d'};
const sampleMotion = (motion, progress, options) => ({width: options.width, height: options.height, background: '#08111f',
  primitives: [{type: 'circle', x: options.rtl ? options.width * (1 - progress) : options.width * progress,
    y: options.height / 2, r: 12, fill: '#00ffff', opacity: 1}],
  meta: {id: motion.id, progress: options.reducedMotion ? 1 : progress, engine: 'canvas2d', reducedMotion: options.reducedMotion}});
function fixture() {
  const sdk = createMotionSystem(); sdk.registerCatalog({definitions: [definition], sampleMotion});
  return sdk;
}
function scheduler() {
  let time = 0, id = 0; const scheduled = new Map();
  return {now: () => time, requestFrame: (callback) => { scheduled.set(++id, callback); return id; },
    cancelFrame: (key) => scheduled.delete(key), get pending() { return scheduled.size; },
    advance(value) { time = value; const jobs = [...scheduled.values()]; scheduled.clear(); jobs.forEach((callback) => callback(time)); }};
}
function context() {
  const calls = [];
  const ctx = {calls};
  for (const method of ['setTransform','clearRect','fillRect','save','restore','beginPath','arc','moveTo','lineTo','closePath','rect','roundRect','translate','rotate','fill','stroke','fillText','strokeText']) {
    ctx[method] = (...args) => calls.push([method, ...args]);
  }
  return ctx;
}
function canvas(ctx = context()) {
  const attributes = new Map([['style', 'border:1px solid red']]);
  return {width: 31, height: 47, style: {}, getContext: () => ctx, context: ctx,
    getAttribute: (name) => attributes.get(name) ?? null,
    setAttribute: (name, value) => attributes.set(name, value), removeAttribute: (name) => attributes.delete(name),
    toDataURL: () => 'data:image/png;base64,AA==', remove() { this.removed = true; }};
}

test('deterministic frames and logical direction are isolated from metadata mutation', () => {
  const sdk = fixture(), instance = sdk.create('test-orbit', {width: 200, height: 100});
  const first = instance.render(.25); assert.equal(first.primitives[0].x, 50);
  first.primitives[0].x = 999; assert.equal(instance.render(.25).primitives[0].x, 50);
  const mirrored = sdk.create('test-orbit', {width: 200, height: 100, rtl: true});
  assert.equal(mirrored.render(.25).primitives[0].x, 150);
  assert.throws(() => { instance.definition.id = 'changed'; }, TypeError);
  assert.equal(frameSequence(instance, {frames: 3}).length, 3);
  instance.destroy(); mirrored.destroy(); assert.equal(sdk.getCapabilities().live_instances, 0);
});

test('play/pause/resume/reverse/stop use an actual controlled scheduler and clean it', () => {
  const sdk = fixture(), time = scheduler(), instance = sdk.create('test-orbit', time);
  instance.play(); assert.equal(time.pending, 1);
  time.advance(250); assert.equal(instance.progress, .25);
  instance.pause(); assert.equal(time.pending, 0); assert.equal(instance.state, 'paused');
  time.advance(500); assert.equal(instance.progress, .25);
  instance.resume(); time.advance(750); assert.equal(instance.progress, .5);
  instance.reverse(); time.advance(1000); assert.equal(instance.progress, .25);
  instance.stop(); assert.equal(instance.progress, 0); assert.equal(instance.state, 'idle');
  assert.equal(time.pending, 0); instance.reverse().play(); time.advance(2000);
  assert.equal(instance.progress, 0); assert.equal(instance.state, 'finished');
  instance.destroy(); assert.throws(() => instance.play(), /destroyed/); assert.equal(time.pending, 0);
});

test('reduced motion never schedules a frame; capabilities are honest about optional engines', () => {
  const sdk = fixture(), time = scheduler();
  const instance = sdk.create('test-orbit', {...time, reducedMotion: 'auto', view: {matchMedia: () => ({matches: true})}});
  instance.play(); assert.equal(instance.state, 'finished'); assert.equal(time.pending, 0);
  assert.equal(instance.render(.2).meta.reducedMotion, true);
  assert.deepEqual(instance.render(.2).primitives, instance.render(.8).primitives);
  assert.equal(instance.getCapabilities().webgpu, 'not-enabled');
  assert.equal(instance.getCapabilities().remotion, 'not-installed');
  assert.equal(instance.getCapabilities().encoded_video, false); instance.destroy();
});

test('caller-owned canvas is restored and created canvas is removed on destroy or failure', () => {
  const sdk = fixture(), external = canvas();
  const instance = sdk.create('test-orbit', {canvas: external, width: 320, height: 180, pixelRatio: 2});
  assert.equal(external.width, 640); assert.equal(external.height, 360);
  assert(external.context.calls.some((call) => call[0] === 'arc'));
  instance.destroy(); assert.equal(external.width, 31); assert.equal(external.height, 47); assert(!external.removed);
  const created = canvas(), container = {ownerDocument: {createElement: () => created}, append: () => {}};
  const owned = sdk.create('test-orbit', {container}); owned.destroy(); assert.equal(created.removed, true);
  const invalid = canvas(); invalid.getContext = () => null;
  assert.throws(() => sdk.create('test-orbit', {container: {ownerDocument: {createElement: () => invalid}, append: () => {}}}), /unavailable/);
  assert.equal(invalid.removed, true);
});

test('all five finite primitives draw and SVG text is safely escaped', () => {
  const scene = {width: 200, height: 100, background: '#000000', primitives: [
    {type: 'circle', x: 20, y: 20, r: 5, fill: '#ffffff'},
    {type: 'line', x1: 0, y1: 0, x2: 100, y2: 100, stroke: '#ffffff'},
    {type: 'polyline', points: [{x: 0, y: 0}, {x: 100, y: 0}, {x: 100, y: 100}], stroke: '#ffffff', closed: true},
    {type: 'rect', x: 10, y: 10, width: 20, height: 20, fill: '#ffffff', radius: 4, rotation: .5},
    {type: 'text', x: 100, y: 50, text: '<script>&" unsafe', size: 16, fill: '#ffffff'},
  ]};
  const ctx = context(); drawScene(ctx, scene); assert(ctx.calls.some((call) => call[0] === 'fillText'));
  assert.doesNotThrow(()=>validateScene({...scene,primitives:[{type:'circle',x:1,y:1,r:1,fill:'rgba(96,224,244,1.6980436163343905e-9)'}]}));
  const svg = sceneToSVG(scene); assert(svg.startsWith('<svg')); assert(svg.includes('&lt;script&gt;&amp;')); assert(!svg.includes('<script>'));
});

test('invalid dimensions, budgets, primitives and unsafe exports are refused', () => {
  const sdk = fixture();
  for (const options of [{width: NaN}, {height: Infinity}, {width: 4096, height: 4096}, {detail: 50}, {seed: -.5}, {intensity: 2}, {rtl: 'yes'}, {interaction: {x: 2, y: 0}}, {reducedMotion: 'maybe'}, {engine: 'webgpu'}]) {
    assert.throws(() => sdk.create('test-orbit', options));
  }
  for (const primitive of [{type: 'image', src: 'https://example.com'}, {type: 'circle', x: 0, y: 0, r: -1}, {type: 'rect', x: 0, y: 0, width: 2, height: 2, fill: 'url(https://example.com)'}]) {
    assert.throws(() => validateScene({width: 100, height: 100, primitives: [primitive]}));
  }
  const instance = sdk.create('test-orbit'); assert.throws(() => instance.export('mp4'), /reviewed renderer/);
  assert.throws(() => instance.play(), /scheduling/); assert.throws(() => instance.render(NaN)); instance.destroy();
});

test('registration fails atomically on duplicates and remote catalog imports are refused', async () => {
  const sdk = fixture();
  assert.throws(() => sdk.registerCatalog({definitions: [{...definition, id: 'second'}, definition], sampleMotion}), /Duplicate/);
  assert.equal(sdk.definitions().length, 1);
  await assert.rejects(sdk.loadCatalog('https://example.com/catalog.mjs'), /local or same-origin/);
  assert.throws(() => sdk.create('not-registered'));
});

test('separate reviewed catalogs retain their own sampler when another pack registers', () => {
  const sdk = fixture();
  sdk.registerCatalog({definitions:[{...definition,id:'separate-catalog'}],sampleMotion:(definition,progress,options)=>{
    const scene=sampleMotion(definition,progress,options);scene.primitives[0].x=17;return scene;
  }});
  const first=sdk.create('test-orbit',{width:200}),second=sdk.create('separate-catalog',{width:200});
  assert.equal(first.render(.5).primitives[0].x,100);assert.equal(second.render(.5).primitives[0].x,17);
  sdk.destroyAll();assert.equal(sdk.getCapabilities().live_instances,0);
});

test('frame export and bounded benchmark distinguish measurements from production FPS', () => {
  const sdk = fixture(), instance = sdk.create('test-orbit', {canvas: canvas()});
  const json = JSON.parse(instance.export('json', .5)); assert.equal(json.scene.primitives[0].x, 320);
  assert(instance.export('svg', .5).includes('<circle'));
  assert(instance.export('png').startsWith('data:image/png'));
  assert.equal(instance.optimize({profile: 'mobile'}).detail, 6);
  assert.equal(instance.optimize({profile: 'mobile'}).pixelRatio, 1);
  instance.configure({width: 320,height: 180,rtl: true,intensity: .5});
  assert.equal(instance.render(.25).primitives[0].x,240);
  assert.throws(() => instance.configure({width: NaN}));
  assert.throws(() => instance.configure({unknown: true}));
  assert.equal(instance.render(.25).primitives[0].x,240);
  const measured = instance.benchmark({frames: 10});
  assert.equal(measured.frames, 10); assert.equal(measured.production_fps_verified, false); assert(measured.p95_ms >= 0);
  assert.throws(() => instance.benchmark({frames: Infinity})); assert.throws(() => instance.benchmark({frames: 1}));
  instance.destroy();
});

test('WAAPI uses an explicit real-host adapter contract and the same lifecycle', () => {
  const sdk = createMotionSystem(), time = scheduler();
  const animation = {pause() { this.paused = true; }, cancel() { this.cancelled = true; }, currentTime: null};
  const target = {animate(frames, options) { assert.equal(frames.length, 2); assert.equal(options.duration, 1000); return animation; }};
  const spec = {id: 'local-waapi', duration_ms: 1000, engine: 'waapi', keyframes: [{offset: 0, opacity: 0}, {offset: 1, opacity: 1}]};
  const instance = sdk.create(spec, {target, ...time}); assert.equal(animation.currentTime, 0);
  instance.render(.5); assert.equal(animation.currentTime, 500);
  assert.equal(JSON.parse(instance.export('json')).scene.meta.engine, 'waapi');
  assert.throws(() => instance.export('svg'), /JSON export only/);
  instance.play(); time.advance(250); assert.equal(instance.progress, .75);
  instance.destroy(); assert.equal(animation.cancelled, true); assert.equal(time.pending, 0);
  assert.throws(() => sdk.create({...spec, keyframes: [{opacity: 0, transform: 'url(javascript:x)'}, {opacity: 1}]}, {target}), /Unsafe/);
  assert.throws(() => sdk.create({...spec, keyframes: [{offset: 1, opacity: 0}, {offset: 0, opacity: 1}]}, {target}), /Unordered/);
});
