import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {createMotion, definitions} from '../motion-library/expansion/nextgen-motion-webgl.mjs';

test('WebGL2 catalog implements the original shader, swarm and composition identities', () => {
  const inventory = JSON.parse(readFileSync(new URL(
    '../docs/evidence/nextgen-cinematic-inventory.json', import.meta.url)));
  const originals = inventory.motions.filter((row) =>
    (row.module === 'shaders' && row.number !== 132) || [61, 191, 198].includes(row.number));
  const names = new Map(originals.map((row) => [row.id, row.name]));
  assert.equal(names.size, 12);
  assert.equal(definitions.length, 12);
  for (const motion of definitions) {
    assert.equal(motion.name_en, names.get(motion.id));
    assert.equal(motion.engine, 'webgl2');
    assert.match(motion.name_ar, /\p{Script=Arabic}/u);
    assert.equal(motion.runtime_status, 'requires-current-source-bound-proof');
    assert(motion.renderers.includes('webgl2'));
    names.delete(motion.id);
  }
  assert.equal(names.size, 0);
  assert.deepEqual(definitions.find(({id}) => id === 'compositions-multi-engine-cinematic').renderers,
    ['webgl2', 'canvas2d']);
});

test('unsupported WebGL2 surfaces fail closed instead of selecting a CPU renderer', () => {
  const requested = [];
  const surface = {width: 390, height: 844, getContext(kind) {
    requested.push(kind);
    return null;
  }};
  assert.throws(() => createMotion(surface, 'shaders-fresnel'), /WebGL2 context unavailable/);
  assert.deepEqual(requested, ['webgl2']);
});

test('unknown programs and unsafe sizes or preferences are rejected before context creation', () => {
  const surface = {width: 390, height: 844, getContext() {
    throw new Error('A rejected input should never initialize WebGL2');
  }};
  assert.throws(() => createMotion(surface, 'custom-shader'), RangeError);
  assert.throws(() => createMotion(surface, 'shaders-fractal', {width: 4097}), RangeError);
  assert.throws(() => createMotion(surface, 'shaders-fractal', {height: Infinity}), RangeError);
  assert.throws(() => createMotion(surface, 'shaders-fractal', {rtl: 'true'}), RangeError);
  assert.throws(() => createMotion(surface, 'shaders-fractal', {reducedMotion: 'system'}), RangeError);
  assert.throws(() => createMotion(null, 'shaders-fractal'), TypeError);
});
