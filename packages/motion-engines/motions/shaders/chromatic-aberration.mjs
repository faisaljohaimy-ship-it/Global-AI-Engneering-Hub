import { defineMotion } from '../../core/define.mjs';
import { fragment } from '../../engines/webgl.mjs';
import { centred, hash, rotate } from '../../shaders/chunks.mjs';

export default defineMotion({
  id: 'shaders-chromatic-aberration',
  number: 136,
  module: 'shaders',
  name: { en: 'Chromatic Aberration Transition', ar: 'انتقال الزيغ اللوني' },
  summary: {
    en: 'A target of rings hands over to a field of dots. During the cut the red, green and blue of the picture are pulled apart radially and slipped sideways in bands, then snap back together on the new scene.',
    ar: 'هدفٌ من الحلقات يسلّم مكانه لحقلٍ من النقاط. خلال القطع تنفصل مكوّنات الأحمر والأخضر والأزرق في الصورة شعاعيًّا وتنزلق جانبيًّا في شرائط، ثم تلتئم من جديد على المشهد الجديد.',
  },
  meaning: {
    en: 'System cut-over: the legacy interface switches to the new digital platform in one controlled glitch.',
    ar: 'التحوّل إلى النظام الجديد: تنتقل الواجهة القديمة إلى المنصّة الرقمية الجديدة في قطعٍ واحدٍ مضبوط.',
  },
  engine: 'webgl2-glsl',
  kind: 'oneshot',
  duration: 2400,
  easing: 'ease-in-out',
  colors: ['#05050a', '#f43f5e', '#22d3ee', '#facc15'],
  params: {
    strength: { default: 0.08, min: 0.01, max: 0.2, step: 0.01, label: { en: 'Colour split', ar: 'مقدار انفصال الألوان' } },
    bands: { default: 7, min: 0, max: 16, step: 1, label: { en: 'Glitch bands', ar: 'شرائط التشويش' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'webgl2', cost: 'low' },
  still: 1,
  tags: ['transition', 'glitch', 'cut', 'shader', 'rgb'],
  setup: fragment({
    fragment: `
uniform float u_strength;
uniform float u_bands;
${hash}${centred}${rotate}
vec3 rings(vec2 p) {
  float r = length(p);
  float band = smoothstep(0.1, 0.0, abs(fract(r * 4.0 - u_time * 0.3) - 0.5) - 0.18);
  float axes = smoothstep(0.012, 0.0, min(abs(p.x), abs(p.y))) * step(r, 0.95);
  return u_color0 + u_color1 * band * smoothstep(1.1, 0.2, r) + u_color3 * axes * 0.7;
}
vec3 dots(vec2 p) {
  vec2 q = rot(0.4) * p * 5.0;
  vec2 f = fract(q) - 0.5;
  float size = 0.18 + 0.14 * sin(floor(q.x) * 0.9 + floor(q.y) * 1.3 + u_time * 2.0);
  float disc = smoothstep(size, size - 0.05, length(f));
  return u_color0 + mix(u_color2, u_color3, hash21(floor(q))) * disc * smoothstep(1.6, 0.3, length(p));
}
vec3 scene(vec2 p, float mixAmount) {
  return mix(rings(p), dots(p), mixAmount);
}
void main() {
  vec2 p = centredUv();
  float cut = smoothstep(0.42, 0.58, u_progress);
  float shake = sin(3.14159265 * clamp(u_progress, 0.0, 1.0));
  shake *= shake;
  // Horizontal bands slip sideways by their own amount while the cut is on.
  float row = floor((p.y + 2.0) * u_bands * 0.5);
  float slip = (hash11(row + floor(u_progress * 12.0)) - 0.5) * step(0.5, u_bands) * shake * 0.35;
  vec2 q = p + vec2(slip, 0.0);
  vec2 radial = normalize(q + 1e-4) * u_strength * shake * (0.4 + length(q));
  vec3 colour;
  colour.r = scene(q + radial, cut).r;
  colour.g = scene(q, cut).g;
  colour.b = scene(q - radial, cut).b;
  outColor = vec4(colour, 1.0);
}`,
    uniforms: (ctx) => ({ u_strength: ctx.params.strength, u_bands: Math.round(ctx.params.bands) }),
  }),
});
