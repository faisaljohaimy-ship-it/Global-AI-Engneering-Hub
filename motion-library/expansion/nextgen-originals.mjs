// SPDX-License-Identifier: MIT
// Original camera studies and interaction previews for the Canvas2D motion SDK.
// Ported from origin/codex/nextgen-intelligence (e3fda12): five interaction previews. The seven camera
// studies and four other previews are native on HEAD or show no digital meaning (docs/evidence/ported-motions.json).
const source = 'motion-library/expansion/nextgen-originals.mjs';
const background = '#08111f';
const ink = '#e2e8f0';
const cyan = '#67e8f9';
const violet = '#a78bfa';
const muted = '#38536d';
const surface = '#15263c';
const clamp = (value) => Math.max(0, Math.min(1, value));
const mix = (from, to, progress) => from + (to - from) * progress;
const smooth = (value) => {
  const t = clamp(value);
  return t * t * (3 - 2 * t);
};
const between = (value, low, high) =>
  typeof value === 'number' && Number.isFinite(value) && low <= value && value <= high;

const microSpecs = [
  ['micro-button-compression', 'Button Compression', 'انضغاط الزر', 'A fixed control compresses toward its contact plane, then rebounds.'],
  ['micro-hover-elevation', 'Hover Elevation', 'ارتفاع عند التحويم', 'A card lifts relative to an anchored contact shadow and tilts with the pointer.'],
  ['micro-input-focus', 'Input Focus', 'تركيز حقل الإدخال', 'A focus underline expands while its label rises and a caret emerges.'],
  ['micro-elastic-selection', 'Elastic Selection', 'اختيار مرن', 'An underlay tracks a three-part selection with staggered leading and trailing edges.'],
  ['micro-navigation-morph', 'Navigation Morph', 'تحول قائمة التنقل', 'Three navigation bars reshape into a close control and reveal the menu rows.'],
];

// The digital meaning of each motion (governance/policies/motion-purpose.json), written when it was
// ported from origin/codex/nextgen-intelligence; the source branch stated none.
const meanings = {
  'micro-button-compression': {en: 'Starting a job: the Run button sinks toward its base when pressed and springs back, confirming that the command was received.', ar: 'بدء مهمة: ينخفض زر التشغيل نحو قاعدته عند الضغط ثم يرتد، مؤكدًا استلام الأمر.'},
  'micro-hover-elevation': {en: 'Hovering over a service card: the card lifts off its shadow and tilts toward the pointer to show that it can be opened.', ar: 'التمرير فوق بطاقة خدمة: ترتفع البطاقة عن ظلها وتميل نحو المؤشر لتبيّن أنها قابلة للفتح.'},
  'micro-input-focus': {en: 'Filling in an email field on a digital form: on focus the label moves up, the underline extends and a caret waits for typing.', ar: 'تعبئة حقل البريد الإلكتروني في نموذج رقمي: عند التركيز يرتفع العنوان ويمتد الخط السفلي ويظهر مؤشر الكتابة.'},
  'micro-elastic-selection': {en: 'Choosing an option in a segmented control: the highlight stretches from the current choice to the next one.', ar: 'اختيار خيار في عنصر تحكم مقسّم: يمتد التظليل من الخيار الحالي إلى الخيار التالي.'},
  'micro-navigation-morph': {en: 'Opening an app\'s menu: the three-bar menu icon turns into a close button while the menu items slide in.', ar: 'فتح قائمة التطبيق: تتحول أيقونة القائمة ذات الخطوط الثلاثة إلى زر إغلاق بينما تنزلق عناصر القائمة.'},
};
if (microSpecs.some(([id]) => !meanings[id])) throw new Error('Every interaction motion states its digital meaning');
function definition([id, name_en, name_ar, mechanism], category) {
  return Object.freeze({
    id, name_en, name_ar, mechanism, meaning: Object.freeze({...meanings[id]}), engine: 'canvas2d',
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
  ...microSpecs.map((spec) => definition(spec, 'micro')),
]);
const known = new Map(definitions.map((row) => [row.id, row]));

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
  'micro-hover-elevation'(draw, t, pointer) {
    const lift = 7 + 25 * smooth(t);
    const roll = 0.14 * pointer.x + mix(-0.07, 0.07, t);
    draw.rect(0, 30, 200 - lift, 21, '#213147', 10, {opacity: 0.7 - lift / 100});
    draw.rect(0, 13 - lift, 185, 77, surface, 14, {stroke: cyan, rotation: roll, lineWidth: 1.4});
    draw.circle(-58, 13 - lift, 12, cyan);
    draw.rect(27, 5 - lift, 93, 5, ink, 2);
    draw.rect(18, 19 - lift, 73, 4, muted, 2);
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
  const extra = microScenes[id](designSpace(width, height, rtl, primitives), t, pointer);
  return {width, height, background, primitives, meta: {id, progress: p, engine: 'canvas2d', reducedMotion, ...extra}};
}
