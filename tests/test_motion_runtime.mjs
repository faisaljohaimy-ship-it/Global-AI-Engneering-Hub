import assert from "node:assert/strict";
import test from "node:test";
import {crossDissolveAtFrame, crossDissolveSequence} from "../motion-library/adapters/remotion.mjs";
import {orbitCameraAtProgress} from "../motion-library/adapters/three.mjs";
import {animationOptions, mirroredKeyframes, reducedMotionRequested, statusFor, validateComponent} from "../motion-library/runtime/core.mjs";

test("Remotion adapter is deterministic at first, middle and final frame", () => {
  assert.deepEqual(crossDissolveAtFrame(0, 31), {outgoingOpacity: 1, incomingOpacity: 0});
  assert.deepEqual(crossDissolveAtFrame(15, 31), {outgoingOpacity: 0.5, incomingOpacity: 0.5});
  assert.deepEqual(crossDissolveAtFrame(30, 31), {outgoingOpacity: 0, incomingOpacity: 1});
  assert.deepEqual(crossDissolveSequence(3), crossDissolveSequence(3));
});

test("Three adapter closes an exact deterministic orbit", () => {
  const start = orbitCameraAtProgress(0, {radius: 2, height: 1});
  const end = orbitCameraAtProgress(1, {radius: 2, height: 1});
  assert.equal(start.position.x, 2);
  assert.equal(start.position.y, 1);
  assert.ok(Math.abs(start.position.z) < 1e-12);
  assert.ok(Math.abs(end.position.x - start.position.x) < 1e-12);
  assert.ok(Math.abs(end.position.z - start.position.z) < 1e-12);
});

test("runtime exposes honest status and motion preference", () => {
  const catalogEntry = {id: "one"};
  assert.deepEqual(statusFor(catalogEntry, new Map()), {
    indexed: true, implemented: false, tested: false, runtime: "not-tested", used: false,
  });
  assert.equal(reducedMotionRequested("reduce", false), true);
  assert.equal(reducedMotionRequested("full", true), false);
  assert.equal(reducedMotionRequested("system", true), true);
  assert.deepEqual(animationOptions({duration_ms: 200, easing: "linear"}), {
    duration: 200, easing: "linear", fill: "both", iterations: 1,
  });
});

test("Motion Lab accepts only declared executable behavior components", () => {
  const catalogIds = new Set(["ui-staggered-list"]);
  const component = {
    id: "ui-staggered-list",
    engine: "waapi-behavior",
    implementation: "runtime/hub-motion.mjs#stagger",
    implementation_status: "implemented",
    used_by: ["motion-lab"],
  };
  assert.equal(validateComponent(component, catalogIds), component);
  assert.throws(() => validateComponent({...component, implementation: undefined}, catalogIds), /implementation/);
  assert.throws(() => validateComponent({...component, engine: "unknown"}, catalogIds), /engine/);
});

test("RTL mirroring reverses logical horizontal travel without mutating source", () => {
  const source = [{offset: 0, transform: "translateX(-24px)"}, {offset: 1, transform: "translateX(0)"}];
  const result = mirroredKeyframes(source, true);
  assert.equal(result[0].transform, "translateX(24px)");
  assert.equal(result[1].transform, "translateX(0)");
  assert.equal(source[0].transform, "translateX(-24px)");
});
