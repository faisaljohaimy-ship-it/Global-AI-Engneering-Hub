import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {definitions} from '../motion-library/expansion/nextgen-catalog.mjs';
import {definitions as webglDefinitions} from '../motion-library/expansion/nextgen-motion-webgl.mjs';

const load = name => JSON.parse(readFileSync(new URL('../docs/evidence/' + name, import.meta.url)));

test('authored Canvas2D originals bind each owner identity to the exact exported module', async () => {
  const inventory = load('nextgen-cinematic-inventory.json');
  const eligible = new Set(inventory.motions.filter(row => !row.pr16_source).map(row => row.id));
  const manifest = load('nextgen-local-motion-inventory.json');
  const authored = new Set();
  for (const {source, ids} of manifest.catalogs) {
    assert.match(source, /^motion-library\/expansion\/nextgen-[a-z-]+\.mjs$/);
    const catalog = await import(new URL('../' + source, import.meta.url));
    assert.deepEqual(catalog.definitions.map(row => row.id).sort(), ids);
    for (const definition of catalog.definitions) {
      assert(eligible.delete(definition.id), `ID missing, historical or reused: ${definition.id}`);
      assert.equal(definition.source.module, source);
      assert.equal(definition.engine, 'canvas2d');
      authored.add(definition.id);
    }
  }
  assert.deepEqual(new Set(definitions.map(row => row.id)), authored);
  assert.equal(definitions.length, authored.size);
  assert.equal(webglDefinitions.length, 12);
  for (const definition of webglDefinitions) {
    assert.equal(definition.engine, 'webgl2');
    assert(eligible.delete(definition.id), `WebGL ID missing, historical or reused: ${definition.id}`);
  }
  assert.equal(eligible.size, 0, 'Every original absent from PR16 has its own authored mechanism');
});
