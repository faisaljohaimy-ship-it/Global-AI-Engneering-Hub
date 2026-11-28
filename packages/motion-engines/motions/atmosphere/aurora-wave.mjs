import { defineMotion } from '../../core/define.mjs';
import { fragment } from '../../engines/webgl.mjs';
import { hash, noise } from '../../shaders/chunks.mjs';

export default defineMotion({
  id: 'atmosphere-aurora-wave',
  number: 175,
  module: 'atmosphere',
  name: { en: 'Aurora Energy Wave', ar: 'موجة الشفق القطبي' },
  summary: {
    en: 'Curtains of aurora hang over a dark ridge under the stars: their lower hems ripple like cloth while fine rays climb from green into violet and surges of light travel along the folds.',
    ar: 'ستائر من الشفق القطبي تتدلّى فوق سلسلة تلال معتمة تحت النجوم: حوافّها السفلى تتموّج كالقماش، وأشعتها الدقيقة تصعد من الأخضر إلى البنفسجي، ودفقات الضوء تسري على طول الطيّات.',
  },
  engine: 'webgl2-glsl',
  kind: 'loop',
  duration: 12000,
  easing: 'ease-out',
  colors: ['#020716', '#3bf7a2', '#9d5cff', '#eafff6', '#0e1c2a'],
  params: {
    curtains: { default: 3, min: 1, max: 5, step: 1, label: { en: 'Curtains', ar: 'عدد الستائر' } },
    reach: { default: 1, min: 0.4, max: 1.8, step: 0.05, label: { en: 'Ray height', ar: 'ارتفاع الأشعة' } },
    sway: { default: 1, min: 0, max: 2.5, step: 0.05, label: { en: 'Sway of the folds', ar: 'تمايل الطيّات' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'webgl2', cost: 'medium' },
  still: 0.5,
  tags: ['background', 'ambient', 'night', 'sky', 'hero'],
  setup: fragment({
    fragment: `
uniform float u_curtains;
uniform float u_reach;
uniform float u_sway;
${hash}${noise}
void main() {
  float unit = min(u_resolution.x, u_resolution.y);
  vec2 uv = gl_FragCoord.xy / u_resolution;
  float x = (gl_FragCoord.x - 0.5 * u_resolution.x) / unit;
  float t = u_time;
  vec3 colour = mix(u_color0 + u_color1 * 0.05, u_color0, smoothstep(0.0, 0.8, uv.y));
  // Stars.
  vec2 grid = gl_FragCoord.xy / unit * 30.0;
  vec2 cell = floor(grid);
  vec2 spot = fract(grid) - 0.5 - (hash22(cell) - 0.5) * 0.6;
  float twinkle = 0.6 + 0.4 * sin(t * (1.0 + 3.0 * hash21(cell + 9.0)) + 40.0 * hash21(cell + 4.0));
  colour += u_color3 * step(0.84, hash21(cell + 2.0)) * smoothstep(0.2, 0.0, length(spot)) * twinkle;
  // Curtains, far to near: a sharp rippling hem, rays fading upward.
  float count = floor(u_curtains + 0.5);
  float skyGlow = 0.0;
  for (int i = 0; i < 5; i++) {
    if (float(i) >= count) break;
    float k = float(i);
    float z = (k + 0.5) / count;
    float sx = x * (0.8 + 0.6 * z) + k * 2.7;
    float way = mod(k, 2.0) < 0.5 ? 1.0 : -1.0;
    float fold = u_sway * (0.1 * sin(sx * 2.3 + way * t * 0.45 + k * 1.9) + 0.045 * sin(sx * 5.9 - way * t * 0.7 + k * 4.2));
    float hem = mix(0.52, 0.25, z) + fold;
    float tall = u_reach * (0.38 + 0.2 * z) * (0.75 + 0.25 * sin(sx * 1.3 + t * 0.3 + k)) * (0.3 + 0.7 * u_intro);
    float h = uv.y - hem;
    float lean = sx + h * 0.25 * sin(sx * 1.1 + k);
    float rays = (0.35 + 0.65 * noise(vec2(lean * 16.0 + way * t * 0.5, k * 7.3))) * (0.55 + 0.45 * noise(vec2(lean * 52.0 - way * t * 0.8, k * 3.1)));
    float surge = 0.25 + 0.75 * noise(vec2(sx * 1.4 - way * t * 0.3, k * 5.7 + t * 0.08));
    float body = smoothstep(-0.01, 0.01, h) * exp(-max(h, 0.0) / tall * 1.7);
    float edge = exp(-pow(h / 0.014, 2.0));
    float light = (body * rays * 1.7 + edge * 0.35) * surge * (0.55 + 0.45 * z) * u_intro;
    colour += mix(u_color1, u_color2, smoothstep(0.0, 0.6, h / tall)) * light + u_color3 * edge * surge * rays * 0.3 * u_intro;
    skyGlow += surge * (0.55 + 0.45 * z) / count;
  }
  // The ridge below, faintly lit by the sky.
  float ridge = 0.09 + 0.08 * noise(vec2(x * 2.6 + 4.0, 1.5)) + 0.025 * noise(vec2(x * 11.0, 8.0));
  float soft = 1.5 / u_resolution.y;
  vec3 land = u_color4 * (0.55 + 0.9 * uv.y / ridge * (0.4 + 0.6 * noise(vec2(x * 30.0, uv.y * 60.0)))) + u_color1 * 0.12 * skyGlow * u_intro * uv.y / ridge;
  colour = mix(colour, land, smoothstep(ridge + soft, ridge - soft, uv.y));
  outColor = vec4(colour, 1.0);
}`,
    uniforms: (ctx) => ({ u_curtains: ctx.params.curtains, u_reach: ctx.params.reach, u_sway: ctx.params.sway }),
  }),
});
