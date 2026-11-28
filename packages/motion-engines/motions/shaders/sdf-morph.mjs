import { defineMotion } from '../../core/define.mjs';
import { fragment } from '../../engines/webgl.mjs';
import { centred, rotate } from '../../shaders/chunks.mjs';

export default defineMotion({
  id: 'shaders-sdf-morph',
  number: 134,
  module: 'shaders',
  name: { en: 'Signed Distance Field Morph', ar: 'تحوّل حقل المسافة المؤشَّرة' },
  summary: {
    en: 'One shape keeps becoming the next: circle, rounded square, six-petal flower, five-point star. Its distance field is drawn outside as contour rings that bend with every morph, and a bright edge traces the outline.',
    ar: 'شكلٌ واحد يتحوّل باستمرار إلى ما يليه: دائرة، فمربّع مستدير، فزهرة سداسية البتلات، فنجمة خماسية. يُرسم حقل مسافته في الخارج حلقاتِ كنتورٍ تنثني مع كل تحوّل، وحافةٌ مضيئة تتتبّع حدوده.',
  },
  engine: 'webgl2-glsl',
  kind: 'loop',
  duration: 8000,
  easing: 'ease-in-out',
  colors: ['#070512', '#f472b6', '#fde68a', '#7c3aed'],
  params: {
    rings: { default: 9, min: 3, max: 18, step: 1, label: { en: 'Contour rings', ar: 'حلقات الكنتور' } },
    glow: { default: 0.03, min: 0.005, max: 0.1, step: 0.005, label: { en: 'Edge glow', ar: 'توهّج الحافة' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'webgl2', cost: 'low' },
  still: 0.6,
  tags: ['shape', 'morph', 'sdf', 'logo', 'background', 'loading'],
  setup: fragment({
    fragment: `
uniform float u_rings;
uniform float u_glow;
${centred}${rotate}
// Each shape is a radius as a function of the angle; the distance field is the gap to that outline.
float radiusOf(int shape, float a) {
  if (shape == 0) return 0.56;
  if (shape == 1) { float c = abs(cos(a)); float s = abs(sin(a)); return 0.5 / pow(pow(c, 5.0) + pow(s, 5.0), 0.2); }
  if (shape == 2) return 0.46 + 0.12 * cos(6.0 * a);
  return 0.38 + 0.26 * pow(0.5 + 0.5 * cos(5.0 * a), 2.2);
}
void main() {
  vec2 p = centredUv();
  float phase = u_raw * 4.0;
  int from = int(floor(phase)) % 4;
  int to = (from + 1) % 4;
  float blend = smoothstep(0.35, 0.95, fract(phase));
  vec2 q = rot(u_raw * 6.2831853 * 0.25 + 0.3 * sin(u_time * 0.7)) * p;
  float a = atan(q.y, q.x);
  float r = mix(radiusOf(from, a), radiusOf(to, a), blend) * (0.55 + 0.45 * u_intro);
  float d = (length(q) - r) * 0.8;
  vec3 colour = u_color0;
  // Outside: rings of equal distance, brighter near the shape.
  float band = abs(fract(d * u_rings) - 0.5);
  float ring = smoothstep(0.08, 0.0, band - 0.02) * exp(-max(d, 0.0) * 2.2) * step(0.0, d);
  colour += u_color3 * ring * 0.8;
  // Inside: a gradient from the edge to the core.
  float inside = smoothstep(0.004, -0.004, d);
  vec3 fill = mix(u_color1, u_color2, smoothstep(0.0, -0.45, d));
  colour = mix(colour, fill * (0.75 + 0.25 * cos(d * 40.0)), inside);
  colour += u_color2 * u_glow / (abs(d) + u_glow) * 0.6;
  outColor = vec4(colour, 1.0);
}`,
    uniforms: (ctx) => ({ u_rings: Math.round(ctx.params.rings), u_glow: ctx.params.glow }),
  }),
});
