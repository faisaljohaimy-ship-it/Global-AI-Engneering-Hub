// The purposeful-motion policy (governance/policies/motion-purpose.json) at its enforcement point
// in this package: the registry builder refuses a motion that states no digital meaning unless its
// id is a pinned legacy id. The refusals are provoked on temporary copies; no repository file is edited.
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { cpSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { PURPOSE_POLICY, brief, purposePolicy, scan } from '../tools/build_registry.mjs';

const sdk = fileURLToPath(new URL('..', import.meta.url));
const repo = join(sdk, '..', '..');
const { motions } = JSON.parse(readFileSync(join(sdk, 'registry.json'), 'utf8'));
const policy = JSON.parse(readFileSync(join(repo, PURPOSE_POLICY), 'utf8'));
const legacy = new Set(policy.registries['native-engine'].legacy_ids);
const PURPOSEFUL = 'packages/motion-engines/motions/micro/success-feedback.mjs';
const MEANING = /  meaning: \{\n.*\n.*\n  \},\n/;

/** A copy of the package and of the policy in a temporary tree; `check()` runs its registry builder. */
function copy(t) {
  const root = mkdtempSync(join(tmpdir(), 'mp-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  cpSync(sdk, join(root, 'packages', 'motion-engines'), { recursive: true });
  mkdirSync(join(root, 'governance', 'policies'), { recursive: true });
  cpSync(join(repo, PURPOSE_POLICY), join(root, PURPOSE_POLICY));
  const read = (path) => readFileSync(join(root, path), 'utf8');
  const write = (path, text) => {
    mkdirSync(join(root, path, '..'), { recursive: true });
    writeFileSync(join(root, path), text);
  };
  const check = () => {
    const done = spawnSync(process.execPath, [join(root, 'packages', 'motion-engines', 'tools', 'build_registry.mjs'), '--check'], { encoding: 'utf8', timeout: 120000 });
    return { status: done.status, stderr: done.stderr };
  };
  const editPolicy = (change) => {
    const value = JSON.parse(read(PURPOSE_POLICY));
    change(value);
    write(PURPOSE_POLICY, JSON.stringify(value, null, 2) + '\n');
  };
  return { root, read, write, check, editPolicy };
}

/** The source of a new motion under a free brief id, made from a proven purposeful motion. */
function newMotion(tree, { withMeaning }) {
  const row = brief.find((item) => item.id === 'micro-input-focus');
  let source = tree.read(PURPOSEFUL)
    .replace("id: 'micro-success-feedback'", `id: '${row.id}'`).replace('number: 100', `number: ${row.number}`)
    .replace("en: 'Context-aware Success Feedback'", `en: '${row.name}'`);
  assert.match(source, MEANING);
  if (!withMeaning) source = source.replace(MEANING, '');
  tree.write('packages/motion-engines/motions/micro/input-focus.mjs', source);
  return row.id;
}

test('the builder reads the legacy and withdrawn ids from the central policy', async () => {
  const purpose = purposePolicy();
  assert.deepEqual([...purpose.legacy].sort(), [...legacy].sort());
  assert.equal(purpose.legacy.size, 34);
  assert.deepEqual([...purpose.withdrawn].sort(), [...policy.registries['native-engine'].withdrawn_ids].sort());
  assert.deepEqual([purpose.minChars, purpose.maxChars], [12, 240]);
  const found = await scan();
  for (const { id, definition } of found) assert.equal(definition.meaning === undefined, legacy.has(id), id);
  assert.ok(found.every(({ id }) => !purpose.withdrawn.has(id)));
});

test('an untouched copy builds, so every refusal below is caused by the change made to it', (t) => {
  const tree = copy(t);
  assert.deepEqual(tree.check(), { status: 0, stderr: '' });
});

test('a new motion that states a meaning is accepted, and the same motion without one is refused', (t) => {
  const tree = copy(t);
  const id = newMotion(tree, { withMeaning: true });
  let result = tree.check();
  assert.equal(result.status, 1);
  assert.match(result.stderr, /^Out of date: registry\.mjs, registry\.json/, 'accepted: only the generated files are stale');
  newMotion(tree, { withMeaning: false });
  result = tree.check();
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, new RegExp(`${id}: a motion must state its digital meaning`));
  assert.doesNotMatch(result.stderr, /Out of date/);
});

test('removing the meaning of a registered motion is refused, and so is a meaning without Arabic', (t) => {
  const tree = copy(t);
  const source = tree.read(PURPOSEFUL);
  tree.write(PURPOSEFUL, source.replace(MEANING, ''));
  let result = tree.check();
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /micro-success-feedback: a motion must state its digital meaning/);
  tree.write(PURPOSEFUL, source.replace(MEANING, "  meaning: {\n    en: 'An audit trail issues a receipt.',\n    ar: 'An audit trail issues a receipt.',\n  },\n"));
  result = tree.check();
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /micro-success-feedback: meaning needs one English and one Arabic sentence/);
});

test('a legacy motion is accepted only while its id is pinned', (t) => {
  const tree = copy(t);
  tree.editPolicy((value) => {
    value.registries['native-engine'].legacy_ids = value.registries['native-engine'].legacy_ids.filter((id) => id !== 'glass-card-elevation');
  });
  const result = tree.check();
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /glass-card-elevation: a motion must state its digital meaning/);
});

test('a withdrawn id is refused even when its file states a meaning', (t) => {
  const tree = copy(t);
  tree.write('packages/motion-engines/motions/lighting/lens-flare.mjs', tree.read(PURPOSEFUL));
  const result = tree.check();
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /lighting-lens-flare: withdrawn in governance\/policies\/motion-purpose\.json/);
});

test('the legacy list cannot grow, and nothing is built without the policy', (t) => {
  const tree = copy(t);
  tree.editPolicy((value) => value.registries['native-engine'].legacy_ids.push('micro-input-focus'));
  newMotion(tree, { withMeaning: false });
  let result = tree.check();
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /legacy_ids may only shrink from the 34 motions/);
  tree.editPolicy((value) => delete value.registries['native-engine'].withdrawn_ids);
  result = tree.check();
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /needs legacy_ids and withdrawn_ids/);
  rmSync(join(tree.root, PURPOSE_POLICY));
  result = tree.check();
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /motion-purpose\.json is missing/);
});
