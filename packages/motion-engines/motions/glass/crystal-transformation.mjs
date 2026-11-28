import { defineMotion } from '../../core/define.mjs';
import { fragment } from '../../engines/webgl.mjs';
import { centred, rotate } from '../../shaders/chunks.mjs';

export default defineMotion({
  id: 'glass-crystal-transformation',
  number: 37,
  module: 'glass',
  name: { en: 'Crystal Geometry Transformation', ar: 'تحوّل هندسة البلّورة' },
  summary: {
    en: 'A glass cube turns while its eight corners are cut away. The cuts grow into faces, the old faces shrink, and the cube ends as an octahedron. Light bends through the front facets and shows the back ones in colour.',
    ar: 'مكعّب زجاجي يدور وزواياه الثماني تُشطف. تكبر الشطفات حتى تصير أوجهًا وتنكمش الأوجه القديمة، فينتهي المكعّب مجسّمًا ثُمانيّ الأوجه. ينكسر الضوء عبر الأوجه الأمامية فيُظهر الخلفية منها ملوّنة.',
  },
  engine: 'webgl2-glsl',
  kind: 'oneshot',
  duration: 3600,
  easing: 'ease-in-out',
  colors: ['#070a14', '#22d3ee', '#a855f7', '#f8fafc'],
  params: {
    target: { default: 1, min: 0.3, max: 1, step: 0.05, label: { en: 'Final form (cube to octahedron)', ar: 'الشكل النهائي (من المكعّب إلى ثُمانيّ الأوجه)' } },
    spin: { default: 0.5, min: 0, max: 1.5, step: 0.05, label: { en: 'Turns', ar: 'عدد الدورات' } },
    ior: { default: 1.6, min: 1.1, max: 2.4, step: 0.05, label: { en: 'Index of refraction', ar: 'معامل الانكسار' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'webgl2', cost: 'low' },
  still: 1,
  tags: ['crystal', 'gem', 'geometry', 'morph', 'hero', '3d'],
  setup: fragment({
    fragment: `
uniform float u_target;
uniform float u_spin;
uniform float u_ior;
${centred}${rotate}
// The crystal is the space between seven pairs of parallel planes: three of a cube, four of an octahedron.
// One pair narrows the stretch of the ray that is inside: t.x entry, t.y the entry before it, t.z exit, t.w the exit after it.
void slab(vec3 n, float d, vec3 ro, vec3 rd, inout vec4 t, inout vec3 front, inout vec3 back) {
  float along = dot(n, rd); float from = dot(n, ro);
  float inv = 1.0 / (abs(along) < 1e-5 ? 1e-5 : along);
  float a = (-d - from) * inv; float b = (d - from) * inv;
  float way = along < 0.0 ? 1.0 : -1.0;
  float enter = min(a, b); float leave = max(a, b);
  if (enter > t.x) { t.y = t.x; t.x = enter; front = way * n; } else if (enter > t.y) t.y = enter;
  if (leave < t.z) { t.w = t.z; t.z = leave; back = -way * n; } else if (leave < t.w) t.w = leave;
}
vec4 crystal(vec3 ro, vec3 rd, float cube, float octa, out vec3 front, out vec3 back) {
  vec4 t = vec4(-1e4, -1e4, 1e4, 1e4);
  front = vec3(0.0); back = vec3(0.0);
  slab(vec3(1.0, 0.0, 0.0), cube, ro, rd, t, front, back);
  slab(vec3(0.0, 1.0, 0.0), cube, ro, rd, t, front, back);
  slab(vec3(0.0, 0.0, 1.0), cube, ro, rd, t, front, back);
  slab(vec3(0.57735), octa, ro, rd, t, front, back);
  slab(vec3(0.57735, 0.57735, -0.57735), octa, ro, rd, t, front, back);
  slab(vec3(0.57735, -0.57735, 0.57735), octa, ro, rd, t, front, back);
  slab(vec3(-0.57735, 0.57735, 0.57735), octa, ro, rd, t, front, back);
  return t;
}
// The room around it: a dim gradient, a wide violet lamp, a small white one and a thin strip at the horizon.
vec3 room(vec3 d) {
  vec3 colour = mix(u_color0 * 0.5, u_color1 * 0.5, smoothstep(-0.4, 0.9, d.y));
  colour += u_color2 * 0.9 * pow(max(dot(d, normalize(vec3(-0.7, 0.3, 0.5))), 0.0), 5.0);
  colour += u_color3 * 2.2 * pow(max(dot(d, normalize(vec3(0.45, 0.7, 0.55))), 0.0), 30.0);
  return colour + u_color3 * 0.45 * smoothstep(0.03, 0.0, abs(d.y + 0.15) - 0.02);
}
void main() {
  vec2 p = centredUv();
  float form = u_progress * u_target;
  float turn = 0.6 + 6.2831853 * u_spin * u_progress;
  float lean = 0.45 + 0.25 * sin(3.14159265 * u_progress);
  mat2 ry = rot(turn); mat2 rx = rot(lean);
  vec3 eye = vec3(0.0, 0.0, 4.2); vec3 view = normalize(vec3(p, -3.2));
  vec3 ro = eye; ro.yz = rx * ro.yz; ro.xz = ry * ro.xz;
  vec3 rd = view; rd.yz = rx * rd.yz; rd.xz = ry * rd.xz;
  float cube = mix(0.6, 1.04, form); float octa = mix(1.04, 0.6, form);
  vec3 front; vec3 back;
  vec4 t = crystal(ro, rd, cube, octa, front, back);
  // The backdrop: a glow behind the crystal and its shadow on the ground.
  float r = length(p);
  vec3 colour = u_color0 * (1.25 - 0.4 * r) + u_color1 * 0.13 * exp(-r * r * 1.6) + u_color2 * 0.1 * exp(-dot(p + vec2(0.0, 0.8), p + vec2(0.0, 0.8)) * 6.0);
  colour *= 1.0 - 0.45 * exp(-(p.x * p.x * 1.6 + (p.y + 0.86) * (p.y + 0.86) * 30.0));
  if (t.x < t.z && t.x > 0.0) {
    vec3 hit = ro + rd * t.x;
    // Through the front facet to the back of the crystal, and out again (or back in, when the angle is too flat).
    vec3 inside = refract(rd, front, 1.0 / u_ior);
    vec3 unused; vec3 rear;
    vec4 s = crystal(hit + inside * 1e-3, inside, cube, octa, unused, rear);
    vec3 leave = refract(inside, -rear, u_ior);
    float trapped = step(dot(leave, leave), 0.5);
    leave = mix(leave, reflect(inside, -rear), trapped);
    leave.xz = leave.xz * ry; leave.yz = leave.yz * rx;
    vec3 tint = mix(u_color1, u_color2, 0.5 + 0.5 * dot(rear, vec3(0.37, 0.74, 0.56)));
    vec3 body = room(leave) * mix(vec3(1.0), tint, 0.6) + tint * (0.14 + 0.3 * trapped);
    body *= exp(-s.z * 0.22);
    body += u_color3 * 0.3 * smoothstep(0.06, 0.0, s.w - s.z);
    // The mirror image of the room on the front facet, stronger at grazing angles, and the lit edges.
    vec3 mirror = reflect(rd, front);
    mirror.xz = mirror.xz * ry; mirror.yz = mirror.yz * rx;
    float glance = 0.07 + 0.93 * pow(1.0 - max(dot(-rd, front), 0.0), 4.0);
    colour = mix(body, room(mirror), glance);
    colour += u_color3 * smoothstep(0.045, 0.0, t.x - t.y) * (0.45 + 0.5 * sin(3.14159265 * form));
  }
  outColor = vec4(colour, 1.0);
}`,
    uniforms: (ctx) => ({ u_target: ctx.params.target, u_spin: ctx.params.spin, u_ior: ctx.params.ior }),
  }),
});
