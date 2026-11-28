import { defineMotion } from '../../core/define.mjs';
import { fragment } from '../../engines/webgl.mjs';
import { centred, ray, rotate, sdf } from '../../shaders/chunks.mjs';

export default defineMotion({
  id: 'shaders-raymarched-geometry',
  number: 133,
  module: 'shaders',
  name: { en: 'Ray-marched Geometry', ar: 'هندسة بتتبّع الأشعة' },
  summary: {
    en: 'A twisted rounded cube, a tilted ring and a small moon are ray-marched as one distance field. Where they come close the surfaces melt into each other; a lit floor of grid lines darkens under them.',
    ar: 'مكعّب مستدير ملتوٍ وحلقة مائلة وقمر صغير تُرسم بتتبّع الأشعة حقلَ مسافةٍ واحدًا. حيث تقترب تذوب أسطحها بعضها في بعض، وتُظلم تحتها أرضيةٌ مضاءة من خطوط الشبكة.',
  },
  engine: 'webgl2-glsl',
  kind: 'loop',
  duration: 10000,
  easing: 'ease-out',
  colors: ['#05060d', '#6366f1', '#22d3ee', '#f8fafc'],
  params: {
    blend: { default: 0.25, min: 0.02, max: 0.6, step: 0.01, label: { en: 'Melt between shapes', ar: 'ذوبان الأشكال بعضها في بعض' } },
    twist: { default: 0.8, min: 0, max: 2.5, step: 0.05, label: { en: 'Twist of the cube', ar: 'التواء المكعّب' } },
  },
  camera: {
    distance: { default: 3.1, min: 2.4, max: 6, step: 0.1, label: { en: 'Camera distance', ar: 'بُعد الكاميرا' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'webgl2', cost: 'medium' },
  still: 0.2,
  tags: ['3d', 'shader', 'sdf', 'raymarch', 'hero', 'background'],
  setup: fragment({
    fragment: `
uniform float u_blend;
uniform float u_twist;
uniform float u_distance;
${centred}${rotate}${sdf}${ray}
float shapes(vec3 p) {
  float a = u_time * 0.55;
  vec3 q = p;
  q.xz = rot(a) * q.xz;
  q.xz = rot(q.y * u_twist) * q.xz;
  float box = sdRoundBox(q, vec3(0.42), 0.09);
  vec3 r = p;
  r.yz = rot(0.9 + u_time * 0.4) * r.yz;
  r.xy = rot(u_time * 0.23) * r.xy;
  float ring = sdTorus(r, vec2(0.86, 0.1));
  vec3 moon = vec3(cos(u_time * 1.1) * 1.15, 0.35 * sin(u_time * 0.7), sin(u_time * 1.1) * 1.15);
  float d = smin(box, ring, u_blend);
  return smin(d, sdSphere(p - moon, 0.2), u_blend);
}
vec3 normalAt(vec3 p) {
  vec2 e = vec2(0.002, -0.002);
  return normalize(e.xyy * shapes(p + e.xyy) + e.yyx * shapes(p + e.yyx) + e.yxy * shapes(p + e.yxy) + e.xxx * shapes(p + e.xxx));
}
void main() {
  vec2 p = centredUv();
  float grow = 0.35 + 0.65 * u_intro;
  vec3 eye = vec3(sin(u_time * 0.2) * 0.6, 0.75 + 0.15 * sin(u_time * 0.31), u_distance);
  vec3 rd = cameraRay(eye, vec3(0.0, -0.05, 0.0), p, 1.7);
  vec3 colour = mix(u_color0, mix(u_color0, u_color1, 0.22), smoothstep(-0.6, 1.0, p.y));
  // The floor: grid lines that fade with distance and an occlusion shadow from the shapes above.
  if (rd.y < 0.0) {
    float t = (-1.05 - eye.y) / rd.y;
    vec3 f = eye + rd * t;
    vec2 cell = abs(fract(f.xz * 2.0) - 0.5);
    float line = smoothstep(0.06, 0.0, min(cell.x, cell.y) - 0.01 * t);
    float fade = exp(-t * 0.18);
    float shade = clamp(shapes(f / grow) * grow / 0.9, 0.0, 1.0);
    colour = mix(colour, u_color0 * 1.4 + u_color1 * (0.08 + 0.35 * line) * fade, fade) * (0.35 + 0.65 * shade);
  }
  float travelled = 0.0;
  int steps = 24 + 12 * u_quality;
  bool hit = false;
  for (int i = 0; i < 64; i++) {
    if (i >= steps) break;
    float d = shapes((eye + rd * travelled) / grow) * grow;
    if (d < 0.0015) { hit = true; break; }
    travelled += d;
    if (travelled > 12.0) break;
  }
  if (hit) {
    vec3 at = (eye + rd * travelled) / grow;
    vec3 n = normalAt(at);
    vec3 light = normalize(vec3(0.6, 0.9, 0.5));
    float diffuse = max(dot(n, light), 0.0);
    float rim = pow(1.0 - max(dot(n, -rd), 0.0), 3.0);
    float shine = pow(max(dot(reflect(-light, n), -rd), 0.0), 40.0);
    float height = smoothstep(-1.0, 1.0, at.y);
    vec3 body = mix(u_color1, u_color2, height) * (0.12 + 0.88 * diffuse);
    colour = body + u_color2 * rim * 0.8 + u_color3 * shine * 0.9;
  }
  outColor = vec4(mix(u_color0, colour, 0.4 + 0.6 * u_intro), 1.0);
}`,
    uniforms: (ctx) => ({ u_blend: ctx.params.blend, u_twist: ctx.params.twist, u_distance: ctx.camera.distance }),
  }),
});
