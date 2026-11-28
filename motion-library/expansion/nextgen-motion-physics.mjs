// SPDX-License-Identifier: MIT
// Original generated-data engineering scenes. All trajectories are repeatable.
// Ported from origin/codex/nextgen-intelligence (9f77420): the eight digital twin scenes. Five motions are
// native on HEAD and seven physics studies show no digital meaning (docs/evidence/ported-motions.json).
const SOURCE = 'motion-library/expansion/nextgen-motion-physics.mjs';
const BACKGROUND = '#08111f';
const CYAN = '#67e8f9';
const PURPLE = '#a78bfa';
const INK = '#e2e8f0';
const AMBER = '#fbbf24';
const MUTED = '#314762';
const GREEN = '#6ee7b7';
const TAU = 2 * Math.PI;
const clamp = (value) => Math.max(0, Math.min(1, value));
const mix = (a, b, t) => a + (b - a) * t;
const lerp = (a, b, t) => [mix(a[0], b[0], t), mix(a[1], b[1], t)];
function smooth(value) {
  const t = clamp(value);
  return t * t * (3 - 2 * t);
}
const dots = (count, point) => Array.from({length: count}, (_, i) => point(i));
const polygon = (x, y, radius, count, phase = 0) => dots(count, i => {
  const angle = phase + TAU * i / count;
  return [x + radius * Math.cos(angle), y + radius * Math.sin(angle)];
});

function drawing(width, height, rtl) {
  const size = Math.min(width, height);
  const strokeWidth = Math.max(1.15, size * .004);
  const primitives = [];
  const point = ([x, y]) => ({x: width * .5 + (rtl ? -1 : 1) * size * (x - .5),
    y: height * .5 + size * (y - .5)});
  return {
    primitives,
    line(a, b, stroke = CYAN, opacity = 1) {
      if (opacity <= 0) return;
      const from = point(a);
      const to = point(b);
      primitives.push({type: 'line', x1: from.x, y1: from.y, x2: to.x, y2: to.y,
        stroke, opacity, lineWidth: strokeWidth});
    },
    path(points, {stroke = CYAN, fill, closed = false, opacity = 1} = {}) {
      if (opacity <= 0 || points.length < 2) return;
      primitives.push({type: 'polyline', points: points.map(point), closed, stroke, fill,
        opacity, lineWidth: strokeWidth});
    },
    dot(position, radius, {fill = CYAN, stroke, opacity = 1} = {}) {
      if (opacity <= 0) return;
      primitives.push({type: 'circle', ...point(position), r: radius * size, fill, stroke, opacity,
        lineWidth: strokeWidth});
    },
  };
}

const iso = (x, y, z) => [.47 + x * .29 - z * .17, .67 + x * .115 + z * .12 - y * .34];
function box(draw, center, dimensions, stroke = CYAN, opacity = 1) {
  const [x, y, z] = center;
  const [w, h, d] = dimensions;
  const foot = [[x, z], [x + w, z], [x + w, z + d], [x, z + d]];
  for (let i = 0; i < 4; i++) {
    const [a, b] = foot[i];
    const [c, e] = foot[(i + 1) % 4];
    draw.line(iso(a, y, b), iso(c, y, e), stroke, opacity);
    draw.line(iso(a, y + h, b), iso(c, y + h, e), stroke, opacity);
    draw.line(iso(a, y, b), iso(a, y + h, b), stroke, opacity);
  }
}

function construction(draw, t) {
  box(draw, [-.93, -.14, -.35], [1.48, .1, .85], MUTED);
  for (let floor = 0; floor < 5; floor++) {
    const growth = smooth(t * 5.1 + .3 - floor);
    const y = floor * .23;
    const width = 1.08 - floor * .07;
    box(draw, [-.68, y, -.27], [width, .16 * growth, .6], floor % 2 ? PURPLE : CYAN, growth);
    draw.dot(iso(-.68, y + .16 * growth, -.27), .018, {fill: AMBER, opacity: growth});
  }
}

function synchronize(draw, t) {
  const source = [.24, .36];
  const target = [.73, .66];
  draw.path(polygon(...source, .14, 6, .17), {closed: true, stroke: PURPLE});
  draw.path(polygon(...target, .145, 6, .17), {closed: true, stroke: GREEN});
  const route = [source, [.48, .36], [.48, .66], target];
  draw.path(route, {stroke: MUTED});
  for (let i = 0; i < 4; i++) {
    const phase = clamp(1.3 * t - i * .14);
    const segment = Math.min(2, Math.floor(phase * 3));
    draw.dot(lerp(route[segment], route[segment + 1], phase * 3 - segment), .017, {fill: AMBER});
    const current = smooth((phase - .64) * 3);
    draw.line([.64, .61 + i * .034], [.64 + current * (.11 + i * .014), .61 + i * .034], GREEN);
    draw.line([.16, .31 + i * .033], [.29 + i * .011, .31 + i * .033], PURPLE, .85);
  }
}

function explodedAssembly(draw, t) {
  const spread = .43 * smooth(t);
  const pieces = [
    {at: [-.65, -.1, -.23], size: [1.02, .16, .63], shift: [-.7, .1, 0], color: MUTED},
    {at: [-.54, .12, -.15], size: [.43, .39, .42], shift: [-.53, .48, .3], color: CYAN},
    {at: [-.05, .12, -.15], size: [.37, .31, .42], shift: [.62, .28, -.28], color: PURPLE},
    {at: [-.67, .56, -.27], size: [1.06, .1, .66], shift: [.0, 1.18, 0], color: AMBER},
  ];
  for (const {at, size, shift, color} of pieces) {
    const moved = at.map((coordinate, i) => coordinate + spread * shift[i]);
    draw.line(iso(...at), iso(...moved), MUTED, .8);
    box(draw, moved, size, color);
  }
}

function isolateLayer(draw, t) {
  const scan = t * 3.4;
  for (let layer = 0; layer < 4; layer++) {
    const proximity = Math.max(.16, 1 - Math.abs(layer - scan) * .78);
    const y = .035 + layer * .28;
    const z = -.37 + .1 * layer;
    box(draw, [-.75, y, z], [1.18 - layer * .1, .055, .77], CYAN, proximity);
    for (let i = 1; i <= 4; i++) {
      draw.line(iso(-.75 + i * .15, y + .055, z), iso(-.75 + i * .15, y + .055, z + .77), PURPLE, proximity);
    }
  }
  draw.line([.8, .15], [.8, .79], MUTED);
  draw.dot([.8, .75 - t * .56], .021, {fill: AMBER});
}

function blueprint(draw, t) {
  const face = [[-.77, -.37], [.49, -.37], [.49, .49], [-.77, .49]];
  const plan = (x, z) => [.49 + x * .37, .54 + z * .47];
  const fold = (x, y, z) => lerp(plan(x, z), iso(x, y, z), smooth(t));
  for (let i = 0; i < face.length; i++) {
    const [x, z] = face[i];
    const [a, b] = face[(i + 1) % face.length];
    draw.line(fold(x, 0, z), fold(a, 0, b), MUTED);
    draw.line(fold(x, .74, z), fold(a, .74, b), CYAN);
    draw.line(fold(x, 0, z), fold(x, .74, z), PURPLE);
  }
  draw.line(fold(-.5, .74, -.24), fold(.32, .74, .36), AMBER);
  draw.line(fold(-.5, .74, .36), fold(.32, .74, -.24), AMBER);
}

function flythrough(draw, t) {
  // Perspective passage between three offset sensor banks.
  const camera = t * 8.6;
  const project = (x, y, z) => [.45 + x * .61 / z, .48 + y * .61 / z];
  for (let bank = 12; bank >= 1; bank--) {
    const depth = bank * 1.35 - camera;
    if (depth < 1.8) continue;
    const offset = .22 * Math.sin(bank * .9);
    const top = project(-.94 + offset, -.66, depth);
    const left = project(-.94 + offset, .68, depth);
    const bottom = project(1.05 + offset, .68, depth);
    const right = project(1.05 + offset, -.66, depth);
    draw.path([top, left, bottom, right], {closed: true, stroke: CYAN, opacity: .76});
    for (let sensor = 0; sensor < 3; sensor++) {
      draw.dot(project(.85 + offset, -.42 + sensor * .36, depth), .049 / depth, {fill: AMBER});
    }
  }
  draw.line([.19, .83], [.7, .83], MUTED);
  draw.dot([.19 + t * .51, .83], .012, {fill: AMBER});
}

const elevation = (x, z) => .13 + .45 * Math.exp(-3 * ((x - .2) ** 2 + (z + .18) ** 2))
  + .08 * Math.sin(8 * x + 2 * z) * Math.cos(4 * z);
function reconstructTerrain(draw, t) {
  const count = 10;
  const z = i => i / count * 1.42 - .76;
  const x = i => i / count * 1.51 - .85;
  const station = t * 11.2;
  for (let row = 0; row <= count; row++) {
    const visibility = smooth(station - row + .4);
    const p = index => iso(x(index), elevation(x(index), z(row)), z(row));
    draw.path(dots(count + 1, p), {stroke: row % 2 ? CYAN : PURPLE, opacity: visibility});
    if (row > 0) for (let col = 0; col <= count; col++) {
      draw.line(p(col), iso(x(col), elevation(x(col), z(row - 1)), z(row - 1)),
        MUTED, .85 * visibility);
    }
  }
  const front = z(Math.min(count, station));
  draw.path(dots(count + 1, i => iso(x(i), elevation(x(i), front) + .045, front)), {stroke: AMBER});
}

function assetCondition(draw, t) {
  const timeline = [.12, .26, .39, .57, .62, .88, .81, .72];
  box(draw, [-.86, .09, -.4], [.62, .85, .47], PURPLE);
  const at = p => [.45 + p * .38, .68 - timeline[Math.min(7, Math.floor(p * 8))] * .43];
  draw.line([.45, .72], [.85, .72], MUTED);
  draw.line([.45, .28], [.45, .72], MUTED);
  draw.line([.45, .38], [.85, .38], AMBER, .66);
  const head = t * 7;
  for (let i = 0; i < 7; i++) {
    const amount = clamp(head - i);
    const a = at(i / 8);
    const b = at((i + 1) / 8);
    draw.line(a, lerp(a, b, amount), b[1] < .38 ? AMBER : GREEN, amount);
  }
  const index = Math.min(6, Math.floor(head));
  const value = lerp(at(index / 8), at((index + 1) / 8), head - index);
  draw.dot(value, .02, {fill: INK});
  draw.dot(iso(-.49, .59, -.4), .023 + .022 * (1 - value[1]),
    {fill: value[1] < .38 ? AMBER : GREEN});
}

const specs = [
  ['twin-construction', 'Twin Construction', 'بناء التوأم الرقمي', 'Stage the shell and floors from an isometric base.', construction],
  ['twin-asset-synchronization', 'Asset Synchronization', 'مزامنة الأصل', 'Move version packets to a replica and fill the received rows.', synchronize],
  ['twin-exploded-assembly', 'Exploded Assembly', 'تفكيك التجميع', 'Separate four volumes along individual assembly axes.', explodedAssembly],
  ['twin-layer-isolation', 'Layer Isolation', 'عزل الطبقات', 'Sweep a layer selector with opacity on adjacent strata.', isolateLayer],
  ['twin-blueprint-transformation', 'Blueprint Transformation', 'تحويل المخطط', 'Fold a two-dimensional plan into an isometric volume.', blueprint],
  ['twin-system-flythrough', 'System Flythrough', 'جولة داخل النظام', 'Advance a perspective eye through a sequence of sensor banks.', flythrough],
  ['twin-terrain-reconstruction', 'Terrain Reconstruction', 'إعادة بناء التضاريس', 'Reveal cross-sections and join neighboring scans into a mesh.', reconstructTerrain],
  ['twin-asset-condition', 'Asset Condition', 'حالة الأصل', 'Advance a condition series through its alert threshold and mark the asset.', assetCondition],
];
// The digital meaning of each motion (governance/policies/motion-purpose.json), written when it was
// ported from origin/codex/nextgen-intelligence; the source branch stated none.
const meanings = {
  'twin-construction': {en: 'Building a facility\'s digital twin: its base, shell and floors are added to the model level by level.', ar: 'بناء التوأم الرقمي لمنشأة: تُضاف قاعدتها وهيكلها وطوابقها إلى النموذج طابقًا بعد طابق.'},
  'twin-asset-synchronization': {en: 'Twin synchronisation: version updates travel from the asset\'s record to its digital replica and fill in the received rows.', ar: 'مزامنة التوأم: تنتقل تحديثات الإصدار من سجل الأصل إلى نسخته الرقمية وتملأ الصفوف المستلمة.'},
  'twin-exploded-assembly': {en: 'An exploded view in a digital twin: the asset\'s modules pull apart along their assembly axes so each part can be inspected.', ar: 'عرض مفكّك في التوأم الرقمي: تتباعد وحدات الأصل على محاور تجميعها ليُفحص كل جزء على حدة.'},
  'twin-layer-isolation': {en: 'Layer isolation in a digital twin: a selector moves through the building\'s strata and brings one layer forward while the others dim.', ar: 'عزل الطبقات في التوأم الرقمي: يتحرك محدِّد عبر طبقات المبنى فيُبرز طبقة واحدة بينما تخفت الأخرى.'},
  'twin-blueprint-transformation': {en: 'From plan to model: a two-dimensional floor plan is raised into a three-dimensional volume for the digital twin.', ar: 'من المخطط إلى النموذج: يُرفع مخطط الطابق ثنائي الأبعاد إلى حجم ثلاثي الأبعاد في التوأم الرقمي.'},
  'twin-system-flythrough': {en: 'Inspecting an installation in its digital twin: the view travels through its successive sensor banks while a marker shows how far it has gone.', ar: 'فحص منشأة في توأمها الرقمي: يعبر المنظور بنوك الحساسات المتتالية بينما يبيّن مؤشرٌ المسافة المقطوعة.'},
  'twin-terrain-reconstruction': {en: 'From survey to digital terrain: scanned cross-sections are joined one after another into a terrain mesh.', ar: 'من المسح إلى التضاريس الرقمية: تُوصل المقاطع العرضية الممسوحة واحدًا تلو الآخر في شبكة تضاريس.'},
  'twin-asset-condition': {en: 'Condition monitoring: an asset\'s sensor reading climbs past its alert threshold and the asset is flagged in the twin.', ar: 'مراقبة الحالة: ترتفع قراءة حساس الأصل فوق عتبة التنبيه فيُعلَّم الأصل في التوأم الرقمي.'},
};
if (specs.some(([id]) => !meanings[id])) throw new Error('Every digital twin motion states its digital meaning');
const samplers = new Map(specs.map(([id, ...rest]) => [id, rest.at(-1)]));
export const definitions = Object.freeze(specs.map(([id, name_en, name_ar, mechanism]) => {
  const category = id.split('-')[0];
  return Object.freeze({
    id, name_en, name_ar, mechanism, meaning: Object.freeze({...meanings[id]}), category, engine: 'canvas2d', duration_ms: 3200,
    license: 'MIT', license_file: 'motion-library/expansion/LICENSE',
    implementation_status: 'implemented-source', runtime_status: 'requires-current-source-bound-proof',
    source: Object.freeze({module: SOURCE}), reduced_motion: Object.freeze({mode: 'static-poster', progress: .55}),
    semantics: category === 'twin' ? 'Generated-data digital twin visualization.' : 'Bounded illustrative physics model.',
  });
}));

export function sampleMotion(input, progress, options = {}) {
  const id = typeof input === 'string' ? input : input?.id;
  const sampler = samplers.get(id);
  if (!sampler || !Number.isFinite(progress)) throw new RangeError('Unknown motion or invalid progress');
  const {width = 640, height = 360, intensity = 1, rtl = false, reducedMotion = false} = options;
  if (!Number.isFinite(width) || width < 120 || width > 4096 || !Number.isFinite(height) || height < 90
      || height > 4096 || !Number.isFinite(intensity) || intensity < 0 || intensity > 1
      || typeof rtl !== 'boolean' || typeof reducedMotion !== 'boolean') throw new RangeError('Invalid motion options');
  const t = reducedMotion ? .55 : mix(.5, clamp(progress), intensity);
  const draw = drawing(width, height, rtl);
  sampler(draw, t);
  return {width, height, background: BACKGROUND, primitives: draw.primitives,
    meta: {id, progress: t, engine: 'canvas2d', reducedMotion}};
}
