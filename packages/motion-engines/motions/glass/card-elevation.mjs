import { defineMotion } from '../../core/define.mjs';
import { fragment } from '../../engines/webgl.mjs';
import { centred, sdf } from '../../shaders/chunks.mjs';

export default defineMotion({
  id: 'glass-card-elevation',
  number: 34,
  module: 'glass',
  name: { en: 'Glass Card Elevation', ar: 'ارتفاع البطاقة الزجاجية' },
  summary: {
    en: 'A glass card lying flat on a lit backdrop rises toward the viewer. Its shadow drops away and softens, the backdrop seen through it turns to frost, and a sheen crosses the face before it settles.',
    ar: 'بطاقة زجاجية مستلقية على خلفية مضيئة ترتفع نحو المشاهد، فيبتعد ظلّها ويلين، وتتحوّل الخلفية التي تُرى من خلالها إلى زجاج مُصنفر، وتعبر وجهَها لمعة قبل أن تستقر.',
  },
  engine: 'webgl2-glsl',
  kind: 'oneshot',
  duration: 1800,
  easing: 'ease-out-cubic',
  colors: ['#0a0f1e', '#6366f1', '#ec4899', '#f8fafc', '#38bdf8'],
  params: {
    elevation: { default: 1, min: 0.3, max: 2, step: 0.05, label: { en: 'Elevation', ar: 'مقدار الارتفاع' } },
    radius: { default: 0.12, min: 0.02, max: 0.3, step: 0.01, label: { en: 'Corner radius', ar: 'استدارة الزوايا' } },
    frost: { default: 0.6, min: 0, max: 1, step: 0.05, label: { en: 'Frost', ar: 'درجة الصنفرة' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'webgl2', cost: 'low' },
  still: 1,
  tags: ['glass', 'card', 'elevation', 'shadow', 'ui', 'glassmorphism'],
  setup: fragment({
    fragment: `
uniform float u_elevation;
uniform float u_radius;
uniform float u_frost;
${centred}${sdf}
// The backdrop: two soft lights with thin rings around them. \`blur\` spreads everything, as frosted glass does.
vec3 backdrop(vec2 p, float blur) {
  vec2 span = u_resolution / min(u_resolution.x, u_resolution.y);
  float px = 2.0 / min(u_resolution.x, u_resolution.y);
  vec2 a = span * vec2(-0.42, 0.34); vec2 b = span * vec2(0.46, -0.38);
  float ra = length(p - a); float rb = length(p - b);
  float sa = 0.55 + blur; float sb = 0.5 + blur;
  vec3 colour = u_color0 + u_color1 * 0.75 * exp(-ra * ra / (sa * sa)) + u_color2 * 0.7 * exp(-rb * rb / (sb * sb));
  float w = 0.012 + px; float soft = w + blur * 1.4;
  float ringA = smoothstep(soft, 0.0, abs(fract(ra * 3.2) - 0.5) / 3.2) * exp(-ra * 0.9);
  float ringB = smoothstep(soft, 0.0, abs(fract(rb * 3.2) - 0.5) / 3.2) * exp(-rb * 0.9);
  return colour + (u_color1 * ringA + u_color2 * ringB) * 0.55 * w / soft;
}
void main() {
  vec2 p = centredUv();
  vec2 span = u_resolution / min(u_resolution.x, u_resolution.y);
  float px = 2.0 / min(u_resolution.x, u_resolution.y);
  float lift = u_progress * u_elevation;
  vec2 size = span * vec2(0.58, 0.56) * (0.9 + 0.06 * lift);
  float corner = min(u_radius * 2.0, min(size.x, size.y) * 0.95);
  vec2 centre = vec2(0.0, 0.05 * lift);
  vec2 q = p - centre;
  float d = sdBox(q, size - corner) - corner;
  float inside = smoothstep(px, -px, d);
  // The shadow leaves the card as it rises: further, wider and softer.
  float reach = sdBox(p - vec2(0.03, -0.13) * lift, size - corner) - corner;
  float spread = 0.012 + 0.2 * lift;
  float shadow = smoothstep(spread, -spread, reach) * min(lift * 5.0, 1.0) * (0.7 - 0.12 * min(lift, 2.0));
  vec3 colour = backdrop(p, 0.0) * (1.0 - shadow);
  // The face: the backdrop behind it, frosted more the higher the card floats, under a light veil.
  vec3 face = backdrop(centre + q * (1.0 - 0.04 * lift), u_frost * (0.02 + 0.22 * lift));
  face = mix(face, u_color3, 0.07 + 0.05 * min(lift, 2.0) + 0.05 * u_frost);
  face += u_color3 * 0.1 * smoothstep(-size.y, size.y, q.y);
  float band = dot(q, vec2(0.8, 0.6)) - mix(-1.7, 1.7, u_progress) * span.x;
  face += u_color3 * 0.3 * exp(-band * band / 0.05) * sin(3.14159265 * u_progress);
  // What the card carries: a round mark, two lines and a button, all centred.
  float unit = min(size.x, size.y);
  float mark = smoothstep(px, -px, length(q - vec2(0.0, 0.42 * size.y)) - 0.2 * unit);
  float lines = smoothstep(px, -px, sdBox(q - vec2(0.0, -0.02 * size.y), vec2(0.6 * size.x, 0.035 * unit)) - 0.02 * unit)
    + smoothstep(px, -px, sdBox(q - vec2(0.0, -0.24 * size.y), vec2(0.4 * size.x, 0.035 * unit)) - 0.02 * unit);
  float button = smoothstep(px, -px, sdBox(q - vec2(0.0, -0.62 * size.y), vec2(0.26 * size.x, 0.055 * unit)) - 0.05 * unit);
  face = mix(face, u_color3, 0.85 * mark + 0.5 * min(lines, 1.0));
  face = mix(face, u_color4, 0.95 * button);
  // The rim: a bright bevel that is strongest where the light comes from.
  float rim = smoothstep(0.03, 0.0, -d) * (0.12 + 0.5 * max(dot(normalize(q / size + 1e-5), vec2(-0.5, 0.866)), 0.0));
  face += u_color3 * rim * (0.5 + 0.5 * min(lift, 1.0));
  outColor = vec4(mix(colour, face, inside), 1.0);
}`,
    uniforms: (ctx) => ({ u_elevation: ctx.params.elevation, u_radius: ctx.params.radius, u_frost: ctx.params.frost }),
  }),
});
