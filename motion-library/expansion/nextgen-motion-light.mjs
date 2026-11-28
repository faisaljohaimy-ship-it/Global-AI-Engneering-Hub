// SPDX-License-Identifier: MIT
// Original cinematic lighting and product illustrations for the Universal Motion SDK.
// Ported from origin/codex/nextgen-intelligence (eb2366f): three product scenes. Three lighting ids are
// withdrawn and fourteen other studies show no digital meaning (docs/evidence/ported-motions.json).

const INK = '#08111f';
const PANEL = '#162b43';
const DIM = '#38516a';
const WHITE = '#f1f5f9';
const CYAN = '#67e8f9';
const BLUE = '#60a5fa';
const VIOLET = '#a78bfa';
const GOLD = '#fbbf77';
const MINT = '#6ee7b7';

const clamp = (value) => Math.max(0, Math.min(1, value));
const mix = (start, end, amount) => start + (end - start) * amount;
const ease = (amount) => {
  const bounded = clamp(amount);
  return bounded * bounded * (3 - 2 * bounded);
};
const phase = (time, start, duration) => ease((time - start) / duration);
const bounded = (value, minimum, maximum) => Number.isFinite(value) && value >= minimum && value <= maximum;

function stage(width, height, rtl) {
  const scale = Math.min(width, height) * .93;
  const mirror = rtl ? -1 : 1;
  const x = (value) => width / 2 + mirror * (value - .025) * scale;
  const y = (value) => height / 2 + value * scale;
  const primitives = [];
  const strokeWidth = (value) => Math.max(.6, value * scale);
  return {
    primitives,
    line(from, to, stroke = DIM, opacity = 1, weight = .003) {
      primitives.push({type: 'line', x1: x(from[0]), y1: y(from[1]), x2: x(to[0]), y2: y(to[1]),
        stroke, opacity: clamp(opacity), lineWidth: strokeWidth(weight)});
    },
    path(points, stroke, opacity = 1, {fill, closed = false, weight = .003} = {}) {
      primitives.push({type: 'polyline', points: points.map(([px, py]) => ({x: x(px), y: y(py)})),
        stroke, fill, closed, opacity: clamp(opacity), lineWidth: strokeWidth(weight)});
    },
    dot(px, py, radius, fill, opacity = 1, stroke) {
      primitives.push({type: 'circle', x: x(px), y: y(py), r: radius * scale, fill, stroke,
        opacity: clamp(opacity), lineWidth: strokeWidth(.002)});
    },
    rect(px, py, w, h, fill, {opacity = 1, stroke, rotation = 0, radius = .012} = {}) {
      primitives.push({type: 'rect', x: x(px) - w * scale / 2, y: y(py) - h * scale / 2,
        width: w * scale, height: h * scale, fill, stroke, rotation: mirror * rotation,
        radius: Math.min(radius, w / 2, h / 2) * scale, opacity: clamp(opacity), lineWidth: strokeWidth(.002)});
    },
    label(px, py, english, arabic, opacity = 1, size = .032, fill = WHITE) {
      primitives.push({type: 'text', x: x(px), y: y(py), text: rtl ? arabic : english, fill,
        opacity: clamp(opacity), align: 'center', size: Math.max(1, size * scale)});
    },
  };
}

function device(graph, x = 0, y = 0, size = 1, opacity = 1) {
  graph.rect(x, y, .35 * size, .48 * size, PANEL, {stroke: DIM, opacity});
  graph.rect(x, y - .012 * size, .31 * size, .405 * size, INK, {stroke: DIM, opacity});
  graph.dot(x, y + .211 * size, .012 * size, DIM, opacity);
}

function panel(graph, x, y, width, height, color, level, opacity = 1, rotation = 0) {
  const position = (dx, dy) => [x + dx * Math.cos(rotation) - dy * Math.sin(rotation),
    y + dx * Math.sin(rotation) + dy * Math.cos(rotation)];
  graph.rect(x, y, width, height, PANEL, {stroke: color, opacity, rotation});
  graph.rect(...position(-width * .19, -height * .21), width * .4, height * .075, color, {opacity, rotation});
  graph.rect(...position(width * (-.4 + .39 * level), height * .13),
    width * .78 * level, height * .09, color, {opacity: .7 * opacity, rotation});
}

function featureSpotlight(graph, time) {
  const locations = [[-.137, -.13], [.123, -.038], [-.113, .124]];
  device(graph, -.01, 0, 1.18);
  const step = Math.min(1, Math.floor(time * 2));
  const amount = phase(time, step / 2, .5);
  const point = [mix(locations[step][0], locations[step + 1][0], amount),
    mix(locations[step][1], locations[step + 1][1], amount)];
  for (const [index, [x, y]] of locations.entries()) {
    const focus = 1 - clamp(Math.hypot(x - point[0], y - point[1]) * 6);
    graph.rect(x, y, .108, .071, [BLUE, VIOLET, MINT][index], {opacity: .22 + focus * .68});
  }
  graph.dot(...point, .056, 'none', .97, WHITE);
  graph.path([point, [.212, point[1]], [.286, -.06]], GOLD);
  graph.rect(.29, -.082, .105, .043, PANEL, {stroke: GOLD});
}

function systemDemonstration(graph, time) {
  const endpoints = [[-.347, -.128], [-.13, .086], [.106, -.088], [.325, .139]];
  const stageColors = [BLUE, CYAN, VIOLET, MINT];
  graph.path(endpoints, DIM, .9, {weight: .009});
  const position = time * 3;
  const hop = Math.min(2, Math.floor(position));
  const amount = position - hop;
  for (const [index, [x, y]] of endpoints.entries()) {
    const active = phase(position, index - .45, .6);
    panel(graph, x, y, .153, .101, stageColors[index], .23 + .68 * active);
    if (index > 0) graph.line(endpoints[index - 1], [x, y], stageColors[index], active, .005);
  }
  const x = mix(endpoints[hop][0], endpoints[hop + 1][0], amount);
  const y = mix(endpoints[hop][1], endpoints[hop + 1][1], amount);
  graph.dot(x, y, .022, WHITE, 1, MINT);
  graph.label(0, -.285, 'SYSTEM FLOW', 'مسار النظام', .75);
}

function timelineTransformation(graph, time) {
  graph.line([-.408, .21], [.407, .21], DIM, .9, .006);
  const positions = [-.299, -.105, .09, .295];
  for (const [index, x] of positions.entries()) {
    const transformed = phase(time, index * .17, .45);
    const y = mix(.182, -.06 - .06 * (index % 2), transformed);
    const tone = [BLUE, CYAN, VIOLET, MINT][index];
    graph.line([x, .21], [x, y], tone, .35 + .65 * transformed);
    graph.dot(x, .21, .012, tone, .72);
    graph.rect(x, y, mix(.029, .177, transformed), mix(.029, .231, transformed),
      PANEL, {stroke: tone, radius: .009});
    if (transformed > .18) {
      graph.label(x, y - .054 * transformed, '0' + (index + 1), '٠' + ['١', '٢', '٣', '٤'][index],
        transformed, .042, tone);
      graph.line([x - .055 * transformed, y + .036], [x + .055 * transformed, y + .036], tone, transformed);
    }
  }
  graph.dot(mix(-.4, .4, time), .21, .019, WHITE);
}

const specs = [
  ['product-feature-spotlight', 'Feature-by-Feature Spotlight', 'تسليط الضوء على المزايا', 'A focus ring hands attention between individual device features.', featureSpotlight],
  ['product-system-demonstration', 'Immersive System Demonstration', 'عرض النظام التفاعلي', 'A data packet crosses a system diagram and activates processing stages.', systemDemonstration],
  ['product-timeline-transformation', 'Product Timeline Transformation', 'تحول الجدول الزمني للمنتج', 'Chronological markers expand into milestone cards as the cursor advances.', timelineTransformation],
];

// The digital meaning of each motion (governance/policies/motion-purpose.json), written when it was
// ported from origin/codex/nextgen-intelligence; the source branch stated none.
const meanings = {
  'product-feature-spotlight': {en: 'A guided product tour: a highlight ring moves from one feature of the app screen to the next, each with its own callout.', ar: 'جولة إرشادية في المنتج: تنتقل حلقة تمييز من ميزة في شاشة التطبيق إلى التالية، ولكل ميزة تعليقها.'},
  'product-system-demonstration': {en: 'A request moving through a system: the data packet crosses the system flow and each processing stage lights up as it handles it.', ar: 'طلب يمرّ عبر النظام: تعبر حزمة البيانات مسار النظام وتضيء كل مرحلة معالجة حين تتولاها.'},
  'product-timeline-transformation': {en: 'Release history: as the cursor moves along the timeline, each dated marker opens into a card for that release.', ar: 'سجل الإصدارات: كلما تقدّم المؤشر على الخط الزمني انفتحت كل علامة مؤرخة في بطاقة لذلك الإصدار.'},
};
if (specs.some(([id]) => !meanings[id])) throw new Error('Every product motion states its digital meaning');
const samplers = new Map(specs.map(([id, , , , render]) => [id, render]));
export const definitions = Object.freeze(specs.map(([id, name_en, name_ar, mechanism]) => Object.freeze({
  id, name_en, name_ar, mechanism, meaning: Object.freeze({...meanings[id]}), engine: 'canvas2d', duration_ms: 3200,
  source: {module: 'motion-library/expansion/nextgen-motion-light.mjs'},
  license: 'MIT', license_file: 'motion-library/expansion/LICENSE',
  implementation_status: 'implemented-source', runtime_status: 'requires-current-source-bound-proof',
  reduced_motion: {mode: 'static-poster', progress: .55},
  mobile: {requires_real_device_verification: true},
  semantics: 'Illustrative CPU-rendered scene using Canvas2D vector primitives.',
})));

export function sampleMotion(value, progress, options = {}) {
  const id = typeof value === 'string' ? value : value?.id;
  const sampler = samplers.get(id);
  if (!sampler || !bounded(progress, -1e7, 1e7)) throw new RangeError('Unknown motion or invalid progress');
  const {width = 640, height = 360, intensity = 1, rtl = false, reducedMotion = false,
    interaction = {x: 0, y: 0}} = options;
  if (!bounded(width, 120, 4096) || !bounded(height, 90, 4096) || !bounded(intensity, 0, 1)
      || typeof rtl !== 'boolean' || typeof reducedMotion !== 'boolean'
      || !bounded(interaction?.x, -1, 1) || !bounded(interaction?.y, -1, 1)) {
    throw new RangeError('Invalid motion options');
  }
  const time = reducedMotion ? .55 : clamp(progress);
  const graph = stage(width, height, rtl);
  sampler(graph, .5 + (time - .5) * intensity, reducedMotion ? {x: 0, y: 0} : interaction);
  return {width, height, background: INK, primitives: graph.primitives,
    meta: {id, progress: time, engine: 'canvas2d', reducedMotion}};
}
