import { defineMotion } from '../../core/define.mjs';
import { fragment } from '../../engines/webgl.mjs';
import { centred } from '../../shaders/chunks.mjs';

export default defineMotion({
  id: 'glass-iridescent-morphing',
  number: 38,
  module: 'glass',
  name: { en: 'Iridescent Glass Morphing', ar: 'تحوّل الزجاج القُزحي' },
  summary: {
    en: 'A single bead of glass keeps changing its outline, bulging into lobes and drawing them back. A film on its surface shifts colour with the viewing angle, like oil on water, so bands of colour slide over it as it moves.',
    ar: 'حبّة زجاج واحدة لا يثبت محيطها: تنتفخ فصوصًا ثم تسحبها. على سطحها غشاء رقيق يتبدّل لونه بتبدّل زاوية النظر كالزيت على الماء، فتنزلق عليها أشرطة الألوان كلما تحرّكت.',
  },
  engine: 'webgl2-glsl',
  kind: 'loop',
  duration: 9000,
  easing: 'ease-out',
  colors: ['#0b0716', '#22d3ee', '#f472b6', '#facc15', '#f8fafc'],
  params: {
    lobes: { default: 3, min: 2, max: 6, step: 1, label: { en: 'Lobes', ar: 'عدد الفصوص' } },
    morph: { default: 0.7, min: 0, max: 1, step: 0.05, label: { en: 'Morphing', ar: 'شدّة التحوّل' } },
    film: { default: 1.4, min: 0.5, max: 3, step: 0.1, label: { en: 'Film thickness', ar: 'سماكة الغشاء' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'webgl2', cost: 'low' },
  still: 0.4,
  tags: ['glass', 'iridescent', 'morph', 'blob', 'hero', 'loader'],
  setup: fragment({
    fragment: `
uniform float u_lobes;
uniform float u_morph;
uniform float u_film;
${centred}
// Thin-film colour: as the film thickens the three palette colours take turns, the way interference orders do.
vec3 film(float x) {
  vec3 w = 0.5 + 0.5 * cos(6.2831853 * (x + vec3(0.0, 0.3333, 0.6667)));
  w *= w;
  return (u_color1 * w.x + u_color2 * w.y + u_color3 * w.z) / (w.x + w.y + w.z);
}
vec3 backdrop(vec2 p) {
  vec2 a = p - vec2(-0.8, 0.45); vec2 b = p - vec2(0.85, -0.4);
  return u_color0 * (1.3 - 0.4 * length(p)) + u_color1 * 0.12 * exp(-dot(a, a) * 1.4) + u_color2 * 0.12 * exp(-dot(b, b) * 1.4);
}
void main() {
  vec2 p = centredUv();
  float px = 2.0 / min(u_resolution.x, u_resolution.y);
  float a = u_raw * 6.2831853;
  float r = length(p); float theta = atan(p.y, p.x);
  // The outline: a circle with three waves running round it. Whole numbers of waves and of turns keep it closed.
  float n = u_lobes;
  float wobble = 0.17 * sin(n * theta + a) + 0.1 * sin((n + 1.0) * theta - 2.0 * a + 1.3) + 0.06 * sin((n + 2.0) * theta + 3.0 * a + 4.0);
  float bend = 0.17 * n * cos(n * theta + a) + 0.1 * (n + 1.0) * cos((n + 1.0) * theta - 2.0 * a + 1.3) + 0.06 * (n + 2.0) * cos((n + 2.0) * theta + 3.0 * a + 4.0);
  float radius = 0.72 * mix(0.5, 1.0, u_intro) * (1.0 + u_morph * wobble);
  float u = r / radius;
  // The bead as a dome over that outline, and the direction its surface faces.
  float z = sqrt(max(1.0 - u * u, 0.0));
  vec2 radial = p / max(r, 1e-4);
  vec3 normal = normalize(vec3(u * (radial - vec2(-radial.y, radial.x) * u_morph * bend / (1.0 + u_morph * wobble)), z + 0.05));
  float flow = 0.5 * sin(3.0 * p.x + a + 2.0 * sin(2.3 * p.y - a)) + 0.3 * sin(4.1 * p.y - a + 1.7 * sin(3.1 * p.x + a));
  vec3 sheen = film(u_film * (0.35 + 1.1 * (1.0 - normal.z)) + 0.3 * flow);
  // Outside: the backdrop, a halo of film colour and the bead's shadow.
  float gap = max(r - radius, 0.0);
  vec3 colour = backdrop(p) + film(theta / 6.2831853 + u_raw + 0.2) * 0.22 * exp(-gap * 7.0) * u_intro;
  vec2 below = p - vec2(0.05, -0.1);
  colour *= 1.0 - 0.35 * smoothstep(1.15, 0.85, length(below) / radius);
  // Inside: the backdrop bent by the glass, the film brightest at the rim, a window reflected in the dome.
  float rim = pow(1.0 - normal.z, 2.2);
  vec3 body = backdrop(p - normal.xy * 0.4 * (1.0 - normal.z)) * 0.8 + sheen * (0.32 + 0.9 * rim);
  vec3 mirror = reflect(vec3(0.0, 0.0, -1.0), normal);
  float window = smoothstep(0.07, 0.0, max(abs(mirror.x + 0.52) - 0.2, abs(mirror.y - 0.56) - 0.13));
  float lamp = pow(max(dot(normal, normalize(vec3(0.62, -0.55, 0.3))), 0.0), 9.0);
  body += u_color4 * (0.8 * window + 0.1 * rim) + sheen * 0.4 * lamp;
  body *= 1.0 - 0.3 * pow(u, 8.0);
  outColor = vec4(mix(colour, body, smoothstep(px, -px, r - radius)), 1.0);
}`,
    uniforms: (ctx) => ({ u_lobes: Math.round(ctx.params.lobes), u_morph: ctx.params.morph, u_film: ctx.params.film }),
  }),
});
