import assert from 'node:assert/strict';
import { mkdtempSync, realpathSync, symlinkSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import {
  assertOutputOutsideRepository,
  boundedFrameCount,
  validateRenderOptions,
} from '../motion-library/render/options.mjs';

const repository = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const library = join(repository, 'motion-library');

test('render options accept the bounded deterministic sample', () => {
  const out = mkdtempSync(join(tmpdir(), 'hub-render-'));
  assert.deepEqual(validateRenderOptions({ out, fps: '30', width: '1280', height: '720' }, { library, repository }), {
    out: resolve(out),
    fps: 30,
    width: 1280,
    height: 720,
    scenePath: 'render/scene.html',
  });
  assert.equal(boundedFrameCount(4200, 30), 126);
});

test('renderer refuses repository output and symlinks back into it', () => {
  assert.throws(() => assertOutputOutsideRepository(join(repository, 'render-output'), repository), /outside the repository/);
  const parent = mkdtempSync(join(tmpdir(), 'hub-render-link-'));
  const link = join(parent, 'inside-repository');
  symlinkSync(library, link, 'dir');
  assert.throws(() => assertOutputOutsideRepository(realpathSync(link), realpathSync(repository)), /outside the repository/);
});

test('renderer refuses scene traversal and unbounded resources', () => {
  const out = mkdtempSync(join(tmpdir(), 'hub-render-invalid-'));
  const check = (overrides) => validateRenderOptions({ out, ...overrides }, { library, repository });
  assert.throws(() => check({ scene: '../README.md' }), /local HTML/);
  assert.throws(() => check({ scene: 'specs/fade-in.json' }), /local HTML/);
  assert.throws(() => check({ fps: 61 }), /fps/);
  assert.throws(() => check({ width: 1280, height: 721 }), /16:9/);
  assert.throws(() => check({ width: 1280.5 }), /width/);
  assert.throws(() => boundedFrameCount(30_001, 30), /duration/);
  assert.throws(() => boundedFrameCount(Number.POSITIVE_INFINITY, 30), /duration/);
  assert.throws(() => boundedFrameCount(30_000, 61), /frames/);
});
