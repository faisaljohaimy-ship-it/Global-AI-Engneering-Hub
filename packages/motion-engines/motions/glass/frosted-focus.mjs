import { defineMotion } from '../../core/define.mjs';
import { fragment } from '../../engines/webgl.mjs';
import { centred, hash, noise } from '../../shaders/chunks.mjs';

export default defineMotion({
  id: 'glass-frosted-focus',
  number: 39,
  module: 'glass',
  name: { en: 'Frosted Glass Focus Transition', ar: 'انتقال التركيز عبر الزجاج المُصنفر' },
  summary: {
    en: 'A landscape is seen through frosted glass: soft patches of colour under a grainy veil. The frost clears from the middle outward, and behind the clearing edge the sun, the ridges and the stars come into sharp focus.',
    ar: 'منظر طبيعي يُرى من خلف زجاج مُصنفر: بقع لونية ناعمة تحت غلالة حُبيبية. ينقشع الصقيع من الوسط نحو الأطراف، وخلف حدّ الانقشاع تظهر الشمس والتلال والنجوم بوضوح تام.',
  },
  engine: 'webgl2-glsl',
  kind: 'oneshot',
  duration: 2800,
  easing: 'ease-in-out',
  colors: ['#0c1024', '#0f766e', '#6366f1', '#fbbf24', '#e2e8f0'],
  params: {
    blur: { default: 1, min: 0.3, max: 1.6, step: 0.05, label: { en: 'Blur', ar: 'شدّة التمويه' } },
    grain: { default: 0.5, min: 0, max: 1, step: 0.05, label: { en: 'Frost grain', ar: 'حُبيبات الصنفرة' } },
    softness: { default: 0.3, min: 0.05, max: 0.8, step: 0.05, label: { en: 'Edge softness', ar: 'نعومة حدّ الانقشاع' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'webgl2', cost: 'low' },
  still: 1,
  tags: ['glass', 'frost', 'blur', 'focus', 'reveal', 'transition'],
  setup: fragment({
    fragment: `
uniform float u_blur;
uniform float u_grain;
uniform float u_softness;
${centred}${hash}${noise}
// The landscape, drawn already blurred by \`b\`: every edge is that much softer and every fine detail that much fainter.
vec3 landscape(vec2 p, float b) {
  vec2 span = u_resolution / min(u_resolution.x, u_resolution.y);
  float s = b + 2.0 / min(u_resolution.x, u_resolution.y);
  vec3 colour = mix(mix(u_color0, u_color2, 0.42), u_color0, smoothstep(-0.35, 1.0, p.y));
  vec2 g = p * 5.0; vec2 f = fract(g) - 0.5 - (hash22(floor(g)) - 0.5) * 0.6;
  colour += u_color4 * smoothstep(0.07 + b * 5.0, 0.0, length(f)) * 0.004 / (0.004 + b * b * 20.0) * step(0.35, hash21(floor(g) + 5.0));
  vec2 sun = p - vec2(0.3 * span.x, 0.24);
  colour += u_color3 * 0.3 * exp(-max(length(sun) - 0.34, 0.0) * 3.5);
  colour = mix(colour, u_color3, smoothstep(s, -s, length(sun) - 0.34));
  float far = p.y + 0.16 - 0.2 * sin(p.x * 1.9 + 1.0) - 0.07 * sin(p.x * 5.1 + 0.4);
  colour = mix(colour, u_color2 * (0.85 + 0.3 * smoothstep(-0.5, 0.0, far)), smoothstep(s, -s, far));
  float near = p.y + 0.56 - 0.17 * sin(p.x * 1.4 + 3.6) - 0.05 * sin(p.x * 6.3 + 2.0);
  float strata = smoothstep(0.012 + b, 0.0, abs(fract(near * 7.0) - 0.5) / 7.0) * 0.012 / (0.012 + b);
  return mix(colour, u_color1 * (0.8 + 0.5 * strata), smoothstep(s, -s, near));
}
void main() {
  vec2 p = centredUv();
  vec2 span = u_resolution / min(u_resolution.x, u_resolution.y);
  // How clear the glass is here: the clearing starts in the middle and its edge travels out past the corners.
  float edge = mix(-u_softness, length(span) + u_softness, u_progress);
  float clear = 1.0 - smoothstep(edge - u_softness, edge + u_softness, length(p));
  float frost = 1.0 - clear;
  // Frost scatters the view: each grain looks a little to one side, and the whole is blurred and veiled.
  vec2 fine = hash22(gl_FragCoord.xy) - 0.5;
  vec2 coarse = vec2(noise(p * 34.0), noise(p * 34.0 + 9.0)) - 0.5;
  vec3 colour = landscape(p + frost * u_grain * (0.05 * fine + 0.09 * coarse), frost * u_blur * 0.22);
  colour = mix(colour, u_color4, frost * (0.15 + 0.14 * u_grain * (fine.x + coarse.y)));
  colour += u_color4 * 0.16 * clear * frost * 4.0 * (0.6 + 0.8 * coarse.x * u_grain);
  outColor = vec4(colour, 1.0);
}`,
    uniforms: (ctx) => ({ u_blur: ctx.params.blur, u_grain: ctx.params.grain, u_softness: ctx.params.softness }),
  }),
});
