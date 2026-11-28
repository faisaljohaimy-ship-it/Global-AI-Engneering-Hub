import { defineMotion } from '../../core/define.mjs';
import { points } from '../../engines/webgl.mjs';
import { hash } from '../../shaders/chunks.mjs';

export default defineMotion({
  id: 'quantum-probability-cloud',
  number: 8,
  module: 'quantum',
  name: { en: 'Quantum Probability Cloud', ar: 'سحابة الاحتمال الكمّية' },
  summary: {
    en: 'Thousands of points sample an orbital: dense near the nucleus, split into lobes by angular nodes, each one trembling.',
    ar: 'آلاف النقاط ترسم مدارًا ذريًا: كثيفة قرب النواة، منقسمة إلى فصوص بعُقد زاوية، وكل نقطة ترتجف.',
  },
  engine: 'webgl2-points',
  kind: 'loop',
  duration: 10000,
  easing: 'ease-out',
  colors: ['#04050d', '#67e8f9', '#f0abfc'],
  params: {
    lobes: { default: 2, min: 1, max: 4, step: 1, label: { en: 'Orbital lobes', ar: 'فصوص المدار' } },
    jitter: { default: 1, min: 0, max: 3, step: 0.1, label: { en: 'Uncertainty', ar: 'اللايقين' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'webgl2', cost: 'medium' },
  still: 0.5,
  tags: ['science', 'ambient', 'background', 'explainer'],
  setup: points({
    count: 9000,
    vertex: `
uniform float u_lobes;
uniform float u_jitter;
${hash}
void main() {
  float id = float(gl_VertexID);
  vec3 h = hash31(id * 0.731 + 1.0);
  vec3 k = hash31(id * 1.913 + 7.0);
  float radius = -log(1.0 - h.x * 0.97) * 0.21 + 0.03;
  float theta = h.y * 6.2831853 + u_raw * 6.2831853;
  float cosPhi = 2.0 * h.z - 1.0;
  float sinPhi = sqrt(1.0 - cosPhi * cosPhi);
  vec3 pos = radius * vec3(sinPhi * cos(theta), cosPhi, sinPhi * sin(theta));
  float node = pow(abs(cos(u_lobes * atan(pos.y, length(pos.xz)))), 2.0);
  pos += (k - 0.5) * u_jitter * 0.05 * sin(u_time * 4.0 + id);
  float perspective = 1.0 / (1.7 + pos.z);
  vec2 screen = pos.xy * perspective * 2.0;
  screen.x *= u_resolution.y / u_resolution.x;
  gl_Position = vec4(screen, 0.0, 1.0);
  gl_PointSize = max(1.0, (1.2 + 2.2 * k.y) * perspective * u_resolution.y / 100.0);
  v_color = vec4(mix(u_color1, u_color2, k.x), node * 0.75 * u_intro);
}`,
    fragment: `
void main() {
  float falloff = smoothstep(0.5, 0.0, length(gl_PointCoord - 0.5));
  outColor = vec4(v_color.rgb, v_color.a * falloff);
}`,
    uniforms: (ctx) => ({ u_lobes: ctx.params.lobes, u_jitter: ctx.params.jitter }),
  }),
});
