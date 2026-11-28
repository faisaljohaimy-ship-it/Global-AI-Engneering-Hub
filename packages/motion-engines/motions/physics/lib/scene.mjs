// A perspective camera for 3D scenes drawn on a 2D canvas, fitted to the frame: the picture
// is scaled and centred so that the scene's corner points fill the frame inside a margin,
// whatever the frame's shape. Projection writes into an array, so drawing a mesh allocates nothing.
import { cross, normalize, sub } from '../../../engines/math3d.mjs';

export function fittedCamera({ eye, target = [0, 0, 0], fov = 40, width, height, corners, margin = [0.06, 0.08] }) {
  const forward = normalize(sub(target, eye));
  const right = normalize(cross(forward, [0, 1, 0]));
  const up = cross(right, forward);
  const focal = 1 / Math.tan((fov * Math.PI) / 360);
  let zoom = 1;
  let shiftX = 0;
  let shiftY = 0;
  /** Writes the x and y (CSS pixels) and the depth of a world point into out[at], out[at + 1], out[at + 2]. */
  const project = (x, y, z, out, at = 0) => {
    const rx = x - eye[0];
    const ry = y - eye[1];
    const rz = z - eye[2];
    const depth = Math.max(0.05, rx * forward[0] + ry * forward[1] + rz * forward[2]);
    out[at] = shiftX + ((rx * right[0] + ry * right[1] + rz * right[2]) / depth) * focal * zoom;
    out[at + 1] = shiftY - ((rx * up[0] + ry * up[1] + rz * up[2]) / depth) * focal * zoom;
    out[at + 2] = depth;
    return out;
  };
  const box = [Infinity, -Infinity, Infinity, -Infinity];
  const point = [0, 0, 0];
  for (const corner of corners) {
    project(corner[0], corner[1], corner[2], point);
    box[0] = Math.min(box[0], point[0]);
    box[1] = Math.max(box[1], point[0]);
    box[2] = Math.min(box[2], point[1]);
    box[3] = Math.max(box[3], point[1]);
  }
  zoom = Math.min((width * (1 - 2 * margin[0])) / (box[1] - box[0]), (height * (1 - 2 * margin[1])) / (box[3] - box[2]));
  shiftX = width / 2 - (zoom * (box[0] + box[1])) / 2;
  shiftY = height / 2 - (zoom * (box[2] + box[3])) / 2;
  return { project, eye, forward };
}
