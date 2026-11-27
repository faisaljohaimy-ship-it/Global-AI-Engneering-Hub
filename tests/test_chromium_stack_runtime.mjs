import assert from 'node:assert/strict';
import { runProbe } from '../motion-library/chromium-stack/smoke.mjs';
const report = await runProbe({ frames: 12, frameBudgetMs: 100 });
assert.equal(report.status, 'passed');
assert.equal(report.cases.length, 3);
assert.equal(report.webgpu_rendering_cases, 0);
for (const row of report.cases) {
  assert.equal(row.status, 'passed');
  assert.equal(row.checks.canvas_pixel, true);
  assert.equal(row.checks.webgl_shader_pixels, true);
  assert.equal(row.checks.wasm_execution, true);
  assert.equal(row.webgpu.rendering_tested, false);
  assert.equal(row.benchmark.frames, 12);
  assert.equal(row.benchmark.intervals_ms.length, 12);
  assert.equal(row.page_errors, 0);
  assert.equal(row.external_requests, 0);
}
assert.equal(report.cases[1].direction, 'rtl');
assert.equal(report.cases[2].reduced_motion, true);
assert.equal(report.cases[2].rendered.waapi, false);
assert.equal(report.cases[2].checks.reduced_canvas_static, true);
assert.equal(report.cases[2].checks.reduced_transform_static, true);
const overBudget = await runProbe({ frames: 12, frameBudgetMs: 1 });
assert.equal(overBudget.status, 'failed-performance-budget');
assert.equal(overBudget.functional_status, 'passed');
assert.equal(overBudget.performance_budget.status, 'failed');
console.log('Chromium stack: native rendering/reduced-motion/RTL passed; impossible frame budget correctly failed; WebGPU remains availability-only.');
