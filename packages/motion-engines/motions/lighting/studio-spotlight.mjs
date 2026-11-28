import { defineMotion } from '../../core/define.mjs';
import { fragment } from '../../engines/webgl.mjs';
import { centred, hash, noise } from '../../shaders/chunks.mjs';

export default defineMotion({
  id: 'lighting-studio-spotlight',
  number: 73,
  module: 'lighting',
  name: { en: 'Moving Studio Spotlight', ar: 'كشّاف الاستوديو المتحرّك' },
  summary: {
    en: 'A spotlight hung above a dark stage sweeps its cone across the floor in a slow figure of eight. The pool of light stretches as it travels, and a podium in the middle lights up and throws a shadow whenever the pool crosses it.',
    ar: 'كشّافٌ معلّق فوق مسرحٍ مظلم يحرّك مخروطه على الأرض في مسارٍ بطيء على شكل ثمانية. تتمدّد بقعة الضوء وهي تتنقّل، ويُضاء منصّةٌ في الوسط ويرمي ظلًّا كلّما عبرته البقعة.',
  },
  engine: 'webgl2-glsl',
  kind: 'loop',
  duration: 9000,
  easing: 'ease-out',
  colors: ['#050507', '#fef3c7', '#a78bfa', '#1e293b'],
  params: {
    width: { default: 0.35, min: 0.15, max: 0.7, step: 0.05, label: { en: 'Cone width', ar: 'اتساع المخروط' } },
    haze: { default: 0.5, min: 0, max: 1, step: 0.05, label: { en: 'Haze in the beam', ar: 'الضباب داخل الحزمة' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'webgl2', cost: 'low' },
  still: 0.15,
  tags: ['light', 'stage', 'product', 'reveal', 'spotlight'],
  setup: fragment({
    fragment: `
uniform float u_width;
uniform float u_haze;
${hash}${noise}${centred}
// The floor is a plane seen from a raised camera: screen y below the horizon maps to depth.
vec2 toFloor(vec2 p) {
  float depth = 0.55 / max(0.02, 0.32 - p.y);
  return vec2(p.x * depth, depth);
}
void main() {
  vec2 p = centredUv();
  float a = u_raw * 6.2831853;
  vec2 pool = vec2(1.1 * sin(a), 2.2 + 0.9 * sin(2.0 * a));
  vec2 lamp = vec2(0.0, 1.15);
  vec3 colour = u_color0 + u_color3 * 0.25 * smoothstep(0.32, 1.0, p.y);
  float onFloor = step(p.y, 0.3);
  vec2 f = toFloor(p);
  // The pool of light on the floor, softened at its edge.
  float size = u_width * (0.8 + 0.25 * pool.y);
  float lit = smoothstep(size, size * 0.6, length((f - pool) * vec2(1.0, 0.7)));
  // The podium: a drum standing on the floor at depth 2.2, drawn as its body and its top.
  vec2 podium = vec2(0.0, 2.2);
  float base = 0.32 - 0.55 / podium.y;
  float podiumLit = smoothstep(size * 1.4, size * 0.4, length(podium - pool));
  float body = smoothstep(0.172, 0.168, abs(p.x)) * step(base - 0.03 * sqrt(max(0.0, 1.0 - p.x * p.x / 0.0289)), p.y) * step(p.y, base + 0.14);
  float onTop = smoothstep(1.02, 0.98, length((p - vec2(0.0, base + 0.14)) / vec2(0.17, 0.03)));
  float face = body * (1.0 - onTop);
  // Its shadow is cast away from the pool.
  vec2 away = normalize(podium - pool + 1e-4);
  float shadow = smoothstep(0.45, 0.25, length((f - podium - away * 0.5) * vec2(1.0, 1.6))) * podiumLit;
  float grain = noise(f * 6.0) * 0.15;
  colour += onFloor * (u_color3 * (0.2 + grain) + u_color1 * lit * 0.9 * (1.0 - 0.75 * shadow)) * u_intro;
  colour = mix(colour, mix(u_color3 * 0.35, u_color2 * 0.7, podiumLit) * (0.7 + 0.3 * smoothstep(-0.17, 0.17, -p.x)), face * u_intro);
  colour = mix(colour, mix(u_color3 * 0.8, u_color1 * 0.95, podiumLit), onTop * u_intro);
  // The beam in the air: a soft cone from the lamp to the pool, lit by drifting haze.
  vec2 target = vec2(pool.x / pool.y, 0.32 - 0.55 / pool.y);
  vec2 axis = target - lamp;
  float along = clamp(dot(p - lamp, axis) / dot(axis, axis), 0.0, 1.0);
  float spread = mix(0.02, size * 0.9 / pool.y * 1.2 + 0.04, along);
  float off = length(p - lamp - axis * along);
  float cone = smoothstep(spread, spread * 0.3, off) * (0.35 + 0.65 * along);
  float drift = 0.6 + 0.4 * noise(p * 3.0 + vec2(u_time * 0.3, 0.0));
  colour += mix(u_color2, u_color1, along) * cone * drift * u_haze * 0.45 * u_intro;
  colour += u_color1 * smoothstep(0.08, 0.0, length(p - lamp)) * 0.9;
  outColor = vec4(colour, 1.0);
}`,
    uniforms: (ctx) => ({ u_width: ctx.params.width, u_haze: ctx.params.haze }),
  }),
});
