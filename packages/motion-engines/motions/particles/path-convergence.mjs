import { defineMotion } from '../../core/define.mjs';
import { points } from '../../engines/webgl.mjs';
import { hash } from '../../shaders/chunks.mjs';

export default defineMotion({
  id: 'particles-path-convergence',
  number: 69,
  module: 'particles',
  name: { en: 'Particle Path Convergence', ar: 'تقارب مسارات الجسيمات' },
  summary: {
    en: 'Particles set out from the whole edge of the frame along curved paths that bend toward one point. They speed up as the paths gather, trace bright threads where they bunch, and pile into a glowing core when they arrive.',
    ar: 'تنطلق الجسيمات من حافة الإطار كلّها على مساراتٍ منحنية تنثني نحو نقطةٍ واحدة. تتسارع كلما تجمّعت المسارات، وترسم خيوطًا مضيئة حيث تتكاثف، وتتراكم في نواةٍ متوهّجة عند وصولها.',
  },
  meaning: {
    en: 'Data from many separate sources converges into one unified platform.',
    ar: 'بياناتٌ من مصادر متفرّقة كثيرة تتقارب لتصبّ في منصّةٍ موحّدة واحدة.',
  },
  engine: 'webgl2-points',
  kind: 'oneshot',
  duration: 3200,
  easing: 'ease-in-out',
  colors: ['#04040a', '#38bdf8', '#c4b5fd', '#fef9c3'],
  params: {
    bend: { default: 1, min: -2, max: 2, step: 0.1, label: { en: 'Bend of the paths', ar: 'انحناء المسارات' } },
    paths: { default: 24, min: 6, max: 60, step: 1, label: { en: 'Paths', ar: 'عدد المسارات' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'webgl2', cost: 'medium' },
  still: 0.95,
  tags: ['particles', 'gpu', 'convergence', 'reveal', 'logo', 'focus'],
  setup: points({
    count: 12000,
    vertex: `
uniform float u_bend;
uniform float u_paths;
${hash}
void main() {
  float id = float(gl_VertexID);
  vec3 h = hash31(id * 0.773 + 9.0);
  // Every particle belongs to one path; a path starts at a point on a wide ellipse around the frame.
  float path = floor(h.x * u_paths);
  float a = (path + 0.5) / u_paths * 6.2831853 + 0.2;
  vec2 start = vec2(cos(a) * 1.9, sin(a) * 1.15);
  vec2 normal = vec2(-start.y, start.x) * 0.5;
  // Particles of one path leave one after another and arrive late in the shot.
  float leave = h.y * 0.55;
  float s = clamp((u_progress - leave) / (1.0 - leave * 0.8), 0.0, 1.0);
  float eased = s * s * (3.0 - 2.0 * s);
  vec2 control = start * 0.45 + normal * u_bend * (0.6 + 0.4 * hash11(path));
  // Each particle comes to rest at its own place inside the core, a disc that fills as they land.
  float landing = hash11(id * 5.3) * 6.2831853;
  vec2 rest = vec2(cos(landing), sin(landing)) * 0.3 * sqrt(hash11(id * 8.9));
  vec2 pos = mix(mix(start, control, eased), mix(control, rest, eased), eased);
  // A small scatter around the path that closes as they arrive.
  float jitter = (1.0 - eased) * 0.06;
  pos += (h.zy - 0.5) * jitter;
  vec2 screen = pos * 0.78;
  screen.x *= u_resolution.y / u_resolution.x;
  gl_Position = vec4(screen, 0.0, 1.0);
  float arrived = smoothstep(0.92, 1.0, eased);
  gl_PointSize = max(1.0, (1.2 + 1.6 * h.z + arrived * 2.0) * u_resolution.y / 180.0);
  vec3 colour = mix(u_color1, u_color2, eased);
  colour = mix(colour, u_color3, arrived);
  float shown = smoothstep(0.0, 0.05, s);
  v_color = vec4(colour, shown * (0.35 + 0.4 * eased) * (1.0 - 0.45 * arrived));
}`,
    fragment: `
void main() {
  float falloff = smoothstep(0.5, 0.0, length(gl_PointCoord - 0.5));
  outColor = vec4(v_color.rgb, v_color.a * falloff);
}`,
    uniforms: (ctx) => ({ u_bend: ctx.params.bend, u_paths: Math.round(ctx.params.paths) }),
  }),
});
