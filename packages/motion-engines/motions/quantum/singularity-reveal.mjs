import { defineMotion } from '../../core/define.mjs';
import { fragment } from '../../engines/webgl.mjs';
import { hash } from '../../shaders/chunks.mjs';

export default defineMotion({
  id: 'quantum-singularity-reveal',
  number: 7,
  module: 'quantum',
  name: { en: 'Quantum Singularity Reveal', ar: 'انكشاف التفرّد الكمّي' },
  summary: {
    en: 'A singularity opens in a star field, bends the stars around it, lights an accretion ring, then releases a wave that reveals the scene.',
    ar: 'تفرّد ينفتح في حقل نجمي، يحني النجوم حوله ويشعل حلقة تراكم، ثم يطلق موجة تكشف المشهد.',
  },
  engine: 'webgl2-glsl',
  kind: 'oneshot',
  duration: 3600,
  easing: 'ease-in-out',
  colors: ['#020308', '#fb923c', '#38bdf8'],
  params: {
    mass: { default: 1, min: 0.4, max: 2, step: 0.05, label: { en: 'Lens strength', ar: 'قوة العدسة' } },
    ring: { default: 0.05, min: 0.02, max: 0.12, step: 0.005, label: { en: 'Ring thickness', ar: 'سماكة الحلقة' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'webgl2', cost: 'medium' },
  still: 0.55,
  tags: ['reveal', 'hero', 'transition', 'cinematic'],
  setup: fragment({
    fragment: `
uniform float u_mass;
uniform float u_ring;
${hash}
void main() {
  vec2 p = (2.0 * gl_FragCoord.xy - u_resolution) / min(u_resolution.x, u_resolution.y);
  float r = length(p);
  float open = smoothstep(0.0, 0.45, u_progress);
  float horizon = 0.2 * sqrt(u_mass) * open;
  vec2 lensed = p * (1.0 - u_mass * horizon * horizon * 1.6 / (r * r + 0.002));
  vec2 cell = floor(lensed * 26.0);
  vec2 inside = fract(lensed * 26.0) - 0.5;
  vec2 jitter = hash22(cell) - 0.5;
  float star = step(0.9, hash21(cell + 3.0)) * smoothstep(0.16, 0.0, length(inside - jitter * 0.6));
  float disc = smoothstep(horizon, horizon * 0.92, r);
  float ringAt = horizon * 1.7;
  float ring = exp(-pow((r - ringAt) / (u_ring * (0.4 + open)), 2.0)) * open;
  float wave = smoothstep(0.5, 1.0, u_progress) * 2.4;
  float front = exp(-pow((r - wave) / 0.12, 2.0)) * step(0.5, u_progress);
  float revealed = smoothstep(wave, wave - 0.3, r) * step(0.5, u_progress);
  vec3 colour = u_color0 + vec3(star) * (1.0 - disc) + u_color1 * ring * 1.4;
  colour = mix(colour, mix(u_color0, u_color2, 0.35 + 0.65 * smoothstep(1.6, 0.0, r)), revealed * (1.0 - disc * 0.7));
  colour += u_color2 * front;
  outColor = vec4(colour * (1.0 - disc * (1.0 - revealed * 0.3)), 1.0);
}`,
    uniforms: (ctx) => ({ u_mass: ctx.params.mass, u_ring: ctx.params.ring }),
  }),
});
