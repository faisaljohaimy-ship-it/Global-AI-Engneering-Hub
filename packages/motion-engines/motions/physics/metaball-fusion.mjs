import { defineMotion } from '../../core/define.mjs';
import { fragment } from '../../engines/webgl.mjs';
import { centred, hash } from '../../shaders/chunks.mjs';

export default defineMotion({
  id: 'physics-metaball-fusion',
  number: 130,
  module: 'physics',
  name: { en: 'Metaball Surface Fusion', ar: 'اندماج أسطح الكرات المعدنية' },
  summary: {
    en: 'Molten blobs wander on their own orbits. When two come close their fields add up and a glowing neck of hotter material bridges them, then stretches and snaps as they part. The surface is lit as a raised, glossy mass.',
    ar: 'كتلٌ منصهرة تهيم في مداراتٍ خاصة بها. حين تقترب اثنتان تتجمّع حقولهما فيصل بينهما عنقٌ متوهّج من مادةٍ أسخن، ثم يتمدّد وينقطع حين تفترقان. يُضاء السطح ككتلةٍ بارزة لامعة.',
  },
  engine: 'webgl2-glsl',
  kind: 'loop',
  duration: 11000,
  easing: 'ease-out',
  colors: ['#0a0507', '#ef4444', '#fbbf24', '#fff7ed'],
  params: {
    blobs: { default: 6, min: 3, max: 10, step: 1, label: { en: 'Blobs', ar: 'عدد الكتل' } },
    threshold: { default: 1, min: 0.6, max: 1.6, step: 0.05, label: { en: 'Surface level (thinner when higher)', ar: 'مستوى السطح (أنحف كلما ارتفع)' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'webgl2', cost: 'low' },
  still: 0.35,
  tags: ['physics', 'fluid', 'organic', 'background', 'loading'],
  setup: fragment({
    fragment: `
uniform float u_blobs;
uniform float u_threshold;
${hash}${centred}
// Field of all blobs at p; also returns the two largest single contributions for the neck glow.
float field(vec2 p, out vec2 top) {
  float sum = 0.0; top = vec2(0.0);
  for (int i = 0; i < 10; i++) {
    if (float(i) >= u_blobs) break;
    vec3 h = hash31(float(i) * 2.71 + 5.0);
    float tt = u_time * (0.25 + 0.35 * h.z);
    vec2 c = vec2(sin(tt * 1.3 + h.x * 6.28) * 0.95, cos(tt * 1.7 + h.y * 6.28) * 0.6);
    float r = (0.16 + 0.12 * h.z) * (0.4 + 0.6 * u_intro);
    float v = r * r / (dot(p - c, p - c) + 1e-4);
    sum += v;
    if (v > top.x) { top.y = top.x; top.x = v; } else if (v > top.y) top.y = v;
  }
  return sum;
}
void main() {
  vec2 p = centredUv();
  vec2 top; vec2 unused;
  float f = field(p, top);
  // The gradient of the field gives a surface normal for lighting the blobs as a raised mass.
  float e = 0.004;
  float fx = field(p + vec2(e, 0.0), unused) - field(p - vec2(e, 0.0), unused);
  float fy = field(p + vec2(0.0, e), unused) - field(p - vec2(0.0, e), unused);
  vec3 n = normalize(vec3(-fx, -fy, 0.06 * f));
  vec3 colour = u_color0 + u_color1 * 0.06 * smoothstep(1.2, 0.0, length(p));
  float inside = smoothstep(u_threshold - 0.04, u_threshold + 0.04, f);
  // Where two blobs share the surface (the second contribution is large), the material runs hot.
  float neck = smoothstep(0.15, 0.6, top.y / max(top.x, 1e-4)) * smoothstep(0.2, 0.9, top.y * 3.0);
  vec3 light = normalize(vec3(-0.5, 0.6, 0.8));
  float diffuse = max(dot(n, light), 0.0);
  float spec = pow(max(dot(reflect(-light, n), vec3(0.0, 0.0, 1.0)), 0.0), 30.0);
  vec3 body = mix(u_color1, u_color2, neck) * (0.35 + 0.75 * diffuse) + u_color3 * spec * 0.8;
  colour = mix(colour, body, inside);
  // A faint halo of heat around the surface.
  colour += u_color1 * smoothstep(u_threshold * 0.5, u_threshold, f) * (1.0 - inside) * 0.25;
  outColor = vec4(colour, 1.0);
}`,
    uniforms: (ctx) => ({ u_blobs: Math.round(ctx.params.blobs), u_threshold: ctx.params.threshold }),
  }),
});
