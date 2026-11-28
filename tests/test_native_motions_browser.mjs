// L08: re-running the browser harness reproduces the recorded frame hashes exactly, for one motion
// of each engine family in the batch (GLSL, GPU points, Canvas 2D, SVG, DOM). Needs Playwright with
// Chromium on the machine; without it the test is skipped, never passed.
// Run: node --test tests/test_native_motions_browser.mjs
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { loadPlaywright } from '../packages/motion-engines/tools/playwright.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
const recorded = JSON.parse(readFileSync(new URL('../docs/evidence/gaie-20-layers/native-motions.json', import.meta.url), 'utf8'));
let available = true;
try {
  loadPlaywright();
} catch {
  available = false;
}

const sample = ['webgl2-glsl', 'webgl2-points', 'canvas2d', 'svg', 'dom'].map((engine) => recorded.motions.find((motion) => motion.engine === engine)).filter(Boolean);

test('one motion per engine re-renders with the recorded frame signature', { skip: available ? false : 'Playwright is not installed here' }, () => {
  assert.ok(sample.length >= 4);
  for (const motion of sample) {
    // verify/browser.mjs prints "<browser> <version> (<digest>)" where digest hashes id + signature.
    const output = execFileSync(process.execPath, ['packages/motion-engines/verify/browser.mjs', '--id', motion.id], { cwd: root, encoding: 'utf8', timeout: 240000 });
    assert.match(output, /1 passed, 0 failed/, motion.id);
    const digest = /\(([0-9a-f]{8})\)/.exec(output)[1];
    const expected = createDigest(motion.id + motion.proof.frame_signature);
    assert.equal(digest, expected, `${motion.id} drew different frames than recorded`);
  }
});

test('an unknown motion id is refused by the harness', { skip: available ? false : 'Playwright is not installed here' }, () => {
  assert.throws(() => execFileSync(process.execPath, ['packages/motion-engines/verify/browser.mjs', '--id', 'story-no-such-motion'], { cwd: root, encoding: 'utf8', stdio: 'pipe', timeout: 60000 }), (error) => error.status === 2);
});

function createDigest(text) {
  return createHash('sha256').update(text).digest('hex').slice(0, 8);
}
