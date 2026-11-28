import { defineMotion } from '../../core/define.mjs';
import { fragment } from '../../engines/webgl.mjs';
import { centred } from '../../shaders/chunks.mjs';

export default defineMotion({
  id: 'glass-metallic-flow',
  number: 35,
  module: 'glass',
  name: { en: 'Metallic Surface Flow', ar: 'انسياب السطح المعدني' },
  summary: {
    en: 'A pool of liquid chrome folds and rolls slowly. It has no colour of its own: it mirrors a dark studio with a cold strip light above and a warm lamp at the side, so the reflections stretch into bands along every fold.',
    ar: 'بركة من الكروم السائل تتثنّى وتتدحرج ببطء. لا لون لها في ذاتها، فهي مرآة لاستوديو معتم يعلوه شريط ضوء بارد وبجانبه مصباح دافئ، فتتمدّد الانعكاسات شرائطَ على امتداد كل ثنية.',
  },
  engine: 'webgl2-glsl',
  kind: 'loop',
  duration: 12000,
  easing: 'ease-out',
  colors: ['#06080c', '#7f8a9c', '#f4f7fb', '#f59e0b'],
  params: {
    scale: { default: 1.3, min: 0.6, max: 3, step: 0.1, label: { en: 'Fold scale', ar: 'حجم الثنيات' } },
    turbulence: { default: 1, min: 0.2, max: 2, step: 0.05, label: { en: 'Turbulence', ar: 'الاضطراب' } },
    polish: { default: 0.8, min: 0, max: 1, step: 0.05, label: { en: 'Polish', ar: 'درجة الصقل' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'webgl2', cost: 'low' },
  still: 0.3,
  tags: ['metal', 'chrome', 'liquid', 'background', 'reflection'],
  setup: fragment({
    fragment: `
uniform float u_scale;
uniform float u_turbulence;
uniform float u_polish;
${centred}
// The height of the metal: a few sine folds, each one bending the next. Time only enters as whole turns, so the loop closes.
float height(vec2 p) {
  float a = u_raw * 6.2831853;
  vec2 q = p * u_scale;
  for (int i = 1; i <= 4; i++) {
    float f = float(i); float way = mod(f, 2.0) * 2.0 - 1.0;
    q += u_turbulence * 0.45 / f * vec2(sin(f * 1.7 * q.y + way * a + 1.3 * f), cos(f * 1.5 * q.x - way * a + 2.1 * f));
  }
  return 0.5 * sin(q.x * 1.6 + a) * cos(q.y * 1.3) + 0.25 * sin((q.x + q.y) * 2.2 - a);
}
// The studio the metal mirrors: floor, wall, a cold strip light and a warm lamp low at one side.
vec3 studio(vec3 r) {
  float soft = mix(0.5, 0.03, u_polish);
  float wall = smoothstep(-soft, soft, r.y + 0.05);
  vec3 colour = mix(u_color0, u_color1 * (0.3 + 0.7 * smoothstep(-0.3, 0.9, r.y)), wall);
  colour += u_color2 * smoothstep(soft, 0.0, abs(r.y - 0.5) - 0.13) * 0.95;
  colour += u_color3 * smoothstep(soft * 1.5, 0.0, abs(r.x + 0.45) - 0.16) * smoothstep(0.15, -0.35, r.y) * 0.85;
  return colour;
}
void main() {
  vec2 p = centredUv();
  float e = 0.012;
  float h = height(p);
  vec2 slope = (vec2(height(p + vec2(e, 0.0)), height(p + vec2(0.0, e))) - h) / e;
  vec3 normal = normalize(vec3(-slope * 0.3 / u_scale, 1.0));
  vec3 colour = studio(reflect(vec3(0.0, 0.0, -1.0), normal));
  colour *= 0.82 + 0.3 * h;                                   // the troughs see less of the room
  float glint = pow(max(dot(normal, normalize(vec3(-0.35, 0.5, 1.0))), 0.0), mix(30.0, 260.0, u_polish));
  colour += u_color2 * glint * 0.6;
  outColor = vec4(mix(u_color0, colour, 0.12 + 0.88 * u_intro), 1.0);
}`,
    uniforms: (ctx) => ({ u_scale: ctx.params.scale, u_turbulence: ctx.params.turbulence, u_polish: ctx.params.polish }),
  }),
});
