import { defineMotion } from '../../core/define.mjs';
import { fragment } from '../../engines/webgl.mjs';
import { centred } from '../../shaders/chunks.mjs';

export default defineMotion({
  id: 'glass-lens-distortion',
  number: 40,
  module: 'glass',
  name: { en: 'Optical Lens Distortion', ar: 'تشوّه العدسة البصرية' },
  summary: {
    en: 'A mounted lens glides over a test chart of squares, rings and diagonals. Inside it the straight lines bow outward, then inward, as the lens breathes between barrel and pincushion distortion, and colours split toward its rim.',
    ar: 'عدسة في إطارها تنزلق فوق لوحة اختبار من مربعات وحلقات وأقطار. داخلها تنحني الخطوط المستقيمة إلى الخارج ثم إلى الداخل كلما تنقّلت العدسة بين التشوّه البرميلي والوسادي، وتنفصل الألوان قرب حافتها.',
  },
  engine: 'webgl2-glsl',
  kind: 'loop',
  duration: 9000,
  easing: 'ease-out',
  colors: ['#070b14', '#38bdf8', '#f472b6', '#fde68a'],
  params: {
    strength: { default: 0.8, min: 0.2, max: 1.2, step: 0.05, label: { en: 'Distortion', ar: 'شدّة التشوّه' } },
    aberration: { default: 0.5, min: 0, max: 1, step: 0.05, label: { en: 'Chromatic aberration', ar: 'الزيغ اللوني' } },
    density: { default: 6, min: 3, max: 12, step: 1, label: { en: 'Chart density', ar: 'كثافة اللوحة' } },
    size: { default: 0.62, min: 0.35, max: 0.8, step: 0.01, label: { en: 'Lens size', ar: 'حجم العدسة' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'webgl2', cost: 'low' },
  still: 0.35,
  tags: ['lens', 'optics', 'distortion', 'chromatic', 'magnifier', 'camera'],
  setup: fragment({
    fragment: `
uniform float u_strength;
uniform float u_aberration;
uniform float u_density;
uniform float u_size;
${centred}
// The test chart: a chequered grid, rings around the middle and the two diagonals.
vec3 chart(vec2 p) {
  float px = 2.0 / min(u_resolution.x, u_resolution.y);
  vec2 g = p * u_density * 0.5; vec2 f = abs(fract(g) - 0.5); vec2 cell = floor(g);
  float thick = max(0.04, px * u_density * 0.5);
  float line = smoothstep(thick, thick * 0.4, 0.5 - max(f.x, f.y));
  vec3 colour = u_color0 + u_color1 * 0.1 * mod(cell.x + cell.y, 2.0);
  colour = mix(colour, u_color1, line * 0.85);
  colour = mix(colour, u_color2, smoothstep(0.024, 0.008, abs(fract(length(p) * 2.0 + 0.5) - 0.5) * 0.5) * 0.9);
  return mix(colour, u_color3, smoothstep(0.02, 0.006, min(abs(p.x - p.y), abs(p.x + p.y)) * 0.7071) * 0.6);
}
void main() {
  vec2 p = centredUv();
  vec2 span = u_resolution / min(u_resolution.x, u_resolution.y);
  float a = u_raw * 6.2831853;
  float radius = u_size * mix(0.55, 1.0, u_intro);
  vec2 centre = span * 0.3 * vec2(cos(a), sin(2.0 * a));
  vec2 d = (p - centre) / radius; float r2 = dot(d, d); float r = sqrt(r2);
  float edge = 1.5 / (radius * min(u_resolution.x, u_resolution.y));
  // Outside the mount: the chart as it is, under the shadow of the lens.
  vec3 colour = chart(p) * (1.0 - 0.45 * smoothstep(1.3, 0.95, length(d - vec2(0.07, -0.11))));
  // Inside: every point shows the chart from further out or further in, by an amount that grows with the
  // square of its distance from the axis. Each colour is bent a little differently.
  float k = u_strength * cos(a + 0.6);
  vec3 seen;
  for (int c = 0; c < 3; c++) {
    float kc = k + (float(c) - 1.0) * 0.12 * u_aberration;
    seen[c] = chart(centre + d * radius * 0.82 * max(1.0 + kc * min(r2, 1.0), 0.05))[c];
  }
  seen *= 1.0 - 0.4 * r2 * r2;
  float arc = smoothstep(0.035, 0.0, abs(length(d - vec2(0.2, -0.24)) - 1.02)) * smoothstep(0.1, 0.6, dot(d, vec2(-0.64, 0.77)));
  seen += u_color3 * 0.55 * arc + u_color1 * 0.05;
  colour = mix(colour, seen, smoothstep(edge, -edge, r - 1.0));
  // The mount: a metal ring, brightest where it faces the light.
  float ring = smoothstep(edge, -edge, abs(r - 1.045) - 0.045);
  float facing = dot(d / max(r, 1e-4), vec2(-0.6, 0.8));
  colour = mix(colour, u_color3 * (0.3 + 0.7 * facing * facing) * (0.75 + 0.25 * smoothstep(0.045, 0.0, abs(r - 1.045))), ring);
  outColor = vec4(colour, 1.0);
}`,
    uniforms: (ctx) => ({ u_strength: ctx.params.strength, u_aberration: ctx.params.aberration, u_density: ctx.params.density, u_size: ctx.params.size }),
  }),
});
