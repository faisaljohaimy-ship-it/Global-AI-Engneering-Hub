import { defineMotion } from '../../core/define.mjs';
import { fragment } from '../../engines/webgl.mjs';
import { centred, ray } from '../../shaders/chunks.mjs';

export default defineMotion({
  id: 'camera-dolly-out',
  number: 12,
  module: 'camera',
  name: { en: 'Cinematic Dolly Out', ar: 'ابتعاد الكاميرا السينمائي' },
  summary: {
    en: 'The shot opens close on a polished sphere that mirrors the room around it, then the camera pulls back and rises to show it at the centre of a ring of smaller spheres on a reflective floor.',
    ar: 'تبدأ اللقطة قريبةً من كرةٍ مصقولة تعكس ما حولها، ثم تتراجع الكاميرا وترتفع لتُظهرها في قلب حلقةٍ من كراتٍ أصغر على أرضيةٍ عاكسة.',
  },
  meaning: {
    en: 'Zooming out from one core platform to show the ring of connected digital services that depend on it.',
    ar: 'الابتعاد عن منصّةٍ رقمية محورية لإظهار حلقة الخدمات الرقمية المتصلة بها والمعتمدة عليها.',
  },
  engine: 'webgl2-glsl',
  kind: 'oneshot',
  duration: 4200,
  easing: 'ease-in-out',
  colors: ['#06070f', '#c084fc', '#38bdf8', '#f8fafc'],
  params: {
    ring: { default: 7, min: 3, max: 10, step: 1, label: { en: 'Spheres in the ring', ar: 'عدد الكرات في الحلقة' } },
    shine: { default: 0.6, min: 0.1, max: 1, step: 0.05, label: { en: 'Floor reflection', ar: 'انعكاس الأرضية' } },
  },
  camera: {
    distance: { default: 7, min: 4, max: 10, step: 0.25, label: { en: 'Final distance', ar: 'المسافة النهائية' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'webgl2', cost: 'medium' },
  still: 1,
  tags: ['camera', 'reveal', 'hero', 'product', '3d'],
  setup: fragment({
    fragment: `
uniform float u_ring;
uniform float u_shine;
uniform float u_distance;
${centred}${ray}
vec4 sphereAt(int i) {
  if (i == 0) return vec4(0.0, 0.0, 0.0, 0.7);
  float a = 6.2831853 * float(i - 1) / u_ring + 0.4;
  return vec4(cos(a) * 2.1, -0.38, sin(a) * 2.1, 0.32);
}
// Nearest sphere along a ray: distance and index (-1 for none).
vec2 hitSpheres(vec3 ro, vec3 rd) {
  float best = 1e9; float index = -1.0;
  for (int i = 0; i < 11; i++) {
    if (float(i) > u_ring) break;
    vec4 s = sphereAt(i);
    vec3 oc = ro - s.xyz;
    float b = dot(oc, rd); float c = dot(oc, oc) - s.w * s.w; float h = b * b - c;
    if (h > 0.0) { float t = -b - sqrt(h); if (t > 0.001 && t < best) { best = t; index = float(i); } }
  }
  return vec2(best, index);
}
// The room: dark walls, a broad soft box above and a coloured strip at the horizon.
vec3 room(vec3 d) {
  vec3 c = mix(u_color0, u_color0 + u_color1 * 0.18, smoothstep(-0.3, 0.8, d.y));
  c += u_color3 * smoothstep(0.9, 0.97, d.y) * 0.9;
  c += u_color2 * smoothstep(0.05, 0.0, abs(d.y - 0.05)) * 0.6;
  return c;
}
vec3 floorAt(vec3 at, float t) {
  vec2 cell = abs(fract(at.xz) - 0.5);
  float line = smoothstep(0.03, 0.0, min(cell.x, cell.y) - 0.005);
  return u_color0 * 1.2 + u_color1 * line * 0.18 * exp(-t * 0.1);
}
vec3 shadeSphere(vec3 ro, vec3 rd, float t, int i) {
  vec4 s = sphereAt(i);
  vec3 at = ro + rd * t;
  vec3 n = normalize(at - s.xyz);
  vec3 r = reflect(rd, n);
  vec3 env = room(r);
  if (r.y < 0.0) { float ft = (-0.7 - at.y) / r.y; env = floorAt(at + r * ft, ft); }
  float rim = pow(1.0 - max(dot(n, -rd), 0.0), 3.0);
  vec3 tint = i == 0 ? u_color2 : u_color1;
  return env * 0.85 + tint * (0.15 + 0.5 * rim);
}
void main() {
  vec2 p = centredUv();
  float back = u_progress;
  float distance = mix(1.25, u_distance, back);
  float height = mix(0.05, 1.8, back * back);
  vec3 eye = vec3(sin(back * 1.2) * distance * 0.3, height, distance);
  vec3 rd = cameraRay(eye, vec3(0.0, mix(0.05, -0.3, back), 0.0), p, 1.6);
  vec2 hit = hitSpheres(eye, rd);
  vec3 colour = room(rd);
  float tf = rd.y < 0.0 ? (-0.7 - eye.y) / rd.y : 1e9;
  if (hit.y >= 0.0 && hit.x < tf) {
    colour = shadeSphere(eye, rd, hit.x, int(hit.y));
  } else if (tf < 1e8) {
    vec3 at = eye + rd * tf;
    colour = floorAt(at, tf);
    // The floor mirrors the spheres and the room, fading with distance.
    vec3 mirror = reflect(rd, vec3(0.0, 1.0, 0.0));
    vec2 seen = hitSpheres(at, mirror);
    vec3 reflected = seen.y >= 0.0 ? shadeSphere(at, mirror, seen.x, int(seen.y)) : room(mirror);
    colour = mix(colour, reflected, u_shine * 0.6 * exp(-tf * 0.08));
    // Contact shadows under each sphere.
    for (int i = 0; i < 11; i++) {
      if (float(i) > u_ring) break;
      vec4 s = sphereAt(i);
      colour *= 1.0 - 0.6 * smoothstep(s.w * 1.3, 0.0, length(at.xz - s.xz)) * smoothstep(1.5, 0.0, s.y + 0.7 - s.w);
    }
  }
  outColor = vec4(colour, 1.0);
}`,
    uniforms: (ctx) => ({ u_ring: Math.round(ctx.params.ring), u_shine: ctx.params.shine, u_distance: ctx.camera.distance }),
  }),
});
