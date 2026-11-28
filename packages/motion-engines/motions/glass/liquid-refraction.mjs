import { defineMotion } from '../../core/define.mjs';
import { fragment } from '../../engines/webgl.mjs';
import { centred, sdf } from '../../shaders/chunks.mjs';

export default defineMotion({
  id: 'glass-liquid-refraction',
  number: 31,
  module: 'glass',
  name: { en: 'Liquid Glass Refraction', ar: 'انكسار الزجاج السائل' },
  summary: {
    en: 'Drops of liquid glass drift over a striped poster, merge and part, and bend the stripes at their rims like thick lenses, with a wet highlight and a colour fringe on every edge.',
    ar: 'قطرات من زجاج سائل تنساب فوق ملصق مخطّط، تلتحم وتفترق، وتَثني الخطوط عند حوافها كعدسات سميكة، مع لمعة رطبة وهُدب لوني على كل حافة.',
  },
  engine: 'webgl2-glsl',
  kind: 'loop',
  duration: 10000,
  easing: 'ease-out',
  colors: ['#0b1026', '#22d3ee', '#a78bfa', '#fb7185', '#f8fafc'],
  params: {
    ior: { default: 1.45, min: 1, max: 2, step: 0.01, label: { en: 'Index of refraction', ar: 'معامل الانكسار' } },
    dispersion: { default: 0.4, min: 0, max: 1, step: 0.05, label: { en: 'Dispersion', ar: 'التشتّت اللوني' } },
    tension: { default: 0.22, min: 0.03, max: 0.5, step: 0.01, label: { en: 'Surface tension', ar: 'التوتّر السطحي' } },
    drops: { default: 4, min: 2, max: 5, step: 1, label: { en: 'Drops', ar: 'عدد القطرات' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'webgl2', cost: 'low' },
  still: 0.4,
  tags: ['glass', 'liquid', 'refraction', 'hero', 'background'],
  setup: fragment({
    fragment: `
uniform float u_ior;
uniform float u_dispersion;
uniform float u_tension;
uniform float u_drops;
${centred}${sdf}
// The poster under the glass: diagonal bars in a two-colour gradient and one flat disc.
vec3 poster(vec2 p) {
  float across = dot(p, vec2(0.515, 0.857));
  float along = dot(p, vec2(0.857, -0.515));
  float bar = smoothstep(0.17, 0.21, abs(fract(across * 2.6) - 0.5));
  vec3 ink = mix(u_color1, u_color2, smoothstep(-1.3, 1.3, along));
  vec3 c = mix(ink, u_color0, bar * 0.92);
  float disc = smoothstep(0.02, -0.02, length(p - vec2(0.62, 0.18)) - 0.42);
  return mix(c, mix(u_color3, u_color0, bar * 0.28), disc);
}
// Signed distance to the merged drops: each one rides its own closed path, so the loop is seamless.
float drops(vec2 p) {
  vec2 span = u_resolution / min(u_resolution.x, u_resolution.y);
  float a = u_raw * 6.2831853;
  float d = 1e3;
  for (int i = 0; i < 5; i++) {
    float k = float(i);
    if (k >= u_drops) break;
    float odd = mod(k, 2.0);
    vec2 c = span * vec2(0.42 * cos(a * (1.0 + odd) + k * 2.4), 0.30 * sin(a * (2.0 - odd) + k * 1.9 + 0.6));
    d = smin(d, length(p - c) - (0.36 - 0.04 * k) * mix(0.45, 1.0, u_intro), u_tension);
  }
  return d;
}
void main() {
  vec2 p = centredUv();
  float px = 2.0 / min(u_resolution.x, u_resolution.y);
  float d = drops(p);
  vec2 g = normalize(vec2(drops(p + vec2(0.004, 0.0)) - d, drops(p + vec2(0.0, 0.004)) - d) + 1e-6);
  vec2 light = normalize(vec2(-0.6, 0.8));
  // Outside: the poster, darkened where the drops cast their shadow.
  vec3 colour = poster(p) * (1.0 - 0.45 * smoothstep(0.14, -0.06, drops(p + vec2(-0.045, 0.06))));
  // Inside: a rounded rim (flat in the middle) bends the view inward, a little more for each colour in turn.
  float depth = clamp(-d / 0.2, 0.0, 1.0);
  float bend = (1.0 - depth) * (1.0 - depth);
  vec2 shift = g * bend * (u_ior - 1.0) * 0.36;
  float split = 0.3 * u_dispersion;
  vec3 seen = vec3(poster(p - shift * (1.0 - split)).r, poster(p - shift).g, poster(p - shift * (1.0 + split)).b);
  float facing = dot(g, light);
  seen *= 1.06 - 0.3 * (1.0 - depth) * facing;
  vec3 normal = normalize(vec3(g * bend * 1.7, 1.0));
  float glint = pow(max(dot(normal, normalize(vec3(light * 0.75, 0.66) + vec3(0.0, 0.0, 1.0))), 0.0), 60.0);
  float rim = pow(1.0 - depth, 4.0);
  seen += u_color4 * (glint * 0.95 + rim * (0.5 * max(facing, 0.0) + 0.16 * max(-facing, 0.0)));
  colour = mix(colour, seen, smoothstep(px, -px, d));
  colour += u_color4 * 0.22 * smoothstep(1.5 * px, 0.0, abs(d));
  outColor = vec4(colour, 1.0);
}`,
    uniforms: (ctx) => ({ u_ior: ctx.params.ior, u_dispersion: ctx.params.dispersion, u_tension: ctx.params.tension, u_drops: Math.round(ctx.params.drops) }),
  }),
});
