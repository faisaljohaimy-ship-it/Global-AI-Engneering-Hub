import { defineMotion } from '../../core/define.mjs';
import { fragment } from '../../engines/webgl.mjs';
import { hash, noise } from '../../shaders/chunks.mjs';

export default defineMotion({
  id: 'atmosphere-volumetric-clouds',
  number: 178,
  module: 'atmosphere',
  name: { en: 'Volumetric Cloud Movement', ar: 'حركة السحب الحجمية' },
  summary: {
    en: 'Cumulus clouds sail overhead in a deep sky, marched through as a real layer of vapour: sunlit tops, shaded bellies and a silver lining toward the sun, thinning into haze at the horizon.',
    ar: 'سحب ركامية تعبر فوق الرأس في سماء عميقة، محسوبة كطبقة حقيقية من البخار: قمم تضيئها الشمس وبطون مظلّلة وحافة فضية جهة الشمس، وكلها تذوب في الغبش عند الأفق.',
  },
  engine: 'webgl2-glsl',
  kind: 'loop',
  duration: 14000,
  easing: 'ease-out',
  colors: ['#1b4f9e', '#fff7ea', '#5f6f92', '#b9d7f1', '#ffd08a'],
  params: {
    coverage: { default: 0.6, min: 0.2, max: 1, step: 0.02, label: { en: 'Cloud cover', ar: 'تغطية السحب' } },
    wind: { default: 1, min: 0, max: 3, step: 0.1, label: { en: 'Wind speed', ar: 'سرعة الرياح' } },
    depth: { default: 1, min: 0.4, max: 2, step: 0.05, label: { en: 'Layer depth', ar: 'سُمك الطبقة' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'webgl2', cost: 'high' },
  still: 0.5,
  tags: ['background', 'sky', 'weather', 'ambient', 'hero'],
  setup: fragment({
    fragment: `
uniform float u_coverage;
uniform float u_wind;
uniform float u_depth;
${hash}${noise}
float billow(vec2 p, int octaves) {
  float value = 0.0; float amplitude = 0.5;
  for (int i = 0; i < octaves; i++) { value += amplitude * noise(p); p = p * 2.1 + vec2(7.3, 3.9); amplitude *= 0.5; }
  return value / (1.0 - 2.0 * amplitude);
}
void main() {
  float unit = min(u_resolution.x, u_resolution.y);
  vec2 p = (2.0 * gl_FragCoord.xy - u_resolution) / unit;
  // The horizon sits a little above the bottom edge whatever the shape of the frame.
  float rise = p.y + u_resolution.y / unit - 0.24;
  vec3 view = normalize(vec3(p.x, rise, 1.5));
  vec3 sun = normalize(vec3(-0.5, 0.5, 1.0));
  float toSun = max(dot(view, sun), 0.0);
  vec3 sky = mix(u_color3, u_color0, pow(clamp(view.y, 0.0, 1.0), 0.6));
  sky += u_color4 * (smoothstep(0.9985, 0.9993, toSun) + pow(toSun, 60.0) * 0.45);
  vec3 colour = sky;
  if (view.y > 0.015) {
    int steps = 4 + 3 * u_quality;
    float low = 1.0;
    float high = 1.0 + 0.8 * u_depth;
    float near = low / view.y;
    float stride = (high - low) / view.y / float(steps);
    float threshold = 0.74 - 0.4 * u_coverage * (0.35 + 0.65 * u_intro);
    vec2 drift = vec2(0.14, 0.4) * u_time * u_wind;
    float clear = 1.0;
    vec3 lit = vec3(0.0);
    for (int i = 0; i < 14; i++) {
      if (i >= steps || clear < 0.03) break;
      vec3 at = view * (near + (float(i) + 0.5) * stride);
      float level = (at.y - low) / (high - low);
      vec2 w = at.xz * 0.8 + drift + level * vec2(0.3, -0.2);
      float profile = smoothstep(0.0, 0.12, level) * smoothstep(1.0, 0.3, level);
      float density = clamp((billow(w, 1 + u_quality) - threshold - (1.0 - profile) * 0.3) * 6.0, 0.0, 1.0);
      if (density > 0.003) {
        float towards = billow(w + sun.xz * 0.3, 2);
        float shadow = clamp((towards - threshold + 0.1) * 2.2 + (1.0 - level) * 0.5 - 0.15, 0.0, 1.0);
        vec3 tone = mix(u_color1, u_color2, shadow) + u_color4 * pow(toSun, 14.0) * (1.0 - density) * 0.5;
        float cover = 1.0 - exp(-density * stride * 7.0);
        lit += clear * cover * tone;
        clear *= 1.0 - cover;
      }
    }
    colour = mix(sky, sky * clear + lit, exp(-near * 0.07));
  } else {
    // Below the horizon: a floor of haze falling into shadow.
    colour = mix(u_color3, mix(u_color2, u_color0, 0.5) * 0.55, smoothstep(0.02, -0.3, rise)) + u_color4 * 0.25 * exp(-abs(p.x + 0.75) * 3.0) * smoothstep(-0.3, 0.0, rise);
  }
  outColor = vec4(colour, 1.0);
}`,
    uniforms: (ctx) => ({ u_coverage: ctx.params.coverage, u_wind: ctx.params.wind, u_depth: ctx.params.depth }),
  }),
});
