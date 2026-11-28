import { defineMotion } from '../../core/define.mjs';
import { fragment } from '../../engines/webgl.mjs';
import { centred, hash } from '../../shaders/chunks.mjs';

export default defineMotion({
  id: 'camera-focus-pull',
  number: 15,
  module: 'camera',
  name: { en: 'Dynamic Focus Pull', ar: 'سحب التركيز الديناميكي' },
  summary: {
    en: 'Three planes of a scene: leaves of light close to the lens, a ringed emblem in the middle and a city of tiny lamps far away. The focus is pulled from the near plane through the emblem to the lamps, and every shape blurs into a soft disc by its distance from the plane in focus.',
    ar: 'ثلاثة مستويات في المشهد: أوراقٌ من الضوء قريبة من العدسة، وشعارٌ ذو حلقات في الوسط، ومدينةٌ من مصابيح صغيرة في البعيد. يُسحب التركيز من المستوى القريب عبر الشعار إلى المصابيح، فيذوب كلّ شكلٍ قرصًا ناعمًا بقدر بُعده عن مستوى التركيز.',
  },
  engine: 'webgl2-glsl',
  kind: 'oneshot',
  duration: 4200,
  easing: 'ease-in-out',
  colors: ['#060812', '#fbbf24', '#60a5fa', '#f472b6', '#e2e8f0'],
  params: {
    aperture: { default: 1, min: 0.3, max: 2, step: 0.05, label: { en: 'Aperture (depth of field)', ar: 'فتحة العدسة (عمق الميدان)' } },
    lamps: { default: 28, min: 8, max: 40, step: 1, label: { en: 'Distant lamps', ar: 'المصابيح البعيدة' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'webgl2', cost: 'low' },
  still: 0.5,
  tags: ['camera', 'focus', 'depth', 'bokeh', 'cinematic'],
  setup: fragment({
    fragment: `
uniform float u_aperture;
uniform float u_lamps;
${hash}${centred}
// Circle of confusion: how wide a point at depth z spreads when the lens is focused at f.
float blurAt(float z, float f) { return 0.004 + u_aperture * 0.09 * abs(1.0 / z - 1.0 / f); }
// A disc drawn with an edge as soft as its blur, its light spread over its area.
float disc(vec2 p, vec2 c, float r, float blur) {
  float d = length(p - c) - r;
  return smoothstep(blur, -blur, d) * min(1.0, r * r / ((r + blur) * (r + blur)) * 1.6);
}
void main() {
  vec2 p = centredUv();
  // Focus moves from 1 (near leaves) to 3 (emblem) to 12 (city).
  float focus = u_progress < 0.5 ? mix(1.0, 3.0, smoothstep(0.0, 0.5, u_progress)) : mix(3.0, 12.0, smoothstep(0.5, 1.0, u_progress));
  vec3 colour = mix(u_color0, u_color0 + u_color2 * 0.08, smoothstep(-1.0, 1.0, p.y));
  // Far: a horizon of small lamps at depth 12.
  float bFar = blurAt(12.0, focus);
  for (int i = 0; i < 40; i++) {
    if (float(i) >= u_lamps) break;
    vec3 h = hash31(float(i) * 4.13 + 1.0);
    vec2 c = vec2((h.x * 2.0 - 1.0) * 1.9, -0.25 + 0.3 * h.y * h.y);
    float twinkle = 0.75 + 0.25 * sin(u_time * (1.0 + 2.0 * h.z) + h.x * 30.0);
    colour += mix(u_color1, u_color4, h.z) * disc(p, c, 0.012 + 0.01 * h.z, bFar) * twinkle;
  }
  // Middle: the emblem at depth 3, a ring with a bar through it.
  float bMid = blurAt(3.0, focus);
  float r = length(p - vec2(0.0, 0.05));
  float ring = smoothstep(0.04 + bMid, 0.04 - bMid * 0.2, abs(r - 0.36));
  float bar = smoothstep(0.035 + bMid, 0.035 - bMid * 0.2, abs(p.y - 0.05)) * step(abs(p.x), 0.52);
  float inner = smoothstep(0.12 + bMid, 0.12 - bMid, r);
  float emblem = max(max(ring, bar), inner) * (0.6 + 0.4 * 0.04 / (0.04 + bMid));
  colour = mix(colour, mix(u_color2, u_color4, inner), emblem * 0.9);
  // Near: large leaves of light at depth 1, drifting slowly.
  float bNear = blurAt(1.0, focus);
  for (int i = 0; i < 6; i++) {
    vec3 h = hash31(float(i) * 7.7 + 3.0);
    vec2 c = vec2((h.x * 2.0 - 1.0) * 1.6 + 0.05 * sin(u_time * 0.5 + h.y * 6.0), (h.y * 2.0 - 1.0) * 0.9);
    c *= 1.0 + 0.2 * step(0.4, length(c));
    float leaf = disc(p, c, 0.07 + 0.08 * h.z, bNear);
    colour += mix(u_color3, u_color1, h.z) * leaf * 0.85;
  }
  outColor = vec4(colour, 1.0);
}`,
    uniforms: (ctx) => ({ u_aperture: ctx.params.aperture, u_lamps: Math.round(ctx.params.lamps) }),
  }),
});
