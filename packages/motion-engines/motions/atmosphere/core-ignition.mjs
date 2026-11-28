import { defineMotion } from '../../core/define.mjs';
import { fragment } from '../../engines/webgl.mjs';
import { hash, noise } from '../../shaders/chunks.mjs';

export default defineMotion({
  id: 'atmosphere-core-ignition',
  number: 179,
  module: 'atmosphere',
  name: { en: 'Energy Core Ignition', ar: 'اشتعال نواة الطاقة' },
  summary: {
    en: 'Containment rings arm from the outside in while streaks of charge converge on a dim seed. The seed ignites with a flash and a shock ring, then settles into a boiling core that throws steady beams.',
    ar: 'حلقات الاحتواء تتأهّب من الخارج إلى الداخل وخيوط الشحنة تتجمّع نحو بذرة خافتة. تشتعل البذرة بوميض وحلقة صدمة، ثم تستقرّ نواةً تغلي وترسل حزمًا ثابتة من الضوء.',
  },
  engine: 'webgl2-glsl',
  kind: 'oneshot',
  duration: 3600,
  easing: 'ease-in-out',
  colors: ['#06030c', '#48c8f0', '#ffae1a', '#fff2d2', '#f0308c'],
  params: {
    power: { default: 1, min: 0.4, max: 2, step: 0.05, label: { en: 'Core power', ar: 'قدرة النواة' } },
    rings: { default: 3, min: 1, max: 6, step: 1, label: { en: 'Containment rings', ar: 'حلقات الاحتواء' } },
    rays: { default: 8, min: 3, max: 16, step: 1, label: { en: 'Beams', ar: 'عدد الحزم' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'webgl2', cost: 'low' },
  still: 0.85,
  tags: ['reveal', 'energy', 'hero', 'launch', 'science-fiction'],
  setup: fragment({
    fragment: `
uniform float u_power;
uniform float u_rings;
uniform float u_rays;
${hash}${noise}
void main() {
  float unit = min(u_resolution.x, u_resolution.y);
  vec2 p = (2.0 * gl_FragCoord.xy - u_resolution) / unit;
  float px = 2.0 / unit;
  float r = length(p);
  float turn = atan(p.y, p.x) / 6.2831853 + 0.5;
  float g = u_progress;
  float charge = smoothstep(0.0, 0.42, g);
  float lit = smoothstep(0.4, 0.5, g);
  float settle = smoothstep(0.5, 1.0, g);
  float flash = exp(-pow((g - 0.455) / 0.045, 2.0));
  vec3 colour = vec3(0.0);
  // Containment rings: dashed bands that arm from the outside in and counter-rotate.
  float count = floor(u_rings + 0.5);
  for (int i = 0; i < 6; i++) {
    if (float(i) >= count) break;
    float k = float(i);
    float radius = 0.36 + 0.52 * (k + 0.5) / count;
    float armed = smoothstep(0.0, 0.25, charge - (count - 1.0 - k) / count * 0.7);
    float way = mod(k, 2.0) < 0.5 ? 1.0 : -1.0;
    float dash = smoothstep(0.07, 0.11, abs(fract((turn + way * g * (0.25 + 0.08 * k)) * (3.0 + 2.0 * k)) - 0.5));
    float band = smoothstep(0.013 + px, 0.013, abs(r - radius));
    float guide = smoothstep(px * 1.5, 0.0, abs(r - radius - 0.035));
    colour += u_color1 * (band * dash * (0.14 + 0.86 * armed) + guide * (0.12 + 0.2 * armed)) * (1.0 + 1.5 * flash);
  }
  // Charge converging on the seed before ignition.
  float sector = floor(turn * 36.0);
  vec3 chance = hash31(sector + 3.0);
  float travel = fract(r * 1.2 + g * (5.0 + 6.0 * chance.x) + chance.y);
  float streak = smoothstep(0.7, 1.0, travel) * smoothstep(0.5, 0.1, abs(fract(turn * 36.0) - 0.5)) * step(0.4, chance.z);
  colour += u_color4 * streak * charge * (1.0 - lit) * smoothstep(0.08, 0.22, r) * smoothstep(1.4, 0.8, r);
  // Beams and the shock ring thrown by the ignition.
  float seed = 0.035 + 0.05 * charge;
  float coreR = mix(seed, 0.2 * sqrt(u_power), lit) * (1.0 + 0.5 * flash);
  float body = smoothstep(coreR + px, coreR - px, r);
  float beams = floor(u_rays + 0.5);
  float beam = pow(abs(cos((turn + g * 0.12) * 3.14159265 * beams)), 24.0) * (0.65 + 0.35 * noise(vec2(r * 9.0 - g * 12.0, turn * beams)));
  float fall = exp(-max(r - coreR, 0.0) * (3.6 - 1.1 * min(u_power, 2.0)));
  colour += (u_color2 * beam * 0.8 + u_color3 * pow(beam, 3.0) * 0.5) * fall * lit * (0.5 + 0.5 * settle) * u_power;
  float ringAt = (g - 0.44) * 3.2;
  float ring = exp(-pow((r - ringAt) / 0.05, 2.0)) * step(0.44, g) * (1.0 - smoothstep(0.5, 0.85, g));
  colour += u_color3 * (ring * 0.9 + flash * 0.7 / (1.0 + 6.0 * r * r));
  // The core itself: a seed that becomes a boiling sphere.
  float halo = coreR * coreR / (r * r + 0.5 * coreR * coreR);
  colour += mix(u_color4, u_color2, lit) * halo * (0.22 + 0.5 * lit * u_power);
  float depth = sqrt(max(0.0, 1.0 - r * r / (coreR * coreR)));
  float boil = 0.6 * noise(p / coreR * 2.5 + vec2(g * 6.0, -g * 4.0)) + 0.4 * noise(p / coreR * 6.0 - vec2(g * 9.0, g * 3.0));
  vec3 core = mix(u_color4, mix(u_color2, u_color3, clamp(boil * 1.5 * depth + 0.15, 0.0, 1.0)), lit) * (0.55 + 0.6 * depth) + u_color3 * flash;
  colour = mix(colour, core, body);
  outColor = vec4(u_color0 + colour, 1.0);
}`,
    uniforms: (ctx) => ({ u_power: ctx.params.power, u_rings: ctx.params.rings, u_rays: ctx.params.rays }),
  }),
});
