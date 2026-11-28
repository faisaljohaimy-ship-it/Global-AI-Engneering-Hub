// SPDX-License-Identifier: MIT
// Original hologram and dashboard previews, with synthetic input data.
// Ported from origin/codex/nextgen-intelligence (330e662) without the five motions that HEAD already
// has as native engine motions and the five that show no digital meaning (docs/evidence/ported-motions.json).
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
  ['hologram-card-assembly', 'Card Assembly', 'تجميع البطاقات', 'Separate frame, chip, and wave layers converge into a card.'],
  ['hologram-depth-mapping', 'Depth Mapping', 'رسم خريطة العمق', 'A raster sweep turns sampled depth into raised, color-mapped columns.'],
  ['hologram-interface-deconstruction', 'Interface Deconstruction', 'تفكيك الواجهة', 'Panel elements fan out along independent explosion vectors and preserve their tethers.'],
  ['hologram-data-projection', 'Data Projection', 'إسقاط البيانات', 'Points on an emitter surface seed rising columns and a connected data curve.'],
  ['hologram-command-interface', 'Command Interface', 'واجهة الأوامر', 'A visual command travels from input to a read-only synthetic pipeline.'],
  ['dashboard-risk-matrix', 'Risk Matrix', 'مصفوفة المخاطر', 'Risk cells accumulate in progression and a traced assessment traverses the matrix.'],
  ['dashboard-predictive-reveal', 'Predictive Reveal', 'كشف التوقع', 'Historical observations meet a fan of illustrative trajectories.'],
  ['dashboard-geographic-heatmap', 'Geographic Heatmap', 'خريطة حرارية جغرافية', 'Heat kernels expand over nodes on a fictional region map.'],
  ['dashboard-network-graph', 'Network Graph', 'رسم الشبكة', 'A lattice of related nodes relaxes into an orbit with retained edges.'],
  ['dashboard-alert-cascade', 'Alert Cascade', 'تتابع التنبيهات', 'Incoming events fall into a time-ordered alert stack.'],
];

// The digital meaning of each motion (governance/policies/motion-purpose.json), written when it was
// ported from origin/codex/nextgen-intelligence; the source branch stated none.
const meanings = {
  'hologram-card-assembly': {en: 'Building a dashboard card from components: a trend chart, a message badge and a progress bar slot into one panel.', ar: 'بناء بطاقة لوحة معلومات من مكوّناتها: يستقر مخطط الاتجاه وشارة الرسائل وشريط التقدّم في لوحة واحدة.'},
  'hologram-depth-mapping': {en: 'Depth sensing for a digital model: a scan line sweeps the area, samples each point and turns it into a colour-coded height.', ar: 'استشعار العمق لنموذج رقمي: يمسح خط المسح المنطقة، ويقيس كل نقطة ويحوّلها إلى ارتفاع مرمّز بالألوان.'},
  'hologram-interface-deconstruction': {en: 'Interface breakdown: a service screen is pulled apart into its components, and tethers keep each one tied to its place in the layout.', ar: 'تفكيك الواجهة: تُفصل شاشة الخدمة إلى مكوّناتها، وتُبقي الروابط كل مكوّن مشدودًا إلى موضعه في التخطيط.'},
  'hologram-data-projection': {en: 'Data visualisation: readings rise from the platform as columns and are joined into a trend line.', ar: 'تصوير البيانات: ترتفع القراءات من المنصة أعمدةً وتتصل في خط اتجاه واحد.'},
  'hologram-command-interface': {en: 'An operator command runs as a pipeline: the typed request passes check, review and report, and each stage lights up as it completes.', ar: 'أمر المشغّل يعمل كمسار: يمرّ الطلب المكتوب بالتحقق ثم المراجعة ثم التقرير، وتضيء كل مرحلة عند اكتمالها.'},
  'dashboard-risk-matrix': {en: 'Risk assessment: findings fill a likelihood-impact matrix, and the assessment line climbs to the highest-risk cell.', ar: 'تقييم المخاطر: تملأ النتائج مصفوفة الاحتمال والأثر، ويصعد خط التقييم إلى الخلية الأعلى خطورة.'},
  'dashboard-predictive-reveal': {en: 'Forecasting: past observations are followed by a fan of projected scenarios that widens the further ahead it looks.', ar: 'التنبؤ: تتبع المشاهداتِ السابقة مروحةٌ من السيناريوهات المتوقعة تتسع كلما امتد النظر إلى الأمام.'},
  'dashboard-geographic-heatmap': {en: 'Regional activity monitoring: service demand hotspots grow and fade across the regions of a fictional map.', ar: 'مراقبة النشاط الإقليمي: تكبر بؤر الطلب على الخدمة وتخبو عبر مناطق خريطة افتراضية.'},
  'dashboard-network-graph': {en: 'A relationship graph: linked records spread out around their central entity so that each connection can be read.', ar: 'رسم العلاقات: تنتشر السجلات المرتبطة حول الكيان المركزي حتى يمكن قراءة كل صلة.'},
  'dashboard-alert-cascade': {en: 'Incident alerting: platform events arrive and stack in time order in the alert queue, coloured by severity.', ar: 'التنبيه بالحوادث: تصل أحداث المنصة وتتراص بترتيب زمني في طابور التنبيهات، ملوّنة بحسب خطورتها.'},
};
if (metadata.some(([id]) => !meanings[id])) throw new Error('Every UI motion states its digital meaning');
export const definitions = Object.freeze(metadata.map(([id, name_en, name_ar, mechanism]) => Object.freeze({
  id, name_en, name_ar, mechanism,
  meaning: Object.freeze({...meanings[id]}),
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

const glyph = [
  [-53, 46], [-32, 23], [-7, 32], [9, -6], [30, -11], [56, -47], [76, -32],
];

const scenes = {



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
