import assert from "node:assert/strict";
import {performance} from "node:perf_hooks";
import {crossDissolveAtFrame} from "../motion-library/adapters/remotion.mjs";
import {orbitCameraAtProgress} from "../motion-library/adapters/three.mjs";

const samples = 100_000;
const started = performance.now();
let checksum = 0;
for (let index = 0; index < samples; index += 1) {
  const progress = index / (samples - 1);
  const camera = orbitCameraAtProgress(progress);
  const dissolve = crossDissolveAtFrame(index % 60, 60);
  checksum += camera.position.x + camera.position.z + dissolve.incomingOpacity;
}
const elapsedMs = performance.now() - started;

assert.ok(Number.isFinite(checksum));
assert.ok(elapsedMs < 1_000, `deterministic adapter budget exceeded: ${elapsedMs.toFixed(2)}ms`);
console.log(JSON.stringify({samples, elapsed_ms: Number(elapsedMs.toFixed(2)), budget_ms: 1000}));
