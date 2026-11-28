import { defineMotion } from '../../core/define.mjs';
import { fragment } from '../../engines/webgl.mjs';
import { centred, fbm, hash, noise } from '../../shaders/chunks.mjs';

export default defineMotion({
  id: 'shaders-material-dissolve',
  number: 140,
  module: 'shaders',
  name: { en: 'Shader-based Material Dissolve', ar: 'ذوبان المادة بالمظلِّل' },
  summary: {
    en: 'A riveted steel panel burns away in noisy islands from the middle out. A glowing rim and drifting embers ride the burning edge, and a lit circuit board shows through the holes until the panel is gone.',
    ar: 'لوحٌ فولاذيّ مثبَّت بالمسامير يحترق ويتلاشى في جزرٍ متعرّجة من الوسط إلى الخارج. حافةٌ متوهّجة وجمراتٌ هائمة تركب حدّ الاحتراق، ولوحةُ دوائر مضيئة تظهر من الثقوب حتى يختفي اللوح كلّه.',
  },
  meaning: {
    en: 'Legacy modernisation: the old metal layer burns away to reveal the live digital circuitry beneath it.',
    ar: 'تحديث الأنظمة القديمة: تحترق الطبقة المعدنية القديمة لتكشف الدوائر الرقمية الحيّة تحتها.',
  },
  engine: 'webgl2-glsl',
  kind: 'oneshot',
  duration: 3400,
  easing: 'ease-in-out',
  colors: ['#060912', '#38bdf8', '#fb923c', '#fde047', '#64748b'],
  params: {
    grain: { default: 3, min: 1, max: 7, step: 0.5, label: { en: 'Size of the burn islands (smaller with more)', ar: 'حجم جزر الاحتراق (تصغر كلما زادت)' } },
    edge: { default: 0.07, min: 0.02, max: 0.2, step: 0.01, label: { en: 'Width of the burning edge', ar: 'عرض حدّ الاحتراق' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'webgl2', cost: 'low' },
  still: 0.55,
  tags: ['transition', 'dissolve', 'reveal', 'shader', 'material'],
  setup: fragment({
    fragment: `
uniform float u_grain;
uniform float u_edge;
${hash}${noise}${fbm}${centred}
// The material underneath: a dark board with lit traces and pads.
vec3 board(vec2 p) {
  vec2 cell = floor(p * 6.0); vec2 f = fract(p * 6.0) - 0.5;
  float h = hash21(cell);
  float trace = h < 0.5 ? smoothstep(0.06, 0.0, abs(f.y)) : smoothstep(0.06, 0.0, abs(f.x));
  float pad = smoothstep(0.16, 0.1, length(f)) * step(0.7, h);
  float pulse = 0.5 + 0.5 * sin(u_time * 3.0 + h * 20.0);
  return u_color0 * 1.3 + u_color1 * (trace * 0.45 + pad * (0.6 + 0.4 * pulse));
}
// The material on top: brushed steel plates with rivets at the corners.
vec3 steel(vec2 p) {
  vec2 plate = fract(p * 1.6) - 0.5;
  float seam = smoothstep(0.49, 0.47, max(abs(plate.x), abs(plate.y)));
  float brush = noise(vec2(p.x * 2.0, p.y * 90.0)) * 0.25;
  vec2 corner = abs(plate) - 0.4;
  float rivet = smoothstep(0.035, 0.02, length(corner));
  vec3 base = u_color4 * (0.55 + brush + 0.15 * p.y) * (0.55 + 0.45 * seam);
  return base + u_color4 * rivet * 0.5;
}
void main() {
  vec2 p = centredUv();
  float n = fbm(p * u_grain + 3.1);
  // The burn starts at the middle and spreads; the noise breaks the front into islands.
  float front = u_progress * 1.9 - 0.15;
  float field = length(p) * 0.55 + n * 0.75;
  float burnt = field - front;
  vec3 colour = board(p);
  if (burnt > 0.0) {
    colour = steel(p);
    // Heat discolours the metal just ahead of the edge.
    colour = mix(colour, u_color2 * 0.6, smoothstep(u_edge * 3.0, 0.0, burnt) * 0.5);
  }
  float rim = smoothstep(u_edge, 0.0, abs(burnt));
  colour += mix(u_color2, u_color3, rim * rim) * rim * 1.4 * step(u_progress, 0.995);
  // Embers lifted from the edge drift upward and cool.
  vec2 cell = floor(vec2(p.x * 22.0, p.y * 22.0 - u_time * 3.0));
  float spark = hash21(cell);
  vec2 inside = fract(vec2(p.x * 22.0, p.y * 22.0 - u_time * 3.0)) - 0.5;
  float ember = step(0.93, spark) * smoothstep(0.2, 0.0, length(inside)) * smoothstep(u_edge * 5.0, 0.0, abs(burnt + 0.05));
  colour += u_color3 * ember;
  outColor = vec4(colour, 1.0);
}`,
    uniforms: (ctx) => ({ u_grain: ctx.params.grain, u_edge: ctx.params.edge }),
  }),
});
