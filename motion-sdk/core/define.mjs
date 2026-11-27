// The shape every motion must have. defineMotion() refuses anything else, so a module
// that loads is a module the rest of the SDK can drive.
import { EASINGS } from './easing.mjs';
import { hexToRgb } from './util.mjs';

export const ENGINES = Object.freeze(['canvas2d', 'webgl2-glsl', 'webgl2-points', 'dom', 'svg', 'webgpu-wgsl', 'composition']);
export const MODULES = Object.freeze({
  quantum: { letter: 'A', en: 'Quantum-inspired motion', ar: 'حركات مستوحاة من الكم' },
  camera: { letter: 'B', en: 'Cinematic camera systems', ar: 'أنظمة الكاميرا السينمائية' },
  hologram: { letter: 'C', en: 'Holographic interfaces', ar: 'الواجهات الهولوغرافية' },
  glass: { letter: 'D', en: 'Luxury glass and material motion', ar: 'حركات الزجاج والمواد الفاخرة' },
  neural: { letter: 'E', en: 'AI and neural visualization', ar: 'تصوير الذكاء الاصطناعي والشبكات العصبية' },
  twin: { letter: 'F', en: 'Digital twin and spatial systems', ar: 'التوأم الرقمي والأنظمة المكانية' },
  particles: { letter: 'G', en: 'Advanced particle systems', ar: 'أنظمة الجسيمات المتقدمة' },
  lighting: { letter: 'H', en: 'Cinematic lighting', ar: 'الإضاءة السينمائية' },
  typography: { letter: 'I', en: 'Advanced typography', ar: 'الطباعة الحركية المتقدمة' },
  micro: { letter: 'J', en: 'Premium micro-interactions', ar: 'التفاعلات الدقيقة الفاخرة' },
  dashboard: { letter: 'K', en: 'Enterprise dashboard motion', ar: 'حركات لوحات المؤسسات' },
  transitions: { letter: 'L', en: 'Advanced page transitions', ar: 'انتقالات الصفحات المتقدمة' },
  physics: { letter: 'M', en: 'Physics and procedural motion', ar: 'الفيزياء والحركة الإجرائية' },
  shaders: { letter: 'N', en: 'Advanced shader systems', ar: 'أنظمة المظلِّلات المتقدمة' },
  icons: { letter: 'O', en: 'Interactive 3D icons', ar: 'الأيقونات ثلاثية الأبعاد التفاعلية' },
  product: { letter: 'P', en: 'Cinematic product presentation', ar: 'العرض السينمائي للمنتج' },
  networks: { letter: 'Q', en: 'Advanced spatial networks', ar: 'الشبكات المكانية المتقدمة' },
  atmosphere: { letter: 'R', en: 'Atmospheric and energy effects', ar: 'المؤثرات الجوية وتأثيرات الطاقة' },
  story: { letter: 'S', en: 'Executive storytelling', ar: 'السرد التنفيذي' },
  compositions: { letter: 'T', en: 'Ultra-advanced motion compositions', ar: 'التراكيب الحركية فائقة التقدم' },
});

const ID = /^[a-z][a-z0-9]*(?:-[a-z0-9]+)+$/;
const ARABIC = /[\u0600-\u06ff]/;
const fail = (id, message) => {
  throw new TypeError(`Motion ${id ?? '(no id)'}: ${message}`);
};

function numeric(id, name, spec) {
  const { default: value, min, max } = spec ?? {};
  if (![value, min, max].every(Number.isFinite) || min >= max || value < min || value > max) {
    fail(id, `parameter ${name} needs finite default, min and max with min <= default <= max`);
  }
  if (!spec.label || typeof spec.label.en !== 'string' || typeof spec.label.ar !== 'string') fail(id, `parameter ${name} needs label.en and label.ar`);
}

export function defineMotion(definition) {
  const d = definition ?? {};
  const id = d.id;
  if (typeof id !== 'string' || !ID.test(id)) fail(id, 'id must be kebab-case with a module prefix');
  if (!Object.hasOwn(MODULES, d.module) || !id.startsWith(d.module + '-')) fail(id, 'module must be a known key and prefix the id');
  if (!Number.isInteger(d.number) || d.number < 1) fail(id, 'number must be a positive integer');
  if (!d.name || typeof d.name.en !== 'string' || typeof d.name.ar !== 'string' || !ARABIC.test(d.name.ar)) fail(id, 'name.en and an Arabic name.ar are required');
  if (!ENGINES.includes(d.engine)) fail(id, `engine must be one of ${ENGINES.join(', ')}`);
  if (d.kind !== 'loop' && d.kind !== 'oneshot') fail(id, "kind must be 'loop' or 'oneshot'");
  if (!Number.isInteger(d.duration) || d.duration < 100 || d.duration > 120000) fail(id, 'duration must be an integer number of milliseconds from 100 to 120000');
  if (!EASINGS.includes(d.easing)) fail(id, `easing must be one of ${EASINGS.join(', ')}`);
  if (!Array.isArray(d.colors) || d.colors.length < 3 || d.colors.length > 5) fail(id, 'colors must list three to five hex colours: background first');
  d.colors.forEach(hexToRgb);
  const params = d.params ?? {};
  if (Object.keys(params).length < 2) fail(id, 'at least two configurable parameters are required');
  for (const [name, spec] of Object.entries(params)) numeric(id, name, spec);
  for (const [name, spec] of Object.entries(d.camera ?? {})) numeric(id, `camera.${name}`, spec);
  if (!['neutral', 'mirror', 'text'].includes(d.rtl)) fail(id, "rtl must be 'neutral', 'mirror' or 'text'");
  const needs = d.requirements ?? {};
  if (!['none', 'webgl2', 'webgpu'].includes(needs.gpu) || !['low', 'medium', 'high'].includes(needs.cost)) fail(id, "requirements needs gpu ('none' | 'webgl2' | 'webgpu') and cost ('low' | 'medium' | 'high')");
  if (!(d.still >= 0 && d.still <= 1)) fail(id, 'still must be the 0..1 progress shown under reduced motion');
  if (!Array.isArray(d.tags) || !d.tags.length || !d.tags.every((tag) => typeof tag === 'string')) fail(id, 'tags are required');
  if (typeof d.summary?.en !== 'string' || typeof d.summary?.ar !== 'string' || !ARABIC.test(d.summary.ar)) fail(id, 'summary.en and an Arabic summary.ar are required');
  if (d.text !== undefined) {
    const { en, ar } = d.text ?? {};
    const keys = Object.keys(en ?? {});
    const strings = (set) => set && Object.values(set).every((value) => typeof value === 'string' && value.length > 0 && value.length <= 200);
    if (!keys.length || !strings(en) || !strings(ar) || keys.join() !== Object.keys(ar).join()) fail(id, 'text needs en and ar with the same keys and non-empty strings');
    if (!Object.values(ar).some((value) => ARABIC.test(value))) fail(id, 'text.ar must be Arabic');
  }
  if (d.interactive !== undefined) {
    const sample = d.interactive?.sample;
    if (!sample || typeof sample !== 'object' || !Object.keys(sample).length) fail(id, 'interactive needs a sample input that visibly changes the frame');
    if (typeof d.interactive.note?.en !== 'string' || typeof d.interactive.note?.ar !== 'string') fail(id, 'interactive needs note.en and note.ar saying what the input does');
  }
  if (typeof d.setup !== 'function') fail(id, 'setup(ctx) is required');
  if (d.fallback !== undefined && typeof d.fallback !== 'function') fail(id, 'fallback must be a function');
  return Object.freeze({ ...d, params: Object.freeze(params), camera: Object.freeze(d.camera ?? {}) });
}

/** Thrown by setup() when the device lacks what the motion needs; the core then uses the fallback. */
export class Unsupported extends Error {
  constructor(what) {
    super(`${what} is not available`);
    this.unsupported = what;
  }
}
