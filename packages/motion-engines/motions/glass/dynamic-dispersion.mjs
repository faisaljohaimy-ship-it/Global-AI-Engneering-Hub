import { defineMotion } from '../../core/define.mjs';
import { fragment } from '../../engines/webgl.mjs';
import { centred } from '../../shaders/chunks.mjs';

export default defineMotion({
  id: 'glass-dynamic-dispersion',
  number: 32,
  module: 'glass',
  name: { en: 'Dynamic Glass Dispersion', ar: 'تشتّت الضوء الحيّ في الزجاج' },
  summary: {
    en: 'A beam of white light crosses a bevelled glass prism swaying on an optical table and leaves as a fan of colours. Each colour is bent by its own index of refraction, so the fan swings and widens as the prism turns.',
    ar: 'حزمة ضوء أبيض تعبر منشورًا زجاجيًا مشطوف الحواف يتمايل فوق طاولة بصرية، وتخرج منه مروحةً من الألوان. لكل لون معامل انكساره، فتتأرجح المروحة وتتّسع كلما دار المنشور.',
  },
  engine: 'webgl2-glsl',
  kind: 'loop',
  duration: 8000,
  easing: 'ease-out',
  colors: ['#05060c', '#f8fafc', '#ff4d6d', '#a3e635', '#3b82f6'],
  params: {
    ior: { default: 1.5, min: 1.35, max: 1.65, step: 0.01, label: { en: 'Index of refraction', ar: 'معامل الانكسار' } },
    dispersion: { default: 0.5, min: 0, max: 1, step: 0.05, label: { en: 'Dispersion', ar: 'شدّة التشتّت' } },
    faces: { default: 6, min: 3, max: 6, step: 3, label: { en: 'Prism faces (3 or 6)', ar: 'أوجه المنشور (3 أو 6)' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'webgl2', cost: 'low' },
  still: 0.3,
  tags: ['glass', 'prism', 'light', 'spectrum', 'hero'],
  setup: fragment({
    fragment: `
uniform float u_ior;
uniform float u_dispersion;
uniform float u_faces;
${centred}
vec2 unit(float a) { return vec2(cos(a), sin(a)); }
// Light of a ray from a to b whose width grows from w0 to w1 while its energy is kept.
float ray(vec2 p, vec2 a, vec2 b, float w0, float w1) {
  vec2 ab = b - a; float h = clamp(dot(p - a, ab) / dot(ab, ab), 0.0, 1.0);
  float w = mix(w0, w1, h); float d = length(p - a - ab * h);
  return exp(-d * d / (w * w)) * w0 / w;
}
vec3 spectrum(float s) { return s < 0.5 ? mix(u_color2, u_color3, s * 2.0) : mix(u_color3, u_color4, s * 2.0 - 1.0); }
void main() {
  vec2 p = centredUv();
  if (u_resolution.y > u_resolution.x) p = vec2(-p.y, p.x);   // upright frames: the beam runs from top to bottom
  float px = 2.0 / min(u_resolution.x, u_resolution.y);
  float count = u_faces < 4.5 ? 3.0 : 6.0;
  float apothem = count < 4.0 ? 0.4 : 0.6;
  vec2 centre = count < 4.0 ? vec2(-0.24, -0.14) : vec2(-0.36, -0.12);
  float turn = 0.13 * sin(u_raw * 6.2831853);
  // The prism from above: the nearest face gives the distance to the edge and the light its bevel catches.
  float d = -9.0; vec2 near = vec2(0.0);
  for (int i = 0; i < 6; i++) {
    if (float(i) >= count) break;
    vec2 n = unit(turn + 0.5236 + 6.2831853 * float(i) / count);
    float reach = dot(p - centre, n) - apothem;
    if (reach > d) { d = reach; near = n; }
  }
  float inside = smoothstep(px, -px, d);
  float top = smoothstep(px, -px, d + 0.075);
  // The optical table: a grid of small holes, seen a little larger through the glass.
  vec2 seen = mix(p, centre + (p - centre) * 0.82, inside);
  float hole = smoothstep(0.045, 0.025, length(fract(seen * 3.0 + 0.5) - 0.5));
  vec3 colour = u_color0 * (1.3 - 0.3 * length(p)) + u_color1 * hole * (0.07 + 0.07 * inside);
  float gloss = smoothstep(0.12, 0.0, abs(dot(p - centre, vec2(0.8, 0.6)) + 0.1));
  float bevel = 0.07 + 0.34 * pow(max(dot(near, vec2(-0.5, 0.866)), 0.0), 2.0) + 0.1 * max(-near.y, 0.0);
  colour += u_color1 * inside * mix(bevel, 0.045 + 0.06 * gloss, top) * u_intro;
  colour += u_color1 * (0.55 * smoothstep(1.5 * px, 0.0, abs(d)) + 0.2 * smoothstep(1.5 * px, 0.0, abs(d + 0.075))) * u_intro;
  // The beam: aimed at the middle of one face, refracted in and out through two faces 60 degrees apart, once for every colour.
  vec2 enter = unit(turn + 2.618), leave = unit(turn + 0.5236);
  vec2 d0 = normalize(vec2(1.0, 0.32));
  vec2 o = centre + apothem * unit(2.618) - d0 * 5.0;
  vec2 E = o + d0 * (apothem - dot(o - centre, enter)) / dot(d0, enter);
  float flow = 0.85 + 0.15 * sin(dot(p, d0) * 30.0 - u_time * 7.0);
  vec3 light = u_color1 * (ray(p, o, E, 0.016, 0.016) * flow + 0.1 * ray(p, E, E + reflect(d0, enter) * 3.0, 0.016, 0.12));
  int colours = 5 + 2 * u_quality;
  for (int i = 0; i < colours; i++) {
    float s = float(i) / float(colours - 1);
    float n = u_ior + 0.5 * u_dispersion * (s - 0.5);
    vec2 d1 = refract(d0, enter, 1.0 / n);
    vec2 X = E + d1 * (apothem - dot(E - centre, leave)) / dot(d1, leave);
    vec2 d2 = refract(d1, -leave, n);
    float lit = ray(p, E, X, 0.016, 0.022);
    if (dot(d2, d2) > 0.5) lit += ray(p, X, X + d2 * 4.0, 0.022, 0.2 + 0.5 * u_dispersion) * 3.2;   // otherwise this colour stays inside the glass
    light += spectrum(s) * lit * 2.2 / float(colours);
  }
  outColor = vec4(colour + light * (0.25 + 0.75 * u_intro), 1.0);
}`,
    uniforms: (ctx) => ({ u_ior: ctx.params.ior, u_dispersion: ctx.params.dispersion, u_faces: ctx.params.faces }),
  }),
});
