import { defineMotion } from '../../core/define.mjs';
import { fragment } from '../../engines/webgl.mjs';
import { centred, hash, rotate } from '../../shaders/chunks.mjs';

export default defineMotion({
  id: 'camera-spatial-roll',
  number: 20,
  module: 'camera',
  name: { en: 'Spatial Camera Roll', ar: 'دحرجة الكاميرا المكانية' },
  summary: {
    en: 'The camera flies low over a gridded plain between two rows of beacons and rolls about its line of flight. The horizon tilts, turns upside down and comes level again while the beacons stream past and the sun keeps its place in the sky.',
    ar: 'تطير الكاميرا منخفضةً فوق سهلٍ مُشبَّك بين صفّين من المنارات وتدور حول خطّ طيرانها. يميل الأفق وينقلب ثم يعود مستويًا بينما تتدفّق المنارات مارّةً وتبقى الشمس في مكانها من السماء.',
  },
  engine: 'webgl2-glsl',
  kind: 'oneshot',
  duration: 4400,
  easing: 'ease-in-out',
  colors: ['#04060e', '#22d3ee', '#f97316', '#e0e7ff'],
  params: {
    turns: { default: 1, min: 0.25, max: 2, step: 0.25, label: { en: 'Turns of roll', ar: 'عدد دورات الدحرجة' } },
    speed: { default: 1, min: 0.3, max: 2.5, step: 0.1, label: { en: 'Flight speed', ar: 'سرعة الطيران' } },
  },
  camera: {
    height: { default: 0.6, min: 0.25, max: 1.4, step: 0.05, label: { en: 'Height above the ground', ar: 'الارتفاع عن الأرض' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'webgl2', cost: 'low' },
  still: 1,
  tags: ['camera', 'flight', 'roll', 'transition', 'immersive'],
  setup: fragment({
    fragment: `
uniform float u_turns;
uniform float u_speed;
uniform float u_height;
${hash}${centred}${rotate}
void main() {
  vec2 p = centredUv();
  float roll = u_progress * 6.2831853 * u_turns;
  vec2 q = rot(roll) * p;
  vec3 rd = normalize(vec3(q, 1.5));
  float travel = u_progress * 14.0 * u_speed;
  vec3 eye = vec3(0.0, u_height, travel);
  vec3 colour;
  // Sky: a gradient by how far the ray looks up, a sun ahead and a little to the side.
  float up = rd.y;
  colour = mix(u_color0 + u_color2 * 0.25, u_color0, smoothstep(-0.05, 0.6, up));
  vec3 sunDir = normalize(vec3(0.35, 0.18, 1.0));
  float sun = max(dot(rd, sunDir), 0.0);
  colour += u_color2 * pow(sun, 200.0) * 2.0 + u_color2 * pow(sun, 8.0) * 0.25;
  float stars = step(0.997, hash21(floor(rd.xy / max(rd.z, 0.1) * 90.0))) * smoothstep(0.1, 0.4, up);
  colour += u_color3 * stars * 0.7;
  // Ground: a glowing grid that fades into the distance.
  if (rd.y < 0.0) {
    float t = -eye.y / rd.y;
    vec3 g = eye + rd * t;
    vec2 cell = abs(fract(g.xz * 0.8) - 0.5);
    float line = smoothstep(0.04 + 0.004 * t, 0.0, min(cell.x, cell.y)) * smoothstep(26.0, 8.0, t);
    float fog = exp(-t * 0.11);
    colour = mix(colour, u_color0 * 1.5 + u_color1 * line * 0.9, fog);
  }
  // Beacons: two rows of upright glowing posts beside the flight line, found per row by plane hits.
  for (int side = 0; side < 2; side++) {
    float x = side == 0 ? -1.6 : 1.6;
    float t = (x - eye.x) / (abs(rd.x) < 1e-4 ? 1e-4 : rd.x);
    if (t > 0.0) {
      vec3 h = eye + rd * t;
      float row = floor(h.z / 3.0);
      float local = fract(h.z / 3.0) - 0.5;
      float post = smoothstep(0.06, 0.0, abs(local) - 0.02) * step(0.0, h.y) * step(h.y, 1.4 + 0.5 * hash11(row + float(side) * 31.0));
      float glow = smoothstep(0.25, 0.0, abs(local)) * smoothstep(0.4, 0.0, abs(h.y - 1.5)) * 0.4;
      float fade = exp(-t * 0.07);
      colour += mix(u_color1, u_color3, hash11(row * 1.7)) * (post * 0.9 + glow) * fade;
    }
  }
  outColor = vec4(colour, 1.0);
}`,
    uniforms: (ctx) => ({ u_turns: ctx.params.turns, u_speed: ctx.params.speed, u_height: ctx.camera.height }),
  }),
});
