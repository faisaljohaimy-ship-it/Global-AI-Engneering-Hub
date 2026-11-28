// SPDX-License-Identifier: MIT
// Original hologram and dashboard previews, with synthetic input data.
const BG = '#08111f';
const PANEL = '#12233a';
const GRID = '#2a4660';
const INK = '#e2e8f0';
const CYAN = '#67e8f9';
const VIOLET = '#a78bfa';
const GREEN = '#6ee7b7';
const AMBER = '#fbbf24';
const PINK = '#fb7185';
const TAU = 2 * Math.PI;
const SOURCE = 'motion-library/expansion/nextgen-motion-ui.mjs';

const clamp = (x) => Math.max(0, Math.min(1, x));
const lerp = (a, b, t) => a + (b - a) * t;
const smooth = (x) => {
  const t = clamp(x);
  return t * t * (3 - 2 * t);
};
const inRange = (value, min, max) => typeof value === 'number' && min <= value && value <= max;

const metadata = [
  ['hologram-materialization', 'Hologram Materialization', 'تشكل الهولوغرام', 'A projected wireframe forms slice by slice above an emitter.'],
  ['hologram-scanline-reveal', 'Scanline Reveal', 'كشف بخط المسح', 'A scan boundary clips a map to the portion already scanned.'],
  ['hologram-volumetric-projection', 'Volumetric Projection', 'إسقاط مجسّم', 'A projector frustum contains animated depth planes and reconstructed voxels.'],
  ['hologram-card-assembly', 'Card Assembly', 'تجميع البطاقات', 'Separate frame, chip, and wave layers converge into a card.'],
  ['hologram-floating-grid', 'Floating Grid', 'شبكة طافية', 'A traveling displacement wave lifts grid vertices in depth.'],
  ['hologram-depth-mapping', 'Depth Mapping', 'رسم خريطة العمق', 'A raster sweep turns sampled depth into raised, color-mapped columns.'],
  ['hologram-interface-deconstruction', 'Interface Deconstruction', 'تفكيك الواجهة', 'Panel elements fan out along independent explosion vectors and preserve their tethers.'],
  ['hologram-data-projection', 'Data Projection', 'إسقاط البيانات', 'Points on an emitter surface seed rising columns and a connected data curve.'],
  ['hologram-interactive-rotation', 'Interactive Rotation', 'دوران تفاعلي', 'Pointer and timeline rotate a wireframe object around two axes.'],
  ['hologram-command-interface', 'Command Interface', 'واجهة الأوامر', 'A visual command travels from input to a read-only synthetic pipeline.'],
  ['dashboard-kpi-flow', 'KPI Flow', 'تدفق المؤشرات', 'Metric cards count up while a weighted signal fans out from a source.'],
  ['dashboard-risk-matrix', 'Risk Matrix', 'مصفوفة المخاطر', 'Risk cells accumulate in progression and a traced assessment traverses the matrix.'],
  ['dashboard-predictive-reveal', 'Predictive Reveal', 'كشف التوقع', 'Historical observations meet a fan of illustrative trajectories.'],
  ['dashboard-geographic-heatmap', 'Geographic Heatmap', 'خريطة حرارية جغرافية', 'Heat kernels expand over nodes on a fictional region map.'],
  ['dashboard-network-graph', 'Network Graph', 'رسم الشبكة', 'A lattice of related nodes relaxes into an orbit with retained edges.'],
  ['dashboard-sankey-flow', 'Sankey Flow', 'تدفق سانكي', 'Width-preserving flows split at a source and merge into destinations.'],
  ['dashboard-data-orbit', 'Data Orbit', 'مدار البيانات', 'Independent oriented orbits move metric nodes with tapered trails.'],
  ['dashboard-time-series-reveal', 'Time Series Reveal', 'كشف السلسلة الزمنية', 'A piecewise time series unveils left to right with a cursor at the latest sample.'],
  ['dashboard-signal-pulse', 'Signal Pulse', 'نبضة الإشارة', 'A synthetic waveform propagates across a sweep grid.'],
  ['dashboard-alert-cascade', 'Alert Cascade', 'تتابع التنبيهات', 'Incoming events fall into a time-ordered alert stack.'],
];

export const definitions = Object.freeze(metadata.map(([id, name_en, name_ar, mechanism]) => Object.freeze({
  id, name_en, name_ar, mechanism,
  engine: 'canvas2d',
  category: id.split('-')[0],
  duration_ms: 2600,
  license: 'MIT',
  license_file: 'motion-library/expansion/LICENSE',
  implementation_status: 'implemented-source',
  runtime_status: 'requires-current-source-bound-proof',
  source: Object.freeze({module: SOURCE}),
  reduced_motion: Object.freeze({mode: 'static-poster', progress: 0.58}),
  semantics: 'Deterministic synthetic scene. Command, predictive and monitoring displays use illustrative data.',
})));
const indexed = new Map(definitions.map((definition) => [definition.id, definition]));

function drawing(width, height, rtl, primitives) {
  const scale = Math.min(width / 400, height / 270);
  const mirror = rtl ? -1 : 1;
  const x = (logical) => width * 0.5 + logical * scale * mirror;
  const y = (logical) => height * 0.5 + logical * scale;
  return {
    path(points, stroke, options = {}) {
      const {fill = 'none', lineWidth = 1.45, closed = false, opacity = 1} = options;
      primitives.push({type: 'polyline', points: points.map(([px, py]) => ({x: x(px), y: y(py)})),
        stroke, fill, closed, opacity, lineWidth: lineWidth * scale});
    },
    circle(cx, cy, r, fill, options = {}) {
      const {stroke = 'none', opacity = 1, lineWidth = 1.45} = options;
      primitives.push({type: 'circle', x: x(cx), y: y(cy), r: r * scale, fill, stroke, opacity, lineWidth: lineWidth * scale});
    },
    box(cx, cy, w, h, fill, options = {}) {
      const {radius = 0, stroke = 'none', opacity = 1} = options;
      primitives.push({type: 'rect', x: x(cx) - w * scale * 0.5, y: y(cy) - h * scale * 0.5,
        width: w * scale, height: h * scale, radius: radius * scale, fill, stroke, opacity, lineWidth: scale});
    },
    text(cx, cy, text, size, fill = INK) {
      primitives.push({type: 'text', text, x: x(cx), y: y(cy), size: size * scale, fill});
    },
  };
}

function extentLine(draw, points, progress, color, options) {
  const available = clamp(progress) * (points.length - 1);
  const count = Math.min(points.length - 2, Math.floor(available));
  const from = points[count];
  const to = points[count + 1];
  const fraction = available - count;
  const head = [lerp(from[0], to[0], fraction), lerp(from[1], to[1], fraction)];
  draw.path([...points.slice(0, count + 1), head], color, options);
  return head;
}

function panel(draw, label) {
  draw.box(0, 0, 330, 205, PANEL, {radius: 10, stroke: GRID});
  draw.circle(-146, -82, 3.5, CYAN);
  draw.text(-69, -82, label, 10);
  draw.path([[-151, -68], [151, -68]], GRID);
}

function chartGrid(draw, left, top, width, height) {
  for (let i = 0; i <= 5; i += 1) {
    const y = top + i * height / 5;
    draw.path([[left, y], [left + width, y]], GRID, {opacity: i === 5 ? 1 : 0.65});
  }
  for (let i = 0; i <= 6; i += 1) {
    const x = left + i * width / 6;
    draw.path([[x, top], [x, top + height]], GRID, {opacity: i === 0 ? 1 : 0.38});
  }
}

function isometric(x, y, z) {
  return [18 * (x - y), 9 * (x + y) - 18 * z - 10];
}

function emitter(draw) {
  const outline = [[-129, 76], [0, 102], [128, 76], [0, 51]];
  draw.path(outline, GRID, {closed: true, fill: PANEL});
  draw.path([[-112, 76], [0, 96], [111, 76]], CYAN, {opacity: 0.5});
  draw.circle(-77, 85, 3.5, VIOLET);
}

function outlineAt(radius, centerX, centerY, flatten, count = 32) {
  return Array.from({length: count}, (_, index) => {
    const angle = TAU * index / count;
    return [centerX + Math.cos(angle) * radius, centerY + Math.sin(angle) * radius * flatten];
  });
}

const glyph = [
  [-53, 46], [-32, 23], [-7, 32], [9, -6], [30, -11], [56, -47], [76, -32],
];

const scenes = {
  'hologram-materialization'(draw, t) {
    emitter(draw);
    for (let slice = 0; slice < 12; slice += 1) {
      const ready = smooth(t * 1.5 - slice * 0.09);
      const level = slice * 9;
      const radius = (25 + 32 * Math.sin(Math.PI * slice / 12)) * (0.45 + 0.55 * ready);
      draw.path(outlineAt(radius, 0, 59 - level * ready, 0.26, 20), slice % 3 ? CYAN : VIOLET,
        {closed: true, opacity: 0.17 + ready * 0.65});
    }
    const rise = 106 * smooth(t);
    draw.path([[-87, 70 - rise], [87, 70 - rise]], CYAN, {lineWidth: 2.4});
  },

  'hologram-scanline-reveal'(draw, t) {
    panel(draw, 'SCAN MAP');
    const boundary = lerp(-151, 140, t);
    const features = [
      [[-143, -40], [-85, -51], [-36, -31], [27, -48], [102, -42], [144, -12]],
      [[-143, 10], [-91, -11], [-32, 12], [14, -2], [62, 22], [144, 12]],
      [[-143, 62], [-49, 57], [-14, 30], [45, 51], [107, 47], [144, 61]],
    ];
    features.forEach((line, index) => {
      draw.path(line, GRID);
      const covered = [];
      for (let i = 0; i < line.length - 1; i += 1) {
        const [a, b] = line.slice(i, i + 2);
        if (boundary <= a[0]) break;
        if (!covered.length) covered.push(a);
        covered.push(boundary >= b[0] ? b : [boundary, lerp(a[1], b[1], (boundary - a[0]) / (b[0] - a[0]))]);
      }
      if (covered.length >= 2) draw.path(covered, index === 1 ? VIOLET : CYAN, {lineWidth: 2.4});
    });
    draw.box(boundary - 7, 6, 16, 133, CYAN, {opacity: 0.08});
    draw.path([[boundary, -60], [boundary, 72]], CYAN, {lineWidth: 2});
  },

  'hologram-volumetric-projection'(draw, t) {
    emitter(draw);
    const level = smooth(t);
    const rim = [[-103, -68], [90, -68], [104, 44], [-90, 44]];
    draw.path(rim, VIOLET, {closed: true, fill: VIOLET, opacity: 0.12});
    for (const point of rim) draw.path([[0, 64], point], CYAN, {opacity: 0.4, lineWidth: 0.9});
    for (let z = 0; z < 4; z += 1) {
      const scale = (z + 1) / 4;
      const plane = rim.map(([x, y]) => [x * scale, lerp(64, y, scale)]);
      draw.path(plane, CYAN, {closed: true, opacity: 0.42});
      for (let bit = 0; bit < 6; bit += 1) {
        const x = 78 * scale * Math.cos(bit * TAU / 6 + z);
        const y = 35 - scale * 43 + 24 * scale * Math.sin(bit * TAU / 6);
        const shown = smooth(level * 1.75 - (z * 6 + bit) / 31);
        if (shown > 0) draw.box(x, y, 3 + 7 * shown, 3 + 7 * shown, z % 2 ? VIOLET : CYAN, {opacity: shown});
      }
    }
    draw.path([[-105 * level, 64 - 124 * level], [98 * level, 64 - 124 * level]], CYAN);
  },

  'hologram-card-assembly'(draw, t) {
    emitter(draw);
    const gather = smooth(t);
    draw.box(lerp(-105, 0, gather), lerp(24, -22, gather), 190, 103, PANEL, {stroke: CYAN, radius: 10});
    const chipX = lerp(110, -59, gather);
    const chipY = lerp(-71, -26, gather);
    draw.box(chipX, chipY, 32, 25, VIOLET, {radius: 3});
    for (let i = -1; i <= 1; i += 1) draw.path([[chipX - 9, chipY + 5 * i], [chipX + 9, chipY + 5 * i]], BG);
    const waveX = lerp(-116, 20, gather);
    const waveY = lerp(-87, -9, gather);
    draw.path(glyph.map(([x, y]) => [x * 0.54 + waveX, y * 0.42 + waveY]), GREEN, {lineWidth: 2.1});
    draw.box(lerp(108, -28, gather), lerp(57, 10, gather), 105, 5, INK, {radius: 2});
  },

  'hologram-floating-grid'(draw, t) {
    emitter(draw);
    const point = (x, y) => isometric(x, y, 1.1 + 0.92 * Math.sin(0.57 * x + 0.68 * y - TAU * t));
    for (let i = -4; i <= 4; i += 1) {
      const row = [], column = [];
      for (let j = -4; j <= 4; j += 1) {
        row.push(point(i, j));
        column.push(point(j, i));
      }
      draw.path(row, i === 0 ? CYAN : GRID, {lineWidth: i === 0 ? 2 : 1.4});
      draw.path(column, i === 0 ? VIOLET : GRID);
    }
    draw.circle(...point(2, -1), 4.5, CYAN);
  },

  'hologram-depth-mapping'(draw, t) {
    emitter(draw);
    for (let ix = -3; ix <= 3; ix += 1) {
      for (let iy = -3; iy <= 3; iy += 1) {
        const depth = 0.4 + 2.35 * Math.exp(-((ix - 1.2) ** 2 + (iy + 0.8) ** 2) / 6);
        const measured = smooth(1.46 * t - ((ix + 3) * 7 + (iy + 3)) / 88);
        const base = isometric(ix, iy, 0);
        const top = isometric(ix, iy, 0.13 + depth * measured);
        const color = depth > 1.75 ? VIOLET : CYAN;
        draw.path([base, top], color, {lineWidth: 1 + 3 * measured, opacity: 0.25 + 0.7 * measured});
        draw.circle(...top, 1.5 + measured * 1.2, color, {opacity: 0.25 + 0.65 * measured});
      }
    }
    const line = lerp(-93, 93, t);
    draw.path([[line, -77], [line - 33, 71]], CYAN, {opacity: 0.64});
  },

  'hologram-interface-deconstruction'(draw, t) {
    draw.box(0, 0, 218, 122, 'none', {stroke: GRID, radius: 8});
    const separation = smooth(t);
    const parts = [
      {x: -57, y: -28, dx: -75, dy: -45, w: 64, h: 24, color: CYAN},
      {x: 51, y: -20, dx: 74, dy: -47, w: 73, h: 41, color: VIOLET},
      {x: -29, y: 25, dx: -86, dy: 57, w: 111, h: 17, color: GREEN},
      {x: 66, y: 29, dx: 67, dy: 51, w: 42, h: 22, color: AMBER},
    ];
    for (const part of parts) {
      const endpoint = [part.x + part.dx * separation, part.y + part.dy * separation];
      const anchor = [part.x, part.y];
      draw.path([anchor, [endpoint[0], part.y], endpoint], GRID, {opacity: separation});
      draw.box(...endpoint, part.w, part.h, PANEL, {stroke: part.color, radius: 4});
      draw.box(endpoint[0] - part.w * 0.22, endpoint[1], part.w * 0.26, 3, part.color);
    }
  },

  'hologram-data-projection'(draw, t) {
    emitter(draw);
    const values = [26, 45, 39, 71, 49, 78, 65, 92, 57, 81];
    const tops = values.map((height, index) => {
      const x = -104 + index * 23;
      const baseY = 73 - Math.abs(x) * 0.09;
      const rise = 10 + height * smooth(t * 1.45 - index * 0.046);
      draw.path([[x, baseY], [x, baseY - rise]], index % 2 ? CYAN : VIOLET, {opacity: 0.7, lineWidth: 2.5});
      draw.circle(x, baseY, 2.7, CYAN);
      return [x, baseY - rise];
    });
    draw.path(tops, INK, {lineWidth: 1.75});
    for (const top of tops) draw.circle(...top, 3.4, GREEN);
  },

  'hologram-interactive-rotation'(draw, t, pointer) {
    emitter(draw);
    const yaw = TAU * (t + pointer.x * 0.19);
    const pitch = 0.4 + pointer.y * 0.68;
    const vertices = [[-1,-1,-1], [1,-1,-1], [1,1,-1], [-1,1,-1], [-1,-1,1], [1,-1,1], [1,1,1], [-1,1,1]];
    const rotated = vertices.map(([x, y, z]) => {
      const x1 = x * Math.cos(yaw) + z * Math.sin(yaw);
      const z1 = -x * Math.sin(yaw) + z * Math.cos(yaw);
      const y2 = y * Math.cos(pitch) - z1 * Math.sin(pitch);
      const z2 = y * Math.sin(pitch) + z1 * Math.cos(pitch);
      const zoom = 142 / (4.4 + z2);
      return [x1 * zoom, -21 + y2 * zoom];
    });
    for (let i = 0; i < 4; i += 1) {
      draw.path([rotated[i], rotated[(i + 1) % 4]], VIOLET, {lineWidth: 2.2});
      draw.path([rotated[i + 4], rotated[(i + 1) % 4 + 4]], CYAN, {lineWidth: 2.2});
      draw.path([rotated[i], rotated[i + 4]], INK);
    }
    draw.path([rotated[0], rotated[6]], GREEN, {opacity: 0.6});
    draw.circle(...rotated[6], 5, CYAN);
  },

  'hologram-command-interface'(draw, t) {
    panel(draw, 'COMMAND PREVIEW');
    const stages = ['CHECK', 'REVIEW', 'REPORT'];
    draw.box(0, -43, 250, 28, BG, {stroke: CYAN, radius: 5});
    const command = 'verify local snapshot';
    draw.text(-12, -43, command.slice(0, Math.max(1, Math.floor(command.length * clamp(t * 2.8)))), 12, CYAN);
    const path = [[-102, 20], [-65, 20], [0, 20], [65, 20], [102, 20]];
    draw.path(path, GRID, {lineWidth: 2});
    const head = extentLine(draw, path, t, VIOLET, {lineWidth: 3});
    for (const [index, label] of stages.entries()) {
      const x = (index - 1) * 94;
      const done = t > (index + 1) / 4;
      draw.box(x, 50, 76, 35, done ? '#1d3a49' : BG, {stroke: done ? CYAN : GRID, radius: 5});
      draw.text(x, 50, label, 10, done ? CYAN : INK);
    }
    draw.circle(...head, 5, GREEN);
  },

  'dashboard-kpi-flow'(draw, t) {
    panel(draw, 'METRIC FLOW');
    const motion = smooth(t);
    const metrics = [['Tasks', 124, CYAN], ['Checks', 98, GREEN], ['Reviews', 37, VIOLET]];
    draw.box(0, -42, 78, 25, BG, {stroke: GRID, radius: 6});
    draw.text(0, -42, 'Run totals', 10);
    for (const [index, [label, total, color]] of metrics.entries()) {
      const x = (index - 1) * 99;
      const points = [[0, -29], [0, -12], [x, -12], [x, 18]];
      draw.path(points, GRID, {lineWidth: 1.7 + index});
      extentLine(draw, points, motion, color, {lineWidth: 1.7 + index});
      draw.box(x, 51, 91, 67, BG, {stroke: color, radius: 6});
      draw.text(x, 37, label, 11, color);
      draw.text(x, 63, String(Math.round(total * motion)), 21);
    }
  },

  'dashboard-risk-matrix'(draw, t) {
    panel(draw, 'RISK MATRIX');
    const colors = ['#224a51', '#35756d', '#a66f31', '#d65969'];
    for (let x = 0; x < 5; x += 1) {
      for (let y = 0; y < 5; y += 1) {
        const risk = Math.min(3, Math.max(0, Math.floor((x + 4 - y) / 2)));
        const measured = smooth((t * 36 - x * 5 - y) / 5);
        draw.box(-86 + x * 36, -43 + y * 25, 33, 23, colors[risk], {radius: 3, opacity: 0.2 + 0.8 * measured});
      }
    }
    const route = [[-86, 57], [-50, 32], [-14, 32], [23, 7], [58, -18], [58, -43]];
    const head = extentLine(draw, route, t, INK, {lineWidth: 2.2});
    draw.circle(...head, 5.5, CYAN, {stroke: BG});
    draw.text(109, 5, 'Impact', 10);
  },

  'dashboard-predictive-reveal'(draw, t) {
    panel(draw, 'SCENARIO PREVIEW');
    chartGrid(draw, -138, -53, 279, 131);
    const observed = [[-138, 54], [-108, 35], [-80, 45], [-53, 16], [-22, 23], [2, -2]];
    draw.path(observed, CYAN, {lineWidth: 2.5});
    draw.path([[2, -53], [2, 78]], GRID, {lineWidth: 2});
    const extent = 139 * t;
    const fan = Array.from({length: 5}, (_, index) => {
      const end = lerp(-47, 57, index / 4);
      return [[2, -2], [2 + extent * 0.28, lerp(-2, end * 0.42, t)], [2 + extent * 0.66, lerp(-2, end * 0.8, t)],
        [2 + extent, lerp(-2, end, t)]];
    });
    draw.path([...fan[0], ...fan[4].slice().reverse()], 'none', {closed: true, fill: VIOLET, opacity: 0.19});
    for (const [index, path] of fan.entries()) {
      draw.path(path, index === 2 ? INK : VIOLET, {lineWidth: index === 2 ? 2.1 : 1, opacity: 0.88});
      draw.circle(...path.at(-1), 2, index === 2 ? INK : VIOLET);
    }
  },

  'dashboard-geographic-heatmap'(draw, t) {
    panel(draw, 'REGIONAL ACTIVITY');
    const region = [[-139, 19], [-106, -32], [-70, -26], [-38, -51], [-15, -30], [21, -33], [44, -51],
      [69, -24], [105, -24], [133, 5], [102, 26], [86, 57], [39, 51], [13, 73], [-23, 61], [-38, 36], [-85, 53], [-121, 41]];
    draw.path(region, CYAN, {closed: true, fill: '#153939'});
    draw.path([[-46, -44], [-30, 8], [12, 27], [39, 51]], GRID);
    draw.path([[21, -33], [-30, 8], [-85, 53]], GRID);
    draw.path([[69, -24], [62, 21], [102, 26]], GRID);
    const stations = [[-85, 14], [-21, 25], [39, -6], [91, 9]];
    for (const [index, [x, y]] of stations.entries()) {
      const severity = 0.5 + 0.5 * Math.sin(TAU * t + index * 1.7);
      const radius = 10 + 27 * severity;
      for (let layer = 3; layer >= 1; layer -= 1) {
        draw.circle(x, y, radius * layer / 3, severity > 0.7 ? PINK : AMBER, {opacity: 0.12 + 0.15 * severity});
      }
      draw.circle(x, y, 3.1, INK);
    }
  },

  'dashboard-network-graph'(draw, t) {
    panel(draw, 'RELATION GRAPH');
    const spread = smooth(t);
    const points = Array.from({length: 9}, (_, index) => {
      const angle = TAU * index / 9 - 0.37;
      const gridX = (index % 3 - 1) * 48;
      const gridY = (Math.floor(index / 3) - 1) * 31 + 12;
      return [lerp(gridX, 114 * Math.cos(angle), spread), lerp(gridY, 14 + 59 * Math.sin(angle), spread)];
    });
    for (const [index, point] of points.entries()) {
      draw.path([point, points[(index + 2) % points.length]], GRID, {lineWidth: 1.7});
      if (index % 3 === 0) draw.path([point, [0, 13]], CYAN, {opacity: 0.65});
    }
    for (const [index, point] of points.entries()) draw.circle(...point, 4 + (index % 3) * 1.9, index % 3 === 0 ? CYAN : VIOLET);
    draw.circle(0, 13, 8.3, GREEN, {stroke: BG});
  },

  'dashboard-sankey-flow'(draw, t) {
    panel(draw, 'FLOW BALANCE');
    const links = [
      {from: -31, center: -32, to: -32, width: 16, color: CYAN},
      {from: -18.5, center: -1, to: 52.5, width: 9, color: GREEN},
      {from: 28.5, center: 16, to: -19.5, width: 9, color: VIOLET},
      {from: 39.5, center: 41, to: 63.5, width: 13, color: AMBER},
    ];
    for (const {from, center, to, width, color} of links) {
      const points = Array.from({length: 17}, (_, i) => {
        const step = i / 16;
        const y = step <= 0.5 ? lerp(from, center, smooth(step * 2)) : lerp(center, to, smooth((step - 0.5) * 2));
        return [lerp(-120, 120, step), y];
      });
      draw.path(points, color, {lineWidth: width, opacity: 0.15});
      extentLine(draw, points, t, color, {lineWidth: width, opacity: 0.77});
    }
    for (const [x, y, h] of [[-125, -26.5, 25], [-125, 35, 22], [125, -27.5, 25], [125, 59, 22]]) {
      draw.box(x, y, 10, h, INK, {radius: 2});
    }
  },

  'dashboard-data-orbit'(draw, t) {
    panel(draw, 'METRIC ORBITS');
    const layers = [[112, 28, -0.27, CYAN], [88, 48, 0.36, VIOLET], [64, 39, -0.51, GREEN]];
    for (const [index, [radius, axis, roll, color]] of layers.entries()) {
      const point = (angle) => {
        const u = Math.cos(angle) * radius;
        const v = Math.sin(angle) * axis;
        return [u * Math.cos(roll) - v * Math.sin(roll), 10 + u * Math.sin(roll) + v * Math.cos(roll)];
      };
      draw.path(Array.from({length: 40}, (_, i) => point(TAU * i / 40)), GRID, {closed: true});
      const phase = TAU * t * (1 + index * 0.19) + index * 2.14;
      for (let i = 8; i >= 1; i -= 1) draw.circle(...point(phase - i * 0.075), 2.4, color, {opacity: 1 - i * 0.105});
      draw.circle(...point(phase), 5.6, color, {stroke: BG});
    }
    draw.circle(0, 10, 12, PANEL, {stroke: INK});
  },

  'dashboard-time-series-reveal'(draw, t) {
    panel(draw, 'TIME SERIES');
    chartGrid(draw, -138, -52, 276, 130);
    const values = [19, 24, 18, 39, 40, 29, 51, 49, 55, 43, 63, 70, 64, 76, 74];
    const points = values.map((value, index) => [-138 + index * 276 / (values.length - 1), 78 - value * 1.47]);
    const head = extentLine(draw, points, t, CYAN, {lineWidth: 2.5});
    draw.path([[head[0], -52], [head[0], 78]], VIOLET);
    draw.circle(...head, 6, CYAN, {stroke: BG});
    draw.text(head[0], 87, String(1 + Math.floor(t * (values.length - 1))), 9);
  },

  'dashboard-signal-pulse'(draw, t) {
    panel(draw, 'SIGNAL MONITOR');
    chartGrid(draw, -136, -53, 275, 130);
    const points = Array.from({length: 120}, (_, index) => {
      const x = index / 119;
      const drift = x - t * 1.2;
      const envelope = Math.exp(-140 * (drift - 0.04) ** 2);
      return [-136 + x * 275, 14 + 8 * Math.sin(TAU * drift * 3) + 47 * envelope * Math.sin(TAU * drift * 17)];
    });
    draw.path(points, GREEN, {lineWidth: 2.1});
    const cursor = lerp(-136, 139, t);
    draw.box(cursor, 13, 16, 130, GREEN, {opacity: 0.13});
    draw.path([[cursor, -53], [cursor, 78]], CYAN, {opacity: 0.7});
  },

  'dashboard-alert-cascade'(draw, t) {
    panel(draw, 'ALERT QUEUE');
    const alerts = [['CPU restored', CYAN], ['Input delayed', AMBER], ['Replica offline', PINK], ['Review requested', VIOLET]];
    for (const [index, [label, color]] of alerts.entries()) {
      const enter = smooth((t - index * 0.16) * 3.0);
      const x = 25 + index * 7;
      const start = [-108, -63 + index * 16];
      const top = lerp(start[1], -40 + index * 35, enter);
      const left = lerp(-88, x, enter);
      draw.path([start, [left, start[1]], [left, top]], GRID, {opacity: 0.58});
      draw.box(left, top, 174 * (0.27 + 0.73 * enter), 27, BG, {stroke: color, radius: 5, opacity: 0.3 + 0.7 * enter});
      draw.circle(left - 58 * enter, top, 3 + enter * 1.3, color, {opacity: 0.28 + enter * 0.72});
      if (enter > 0.65) draw.text(left + 14, top, label, 11, color);
    }
  },
};

/** Evaluate visual motion without real commands, customer telemetry, or provider state. */
export function sampleMotion(value, progress, options = {}) {
  const id = typeof value === 'string' ? value : value?.id;
  const definition = indexed.get(id);
  if (!definition || !inRange(progress, -1e7, 1e7)) throw new RangeError('Unknown UI motion or invalid progress');
  const {width = 640, height = 360, rtl = false, intensity = 1, reducedMotion = false,
    interaction = {x: 0, y: 0}} = options;
  if (!inRange(width, 120, 4096) || !inRange(height, 90, 4096) || !inRange(intensity, 0, 1)
      || !inRange(interaction?.x, -1, 1) || !inRange(interaction?.y, -1, 1)
      || typeof rtl !== 'boolean' || typeof reducedMotion !== 'boolean') {
    throw new RangeError('Invalid UI motion options');
  }
  const p = reducedMotion ? definition.reduced_motion.progress : clamp(progress);
  const primitives = [];
  scenes[id](drawing(width, height, rtl, primitives), lerp(0.5, p, intensity), reducedMotion ? {x: 0, y: 0} : interaction);
  return {width, height, background: BG, primitives, meta: {id, progress: p, engine: 'canvas2d', reducedMotion, synthetic: true}};
}
