import { defineMotion } from '../../core/define.mjs';
import { fragment } from '../../engines/webgl.mjs';
import { centred, fbm, hash, noise } from '../../shaders/chunks.mjs';

export default defineMotion({
  id: 'lighting-volumetric-beams',
  number: 71,
  module: 'lighting',
  name: { en: 'Volumetric Light Beams', ar: 'حزم الضوء الحجمية' },
  summary: {
    en: 'Shafts of light fall through a high slatted window into a dusty hall. Drifting haze thickens and thins inside the beams, motes glitter only where the light catches them, and the beams pool on the floor.',
    ar: 'أعمدةٌ من الضوء تسقط عبر نافذةٍ عالية ذات شرائح في قاعةٍ مغبرّة. يتكاثف الضباب الهائم ويخفّ داخل الحزم، ويلمع الغبار حيث يمسّه الضوء وحده، وتتجمّع الحزم بقعًا على الأرض.',
  },
  engine: 'webgl2-glsl',
  kind: 'loop',
  duration: 12000,
  easing: 'ease-out',
  colors: ['#07060a', '#fcd34d', '#f59e0b', '#475569'],
  params: {
    slats: { default: 6, min: 2, max: 12, step: 1, label: { en: 'Window slats', ar: 'شرائح النافذة' } },
    dust: { default: 0.6, min: 0, max: 1, step: 0.05, label: { en: 'Dust in the air', ar: 'كثافة الغبار في الهواء' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'webgl2', cost: 'low' },
  still: 0.3,
  tags: ['light', 'atmosphere', 'background', 'cinematic', 'interior'],
  setup: fragment({
    fragment: `
uniform float u_slats;
uniform float u_dust;
${hash}${noise}${fbm}${centred}
void main() {
  vec2 p = centredUv();
  vec2 source = vec2(-0.55, 1.35);
  vec2 toPixel = p - source;
  float angle = atan(toPixel.x, -toPixel.y);
  float reach = length(toPixel);
  // The window lets light through between its slats: a set of angular openings that sway slightly.
  float opening = fract((angle - 0.25) * u_slats * 1.6 + 0.04 * sin(u_time * 0.4));
  float beam = smoothstep(0.05, 0.2, opening) * smoothstep(0.75, 0.55, opening);
  beam *= smoothstep(-0.25, 0.05, angle) * smoothstep(0.85, 0.55, angle);
  float haze = fbm(vec2(p.x * 2.2 - u_time * 0.08, p.y * 1.6 + u_time * 0.05));
  float density = (0.35 + 0.65 * haze) * mix(0.5, 1.0, u_dust);
  float falloff = exp(-reach * 0.55);
  vec3 colour = mix(u_color0, u_color3 * 0.35, smoothstep(-1.0, 1.0, p.y) * 0.6);
  // The floor, and the bright patches the beams leave on it.
  float floorLine = smoothstep(-0.62, -0.66, p.y);
  colour = mix(colour, u_color3 * 0.22 + u_color0, floorLine);
  colour += mix(u_color2, u_color1, beam) * beam * density * falloff * 1.4 * u_intro;
  colour += u_color1 * beam * floorLine * 0.35 * u_intro;
  // Motes: specks that drift on their own paths and only shine inside a beam.
  vec2 grid = p * 26.0 + vec2(u_time * 0.5, -u_time * 0.25);
  vec2 cell = floor(grid);
  vec2 wobble = vec2(sin(u_time + hash21(cell) * 6.28), cos(u_time * 0.8 + hash21(cell + 3.0) * 6.28)) * 0.25;
  float mote = smoothstep(0.09, 0.0, length(fract(grid) - 0.5 - wobble)) * step(1.0 - 0.25 * u_dust, hash21(cell + 9.0));
  colour += u_color1 * mote * beam * 1.6 * u_intro;
  // The window itself, glowing at the top of the frame.
  colour += u_color1 * smoothstep(0.45, 0.0, length((p - source) * vec2(1.0, 2.0)) - 0.25) * 0.6;
  outColor = vec4(colour, 1.0);
}`,
    uniforms: (ctx) => ({ u_slats: Math.round(ctx.params.slats), u_dust: ctx.params.dust }),
  }),
});
