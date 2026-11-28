import { defineMotion } from '../../core/define.mjs';
import { points } from '../../engines/webgl.mjs';
import { hash } from '../../shaders/chunks.mjs';

export default defineMotion({
  id: 'particles-gpu-swarm',
  number: 61,
  module: 'particles',
  name: { en: 'GPU Particle Swarm', ar: 'سرب الجسيمات على المعالج الرسومي' },
  summary: {
    en: 'A swarm of fifteen thousand points chases a leader along a looping path. Each point keeps its own offset from the leader and lags by its distance, so the swarm stretches on turns, bunches on straights and splits into three streams.',
    ar: 'سربٌ من خمسة عشر ألف نقطة يطارد قائدًا على مسارٍ ملتفّ. تحافظ كل نقطة على إزاحتها الخاصة عن القائد وتتأخر بقدر بُعدها عنه، فيتمدّد السرب في المنعطفات ويتجمّع على المستقيمات وينقسم ثلاثة تيارات.',
  },
  engine: 'webgl2-points',
  kind: 'loop',
  duration: 10000,
  easing: 'ease-out',
  colors: ['#030712', '#34d399', '#fbbf24', '#e879f9'],
  params: {
    lag: { default: 1, min: 0.2, max: 2.5, step: 0.05, label: { en: 'Lag behind the leader', ar: 'التأخّر خلف القائد' } },
    streams: { default: 3, min: 1, max: 6, step: 1, label: { en: 'Streams', ar: 'عدد التيارات' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'webgl2', cost: 'medium' },
  still: 0.45,
  tags: ['particles', 'gpu', 'swarm', 'flock', 'background', 'hero'],
  setup: points({
    count: 15000,
    vertex: `
uniform float u_lag;
uniform float u_streams;
${hash}
// The leader's path: a three-lobed loop through depth.
vec3 path(float t) { return vec3(sin(t) * 0.95 + 0.25 * sin(3.0 * t), cos(1.5 * t) * 0.5, sin(2.0 * t) * 0.6); }
void main() {
  float id = float(gl_VertexID);
  vec3 h = hash31(id * 1.731 + 4.0);
  float stream = floor(h.x * u_streams);
  float delay = u_lag * (0.05 + 0.9 * h.y * h.y) + stream * 0.6;
  float t = u_time * 0.55 - delay;
  vec3 lead = path(t);
  vec3 ahead = path(t + 0.05);
  vec3 forward = normalize(ahead - lead + 1e-5);
  vec3 side = normalize(cross(forward, vec3(0.0, 1.0, 0.0)) + 1e-5);
  vec3 up = cross(side, forward);
  float around = h.z * 6.2831853 + u_time * (1.0 + h.x);
  float spread = 0.03 + 0.16 * h.y;
  vec3 pos = lead + (side * cos(around) + up * sin(around)) * spread;
  float perspective = 1.0 / (2.3 - pos.z);
  vec2 screen = pos.xy * perspective * 2.1 * (0.5 + 0.5 * u_intro);
  screen.x *= u_resolution.y / u_resolution.x;
  gl_Position = vec4(screen, 0.0, 1.0);
  gl_PointSize = max(1.0, (0.8 + 1.6 * h.z) * perspective * u_resolution.y / 110.0);
  vec3 colour = mod(stream, 3.0) < 1.0 ? u_color1 : (mod(stream, 3.0) < 2.0 ? u_color2 : u_color3);
  v_color = vec4(colour, (0.55 - 0.4 * h.y) * u_intro);
}`,
    fragment: `
void main() {
  float falloff = smoothstep(0.5, 0.0, length(gl_PointCoord - 0.5));
  outColor = vec4(v_color.rgb, v_color.a * falloff);
}`,
    uniforms: (ctx) => ({ u_lag: ctx.params.lag, u_streams: Math.round(ctx.params.streams) }),
  }),
});
