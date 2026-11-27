export function orbitCameraAtProgress(progress, {radius = 2.4, height = 0.6} = {}) {
  if (!Number.isFinite(progress) || !Number.isFinite(radius) || !Number.isFinite(height)) {
    throw new TypeError("Orbit inputs must be finite numbers");
  }
  const clamped = Math.min(1, Math.max(0, progress));
  const angle = clamped * Math.PI * 2;
  return {
    position: {x: radius * Math.cos(angle), y: height, z: radius * Math.sin(angle)},
    target: {x: 0, y: 0, z: 0},
    progress: clamped,
  };
}
