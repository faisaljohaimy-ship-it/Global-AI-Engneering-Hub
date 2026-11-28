import { defineMotion } from '../../core/define.mjs';
import { fragment } from '../../engines/webgl.mjs';
import { hash, noise } from '../../shaders/chunks.mjs';

export default defineMotion({
  id: 'atmosphere-procedural-fog',
  number: 171,
  module: 'atmosphere',
  name: { en: 'Procedural Atmospheric Fog', ar: 'الضباب الجوي الإجرائي' },
  summary: {
    en: 'Sheets of fog drift between forested ridges at dawn: each ridge is paler than the one in front of it, and the valleys fill and empty as the wisps pass.',
    ar: 'طبقات من الضباب تنساب بين تلال مكسوّة بالأشجار عند الفجر: كل تلّ أبهت من الذي أمامه، والوديان تمتلئ وتنكشف مع مرور خيوط الضباب.',
  },
  engine: 'webgl2-glsl',
  kind: 'loop',
  duration: 12000,
  easing: 'ease-out',
  colors: ['#0b1a20', '#c3d3ca', '#1f474c', '#f5c48d'],
  params: {
    density: { default: 1, min: 0.2, max: 1.8, step: 0.05, label: { en: 'Fog density', ar: 'كثافة الضباب' } },
    drift: { default: 1, min: 0, max: 3, step: 0.1, label: { en: 'Drift speed', ar: 'سرعة الانسياب' } },
    layers: { default: 5, min: 3, max: 7, step: 1, label: { en: 'Ridges in depth', ar: 'عدد التلال في العمق' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'webgl2', cost: 'medium' },
  still: 0.5,
  tags: ['background', 'ambient', 'landscape', 'weather', 'hero'],
  setup: fragment({
    fragment: `
uniform float u_density;
uniform float u_drift;
uniform float u_layers;
${hash}${noise}
float wisps(vec2 p) {
  float value = 0.0; float amplitude = 0.55;
  for (int i = 0; i < u_quality; i++) { value += amplitude * noise(p); p = p * 2.07 + vec2(13.7, 5.1); amplitude *= 0.5; }
  return value;
}
float pines(float x, float seed) {
  float cell = floor(x); float f = abs(fract(x) - 0.5 + 0.3 * (hash11(cell * 2.3 + seed) - 0.5)) * 2.0;
  return (0.3 + 0.7 * hash11(cell + seed)) * max(0.0, 1.0 - f * (1.5 + 1.5 * hash11(cell * 1.7 + seed + 4.0)));
}
void main() {
  vec2 uv = gl_FragCoord.xy / u_resolution;
  float aspect = u_resolution.x / u_resolution.y;
  float x = (uv.x - 0.5) * aspect;
  float t = u_time;
  float sun = length(vec2(x - 0.2 * aspect, uv.y - 0.72));
  float glow = exp(-sun * 2.4);
  vec3 haze = mix(u_color1, u_color3, 0.15 + 0.6 * glow);
  vec3 colour = mix(haze, mix(u_color2, u_color0, 0.3), smoothstep(0.4, 1.1, uv.y));
  colour += u_color3 * (smoothstep(0.085, 0.04, sun) * 0.7 + glow * 0.3);
  float count = floor(u_layers + 0.5);
  float soft = 1.5 / u_resolution.y;
  float f = 0.5;
  for (int i = 0; i < 7; i++) {
    if (float(i) >= count) break;
    float z = (float(i) + 1.0) / count;
    float seed = float(i) * 17.3;
    float sx = x * (0.9 + 0.7 * z) + t * 0.01 * (0.3 + 2.0 * z);
    float ridge = 0.5 + 0.3 * sin(sx * 2.1 + seed) + 0.14 * sin(sx * 5.3 + seed * 1.7) + 0.06 * sin(sx * 12.7 + seed * 0.6);
    float base = mix(0.6, 0.13, z);
    float trees = max(pines(sx * mix(64.0, 26.0, z), seed), 0.75 * pines(sx * mix(41.0, 17.0, z) + 3.7, seed + 9.0));
    float top = base + (ridge - 0.5) * mix(0.3, 0.15, z) + trees * 0.075 * z * smoothstep(0.25, 0.6, z);
    vec3 land = mix(haze, mix(u_color2, u_color0, z), 0.1 + 0.9 * pow(z, 1.5));
    colour = mix(colour, land, smoothstep(top + soft, top - soft, uv.y));
    float way = mod(float(i), 2.0) < 0.5 ? 1.0 : -1.0;
    f = wisps(vec2(sx * 1.5 + seed + way * t * u_drift * (0.03 + 0.07 * z), uv.y * 5.0 + seed + t * u_drift * 0.012));
    float level = base - 0.09 + 0.06 * u_density + (f - 0.5) * 0.34;
    float sheet = smoothstep(level + 0.03, level - 0.15, uv.y) + 0.35 * smoothstep(0.55, 0.9, f) * smoothstep(base + 0.3, base, uv.y);
    vec3 fog = haze * (0.8 + 0.3 * smoothstep(level - 0.14, level + 0.03, uv.y) * (0.5 + f));
    colour = mix(colour, fog, clamp(sheet * u_density * (0.95 - 0.5 * z), 0.0, 0.97));
  }
  colour = mix(colour, haze * 0.92, clamp(smoothstep(0.3, -0.1, uv.y - f * 0.3) * 0.45 * u_density, 0.0, 0.9));
  colour = mix(haze, colour, 0.25 + 0.75 * u_intro);
  vec2 q = uv - 0.5;
  outColor = vec4(colour * (1.0 - 0.45 * dot(q, q)), 1.0);
}`,
    uniforms: (ctx) => ({ u_density: ctx.params.density, u_drift: ctx.params.drift, u_layers: ctx.params.layers }),
  }),
});
