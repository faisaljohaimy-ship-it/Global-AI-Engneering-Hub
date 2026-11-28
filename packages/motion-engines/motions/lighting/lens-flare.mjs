import { defineMotion } from '../../core/define.mjs';
import { fragment } from '../../engines/webgl.mjs';
import { frame, hash, noise } from '../../shaders/chunks.mjs';

export default defineMotion({
  id: 'lighting-lens-flare',
  number: 74,
  module: 'lighting',
  name: { en: 'Cinematic Lens Flare', ar: 'وهج العدسة السينمائي' },
  summary: {
    en: 'A low sun crosses a dusk sky above a ridge, in the reading direction. As it moves, a chain of coloured ghosts slides along the line through the centre of the lens, a wide streak stretches sideways, and a starburst blooms when the sun clears the ridge.',
    ar: 'شمسٌ منخفضة تعبر سماء الغسق فوق سلسلة تلال باتجاه القراءة. وهي تتحرّك تنزلق سلسلةٌ من الأشباح الملوّنة على الخط المارّ بمركز العدسة، ويمتدّ خطٌّ عريض جانبيًّا، ويتفتّح وهجٌ نجميّ حين تعلو الشمس فوق التلال.',
  },
  engine: 'webgl2-glsl',
  kind: 'oneshot',
  duration: 4000,
  easing: 'ease-in-out',
  colors: ['#0b0a1a', '#fde68a', '#fb7185', '#38bdf8'],
  params: {
    ghosts: { default: 5, min: 1, max: 9, step: 1, label: { en: 'Ghosts', ar: 'عدد الأشباح' } },
    streak: { default: 0.6, min: 0, max: 1, step: 0.05, label: { en: 'Anamorphic streak', ar: 'الخطّ الأفقي الممتدّ' } },
  },
  rtl: 'mirror',
  requirements: { gpu: 'webgl2', cost: 'low' },
  still: 0.7,
  tags: ['light', 'flare', 'sun', 'cinematic', 'hero'],
  setup: fragment({
    fragment: `
uniform float u_ghosts;
uniform float u_streak;
${hash}${noise}${frame}
float ridge(float x) { return -0.35 + 0.18 * noise(vec2(x * 1.7, 2.0)) + 0.08 * noise(vec2(x * 5.0, 7.0)); }
void main() {
  vec2 p = frameUv();
  float aspect = max(u_resolution.x, u_resolution.y) / min(u_resolution.x, u_resolution.y);
  float travel = mix(-1.1, 1.1, u_progress) * aspect * 0.8;
  vec2 sun = vec2(travel, -0.3 + 0.75 * sin(3.14159265 * clamp(u_progress * 0.85 + 0.08, 0.0, 1.0)));
  vec3 colour = mix(u_color2 * 0.35 + u_color0, u_color0, smoothstep(-0.4, 0.9, p.y));
  // How much of the sun is above the ridge decides how strong the flare is.
  float clear = smoothstep(-0.05, 0.12, sun.y - ridge(sun.x));
  float d = length(p - sun);
  colour += u_color1 * (0.04 / (d + 0.04)) * (0.4 + 0.6 * clear);
  colour += u_color1 * smoothstep(0.07, 0.05, d);
  // Starburst: thin rays at fixed angles that brighten as the sun clears the ridge.
  float a = atan(p.y - sun.y, p.x - sun.x);
  float rays = pow(abs(cos(a * 6.0)), 40.0) + 0.6 * pow(abs(cos(a * 9.0 + 0.5)), 60.0);
  colour += u_color1 * rays * exp(-d * 3.0) * clear * 0.6;
  // The streak: a long, thin horizontal glow through the sun.
  colour += u_color3 * exp(-abs(p.y - sun.y) * 60.0) * exp(-abs(p.x - sun.x) * 1.2) * u_streak * clear;
  // Ghosts sit on the line from the sun through the centre, each its own size and colour.
  for (int i = 0; i < 9; i++) {
    if (float(i) >= u_ghosts) break;
    float k = -0.35 - 0.3 * float(i) + 0.9 * hash11(float(i) * 3.7);
    vec2 at = sun * k;
    float size = 0.03 + 0.09 * hash11(float(i) * 9.1);
    float g = smoothstep(size, size * 0.7, length(p - at));
    float ring = smoothstep(0.012, 0.0, abs(length(p - at) - size));
    vec3 tint = mix(u_color2, u_color3, hash11(float(i) * 5.3));
    colour += tint * (g * 0.16 + ring * 0.22) * clear;
  }
  // The ridge in silhouette, rimmed by the light behind it.
  float edge = ridge(p.x);
  float below = smoothstep(edge + 0.004, edge - 0.004, p.y);
  float rim = smoothstep(0.03, 0.0, abs(p.y - edge)) * exp(-abs(p.x - sun.x) * 2.5) * (1.0 - clear * 0.5);
  colour = mix(colour, u_color0 * 0.6, below) + u_color1 * rim * 0.8;
  outColor = vec4(colour, 1.0);
}`,
    uniforms: (ctx) => ({ u_ghosts: Math.round(ctx.params.ghosts), u_streak: ctx.params.streak }),
  }),
});
