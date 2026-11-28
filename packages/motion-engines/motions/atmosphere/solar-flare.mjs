import { defineMotion } from '../../core/define.mjs';
import { fragment } from '../../engines/webgl.mjs';
import { fbm, hash, noise } from '../../shaders/chunks.mjs';

export default defineMotion({
  id: 'atmosphere-solar-flare',
  number: 174,
  module: 'atmosphere',
  name: { en: 'Solar Flare Visualization', ar: 'محاكاة التوهّج الشمسي' },
  summary: {
    en: 'A boiling sun fills the frame: magnetic loops arch over its limb, the corona streams outward, and once per cycle an active region flashes and throws a jet of plasma into space.',
    ar: 'شمس تغلي تملأ الإطار: أقواس مغناطيسية تنحني فوق حافتها والهالة تنساب إلى الخارج، وفي كل دورة تومض منطقة نشطة وتقذف نافورة من البلازما إلى الفضاء.',
  },
  engine: 'webgl2-glsl',
  kind: 'loop',
  duration: 10000,
  easing: 'ease-out',
  colors: ['#070308', '#a81d0a', '#ff8a1f', '#ffe9a8', '#ff4f8b'],
  params: {
    activity: { default: 1, min: 0.3, max: 2, step: 0.05, label: { en: 'Solar activity', ar: 'النشاط الشمسي' } },
    loops: { default: 5, min: 2, max: 8, step: 1, label: { en: 'Magnetic loops', ar: 'عدد الأقواس المغناطيسية' } },
    granulation: { default: 8, min: 4, max: 16, step: 0.5, label: { en: 'Surface granulation', ar: 'حُبيبات السطح' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'webgl2', cost: 'medium' },
  still: 0.4,
  tags: ['space', 'energy', 'hero', 'science', 'background'],
  setup: fragment({
    fragment: `
uniform float u_activity;
uniform float u_loops;
uniform float u_granulation;
${hash}${noise}${fbm}
void main() {
  float unit = min(u_resolution.x, u_resolution.y);
  vec2 q = (2.0 * gl_FragCoord.xy - u_resolution) / unit + vec2(0.0, 0.06);
  float t = u_time;
  float R = 0.56;
  float r = length(q);
  vec2 away = q / max(r, 1e-4);
  float inside = smoothstep(R + 2.0 / unit, R - 2.0 / unit, r);
  // The photosphere: convection cells on a sphere, darker toward the limb.
  float mu = sqrt(max(0.0, 1.0 - r * r / (R * R)));
  vec2 s = q / R * (1.0 + 0.4 * (1.0 - mu));
  float swirl = fbm(s * u_granulation * 0.35 + vec2(t * 0.03, 0.0));
  float cells = fbm(s * u_granulation + vec2(swirl * 2.5 - t * 0.06, swirl * 2.0 + t * 0.04));
  float heat = clamp(0.5 + (cells - 0.5) * 2.4, 0.0, 1.0);
  vec3 disc = mix(u_color1, u_color2, heat) * (0.35 + 0.75 * mu) + u_color3 * pow(heat, 5.0) * mu * 0.9;
  // The corona: streamers that thin out with distance.
  float beyond = max(r - R, 0.0);
  float streams = fbm(away * 2.6 + vec2(t * 0.05, -t * 0.04) + beyond * 0.8);
  float corona = exp(-beyond * (8.0 - 5.0 * streams)) * (0.3 + 0.9 * streams);
  vec3 colour = mix(u_color2 * corona * 0.75 + u_color1 * exp(-beyond * 2.2) * 0.4, disc, inside);
  // Magnetic loops standing on the limb, with plasma running along them.
  float count = floor(u_loops + 0.5);
  for (int i = 0; i < 8; i++) {
    if (float(i) >= count) break;
    float k = float(i);
    vec3 h = hash31(k * 5.17 + 1.0);
    float theta = 6.2831853 * (k + 0.2 + 0.6 * h.x) / count + 2.3;
    vec2 n = vec2(cos(theta), sin(theta));
    vec2 local = vec2(dot(q, vec2(-n.y, n.x)), dot(q, n) - R * 0.97);
    float breathe = 0.65 + 0.35 * sin(t * (0.5 + h.y) + k * 2.1);
    vec2 size = vec2(0.06 + 0.07 * h.z, (0.1 + 0.18 * h.y) * u_activity * breathe);
    float outline = abs(length(local / size) - 1.0) * min(size.x, size.y);
    float thick = 0.006 + 0.004 * h.x;
    float arc = thick / (outline + thick) * smoothstep(-0.01, 0.02, local.y);
    float bead = 0.55 + 0.45 * sin(atan(local.y / size.y, local.x / size.x) * 6.0 - t * (2.0 + 2.0 * h.z) + k);
    colour += (u_color4 * arc * 0.9 + u_color3 * pow(arc, 4.0)) * bead * (1.0 - 0.85 * inside);
  }
  // The flare: an active region flashes and throws a jet that widens, curls and fades.
  float e = u_progress;
  float burst = smoothstep(0.06, 0.18, e) * (1.0 - smoothstep(0.55, 0.96, e));
  vec2 nf = vec2(cos(0.85), sin(0.85));
  vec2 lf = vec2(dot(q, vec2(-nf.y, nf.x)), dot(q, nf) - R);
  float reach = (0.2 + 0.8 * smoothstep(0.06, 0.6, e)) * 0.6 * u_activity;
  float v = lf.y / reach;
  float curl = (fbm(vec2(lf.y * 6.0 - t * 0.8, lf.x * 5.0)) - 0.5) * 0.14 * v;
  float width = 0.022 + 0.1 * v * sqrt(u_activity);
  float jet = exp(-pow((lf.x + curl + 0.07 * v * v) / width, 2.0)) * smoothstep(0.0, 0.06, v) * smoothstep(1.0, 0.5, v);
  float knots = 0.45 + 0.55 * noise(vec2(lf.y * 14.0 - t * 2.5, lf.x * 10.0));
  colour += (u_color2 * jet * 0.9 + u_color3 * jet * jet * knots * 1.3 + u_color4 * jet * 0.5 * (1.0 - clamp(v, 0.0, 1.0))) * burst * (1.0 - inside);
  float foot = length(q - nf * R * 0.96);
  float flash = exp(-pow((e - 0.12) / 0.06, 2.0));
  colour += u_color3 * 0.01 * (0.5 + 3.0 * flash + burst) * u_activity / (foot * foot + 0.004);
  outColor = vec4(u_color0 + colour * u_intro, 1.0);
}`,
    uniforms: (ctx) => ({ u_activity: ctx.params.activity, u_loops: ctx.params.loops, u_granulation: ctx.params.granulation }),
  }),
});
