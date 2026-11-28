import { defineMotion } from '../../core/define.mjs';
import { fragment } from '../../engines/webgl.mjs';
import { fbm, hash, noise } from '../../shaders/chunks.mjs';

export default defineMotion({
  id: 'atmosphere-shockwave',
  number: 180,
  module: 'atmosphere',
  name: { en: 'Atmospheric Shockwave', ar: 'موجة الصدمة الجوية' },
  summary: {
    en: 'A blast on the horizon drives a dome of compressed air across the sky: the front bends the clouds behind it, trails a veil of condensation, tears a hole in the cloud deck and rakes dust off the ground.',
    ar: 'انفجار عند الأفق يدفع قبّة من الهواء المضغوط عبر السماء: جبهتها تحني السحب من خلفها وتجرّ وراءها ستارًا من التكاثف، فتفتح فجوة في غطاء السحب وتثير الغبار عن الأرض.',
  },
  engine: 'webgl2-glsl',
  kind: 'oneshot',
  duration: 3200,
  easing: 'linear',
  colors: ['#0d1630', '#f3f7ff', '#8fa3c9', '#ff9440', '#c7a57e'],
  params: {
    force: { default: 1, min: 0.4, max: 2, step: 0.05, label: { en: 'Blast force', ar: 'قوة الانفجار' } },
    width: { default: 1, min: 0.5, max: 2.5, step: 0.05, label: { en: 'Front thickness', ar: 'سُمك الجبهة' } },
    clouds: { default: 1, min: 0, max: 1.5, step: 0.05, label: { en: 'Cloud cover', ar: 'تغطية السحب' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'webgl2', cost: 'medium' },
  still: 0.38,
  tags: ['impact', 'transition', 'reveal', 'weather', 'cinematic'],
  setup: fragment({
    fragment: `
uniform float u_force;
uniform float u_width;
uniform float u_clouds;
${hash}${noise}${fbm}
void main() {
  float unit = min(u_resolution.x, u_resolution.y);
  // q is measured from the blast point on the ground, in units of the short side.
  vec2 q = (gl_FragCoord.xy - vec2(0.5, 0.24) * u_resolution) / unit;
  float g = u_progress;
  float d = length(q);
  vec2 away = q / max(d, 1e-4);
  float span = length(vec2(0.5, 0.76) * u_resolution) / unit;
  float radius = span * 1.12 * pow(g, 0.7);
  float width = 0.03 * u_width * (0.7 + g);
  float x = (d - radius) / width;
  float strength = u_force * (1.0 - 0.6 * g) * smoothstep(0.0, 0.05, g);
  float passed = smoothstep(0.5, -1.5, x);
  float above = smoothstep(0.0, 0.02, q.y);
  // The front refracts what is behind it; the air it has crossed stays pushed outward.
  vec2 look = q + away * x * exp(-x * x) * width * 2.4 * strength;
  vec2 cq = look - away * passed * 0.12 * u_force * d / max(radius, 1e-3);
  vec3 sky = mix(mix(u_color0, u_color3, 0.55), u_color0, smoothstep(0.0, 0.9, look.y));
  float deck = fbm(vec2(cq.x * 1.7 + 2.0, cq.y * 4.5));
  float wisps = fbm(vec2(cq.x * 5.0 - 1.0, cq.y * 11.0 + 4.0));
  float cloud = smoothstep(0.62, 0.9, deck * 0.75 + wisps * 0.35 + 0.22 * u_clouds) * smoothstep(0.02, 0.3, cq.y);
  cloud *= (1.0 - 0.95 * passed * exp(-d * 0.8)) * min(u_clouds, 1.0);
  vec3 colour = mix(sky, mix(u_color2, u_color1, 0.2 + 0.6 * deck), cloud);
  // The compression front and the condensation that trails it.
  float vapour = exp(-pow((x + 1.6) / 1.4, 2.0)) * (0.3 + 0.7 * fbm(q * 9.0 - away * g * 2.0));
  colour += u_color1 * (exp(-x * x) * 0.75 + vapour * 0.55) * strength * above;
  // Dust raked off the ground behind the front, settling as it ages.
  float gx = abs(q.x);
  float age = clamp((radius - gx) / max(radius, 1e-3), 0.0, 1.0);
  float rise = (0.04 + 0.11 * u_force) * (0.35 + 0.65 * fbm(vec2(q.x * 6.0, g * 2.0))) * smoothstep(0.0, 0.25, age) * (1.0 - 0.45 * g);
  float dust = smoothstep(radius, radius - 0.1, gx) * smoothstep(rise, 0.0, q.y) * (0.5 + 0.5 * fbm(vec2(q.x * 10.0 - sign(q.x) * g * 3.0, q.y * 14.0 - g * 2.0)));
  colour = mix(colour, u_color4, clamp(dust * 0.85, 0.0, 1.0) * above);
  // The fireball cools into a rising column of smoke.
  vec2 capAt = vec2(0.0, 0.04 + 0.22 * pow(g, 0.7) * sqrt(u_force));
  float capR = 0.04 + 0.09 * g * sqrt(u_force);
  float cap = smoothstep(capR, capR * 0.5, length((q - capAt) * vec2(0.8, 1.25)) + (fbm(q * 14.0 + g * 2.0) - 0.5) * 0.05);
  float stem = smoothstep(0.03 + 0.02 * g, 0.01, abs(q.x) + (noise(vec2(q.y * 20.0, g * 5.0)) - 0.5) * 0.02) * smoothstep(capAt.y, capAt.y - 0.02, q.y);
  vec3 smoke = mix(u_color3, mix(u_color4, u_color0, 0.45), smoothstep(0.1, 0.7, g));
  colour = mix(colour, smoke, max(cap, stem) * smoothstep(0.02, 0.12, g) * above);
  // The ground, lit where the front is crossing it.
  vec3 soil = mix(u_color0 * 0.5, u_color4 * 0.4, smoothstep(-0.3, 0.0, q.y)) * (0.8 + 0.4 * noise(vec2(q.x * 14.0, q.y * 50.0)));
  soil += u_color1 * exp(-pow((gx - radius) / (width * 1.5), 2.0)) * strength * exp(q.y * 8.0) * 0.6;
  colour = mix(soil, colour, smoothstep(-0.004, 0.004, q.y));
  float fire = exp(-d * d / (0.004 + 0.03 * g * u_force)) * exp(-g * 3.5);
  colour += u_color3 * (fire * 1.5 + 0.25 * exp(-g * 6.0)) + u_color1 * fire * fire;
  outColor = vec4(colour, 1.0);
}`,
    uniforms: (ctx) => ({ u_force: ctx.params.force, u_width: ctx.params.width, u_clouds: ctx.params.clouds }),
  }),
});
