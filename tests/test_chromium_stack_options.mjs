import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, rmSync, symlinkSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { parseArgs, prepareOutputDirectory, validateOptions, withDeadline } from '../motion-library/chromium-stack/options.mjs';

test('probe workload and timing budgets are finite and bounded', () => {
  assert.equal(validateOptions().frames, 30);
  for (const value of [NaN, Infinity, -Infinity, 0, -1, 101]) assert.throws(() => validateOptions({ frameBudgetMs: value }));
  for (const value of [NaN, Infinity, 1.5, 11, 121]) assert.throws(() => validateOptions({ frames: value }));
  assert.throws(() => validateOptions({ width: 300 }));
  assert.throws(() => validateOptions({ height: 2000 }));
  assert.throws(() => validateOptions({ arbitrary: true }));
});
test('CLI rejects incomplete, duplicate, unknown or non-finite requests', () => {
  assert.equal(parseArgs(['--frames', '12', '--frame-budget-ms', '16.7']).frames, 12);
  for (const args of [['--frames'], ['--unknown', '1'], ['--frames', '12', '--frames', '30'], ['--frames', 'Infinity'], ['--frame-budget-ms', 'NaN']]) assert.throws(() => parseArgs(args));
});
test('evidence output cannot overwrite existing content or escape writable roots', () => {
  const root = mkdtempSync(join(tmpdir(), 'hub-stack-options-'));
  try {
    assert.equal(prepareOutputDirectory(null), null);
    assert.throws(() => prepareOutputDirectory(root));
    assert.throws(() => prepareOutputDirectory('/etc/new-hub-output'));
    assert.throws(() => prepareOutputDirectory('relative-output'));
    assert.throws(() => prepareOutputDirectory(root + '/../escape'));
    assert.throws(() => prepareOutputDirectory(join(root, '.git', 'new')));
    const real = join(root, 'real'); mkdirSync(real);
    symlinkSync(real, join(root, 'link'));
    assert.throws(() => prepareOutputDirectory(join(root, 'link', 'new')));
    const created = prepareOutputDirectory(join(root, 'fresh'));
    assert.equal(created, join(root, 'fresh'));
  } finally { rmSync(root, { recursive: true, force: true }); }
});
test('a stalled native frame probe is bounded by a real deadline', async () => {
  assert.equal(await withDeadline(Promise.resolve(42), 100), 42);
  await assert.rejects(withDeadline(new Promise(() => {}), 20), /deadline/);
  await assert.rejects(withDeadline(Promise.resolve(42), Infinity), /Invalid/);
});
