// SPDX-License-Identifier: MIT
// Original camera studies and interaction previews for the Canvas2D motion SDK.
const source = 'motion-library/expansion/nextgen-originals.mjs';
const background = '#08111f';
const ink = '#e2e8f0';
const cyan = '#67e8f9';
const violet = '#a78bfa';
const muted = '#38536d';
const surface = '#15263c';
const green = '#6ee7b7';
const TAU = 2 * Math.PI;
const clamp = (value) => Math.max(0, Math.min(1, value));
const mix = (from, to, progress) => from + (to - from) * progress;
const smooth = (value) => {
  const t = clamp(value);
  return t * t * (3 - 2 * t);
};
const between = (value, low, high) =>
  typeof value === 'number' && Number.isFinite(value) && low <= value && value <= high;

const cameraSpecs = [
  ['camera-dolly-in', 'Dolly In', 'اقتراب الكاميرا', 'Forward translation magnifies the foreground at changing depth ratios.'],
  ['camera-dolly-out', 'Dolly Out', 'ابتعاد الكاميرا', 'Backward translation reveals a wider space around a centered subject.'],
  ['camera-orbital-sweep', 'Orbital Sweep', 'دوران حول الهدف', 'A curved camera path reveals the sides of a fixed installation.'],
  ['camera-crane-reveal', 'Crane Reveal', 'كشف بالرافعة', 'A vertical crane move reveals a landmark behind a low wall.'],
  ['camera-focus-pull', 'Focus Pull', 'نقل التركيز البؤري', 'Fixed framing shifts a depth-dependent defocus radius between two markers.'],
  ['camera-parallax-tracking', 'Parallax Tracking', 'تتبّع باختلاف المنظر', 'Lateral translation displaces three depth planes at different rates.'],
  ['camera-spatial-roll', 'Spatial Roll', 'التفاف محوري للكاميرا', 'A changing camera roll rotates the projected horizon about the optical axis.'],
];
const microSpecs = [
  ['micro-button-compression', 'Button Compression', 'انضغاط الزر', 'A fixed control compresses toward its contact plane, then rebounds.'],
  ['micro-liquid-button', 'Liquid Button', 'الزر السائل', 'A traveling capillary wave deforms the closed button outline.'],
  ['micro-cursor-distortion', 'Cursor Distortion', 'تشوه حول المؤشر', 'A local radial field bends a lattice around a moving pointer.'],
  ['micro-hover-elevation', 'Hover Elevation', 'ارتفاع عند التحويم', 'A card lifts relative to an anchored contact shadow and tilts with the pointer.'],
  ['micro-toggle-transformation', 'Toggle Transformation', 'تحول مفتاح التبديل', 'The knob moves across a constrained track while the state icon interpolates.'],
  ['micro-input-focus', 'Input Focus', 'تركيز حقل الإدخال', 'A focus underline expands while its label rises and a caret emerges.'],
  ['micro-elastic-selection', 'Elastic Selection', 'اختيار مرن', 'An underlay tracks a three-part selection with staggered leading and trailing edges.'],
  ['micro-navigation-morph', 'Navigation Morph', 'تحول قائمة التنقل', 'Three navigation bars reshape into a close control and reveal the menu rows.'],
  ['micro-success-feedback', 'Success Feedback', 'تأكيد النجاح', 'A checkmark traces its two segments while a confirmation pulse radiates outward.'],
];

function definition([id, name_en, name_ar, mechanism], category) {
  return Object.freeze({
    id, name_en, name_ar, mechanism, engine: 'canvas2d',
    category, duration_ms: category === 'camera' ? 2400 : 1100,
    license: 'MIT', license_file: 'motion-library/expansion/LICENSE',
    implementation_status: 'implemented-source',
    runtime_status: 'requires-current-source-bound-proof',
    source: Object.freeze({module: source}),
    reduced_motion: Object.freeze({mode: 'static-poster', progress: 0.55}),
    semantics: category === 'camera'
      ? 'Synthetic wireframe scene with CPU perspective projection.'
      : 'Sampled control preview. A usable control needs separately implemented DOM semantics and input events.',
  });
}
export const definitions = Object.freeze([
  ...cameraSpecs.map((spec) => definition(spec, 'camera')),
  ...microSpecs.map((spec) => definition(spec, 'micro')),
]);
const known = new Map(definitions.map((row) => [row.id, row]));

const subtract = (a, b) => a.map((value, i) => value - b[i]);
const dot = (a, b) => a.reduce((sum, value, i) => sum + value * b[i], 0);
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const normal = (vector) => vector.map((value) => value / Math.hypot(...vector));
const interpolate = (a, b, t) => a.map((value, i) => mix(value, b[i], t));

function projection({eye, aim, roll = 0}, width, height, rtl, primitives) {
  const forward = normal(subtract(aim, eye));
  const right = normal(cross([0, 1, 0], forward));
  const up = cross(forward, right);
  const cos = Math.cos(roll);
  const sin = Math.sin(roll);
  const scale = Math.min(width, height) * 0.83;
  const cameraPoint = (point) => {
    const relative = subtract(point, eye);
    const x = dot(relative, right);
    const y = dot(relative, up);
    return [x * cos - y * sin, x * sin + y * cos, dot(relative, forward)];
  };
  const screen = ([x, y, z]) => ({
    x: width / 2 + (rtl ? -1 : 1) * scale * x / z,
    y: height * 0.49 - scale * y / z,
    depth: z,
  });
  const near = 0.22;
  function line(from, to, stroke = cyan, opacity = 1, lineWidth = 1.5) {
    let a = cameraPoint(from);
    let b = cameraPoint(to);
    if (a[2] < near && b[2] < near) return;
    if (a[2] < near) a = interpolate(a, b, (near - a[2]) / (b[2] - a[2]));
    if (b[2] < near) b = interpolate(b, a, (near - b[2]) / (a[2] - b[2]));
    const first = screen(a);
    const second = screen(b);
    const dx = second.x - first.x;
    const dy = second.y - first.y;
    let entry = 0;
    let exit = 1;
    // Liang-Barsky clipping keeps perspective geometry inside the exported viewport.
    for (const [direction, distance] of [[-dx, first.x], [dx, width - first.x], [-dy, first.y], [dy, height - first.y]]) {
      if (!direction) {
        if (distance < 0) return;
      } else {
        const hit = distance / direction;
        if (direction < 0) entry = Math.max(entry, hit);
        else exit = Math.min(exit, hit);
        if (entry > exit) return;
      }
    }
    primitives.push({
      type: 'line', x1: first.x + entry * dx, y1: first.y + entry * dy,
      x2: first.x + exit * dx, y2: first.y + exit * dy, stroke, opacity, lineWidth,
    });
  }
  return {
    line,
    point(point) {
      const camera = cameraPoint(point);
      return camera[2] >= near ? screen(camera) : null;
    },
  };
}

function wireBox(draw, [x, y, z], [width, height, depth], color) {
  const face = [[x, y], [x + width, y], [x + width, y + height], [x, y + height]];
  for (let i = 0; i < face.length; i += 1) {
    const next = (i + 1) % face.length;
    draw([...face[i], z], [...face[next], z], color);
    draw([...face[i], z + depth], [...face[next], z + depth], color);
    draw([...face[i], z], [...face[i], z + depth], color);
  }
}

function groundGrid(draw) {
  for (let i = -5; i <= 5; i += 1) draw([i, -1, -1], [i, -1, 10], muted, 0.65);
  for (let i = -1; i <= 10; i += 1) draw([-5, -1, i], [5, -1, i], muted, 0.65);
}

const cameraPaths = {
  'camera-dolly-in': (t) => ({eye: [0, 0.7, mix(-9, -3.4, t)], aim: [0, 0.7, 2.5]}),
  'camera-dolly-out': (t) => ({eye: [0, 0.7, mix(-3.8, -10.4, t)], aim: [0, 0.7, 2.5]}),
  'camera-orbital-sweep': (t) => {
    const angle = mix(-1.02, 1.02, t);
    return {eye: [7 * Math.sin(angle), 2, 1.5 - 7 * Math.cos(angle)], aim: [0, 0, 2.5]};
  },
  'camera-crane-reveal': (t) => ({eye: [0, mix(-0.15, 4.6, t), -5.8], aim: [0, 0.7, 4]}),
  'camera-focus-pull': () => ({eye: [0, 0.7, -5.3], aim: [0, 0.7, 2]}),
  'camera-parallax-tracking': (t) => {
    const x = mix(-2.2, 2.2, t);
    return {eye: [x, 1.3, -5.7], aim: [x, 1.3, 3]};
  },
  'camera-spatial-roll': (t) => ({eye: [0, 1.55, -7.2], aim: [0, 0, 4], roll: mix(-0.31, 0.64, t)}),
};

function marker(draw, x, y, z, color) {
  const vertices = [[x, y + 0.85, z], [x + 0.68, y, z], [x, y - 0.85, z], [x - 0.68, y, z]];
  vertices.forEach((point, index) => {
    draw(point, vertices[(index + 1) % vertices.length], color);
    draw(point, [x, y, z + 0.6], color, 0.7);
  });
}

function cameraScene(id, t, width, height, rtl, primitives) {
  const camera = cameraPaths[id](t);
  const draw = projection(camera, width, height, rtl, primitives);
  groundGrid(draw.line);

  if (id === 'camera-focus-pull') {
    const markers = [[-1.25, 0.75, 0.15, cyan], [1.6, 1.15, 4.6, violet]];
    const focus = mix(5.45, 9.9, t);
    for (const [x, y, z, stroke] of markers) {
      const center = draw.point([x, y, z]);
      const blur = Math.abs(1 / center.depth - 1 / focus) * Math.min(width, height) * 0.52;
      const sharpness = 1 / (1 + blur * 0.16);
      draw.line([x, -1, z], [x, y - 0.24, z], stroke, sharpness);
      for (let i = 0; i < 5; i += 1) {
        primitives.push({
          type: 'circle', x: center.x, y: center.y,
          r: Math.min(width, height) * 0.17 / center.depth + i * blur * 0.42,
          stroke, opacity: sharpness / (1 + i * 0.9), lineWidth: 1.35,
        });
      }
    }
    return {camera, focus_depth: focus};
  }
  if (id === 'camera-crane-reveal') {
    // Draw an opaque screen last below. Draw distant details first so lifting
    // above the projected wall really changes visibility.
    marker(draw.line, 0, 0.6, 4.7, cyan);
    wireBox(draw.line, [-0.8, -1, 4.3], [1.6, 0.8, 1.1], violet);
    const face = [[-2.7, -1, 0.2], [2.7, -1, 0.2], [2.7, 1, 0.2], [-2.7, 1, 0.2]].map(draw.point);
    primitives.push({type: 'polyline', points: face, closed: true, fill: surface, stroke: muted, lineWidth: 1.5});
    draw.line([-2.7, 1, 0.2], [2.7, 1, 0.2], violet);
    return {camera};
  }
  if (id === 'camera-parallax-tracking') {
    marker(draw.line, -1.1, 0.3, 0, cyan);
    marker(draw.line, 0.75, 0.6, 2.8, violet);
    marker(draw.line, -0.7, 0.95, 6.5, green);
    for (const [x, y, z] of [[-1.1, 0.3, 0], [0.75, 0.6, 2.8], [-0.7, 0.95, 6.5]]) {
      draw.line([x, -1, z], [x, y - 0.85, z], muted);
    }
    return {camera};
  }
  wireBox(draw.line, [-1.2, -1, 2], [2.4, 2.05, 1.85], cyan);
  wireBox(draw.line, [0.25, 1.05, 2.5], [0.55, 0.72, 0.55], violet);
  wireBox(draw.line, [-2.4, -1, 5.4], [0.9, 2.5, 1.15], violet);
  marker(draw.line, 2.2, 0.55, 4.2, green);
  draw.line([-3.2, 1.8, 8], [3.2, 1.8, 8], muted, 0.9);
  return {camera};
}

function designSpace(width, height, rtl, primitives) {
  const unit = Math.min(width / 380, height / 262);
  const sign = rtl ? -1 : 1;
  const x = (value) => width / 2 + value * unit * sign;
  const y = (value) => height / 2 + value * unit;
  const points = (values) => values.map(([px, py]) => ({x: x(px), y: y(py)}));
  return {
    rect(cx, cy, w, h, fill, radius = 0, style = {}) {
      primitives.push({type: 'rect', x: x(cx) - w * unit / 2, y: y(cy) - h * unit / 2,
        width: w * unit, height: h * unit, radius: radius * unit, fill, ...style,
        rotation: (style.rotation ?? 0) * sign});
    },
    path(values, stroke, style = {}) {
      primitives.push({type: 'polyline', points: points(values), stroke, lineWidth: 2 * unit, ...style});
    },
    circle(cx, cy, r, fill, style = {}) {
      primitives.push({type: 'circle', x: x(cx), y: y(cy), r: r * unit, fill, ...style});
    },
    text(cx, cy, value, size, fill = ink) {
      primitives.push({type: 'text', x: x(cx), y: y(cy), text: value, size: size * unit, fill});
    },
  };
}

const microScenes = {
  'micro-button-compression'(draw, t) {
    const compression = Math.sin(Math.PI * t) * (0.52 + 0.48 * t);
    draw.rect(0, 18, 167, 39, '#0f1b2d', 18);
    draw.rect(0, 15, 159, 40, muted, 17);
    draw.rect(0, 2 + 11 * compression, 159 - 11 * compression, 43 - 13 * compression, violet, 17);
    const faceY = 2 + 11 * compression;
    draw.text(-10, faceY, 'RUN', 17, background);
    draw.path([[34, faceY - 5], [40, faceY], [34, faceY + 5]], background);
  },
  'micro-liquid-button'(draw, t) {
    const edge = Array.from({length: 64}, (_, i) => {
      const angle = TAU * i / 64;
      const ripple = Math.sin(3 * angle - t * TAU) * 0.12 + Math.sin(5 * angle + t * TAU * 0.5) * 0.045;
      return [75 * Math.cos(angle) * (1 + ripple), 25 * Math.sin(angle) * (1 + ripple)];
    });
    draw.path(edge, cyan, {closed: true, fill: surface});
    draw.path([[-22, 0], [17, 0], [9, -8], [17, 0], [9, 8]], cyan);
  },
  'micro-cursor-distortion'(draw, t, pointer) {
    const cursor = [mix(-68, 67, t) + 28 * pointer.x, 17 * Math.sin(t * TAU) + 20 * pointer.y];
    for (let row = -4; row <= 4; row += 1) {
      for (let column = -8; column <= 8; column += 1) {
        const x = column * 17;
        const y = row * 15;
        const dx = x - cursor[0];
        const dy = y - cursor[1];
        const force = Math.exp(-(dx * dx + dy * dy) / 1000);
        draw.circle(x + dx * force * 0.9, y + dy * force * 0.9, 1.6 + 2.2 * force, force > 0.35 ? cyan : muted);
      }
    }
    draw.path([cursor, [cursor[0] + 5, cursor[1] + 15], [cursor[0] + 13, cursor[1] + 8]], ink, {closed: true, fill: surface});
  },
  'micro-hover-elevation'(draw, t, pointer) {
    const lift = 7 + 25 * smooth(t);
    const roll = 0.14 * pointer.x + mix(-0.07, 0.07, t);
    draw.rect(0, 30, 200 - lift, 21, '#213147', 10, {opacity: 0.7 - lift / 100});
    draw.rect(0, 13 - lift, 185, 77, surface, 14, {stroke: cyan, rotation: roll, lineWidth: 1.4});
    draw.circle(-58, 13 - lift, 12, cyan);
    draw.rect(27, 5 - lift, 93, 5, ink, 2);
    draw.rect(18, 19 - lift, 73, 4, muted, 2);
  },
  'micro-toggle-transformation'(draw, t) {
    const position = smooth(t);
    draw.rect(0, 0, 127, 52, surface, 26, {stroke: muted});
    draw.rect(0, 0, 127, 52, cyan, 26, {opacity: position * 0.46});
    const center = mix(-37, 37, position);
    draw.circle(center, 0, 19, ink);
    draw.path([[center - 8, 0], [center - 2, mix(0, 5, position)], [center + 8, mix(0, -7, position)]], background);
  },
  'micro-input-focus'(draw, t) {
    const focus = smooth(t);
    draw.rect(0, 0, 232, 56, surface, 10, {stroke: muted});
    draw.text(-66, -31 * focus, 'Email', mix(17, 12, focus));
    draw.rect(0, 27, 7 + 220 * focus, 2.7, cyan, 1);
    draw.rect(-95, 6, 2, 19, cyan, 1, {opacity: focus});
  },
  'micro-elastic-selection'(draw, t) {
    draw.rect(0, 0, 248, 53, surface, 14, {stroke: muted});
    const lead = mix(-38, 119, smooth(t / 0.8));
    const trail = mix(-119, 38, smooth((t - 0.18) / 0.82));
    draw.rect((lead + trail) / 2, 0, lead - trail, 43, violet, 12);
    for (const [index, label] of ['One', 'Two', 'Three'].entries()) {
      const center = (index - 1) * 78;
      draw.text(center, 0, label, 15, trail < center && center < lead ? background : ink);
    }
  },
  'micro-navigation-morph'(draw, t) {
    const morph = smooth(t);
    draw.rect(-90, -37, 50, 49, surface, 10);
    draw.rect(-90, -37 - 8 * (1 - morph), 26, 2.8, ink, 1.4, {rotation: Math.PI * morph / 4});
    draw.rect(-90, -37, 26 * (1 - morph), 2.8, ink, 1.4);
    draw.rect(-90, -37 + 8 * (1 - morph), 26, 2.8, ink, 1.4, {rotation: -Math.PI * morph / 4});
    for (let i = 0; i < 3; i += 1) {
      const reveal = smooth((t - i * 0.12) * 1.35);
      draw.rect(-30 + 65 * reveal, -40 + i * 27, 118 * reveal, 14, i === 0 ? violet : muted, 6, {opacity: reveal});
    }
  },
  'micro-success-feedback'(draw, t) {
    const trace = smooth(t);
    draw.circle(0, 0, 39, surface, {stroke: green, lineWidth: 1.5});
    const first = clamp(trace * 2.4);
    const second = clamp((trace - 0.42) / 0.58);
    draw.path([[-16, 1], [mix(-16, -4, first), mix(1, 12, first)]], green, {lineWidth: 3.5});
    draw.path([[-4, 12], [mix(-4, 19, second), mix(12, -15, second)]], green, {lineWidth: 3.5, opacity: Math.min(second * 6, 1)});
    draw.circle(0, 0, 42 + trace * 31, 'none', {stroke: green, opacity: 0.65 * (1 - trace)});
    for (let i = 0; i < 8; i += 1) {
      const angle = i * TAU / 8;
      const distance = 41 + trace * 30;
      draw.circle(distance * Math.cos(angle), distance * Math.sin(angle), 2.5, green, {opacity: 0.85 * (1 - trace)});
    }
  },
};

/** Sample time and pointer inputs without storing interaction state in shared definitions. */
export function sampleMotion(value, progress, options = {}) {
  const id = typeof value === 'string' ? value : value?.id;
  const spec = known.get(id);
  if (!spec || !between(progress, -1e7, 1e7)) throw new RangeError('Unknown original motion or invalid progress');
  const {width = 640, height = 360, intensity = 1, rtl = false, reducedMotion = false,
    interaction = {x: 0, y: 0}} = options;
  if (!between(width, 120, 4096) || !between(height, 90, 4096) || !between(intensity, 0, 1)
      || !between(interaction?.x, -1, 1) || !between(interaction?.y, -1, 1)
      || typeof rtl !== 'boolean' || typeof reducedMotion !== 'boolean') {
    throw new RangeError('Invalid original motion options');
  }
  const p = reducedMotion ? spec.reduced_motion.progress : clamp(progress);
  const t = mix(0.5, p, intensity);
  const primitives = [];
  const pointer = reducedMotion ? {x: 0, y: 0} : interaction;
  const extra = spec.category === 'camera'
    ? cameraScene(id, smooth(t), width, height, rtl, primitives)
    : microScenes[id](designSpace(width, height, rtl, primitives), t, pointer);
  return {width, height, background, primitives, meta: {id, progress: p, engine: 'canvas2d', reducedMotion, ...extra}};
}
