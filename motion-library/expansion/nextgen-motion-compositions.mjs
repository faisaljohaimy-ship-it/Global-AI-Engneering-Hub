// SPDX-License-Identifier: MIT
// A local, offline composition catalog for the Canvas2D motion SDK.
const BG = '#08111f';
const PANEL = '#12243b';
const GRID = '#38556f';
const INK = '#e2e8f0';
const CYAN = '#67e8f9';
const VIOLET = '#a78bfa';
const GREEN = '#6ee7b7';
const AMBER = '#fbbf24';
const TAU = 2 * Math.PI;
const SOURCE = 'motion-library/expansion/nextgen-motion-compositions.mjs';
const between = (value, low, high) => typeof value === 'number' && low <= value && value <= high;
const clamp = (value) => Math.max(0, Math.min(1, value));
const mix = (a, b, t) => a + (b - a) * t;
const smooth = (value) => {
  const t = clamp(value);
  return t * t * (3 - 2 * t);
};
const wrap = (value, cycle) => value - Math.floor(value / cycle) * cycle;

const descriptions = [
  ['compositions-spatial-operating-system', 'Spatial Operating System', 'نظام تشغيل مكاني',
    'A designed spatial shell arranges perspective windows around a changing selected surface.'],
  ['compositions-audio-reactive-neural', 'Audio-Reactive Neural', 'شبكة عصبية تتفاعل مع الصوت',
    'A node graph responds to frequency bands from generated or explicitly supplied normalized PCM samples.'],
  ['compositions-holographic-city', 'Holographic City', 'مدينة هولوغرافية',
    'A projected city reconstructs its blocks along a sweeping elevation boundary.'],
  ['compositions-ai-command-center', 'AI Command Center', 'مركز قيادة الذكاء الاصطناعي',
    'A synthetic task fixture highlights active lanes, routed dependency edges and queued work.'],
  ['compositions-adaptive-universe', 'Adaptive Universe', 'كون متكيّف',
    'A depth starfield adapts its point budget to viewport capacity and the configured detail.'],
  ['compositions-scene-assembly', 'Scene Assembly', 'تجميع المشهد',
    'Independently placed geometry layers align and lock together in a timed assembly.'],
  ['compositions-infinite-storytelling', 'Infinite Storytelling', 'سرد متواصل',
    'Repeating story cards maintain spacing and exact wrap across the timeline endpoint.'],
];
export const definitions = Object.freeze(descriptions.map(([id, name_en, name_ar, mechanism]) => Object.freeze({
  id, name_en, name_ar, mechanism, engine: 'canvas2d', category: 'compositions',
  duration_ms: 3000,
  license: 'MIT', license_file: 'motion-library/expansion/LICENSE',
  implementation_status: 'implemented-source',
  runtime_status: 'requires-current-source-bound-proof',
  source: Object.freeze({module: SOURCE}),
  reduced_motion: Object.freeze({mode: 'static-poster', progress: 0.56}),
  semantics: 'Offline composition preview with synthetic data and sampled geometry.',
})));
const byId = new Map(definitions.map((item) => [item.id, item]));

function drawing(width, height, rtl, primitives) {
  const ratio = Math.min(width / 440, height / 290);
  const x = (value) => width / 2 + (rtl ? -1 : 1) * value * ratio;
  const y = (value) => height / 2 + value * ratio;
  return {
    line(points, stroke, options = {}) {
      const {fill = 'none', width = 1.6, opacity = 1, closed = false} = options;
      primitives.push({type: 'polyline', points: points.map(([px, py]) => ({x: x(px), y: y(py)})),
        stroke, fill, opacity, closed, lineWidth: width * ratio});
    },
    box(cx, cy, w, h, fill, options = {}) {
      const {stroke = 'none', radius = 0, opacity = 1} = options;
      primitives.push({type: 'rect', x: x(cx) - w * ratio / 2, y: y(cy) - h * ratio / 2,
        width: w * ratio, height: h * ratio, radius: radius * ratio, stroke, fill, opacity, lineWidth: ratio});
    },
    circle(cx, cy, r, fill, options = {}) {
      const {stroke = 'none', width = 1.5, opacity = 1} = options;
      primitives.push({type: 'circle', x: x(cx), y: y(cy), r: r * ratio, stroke, fill, opacity, lineWidth: width * ratio});
    },
    text(cx, cy, text, size, fill = INK) {
      primitives.push({type: 'text', x: x(cx), y: y(cy), text, size: size * ratio, fill});
    },
  };
}

function panel(draw, corners, color, label) {
  draw.line(corners, color, {closed: true, fill: PANEL});
  const [topLeft, topRight, bottomRight, bottomLeft] = corners;
  const point = (x, y) => [
    mix(mix(topLeft[0], topRight[0], x), mix(bottomLeft[0], bottomRight[0], x), y),
    mix(mix(topLeft[1], topRight[1], x), mix(bottomLeft[1], bottomRight[1], x), y),
  ];
  draw.line([point(0.08, 0.29), point(0.92, 0.29)], color, {opacity: 0.66});
  draw.circle(...point(0.1, 0.15), 3, color);
  draw.text(...point(0.47, 0.16), label, 10);
  for (let i = 0; i < 3; i += 1) {
    draw.line([point(0.11, 0.44 + i * 0.17), point(0.77 - i * 0.13, 0.44 + i * 0.17)], GRID, {width: 3.3});
  }
}

function demoSamples(t) {
  return Array.from({length: 64}, (_, index) => {
    const phase = TAU * index / 64;
    return 0.33 * Math.sin(phase * 2 + t)
      + (0.2 + 0.14 * Math.sin(TAU * t)) * Math.sin(phase * 5)
      + (0.21 + 0.09 * Math.cos(TAU * t)) * Math.sin(phase * 8);
  });
}

function amplitudes(samples) {
  return Array.from({length: 8}, (_, index) => {
    const bin = index + 1;
    let real = 0;
    let imaginary = 0;
    for (const [i, sample] of samples.entries()) {
      const phase = TAU * bin * i / samples.length;
      real += sample * Math.cos(phase);
      imaginary += sample * Math.sin(phase);
    }
    return clamp(2 * Math.hypot(real, imaginary) / samples.length);
  });
}

function random(seed, index, axis) {
  let value = Math.imul(seed ^ (index + 1), 0x9e3779b1) ^ Math.imul(axis + 1, 0x85ebca6b);
  value ^= value >>> 16;
  value = Math.imul(value, 0x7feb352d);
  value ^= value >>> 15;
  value = Math.imul(value, 0x846ca68b);
  return ((value ^ (value >>> 16)) >>> 0) / 2 ** 32;
}

const scenes = {
  'compositions-spatial-operating-system'(draw, t) {
    const focus = 1.67 * t;
    const floor = [[-175, 74], [20, 112], [174, 74], [-15, 44]];
    draw.line(floor, GRID, {closed: true, fill: '#0d1e32'});
    const surfaces = [['System', CYAN], ['Memory', VIOLET], ['Tasks', GREEN]];
    for (let i = 0; i < surfaces.length; i += 1) {
      const slide = i - 1 - 0.34 * Math.sin(TAU * t);
      const proximity = Math.max(0.3, 1 - Math.abs(i - focus) * 0.46);
      const center = slide * 121;
      const half = 49 + 14 * proximity;
      const top = -58 - 27 * proximity;
      const tilt = slide * 11;
      const corners = [[center - half, top - tilt], [center + half, top + tilt],
        [center + half, 28 + tilt], [center - half, 28 - tilt]];
      draw.line([[center, 28], [center, 65]], GRID);
      draw.circle(center, 65, 5 + proximity * 3, surfaces[i][1], {opacity: proximity});
      panel(draw, corners, surfaces[i][1], surfaces[i][0]);
    }
    const cursor = mix(-124, 124, t);
    draw.line([[cursor - 19, 86], [cursor + 19, 86]], GREEN, {width: 3.4});
  },

  'compositions-audio-reactive-neural'(draw, t, {pcm_samples, interaction}) {
    const samples = pcm_samples ?? demoSamples(t);
    const levels = amplitudes(samples);
    const inputGain = 1 + 0.46 * interaction.y;
    const nodes = levels.map((level, index) => {
      const angle = TAU * (index + 0.24 * t) / 8;
      return [Math.cos(angle) * (102 + level * 32), -22 + Math.sin(angle) * (58 + level * 16)];
    });
    for (const [index, node] of nodes.entries()) {
      const power = clamp(levels[index] * inputGain);
      draw.line([[0, -22], node], power > 0.2 ? CYAN : GRID, {width: 1 + power * 5});
      draw.line([node, nodes[(index + 3) % nodes.length]], VIOLET, {opacity: 0.3 + power * 0.52});
    }
    for (const [index, node] of nodes.entries()) {
      const power = clamp(levels[index] * inputGain);
      draw.circle(...node, 4.3 + 11 * power, CYAN, {opacity: 0.45 + power * 0.5});
      draw.box(-105 + index * 29, 93 - 14 * power, 15, 6 + 28 * power, index % 2 ? CYAN : VIOLET, {radius: 2});
    }
    draw.circle(0, -22, 13, PANEL, {stroke: GREEN});
    draw.circle(0, -22, 5, GREEN);
    return {audio_input: pcm_samples ? 'supplied-normalized-pcm' : 'synthetic-signal', spectrum: levels};
  },

  'compositions-holographic-city'(draw, t) {
    const projection = (x, y, h) => [19 * (x - y), 9 * (x + y) - 19 * h + 22];
    draw.line([projection(-4, -4, 0), projection(4, -4, 0), projection(4, 4, 0), projection(-4, 4, 0)],
      CYAN, {closed: true, fill: '#11263b'});
    for (let axis = -4; axis <= 4; axis += 1) {
      draw.line([projection(axis, -4, 0), projection(axis, 4, 0)], GRID, {opacity: 0.54});
      draw.line([projection(-4, axis, 0), projection(4, axis, 0)], GRID, {opacity: 0.54});
    }
    for (let depth = -3; depth <= 3; depth += 1) {
      for (let side = -3; side <= 3; side += 1) {
        if ((side + depth) % 3 === 0) continue;
        const top = 0.4 + ((side ** 2 + depth ** 2 * 3) % 7) * 0.44;
        const grow = smooth(t * 1.4 - (side + depth + 6) / 20);
        const footprint = [[side - 0.36, depth - 0.36], [side + 0.36, depth - 0.36],
          [side + 0.36, depth + 0.36], [side - 0.36, depth + 0.36]];
        const ground = footprint.map(([x, y]) => projection(x, y, 0));
        const roof = footprint.map(([x, y]) => projection(x, y, 0.1 + top * grow));
        const opacity = 0.3 + 0.69 * grow;
        draw.line([ground[0], roof[0], roof[1], ground[1]], GRID, {closed: true, fill: PANEL, opacity});
        draw.line([ground[1], roof[1], roof[2], ground[2]], VIOLET, {closed: true, fill: PANEL, opacity});
        draw.line(roof, CYAN, {closed: true, fill: '#254759', opacity});
      }
    }
    const sweep = mix(-4, 4, t);
    draw.line([projection(sweep, -4, 0), projection(sweep, 4, 0)], GREEN, {width: 2.3});
  },

  'compositions-ai-command-center'(draw, t) {
    draw.box(0, 0, 370, 221, PANEL, {stroke: GRID, radius: 12});
    draw.text(-110, -92, 'TASK STATUS DEMO', 11);
    draw.box(138, -92, 59, 12, CYAN, {radius: 4, opacity: 0.2 + 0.44 * t});
    const hub = [-74, 6];
    const tasks = [['PLAN', -29, CYAN], ['BUILD', 9, VIOLET], ['VERIFY', 48, GREEN]];
    draw.box(...hub, 68, 73, BG, {stroke: CYAN, radius: 5});
    draw.text(...hub, 'Queue', 11, CYAN);
    for (const [index, [label, y, color]] of tasks.entries()) {
      const run = smooth((t - index * 0.17) * 1.62);
      const path = [[-40, 6], [-8, 6], [-8, y], [43, y]];
      draw.line(path, GRID);
      const pulseIndex = run * (path.length - 1);
      const segment = Math.min(path.length - 2, Math.floor(pulseIndex));
      const a = path[segment], b = path[segment + 1];
      draw.circle(mix(a[0], b[0], pulseIndex - segment), mix(a[1], b[1], pulseIndex - segment), 3.6, color);
      draw.box(97, y, 107, 28, BG, {stroke: color, radius: 5});
      draw.text(75, y, label, 10, color);
      draw.box(119 - 15 * (1 - run), y, 30 * run + 1, 4, color, {radius: 2});
      draw.box(-125 + index * 34, 74, 25, 5 + 12 * run, color, {radius: 3});
    }
  },

  'compositions-adaptive-universe'(draw, t, {width, height, detail, seed}) {
    const stars = Math.min(132, Math.ceil(Math.sqrt(width * height) / 21) + 3 * detail);
    for (let index = 0; index < stars; index += 1) {
      const angle = TAU * random(seed, index, 0);
      const depth = 0.24 + wrap(random(seed, index, 1) + 0.71 * (1 - t), 1);
      const spread = 10 + 43 * random(seed, index, 2);
      const x = Math.cos(angle) * spread / depth;
      const y = Math.sin(angle) * spread / depth;
      if (Math.abs(x) >= 205 || Math.abs(y) >= 123) continue;
      const color = index % 4 ? INK : CYAN;
      const size = 0.8 + 0.6 / depth;
      draw.circle(x, y, size, color, {opacity: clamp(1.23 - depth)});
      if (index % 6 === 0) draw.line([[x * 0.86, y * 0.86], [x, y]], color, {opacity: 0.54, width: 1});
    }
    const angle = TAU * t * 0.36;
    draw.circle(36 + 65 * Math.cos(angle), 3 + 51 * Math.sin(angle), 22, PANEL, {stroke: CYAN});
    draw.circle(44 + 65 * Math.cos(angle), -3 + 51 * Math.sin(angle), 16, VIOLET, {opacity: 0.23});
    draw.circle(-45, 23, 7, AMBER);
    return {point_budget: stars};
  },

  'compositions-scene-assembly'(draw, t) {
    const build = [
      {dx: -115, dy: 43, y: 43, color: CYAN, shape: [[-85, 0], [0, -34], [85, 0], [0, 32]]},
      {dx: 121, dy: -37, y: 19, color: VIOLET, shape: [[-61, 1], [0, -23], [61, 1], [0, 27]]},
      {dx: -105, dy: -51, y: -11, color: GREEN, shape: [[-40, 0], [0, -18], [40, 0], [0, 20]]},
      {dx: 77, dy: 78, y: -28, color: AMBER, shape: [[-23, 0], [0, -10], [23, 0], [0, 12]]},
    ];
    for (const [index, layer] of build.entries()) {
      const move = smooth(t * 1.55 - index * 0.16);
      const dx = layer.dx * (1 - move);
      const dy = mix(layer.y + layer.dy, layer.y, move);
      draw.line(layer.shape.map(([x, y]) => [x, y + layer.y]), GRID, {closed: true, opacity: 0.4});
      draw.line([[dx, dy], [0, layer.y]], layer.color, {opacity: 0.63 * (1 - move)});
      draw.line(layer.shape.map(([x, y]) => [x + dx, y + dy]), layer.color, {closed: true, fill: PANEL, width: 2});
      draw.circle(dx + 1, dy, 2.8 + 2 * move, layer.color);
    }
    draw.line([[0, 48], [0, -24]], CYAN, {opacity: smooth((t - 0.72) * 4)});
  },

  'compositions-infinite-storytelling'(draw, t) {
    const chapters = [['Discover', CYAN], ['Design', VIOLET], ['Build', GREEN], ['Review', AMBER]];
    const cursor = wrap(t, 1) * chapters.length;
    const step = Math.floor(cursor);
    const offset = cursor - step;
    const first = -151;
    const spacing = 96;
    const left = -197;
    const right = 197;
    for (let slot = -1; slot < 5; slot += 1) {
      const position = first + (slot - offset) * spacing;
      const from = Math.max(left, position - 40);
      const to = Math.min(right, position + 40);
      if (from >= to) continue;
      const chapter = wrap(step + slot, chapters.length);
      const [label, color] = chapters[chapter];
      const height = 108 - Math.min(Math.abs(position), 155) * 0.24;
      draw.box((from + to) / 2, -2, to - from, height, PANEL, {stroke: color, radius: Math.min(8, (to - from) / 2)});
      if (to - from > 64) {
        draw.circle(position - 10, -15, 9 + (chapter % 2) * 4, color, {opacity: 0.8});
        draw.text(position + 1, 19, label, 11, color);
      }
    }
    draw.line([[left, 80], [right, 80]], GRID);
    for (let i = 0; i < chapters.length; i += 1) {
      draw.circle(-24 + 16 * i, 80, i === step ? 5 : 3, i === step ? chapters[i][1] : GRID);
    }
  },
};

function reviewedSamples(samples) {
  if (samples === undefined) return undefined;
  if (!Array.isArray(samples) || samples.length < 16 || samples.length > 256) throw new RangeError('PCM must have 16 to 256 normalized samples');
  for (const item of samples) {
    if (!between(item, -1, 1)) throw new RangeError('Invalid PCM amplitude');
  }
  return samples;
}

/** Sample scene geometry. Direct callers can supply normalized PCM for audio-reactive scenes. */
export function sampleMotion(value, progress, options = {}) {
  const id = typeof value === 'string' ? value : value?.id;
  const definition = byId.get(id);
  if (!definition || !between(progress, -1e7, 1e7)) throw new RangeError('Unknown composition or invalid progress');
  const {width = 640, height = 360, intensity = 1, rtl = false, reducedMotion = false, detail = 12, seed = 1,
    interaction = {x: 0, y: 0}} = options;
  if (!between(width, 120, 4096) || !between(height, 90, 4096) || !between(intensity, 0, 1)
      || !Number.isInteger(detail) || !between(detail, 6, 24)
      || !Number.isInteger(seed) || !between(seed, 0, 2 ** 32 - 1)
      || !between(interaction?.x, -1, 1) || !between(interaction?.y, -1, 1)
      || typeof rtl !== 'boolean' || typeof reducedMotion !== 'boolean') throw new RangeError('Invalid composition options');
  const suppliedAudio = reviewedSamples(options.pcm_samples);
  const p = reducedMotion ? definition.reduced_motion.progress : clamp(progress);
  const primitives = [];
  const details = scenes[id](drawing(width, height, rtl, primitives), mix(0.5, p, intensity), {
    width, height, detail, seed, interaction: reducedMotion ? {x: 0, y: 0} : interaction,
    pcm_samples: reducedMotion ? undefined : suppliedAudio,
  });
  return {width, height, background: BG, primitives, meta: {id, progress: p, engine: 'canvas2d', reducedMotion, ...details}};
}
