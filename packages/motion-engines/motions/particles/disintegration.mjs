import { defineMotion } from '../../core/define.mjs';
import { points } from '../../engines/webgl.mjs';
import { hash } from '../../shaders/chunks.mjs';

export default defineMotion({
  id: 'particles-disintegration',
  number: 67,
  module: 'particles',
  name: { en: 'Particle Disintegration', ar: 'تفكّك الجسيمات' },
  summary: {
    en: 'A record card, its frame and field lines made of tightly packed grains, is retired. A line sweeps up through it and every grain it passes breaks loose, glows, and is carried up and away on a curling wind until only dust is left.',
    ar: 'بطاقةُ سجلٍّ، إطارها وأسطر حقولها من حبيباتٍ متراصّة، تُحال إلى الإتلاف. يصعد خطٌّ عبرها وكل حبّةٍ يمرّ بها تنفلت وتتوهّج وتحملها ريحٌ ملتفّة إلى الأعلى بعيدًا حتى لا يبقى إلا الغبار.',
  },
  meaning: {
    en: 'Secure disposal of a retired data record: it is shredded beyond recovery once its retention period ends.',
    ar: 'الإتلاف الآمن لسجلّ بياناتٍ منتهٍ: يُفتَّت بلا إمكانية استرجاع عند انتهاء مدة الاحتفاظ به.',
  },
  engine: 'webgl2-points',
  kind: 'oneshot',
  duration: 3600,
  easing: 'ease-in',
  colors: ['#07070b', '#e2e8f0', '#fb923c', '#f43f5e'],
  params: {
    wind: { default: 1, min: 0.3, max: 2, step: 0.05, label: { en: 'Wind strength', ar: 'قوة الريح' } },
    curl: { default: 1, min: 0, max: 3, step: 0.1, label: { en: 'Curl of the wind', ar: 'التفاف الريح' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'webgl2', cost: 'medium' },
  still: 0.45,
  tags: ['particles', 'gpu', 'exit', 'transition', 'logo', 'dissolve'],
  setup: points({
    count: 14000,
    blend: 'alpha',
    vertex: `
uniform float u_wind;
uniform float u_curl;
${hash}
// A point on the record card: two of every five grains form its frame, the rest its photo box and field lines.
vec2 emblem(vec3 h) {
  vec2 box = vec2(0.85, 0.52);
  if (h.x < 0.4) {
    float along = h.y * 2.0 * (box.x + box.y) * 2.0;
    float edge = 0.025 * (h.z - 0.5);
    if (along < 2.0 * box.x) return vec2(along - box.x, box.y + edge);
    along -= 2.0 * box.x;
    if (along < 2.0 * box.y) return vec2(box.x + edge, box.y - along);
    along -= 2.0 * box.y;
    if (along < 2.0 * box.x) return vec2(box.x - along, -box.y + edge);
    along -= 2.0 * box.x;
    return vec2(-box.x + edge, -box.y + along);
  }
  if (h.x < 0.6) return vec2(-0.68 + h.y * 0.42, -0.3 + h.z * 0.62);
  float row = floor(h.z * 4.0);
  float span = row == 0.0 ? 0.9 : (row == 3.0 ? 0.55 : 0.75);
  return vec2(-0.12 + h.y * span, 0.3 - row * 0.2 + (fract(h.z * 4.0) - 0.5) * 0.05);
}
void main() {
  float id = float(gl_VertexID);
  vec3 h = hash31(id * 0.611 + 2.0);
  vec2 home = emblem(h);
  // The breaking line rises from below the emblem to above it; each grain leaves when it is passed.
  float line = mix(-0.9, 1.1, u_progress);
  float released = clamp((line - home.y) * 1.6 - hash11(id * 3.1) * 0.25, 0.0, 1.0);
  float age = released * released;
  vec2 drift = vec2(0.35, 1.0) * age * u_wind * (0.6 + 0.8 * hash11(id * 1.9));
  float swirl = u_curl * age * 3.0 + h.y * 6.2831853;
  drift += vec2(cos(swirl), sin(swirl)) * age * 0.25 * u_curl;
  vec2 pos = home + drift;
  vec2 screen = pos * 0.85;
  screen.x *= u_resolution.y / u_resolution.x;
  gl_Position = vec4(screen, 0.0, 1.0);
  gl_PointSize = max(1.0, mix(2.2, 1.2, age) * u_resolution.y / 180.0);
  float glow = smoothstep(0.0, 0.15, released) * (1.0 - smoothstep(0.3, 1.0, released));
  vec3 colour = mix(u_color1, mix(u_color2, u_color3, h.z), glow);
  colour = mix(colour, u_color3 * 0.5, smoothstep(0.6, 1.0, released));
  v_color = vec4(colour, 0.9 * (1.0 - smoothstep(0.55, 1.0, released)));
}`,
    fragment: `
void main() {
  float falloff = smoothstep(0.5, 0.2, length(gl_PointCoord - 0.5));
  outColor = vec4(v_color.rgb, v_color.a * falloff);
}`,
    uniforms: (ctx) => ({ u_wind: ctx.params.wind, u_curl: ctx.params.curl }),
  }),
});
