// The registry is generated from the motion files and compared with the brief and with
// the evidence, so that what is counted is what exists and what was proven.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { brief, build, coreHash, scan } from '../tools/build_registry.mjs';
import { MODULES } from '../core/define.mjs';

const registry = JSON.parse(readFileSync(new URL('../registry.json', import.meta.url), 'utf8'));

test('the brief lists 200 motions, ten for each of twenty modules, numbered 1 to 200', () => {
  assert.equal(brief.length, 200);
  assert.deepEqual(brief.map((row) => row.number), Array.from({ length: 200 }, (_, index) => index + 1));
  assert.equal(new Set(brief.map((row) => row.id)).size, 200);
  assert.equal(new Set(brief.map((row) => row.name)).size, 200);
  const perModule = {};
  for (const row of brief) perModule[row.module] = (perModule[row.module] ?? 0) + 1;
  assert.deepEqual(Object.keys(perModule), Object.keys(MODULES));
  assert.ok(Object.values(perModule).every((count) => count === 10));
});

test('registry.json and registry.mjs are up to date with the motion files and the evidence', async () => {
  const { json, module } = await build();
  assert.equal(readFileSync(new URL('../registry.json', import.meta.url), 'utf8'), json, 'run node packages/motion-engines/tools/build_registry.mjs');
  assert.equal(readFileSync(new URL('../registry.mjs', import.meta.url), 'utf8'), module);
});

test('every motion on disk is in the registry under its brief name and number', async () => {
  const found = await scan();
  assert.equal(found.length, registry.motions.length);
  const asked = new Map(brief.map((row) => [row.id, row]));
  for (const { id, definition } of found) {
    const row = asked.get(id);
    assert.ok(row, `${id} is not in the brief`);
    assert.equal(definition.name.en, row.name);
    assert.equal(definition.number, row.number);
  }
});

test('a motion is operational only with a passing evidence row for its exact source and the current core', () => {
  const evidence = JSON.parse(readFileSync(new URL('../evidence/chromium.json', import.meta.url), 'utf8'));
  const rows = new Map(evidence.results.map((row) => [row.id, row]));
  const current = evidence.inputs.core_sha256 === coreHash();
  for (const entry of registry.motions) {
    const row = rows.get(entry.id);
    const proven = current && row && row.pass && row.source_sha256 === entry.source_sha256;
    assert.equal(entry.status === 'operational', Boolean(proven), entry.id);
    if (entry.status === 'operational') {
      assert.ok(Object.values(row.checks).every(Boolean), `${entry.id} has a failing check`);
      assert.ok(Object.keys(row.checks).length >= 14, `${entry.id} was not fully checked`);
    }
  }
  assert.equal(registry.brief.operational, registry.motions.filter((entry) => entry.status === 'operational').length);
  assert.equal(registry.brief.requested, 200);
  assert.equal(registry.brief.implemented + registry.brief.not_implemented.length, 200);
});

test('every record carries the metadata the brief asks for', () => {
  for (const entry of registry.motions) {
    for (const key of ['id', 'number', 'name', 'summary', 'category', 'engine', 'source', 'source_sha256', 'preview', 'controls', 'requirements', 'compatibility', 'reduced_motion', 'test', 'license', 'usage', 'integration', 'status']) {
      assert.ok(entry[key] !== undefined && entry[key] !== '', `${entry.id} lacks ${key}`);
    }
    assert.match(entry.name.ar, /[؀-ۿ]/);
    assert.ok(entry.controls.duration.default >= 100 && entry.controls.easing.options.length >= 5 && entry.controls.colors.length >= 3);
    assert.ok(Object.keys(entry.controls.parameters).length >= 2);
    assert.ok(['neutral', 'mirror', 'text'].includes(entry.compatibility.rtl));
    assert.ok(Object.keys(entry.compatibility.browsers).join() === 'chromium,firefox,webkit');
    if (entry.status === 'operational') assert.ok(entry.benchmark && entry.benchmark.averageMs >= 0 && entry.evidence, `${entry.id} has no benchmark or evidence`);
  }
});

test('no two motions share an id, a number, a name or the frames they draw', () => {
  const evidence = JSON.parse(readFileSync(new URL('../evidence/chromium.json', import.meta.url), 'utf8'));
  for (const key of [(entry) => entry.id, (entry) => entry.number, (entry) => entry.name.en, (entry) => entry.name.ar]) {
    assert.equal(new Set(registry.motions.map(key)).size, registry.motions.length);
  }
  const signatures = evidence.results.filter((row) => row.pass).map((row) => row.measured.signature);
  assert.equal(new Set(signatures).size, signatures.length);
});
