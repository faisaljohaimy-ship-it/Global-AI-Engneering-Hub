import { defineMotion } from '../../core/define.mjs';
import { points } from '../../engines/webgl.mjs';
import { computeParticles } from '../../engines/webgpu.mjs';
import { hash } from '../../shaders/chunks.mjs';

// The same closed-form flow twice: WGSL for the compute shader, GLSL for the fallback.
// Particles stream along a torus knot; each one's place is a function of its id and the time.
const simulate = `
fn simulate(id: u32, f: Frame) -> Particle {
  let n = f32(id);
  let h = hash31(n * 1.37 + 3.0);
  let winding = f.params[0].x;
  let spread = f.params[0].y;
  let u = (h.x + f.time * 0.05 * (0.6 + h.y)) * 6.2831853;
  let ring = 0.62 + 0.26 * cos(winding * u);
  var pos = vec3f(ring * cos(2.0 * u), 0.26 * sin(winding * u), ring * sin(2.0 * u));
  let around = h.z * 6.2831853 + f.time * 0.8;
  let tube = spread * (0.02 + 0.1 * hash11(n * 7.13));
  pos = pos + tube * vec3f(cos(around) * cos(2.0 * u), sin(around), cos(around) * sin(2.0 * u));
  let turn = f.time * 0.25;
  let x1 = pos.x * cos(turn) + pos.z * sin(turn);
  let z1 = -pos.x * sin(turn) + pos.z * cos(turn);
  let y2 = pos.y * 0.8776 - z1 * 0.4794;
  let z2 = pos.y * 0.4794 + z1 * 0.8776;
  let perspective = 1.0 / (2.2 + z2);
  var screen = vec2f(x1, y2) * perspective * 2.0 * (0.4 + 0.6 * f.intro);
  screen.x = screen.x * f.resolution.y / f.resolution.x;
  let heat = 0.5 + 0.5 * sin(winding * u + f.time);
  var particle: Particle;
  particle.position = screen;
  particle.size = max(1.5, (0.8 + 1.8 * h.y) * perspective * f.resolution.y / 70.0);
  particle.color = vec4f(mix(f.color1.rgb, f.color2.rgb, heat), (0.1 + 0.3 * heat) * f.intro);
  return particle;
}`;

const fallbackVertex = `
uniform float u_winding;
uniform float u_spread;
${hash}
void main() {
  float n = float(gl_VertexID);
  vec3 h = hash31(n * 1.37 + 3.0);
  float u = (h.x + u_time * 0.05 * (0.6 + h.y)) * 6.2831853;
  float ring = 0.62 + 0.26 * cos(u_winding * u);
  vec3 pos = vec3(ring * cos(2.0 * u), 0.26 * sin(u_winding * u), ring * sin(2.0 * u));
  float around = h.z * 6.2831853 + u_time * 0.8;
  float tube = u_spread * (0.02 + 0.1 * hash11(n * 7.13));
  pos += tube * vec3(cos(around) * cos(2.0 * u), sin(around), cos(around) * sin(2.0 * u));
  float turn = u_time * 0.25;
  float x1 = pos.x * cos(turn) + pos.z * sin(turn);
  float z1 = -pos.x * sin(turn) + pos.z * cos(turn);
  float y2 = pos.y * 0.8776 - z1 * 0.4794;
  float z2 = pos.y * 0.4794 + z1 * 0.8776;
  float perspective = 1.0 / (2.2 + z2);
  vec2 screen = vec2(x1, y2) * perspective * 2.0 * (0.4 + 0.6 * u_intro);
  screen.x *= u_resolution.y / u_resolution.x;
  float heat = 0.5 + 0.5 * sin(u_winding * u + u_time);
  gl_Position = vec4(screen, 0.0, 1.0);
  gl_PointSize = max(1.5, (0.8 + 1.8 * h.y) * perspective * u_resolution.y / 70.0);
  v_color = vec4(mix(u_color1, u_color2, heat), (0.1 + 0.3 * heat) * u_intro);
}`;

export default defineMotion({
  id: 'shaders-wgsl-compute-particles',
  number: 132,
  module: 'shaders',
  name: { en: 'WGSL Compute Particle Motion', ar: 'حركة الجسيمات بمظلِّل الحساب WGSL' },
  summary: {
    en: 'Nine thousand particles stream along a torus knot. A WGSL compute shader places every one on the GPU each frame; where WebGPU is missing the same flow runs in a WebGL2 vertex shader.',
    ar: 'تسعة آلاف جسيم تنساب على عقدة حلقية. يحدّد مظلِّل الحساب WGSL موضع كل جسيم على المعالج الرسومي في كل إطار، وحيث لا يتوفر WebGPU يعمل الانسياب نفسه في مظلِّل رؤوس WebGL2.',
  },
  engine: 'webgpu-wgsl',
  kind: 'loop',
  duration: 9000,
  easing: 'ease-out',
  colors: ['#04050d', '#38bdf8', '#f0abfc'],
  params: {
    winding: { default: 3, min: 1, max: 7, step: 1, label: { en: 'Knot windings', ar: 'عدد لفّات العقدة' } },
    spread: { default: 1, min: 0.2, max: 2.5, step: 0.1, label: { en: 'Stream width', ar: 'عرض التيار' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'webgpu', cost: 'high' },
  still: 0.3,
  tags: ['particles', 'gpu', 'compute', 'hero', 'background'],
  setup: computeParticles({ count: 9000, simulate, values: (ctx) => [ctx.params.winding, ctx.params.spread] }),
  fallback: points({
    count: 9000,
    vertex: fallbackVertex,
    fragment: `
void main() {
  float falloff = smoothstep(0.5, 0.0, length(gl_PointCoord - 0.5));
  outColor = vec4(v_color.rgb, v_color.a * falloff);
}`,
    uniforms: (ctx) => ({ u_winding: ctx.params.winding, u_spread: ctx.params.spread }),
  }),
});
