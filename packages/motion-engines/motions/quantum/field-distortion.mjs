import { defineMotion } from '../../core/define.mjs';
import { fragment } from '../../engines/webgl.mjs';
import { fbm, hash, noise } from '../../shaders/chunks.mjs';

export default defineMotion({
  id: 'quantum-field-distortion',
  number: 1,
  module: 'quantum',
  name: { en: 'Quantum Field Distortion', ar: 'تشوّه الحقل الكمّي' },
  summary: {
    en: 'A lattice of field lines bends toward two wandering potential wells and ripples with noise.',
    ar: 'شبكة من خطوط الحقل تنحني نحو بئرَي جهد متحركين وتتموّج بضجيج ناعم.',
  },
  engine: 'webgl2-glsl',
  kind: 'loop',
  duration: 9000,
  easing: 'ease-out',
  colors: ['#050816', '#38bdf8', '#a78bfa'],
  params: {
    strength: { default: 1, min: 0, max: 2, step: 0.05, label: { en: 'Distortion strength', ar: 'شدة التشوّه' } },
    density: { default: 6, min: 3, max: 12, step: 1, label: { en: 'Lattice density', ar: 'كثافة الشبكة' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'webgl2', cost: 'medium' },
  still: 0.4,
  tags: ['background', 'hero', 'science', 'ambient'],
  setup: fragment({
    fragment: `
uniform float u_strength;
uniform float u_density;
${hash}${noise}${fbm}
void main() {
  vec2 p = (2.0 * gl_FragCoord.xy - u_resolution) / min(u_resolution.x, u_resolution.y);
  float t = u_time * 0.7;
  vec2 wells[2] = vec2[2](vec2(cos(t) * 0.7, sin(t * 1.3) * 0.4), vec2(cos(t * 0.7 + 2.0) * 0.6, sin(t * 0.9 + 1.0) * 0.5));
  vec2 q = p;
  float glow = 0.0;
  for (int i = 0; i < 2; i++) {
    vec2 d = p - wells[i];
    float pull = u_strength * 0.09 / (0.08 + dot(d, d));
    q -= normalize(d + 1e-4) * pull * 0.5;
    glow += u_strength * 0.012 / (0.01 + dot(d, d));
  }
  q += (vec2(fbm(p * 1.5 + t * 0.4), fbm(p * 1.5 - t * 0.4 + 7.0)) - 0.5) * 0.3 * u_strength;
  vec2 cell = fract(q * u_density * 0.5);
  vec2 edge = min(cell, 1.0 - cell);
  float line = smoothstep(0.07, 0.0, min(edge.x, edge.y));
  vec3 colour = u_color0 + (u_color1 * line * 0.9 + u_color2 * min(glow, 1.5)) * u_intro;
  outColor = vec4(colour, 1.0);
}`,
    uniforms: (ctx) => ({ u_strength: ctx.params.strength, u_density: ctx.params.density }),
  }),
});
