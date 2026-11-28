import { defineMotion } from '../../core/define.mjs';
import { points } from '../../engines/webgl.mjs';
import { hash } from '../../shaders/chunks.mjs';

export default defineMotion({
  id: 'particles-vortex',
  number: 66,
  module: 'particles',
  name: { en: 'Particle Vortex', ar: 'دوّامة الجسيمات' },
  summary: {
    en: 'A funnel of particles turns like a tornado seen from the side: wide and slow at the top, narrow and fast at the base, each grain climbing as it circles and the whole column swaying.',
    ar: 'قمعٌ من الجسيمات يدور كإعصارٍ يُرى من الجانب: عريضٌ بطيء في أعلاه، ضيّقٌ سريع عند قاعدته، كلّ حبّةٍ تصعد وهي تدور والعمود كلّه يتمايل.',
  },
  engine: 'webgl2-points',
  kind: 'loop',
  duration: 8000,
  easing: 'ease-out',
  colors: ['#05070d', '#a5f3fc', '#818cf8', '#f0abfc'],
  params: {
    spin: { default: 1, min: 0.2, max: 3, step: 0.1, label: { en: 'Spin speed', ar: 'سرعة الدوران' } },
    flare: { default: 1, min: 0.4, max: 1.8, step: 0.05, label: { en: 'Width of the funnel mouth', ar: 'اتساع فوهة القمع' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'webgl2', cost: 'medium' },
  still: 0.3,
  tags: ['particles', 'gpu', 'vortex', 'weather', 'hero', 'background'],
  setup: points({
    count: 12000,
    vertex: `
uniform float u_spin;
uniform float u_flare;
${hash}
void main() {
  float id = float(gl_VertexID);
  vec3 h = hash31(id * 0.917 + 11.0);
  // Height along the funnel climbs with time and wraps, so the column is always full.
  float y = fract(h.x + u_time * 0.06 * (0.6 + h.y));
  float radius = mix(0.06, 0.75 * u_flare, pow(y, 1.6)) * (0.8 + 0.4 * h.z);
  // Angular speed rises toward the narrow base, as in a real vortex.
  float angle = h.y * 6.2831853 + u_time * u_spin * (0.6 + 1.8 / (radius * 6.0 + 0.6));
  float sway = 0.12 * sin(y * 4.0 + u_time * 0.9) * y;
  vec3 pos = vec3(cos(angle) * radius + sway, mix(-0.85, 0.85, y), sin(angle) * radius);
  float perspective = 1.0 / (2.4 - pos.z);
  vec2 screen = vec2(pos.x, pos.y * 0.95) * perspective * 2.2 * (0.6 + 0.4 * u_intro);
  screen.x *= u_resolution.y / u_resolution.x;
  gl_Position = vec4(screen, 0.0, 1.0);
  gl_PointSize = max(1.0, (1.0 + 2.2 * h.z) * perspective * u_resolution.y / 120.0);
  float front = smoothstep(-0.6, 0.6, pos.z);
  vec3 colour = mix(u_color2, u_color1, front);
  colour = mix(colour, u_color3, smoothstep(0.75, 1.0, y) * h.z);
  v_color = vec4(colour, (0.18 + 0.5 * front) * u_intro);
}`,
    fragment: `
void main() {
  float falloff = smoothstep(0.5, 0.05, length(gl_PointCoord - 0.5));
  outColor = vec4(v_color.rgb, v_color.a * falloff);
}`,
    uniforms: (ctx) => ({ u_spin: ctx.params.spin, u_flare: ctx.params.flare }),
  }),
});
