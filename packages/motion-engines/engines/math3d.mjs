// Just enough 3D for scenes drawn on a 2D canvas: a look-at camera with perspective.
export const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
export const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
export const scale = (a, s) => [a[0] * s, a[1] * s, a[2] * s];
export const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
export const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
export const length = (a) => Math.hypot(a[0], a[1], a[2]);
export const normalize = (a) => {
  const size = length(a) || 1;
  return [a[0] / size, a[1] / size, a[2] / size];
};
export const rotateY = ([x, y, z], angle) => [x * Math.cos(angle) + z * Math.sin(angle), y, -x * Math.sin(angle) + z * Math.cos(angle)];
export const rotateX = ([x, y, z], angle) => [x, y * Math.cos(angle) - z * Math.sin(angle), y * Math.sin(angle) + z * Math.cos(angle)];
export const rotateZ = ([x, y, z], angle) => [x * Math.cos(angle) - y * Math.sin(angle), x * Math.sin(angle) + y * Math.cos(angle), z];

/**
 * A camera at `eye` looking at `target`. project(point) returns { x, y, depth, scale }
 * in CSS pixels, or null when the point is behind the camera. `scale` is the size of
 * one world unit at that depth, for sizing things by distance.
 */
export function camera({ eye, target = [0, 0, 0], up = [0, 1, 0], fov = 50, width, height }) {
  const forward = normalize(sub(target, eye));
  const right = normalize(cross(forward, up));
  const upward = cross(right, forward);
  const focal = (height / 2) / Math.tan((fov * Math.PI) / 360);
  return {
    eye,
    project(point) {
      const relative = sub(point, eye);
      const depth = dot(relative, forward);
      if (depth <= 0.01) return null;
      const size = focal / depth;
      return { x: width / 2 + dot(relative, right) * size, y: height / 2 - dot(relative, upward) * size, depth, scale: size };
    },
  };
}

/** Sort items far to near so that nearer ones are drawn over farther ones. */
export const farToNear = (items) => items.filter((item) => item.depth !== undefined).sort((a, b) => b.depth - a.depth);
