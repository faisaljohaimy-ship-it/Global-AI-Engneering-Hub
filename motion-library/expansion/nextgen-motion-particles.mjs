// SPDX-License-Identifier: MIT
// Deterministic CPU particle techniques for the owner's nine non-GPU identities.
const TAU = Math.PI * 2;
const COUNT = 64;
const STEP = 1 / 36;
const palette = ['#67e8f9', '#a78bfa', '#6ee7b7', '#fdba74'];
const clamp = (value) => Math.min(1, Math.max(0, value));
const lerp = (a, b, t) => a + (b - a) * t;
const smooth = (value) => {
  const t = clamp(value);
  return t * t * (3 - 2 * t);
};

function salt(index, stream) {
  const bits = Math.imul(index + 1, 0x9e3779b1) ^ Math.imul(stream + 11, 0x045d9f3b);
  return ((bits ^ (bits >>> 16)) >>> 0) / 4294967296;
}

function scatter(index, offset = 0) {
  const angle = TAU * salt(index, offset);
  const radius = .22 + .82 * Math.sqrt(salt(index, offset + 1));
  return [Math.cos(angle) * radius, Math.sin(angle) * radius];
}

function geometry(width, height, rtl) {
  const primitives = [];
  const scale = Math.min(width, height) * .38;
  const px = (x) => {
    const position = .47 * width + scale * x;
    return rtl ? width - position : position;
  };
  const py = (y) => .5 * height + scale * y;
  return {
    primitives,
    dot(x, y, r, fill, opacity = 1, stroke = 'none') {
      primitives.push({type: 'circle', x: px(x), y: py(y), r: r * scale,
        fill, stroke, opacity, lineWidth: 1.5});
    },
    line(x1, y1, x2, y2, stroke, opacity = 1) {
      primitives.push({type: 'line', x1: px(x1), x2: px(x2), y1: py(y1), y2: py(y2),
        stroke, opacity, lineWidth: Math.max(1, scale * .009)});
    },
  };
}

function logoReconstruction(g, t) {
  for (let i = 0; i < COUNT; i++) {
    const [sx, sy] = scatter(i, 1);
    // Original four-bladed mark made of independently seeded polar stripes.
    const blade = i % 4;
    const cell = Math.floor(i / 4);
    const angle = blade * Math.PI / 2 + .16 * (cell % 4) - .2;
    const radius = .11 + .145 * Math.floor(cell / 4) + .021 * (cell % 4);
    const p = smooth(t * 1.1 - .14 * salt(i, 13));
    const startAngle = .55 * (1 - p);
    const x = sx * Math.cos(startAngle) - sy * Math.sin(startAngle);
    const y = sx * Math.sin(startAngle) + sy * Math.cos(startAngle);
    g.dot(lerp(x, radius * Math.cos(angle), p), lerp(y, radius * Math.sin(angle), p),
      .018 + .009 * p, palette[blade], .72 + .28 * p);
  }
}

function attract(g, t, {x: inputX, y: inputY}) {
  const cx = .22 + inputX * .25, cy = -.11 + inputY * .25;
  // Semi-implicit Euler integration with softened inverse-square acceleration.
  const time = t * 1.5;
  for (let i = 0; i < COUNT; i++) {
    let [x, y] = scatter(i, 4);
    let vx = -.22 * y, vy = .22 * x;
    for (let elapsed = 0; elapsed < time; elapsed += STEP) {
      const step = Math.min(STEP, time - elapsed);
      const dx = cx - x, dy = cy - y;
      const acceleration = .21 / Math.pow(dx * dx + dy * dy + .08, 1.5);
      vx = (vx + dx * acceleration * step) * .986;
      vy = (vy + dy * acceleration * step) * .986;
      x += vx * step;
      y += vy * step;
    }
    g.line(x, y, x - vx * .054, y - vy * .054, palette[i % 3], .55);
    g.dot(x, y, .019, palette[i % 3]);
  }
  g.dot(cx, cy, .066, 'none', 1, palette[3]);
}

function repel(g, t, {x: inputX, y: inputY}) {
  const cx = -.20 + inputX * .25, cy = .15 + inputY * .25;
  const ring = .12 + .94 * t;
  for (let i = 0; i < COUNT; i++) {
    let [x, y] = scatter(i, 8);
    const distance = Math.hypot(x, y);
    // The outward impulse reaches farther initial particles later.
    const arrived = Math.max(0, t - distance * .56);
    const push = (.5 + .35 * salt(i, 14)) * arrived;
    const reflect = (v) => v > 1.05 ? 2.1 - v : v < -1.05 ? -2.1 - v : v;
    x = reflect(x * (1 + push / distance)) + cx;
    y = reflect(y * (1 + push / distance)) + cy;
    const wave = Math.max(0, 1 - Math.abs(ring - distance) * 7);
    g.dot(x, y, .018 + .015 * wave, palette[i % 2], .66 + .34 * wave);
  }
  g.dot(cx, cy, ring, 'none', .45 * (1 - t), palette[3]);
}

function magneticOrbit(g, t) {
  for (let i = 0; i < COUNT; i++) {
    const group = i % 3;
    const guide = [-.62 + .59 * group, group === 1 ? .26 : -.16];
    const radius = .12 + .30 * salt(i, 16);
    const phase = TAU * salt(i, 15);
    // Planar cyclotron trajectories around guiding centers. Opposite charge
    // signs reverse angular velocity under the same illustrative field.
    const charge = i % 2 ? 1 : -1;
    const angle = phase + charge * (2 + group * .72) * Math.PI * t;
    const [gx, gy] = [guide[0] + .11 * t, guide[1]];
    const x = gx + radius * Math.cos(angle), y = gy + radius * Math.sin(angle);
    const tail = angle - charge * .36;
    g.line(x, y, gx + radius * Math.cos(tail), gy + radius * Math.sin(tail),
      palette[group], .59);
    g.dot(x, y, .02, palette[group]);
  }
}

function vortex(g, t) {
  const cx = .08 + .14 * Math.sin(t * Math.PI * 2), cy = .02;
  for (let i = 0; i < COUNT; i++) {
    const initialRadius = .23 + .76 * salt(i, 21);
    const radius = initialRadius * Math.exp(-.66 * t);
    const phase = TAU * salt(i, 17) + t * (2.3 + 2.1 / initialRadius);
    const tailRadius = radius + .11;
    const x = cx + radius * Math.cos(phase), y = cy + radius * Math.sin(phase);
    g.line(x, y, cx + tailRadius * Math.cos(phase - .26),
      cy + tailRadius * Math.sin(phase - .26), palette[i % 4], .44);
    g.dot(x, y, .015 + .01 * (1 - radius), palette[i % 4]);
  }
}

function disintegrate(g, t) {
  for (let i = 0; i < COUNT; i++) {
    const column = i % 8, row = Math.floor(i / 8);
    const x = -.62 + column * .16, y = -.63 + row * .16;
    const release = Math.max(0, t * 1.08 - (column + row) * .021);
    const drift = .12 + salt(i, 24) * .40;
    const lift = .13 + salt(i, 25) * .68;
    g.dot(x + drift * release + .27 * release ** 2,
      y - lift * release + .32 * release ** 2, .026 * (1 - .55 * release),
      palette[(column + 2 * row) % 4], clamp(1 - release * .72));
  }
}

function flow(x, y, at) {
  const phaseX = Math.PI * (x + .12 * Math.sin(3 * at));
  const phaseY = Math.PI * (y - .16 * Math.cos(2 * at));
  // The derivatives are perpendicular to the gradient of the same
  // streamfunction. The resulting prescribed velocity has zero divergence.
  return [.42 * Math.sin(phaseX) * Math.cos(phaseY),
    -.42 * Math.cos(phaseX) * Math.sin(phaseY)];
}

function fluid(g, t) {
  const time = 1.6 * t;
  const wrap = (value) => value > 1 ? value - 2 : value < -1 ? value + 2 : value;
  for (let i = 0; i < COUNT; i++) {
    let x = -1 + 2 * salt(i, 31), y = -1 + 2 * salt(i, 33);
    for (let elapsed = 0; elapsed < time; elapsed += STEP) {
      const step = Math.min(STEP, time - elapsed);
      const [vx, vy] = flow(x, y, elapsed);
      const [mx, my] = flow(x + vx * step / 2, y + vy * step / 2, elapsed + step / 2);
      x = wrap(x + mx * step);
      y = wrap(y + my * step);
    }
    const [vx, vy] = flow(x, y, time);
    const color = palette[(i + (x * y > 0 ? 1 : 0)) % 3];
    g.line(x, y, x - .34 * vx, y - .34 * vy, color, .66);
    g.dot(x, y, .017, color);
  }
}

function bezier(a, b, c, t) {
  return lerp(lerp(a, b, t), lerp(b, c, t), t);
}

function converge(g, t) {
  const cx = .29, cy = -.07;
  for (let i = 0; i < COUNT; i++) {
    const [sx, sy] = scatter(i, 39);
    const angle = Math.atan2(sy, sx) + .83;
    const bx = .53 * Math.cos(angle), by = .53 * Math.sin(angle);
    const p = smooth(t * 1.08 - salt(i, 6) * .3);
    const tail = Math.max(0, p - .07);
    const x = bezier(sx, bx, cx, p), y = bezier(sy, by, cy, p);
    const color = palette[i % 4];
    g.line(x, y, bezier(sx, bx, cx, tail), bezier(sy, by, cy, tail), color, .72);
    g.dot(x, y, .019, color);
  }
  g.dot(cx, cy, .04 + .03 * t, 'none', .84, palette[3]);
}

function formSurface(g, t) {
  const p = smooth(t), angle = .7 + 1.7 * t;
  const goldenAngle = Math.PI * (3 - Math.sqrt(5));
  const points = [];
  for (let i = 0; i < COUNT; i++) {
    const y = 1 - 2 * (i + .5) / COUNT;
    const r = Math.sqrt(1 - y * y);
    const theta = goldenAngle * i;
    const x = r * Math.cos(theta), z = r * Math.sin(theta);
    const zx = x * Math.sin(angle) + z * Math.cos(angle);
    const xx = x * Math.cos(angle) - z * Math.sin(angle);
    const perspective = .77 / (1.45 + .36 * zx);
    const initial = scatter(i, 43);
    points.push({x: lerp(initial[0], xx * perspective + .19, p),
      y: lerp(initial[1], y * perspective, p), z: zx, r: .016 + perspective * .023});
  }
  points.sort((a, b) => b.z - a.z);
  for (const point of points) {
    g.dot(point.x, point.y, point.r, point.z > 0 ? palette[1] : palette[0],
      .58 + .32 * (1 - point.z) / 2);
  }
}

const emitters = [
  ['particles-logo-reconstruction', 'Particle Logo Reconstruction', 'إعادة بناء شعار بالجسيمات', 'Seeded particles converge onto an original four-bladed mark.', logoReconstruction],
  ['particles-attraction-field', 'Particle Attraction Field', 'مجال جذب الجسيمات', 'Softened inverse-square attraction with a signed pointer-controlled center.', attract],
  ['particles-repulsion-field', 'Particle Repulsion Field', 'مجال تنافر الجسيمات', 'A traveling repulsive impulse moves seeded particles into reflective boundaries.', repel],
  ['particles-magnetic-orbit', 'Magnetic Particle Orbit', 'مدارات جسيمات مغناطيسية', 'Analytical cyclotron paths use signed charges and independent guiding centers.', magneticOrbit],
  ['particles-vortex', 'Particle Vortex', 'دوامة جسيمات', 'Radius-dependent angular velocity drives spirals into a moving core.', vortex],
  ['particles-disintegration', 'Particle Disintegration', 'تفكك بالجسيمات', 'A gridded surface releases ordered fragments into ballistic wind drift.', disintegrate],
  ['particles-fluid-simulation', 'Particle Fluid Simulation', 'محاكاة تدفق الجسيمات', 'Tracers advect through a prescribed divergence-free velocity field with midpoint steps.', fluid],
  ['particles-path-convergence', 'Particle Path Convergence', 'تقارب مسارات الجسيمات', 'Particles follow staggered quadratic paths toward a shared destination.', converge],
  ['particles-surface-formation', 'Particle Surface Formation', 'تكوين سطح بالجسيمات', 'Seeded scatter settles on a rotating sphere using Fibonacci samples and perspective.', formSurface],
];

const samplers = new Map(emitters.map(([id, , , , draw]) => [id, draw]));
export const definitions = Object.freeze(emitters.map(([id, name_en, name_ar, mechanism]) => Object.freeze({
  id, name_en, name_ar, mechanism, engine: 'canvas2d', duration_ms: 4000,
  license: 'MIT', license_file: 'motion-library/expansion/LICENSE',
  implementation_status: 'implemented-source', runtime_status: 'requires-current-source-bound-proof',
  source: {module: 'motion-library/expansion/nextgen-motion-particles.mjs'},
  reduced_motion: {mode: 'static-poster', progress: .55},
  mobile: {requires_real_device_verification: true},
  semantics: 'Illustrative CPU particle fields. Fluid tracers model advection in a prescribed field.',
})));
const bounded = (x, low, high) => Number.isFinite(x) && x >= low && x <= high;

export function sampleMotion(value, progress, options = {}) {
  const id = typeof value === 'string' ? value : value?.id;
  const draw = samplers.get(id);
  const {width = 640, height = 360, intensity = 1, rtl = false,
    reducedMotion = false, interaction = {x: 0, y: 0}} = options;
  if (!draw || !bounded(progress, -1e7, 1e7)) throw new RangeError('Unknown particle motion or time');
  if (!bounded(width, 120, 4096) || !bounded(height, 90, 4096) || !bounded(intensity, 0, 1)
    || typeof rtl !== 'boolean' || typeof reducedMotion !== 'boolean'
    || !bounded(interaction?.x, -1, 1) || !bounded(interaction?.y, -1, 1)) {
    throw new RangeError('Invalid particle options');
  }
  const p = reducedMotion ? .55 : clamp(progress);
  const g = geometry(width, height, rtl);
  draw(g, .5 + (p - .5) * intensity, reducedMotion ? {x: 0, y: 0} : interaction);
  return {width, height, background: '#08111f', primitives: g.primitives,
    meta: {id, progress: p, engine: 'canvas2d', reducedMotion}};
}
