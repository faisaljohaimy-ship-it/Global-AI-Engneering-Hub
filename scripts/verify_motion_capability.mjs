import assert from 'node:assert/strict';
import {createMotionSystem} from '../packages/motion-sdk/index.mjs';
import * as catalog from '../motion-library/expansion/catalog.mjs';

const system = createMotionSystem();
system.registerCatalog(catalog);
const definition = catalog.getDefinition('os-quantum-b01');
const options = {width: 320, height: 180, seed: 17, rtl: true, reducedMotion: false};
const instance = system.create(definition.id, options);
const reduced = system.create(definition.id, {...options, reducedMotion: true});
let svg;
try {
  const first = instance.render(.25);
  assert.deepEqual(first, instance.render(.25));
  assert.notDeepEqual(first.primitives, instance.render(.75).primitives);
  assert.deepEqual(reduced.render(.25).primitives, reduced.render(.75).primitives);
  svg = instance.export('svg', .25);
  assert.match(svg, /^<svg /);
  assert.ok(svg.includes('viewBox="0 0 320 180"'));
} finally {
  instance.destroy();
  reduced.destroy();
}
const capabilities = system.getCapabilities();
assert.equal(capabilities.live_instances, 0);
console.log(JSON.stringify({
  node_version: process.versions.node,
  motion: definition.id,
  svg_bytes: Buffer.byteLength(svg),
  live_instances_after_cleanup: capabilities.live_instances,
  scope: 'Node scene sampling and SVG export',
}));
