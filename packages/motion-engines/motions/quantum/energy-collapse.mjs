import { defineMotion } from '../../core/define.mjs';
import { points } from '../../engines/webgl.mjs';
import { hash } from '../../shaders/chunks.mjs';

export default defineMotion({
  id: 'quantum-energy-collapse',
  number: 2,
  module: 'quantum',
  name: { en: 'Quantum Energy Collapse', ar: 'انهيار الطاقة الكمّية' },
  summary: {
    en: 'A shell of particles spirals inward, each at its own pace, collapses to a point and bursts.',
    ar: 'قشرة من الجسيمات تلتفّ نحو الداخل كلٌّ بإيقاعه، تنهار إلى نقطة ثم تنفجر.',
  },
  engine: 'webgl2-points',
  kind: 'oneshot',
  duration: 2600,
  easing: 'ease-in-out',
  colors: ['#04060f', '#60a5fa', '#f472b6'],
  params: {
    spin: { default: 1, min: -2, max: 2, step: 0.1, label: { en: 'Spiral spin', ar: 'دوران اللولب' } },
    radius: { default: 0.8, min: 0.4, max: 1.2, step: 0.05, label: { en: 'Shell radius', ar: 'نصف قطر القشرة' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'webgl2', cost: 'medium' },
  still: 0.3,
  tags: ['reveal', 'transition', 'science', 'hero'],
  setup: points({
    count: 6000,
    vertex: `
uniform float u_spin;
uniform float u_radius;
${hash}
void main() {
  float id = float(gl_VertexID);
  vec3 h = hash31(id * 1.37 + 3.0);
  float theta = h.x * 6.2831853;
  float phi = acos(2.0 * h.y - 1.0);
  float fall = min(1.0, pow(u_progress / 0.82, 1.5 + h.z * 2.0));
  float burst = smoothstep(0.82, 1.0, u_progress);
  float r = u_radius * mix(1.0, 0.02, fall) + burst * (0.6 + h.z) * 1.1;
  theta += u_spin * fall * 6.0;
  vec3 pos = r * vec3(sin(phi) * cos(theta), cos(phi), sin(phi) * sin(theta));
  float perspective = 1.0 / (1.8 + pos.z);
  vec2 screen = pos.xy * perspective * 1.7;
  screen.x *= u_resolution.y / u_resolution.x;
  gl_Position = vec4(screen, 0.0, 1.0);
  gl_PointSize = max(1.0, (1.5 + 3.0 * h.z) * perspective * u_resolution.y / 90.0 * (1.0 + burst));
  float heat = min(1.0, fall * 0.8 + burst);
  v_color = vec4(mix(u_color1, u_color2, heat), (0.3 + 0.6 * heat) * (1.0 - burst * 0.7));
}`,
    fragment: `
void main() {
  float falloff = smoothstep(0.5, 0.0, length(gl_PointCoord - 0.5));
  outColor = vec4(v_color.rgb, v_color.a * falloff);
}`,
    uniforms: (ctx) => ({ u_spin: ctx.params.spin, u_radius: ctx.params.radius }),
  }),
});
