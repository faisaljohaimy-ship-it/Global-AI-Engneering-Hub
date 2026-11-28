import { defineMotion } from '../../core/define.mjs';
import { fragment } from '../../engines/webgl.mjs';

export default defineMotion({
  id: 'quantum-light-tunnel',
  number: 6,
  module: 'quantum',
  name: { en: 'Quantum Light Tunnel', ar: 'نفق الضوء الكمّي' },
  summary: {
    en: 'An endless tunnel of light rings rushes toward the viewer while its ribs twist with depth.',
    ar: 'نفق لا ينتهي من حلقات الضوء يندفع نحو المشاهد وأضلاعه تلتوي مع العمق.',
  },
  engine: 'webgl2-glsl',
  kind: 'loop',
  duration: 6000,
  easing: 'ease-out',
  colors: ['#03040c', '#7dd3fc', '#c084fc'],
  params: {
    speed: { default: 1, min: 0.2, max: 3, step: 0.1, label: { en: 'Travel speed', ar: 'سرعة الانتقال' } },
    twist: { default: 1, min: -3, max: 3, step: 0.1, label: { en: 'Twist', ar: 'الالتواء' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'webgl2', cost: 'low' },
  still: 0.3,
  tags: ['background', 'hero', 'transition', 'immersive'],
  setup: fragment({
    fragment: `
uniform float u_speed;
uniform float u_twist;
void main() {
  vec2 p = (2.0 * gl_FragCoord.xy - u_resolution) / min(u_resolution.x, u_resolution.y);
  float r = length(p);
  float depth = 0.4 / (r + 0.03) + u_time * u_speed;
  float angle = atan(p.y, p.x) + u_twist * 0.25 * depth;
  float rings = smoothstep(0.55, 1.0, sin(depth * 6.2831853) * 0.5 + 0.5);
  float ribs = smoothstep(0.8, 1.0, sin(angle * 8.0) * 0.5 + 0.5);
  float fade = smoothstep(0.02, 0.7, r);
  vec3 colour = u_color1 * rings * fade + u_color2 * ribs * fade * 0.7;
  colour += u_color1 * 0.25 / (1.0 + 40.0 * r * r);
  outColor = vec4(mix(u_color0, u_color0 + colour, u_intro), 1.0);
}`,
    uniforms: (ctx) => ({ u_speed: ctx.params.speed, u_twist: ctx.params.twist }),
  }),
});
