import { defineMotion } from '../../core/define.mjs';
import { fragment } from '../../engines/webgl.mjs';
import { centred, hash } from '../../shaders/chunks.mjs';

export default defineMotion({
  id: 'glass-surface-ripple',
  number: 33,
  module: 'glass',
  name: { en: 'Glass Surface Ripple', ar: 'تموّج سطح الزجاج' },
  summary: {
    en: 'Rings spread over a sheet of glass from a few touch points, as if the pane were water. Every crest bends the mosaic underneath and catches a line of light, then the ring fades at the edge.',
    ar: 'حلقات تتّسع فوق لوح زجاجي من بضع نقاط لمس كأنّ اللوح ماء. كل قمّة تحني الفسيفساء التي تحتها وتلتقط خيطًا من الضوء، ثم تخبو الحلقة عند الأطراف.',
  },
  engine: 'webgl2-glsl',
  kind: 'loop',
  duration: 8000,
  easing: 'ease-out',
  colors: ['#04101c', '#0ea5e9', '#2dd4bf', '#f0f9ff'],
  params: {
    amplitude: { default: 1, min: 0.2, max: 2, step: 0.05, label: { en: 'Ripple height', ar: 'ارتفاع التموّج' } },
    wavelength: { default: 0.16, min: 0.08, max: 0.32, step: 0.01, label: { en: 'Wavelength', ar: 'طول الموجة' } },
    sources: { default: 3, min: 1, max: 5, step: 1, label: { en: 'Touch points', ar: 'نقاط اللمس' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'webgl2', cost: 'low' },
  still: 0.45,
  tags: ['glass', 'ripple', 'water', 'background', 'touch'],
  setup: fragment({
    fragment: `
uniform float u_amplitude;
uniform float u_wavelength;
uniform float u_sources;
${centred}${hash}
// The mosaic under the pane: square tiles in two glazes, set in dark grout.
vec3 mosaic(vec2 p) {
  vec2 g = p * 3.5; vec2 cell = floor(g); vec2 f = abs(fract(g) - 0.5);
  float tile = smoothstep(0.47, 0.41, max(f.x, f.y));
  float tone = hash21(cell + 11.0);
  vec3 glaze = mix(u_color1, u_color2, step(0.5, hash21(cell + 4.0))) * (0.3 + 0.55 * tone);
  return mix(u_color0, glaze, tile);
}
void main() {
  vec2 p = centredUv();
  vec2 span = u_resolution / min(u_resolution.x, u_resolution.y);
  float k = 6.2831853 / u_wavelength;
  // The slope of the surface: every touch point sends out one wave packet per loop.
  vec2 slope = vec2(0.0);
  for (int i = 0; i < 5; i++) {
    float n = float(i);
    if (n >= u_sources) break;
    vec2 centre = span * (hash22(vec2(n * 3.7 + 1.0, 9.2)) - 0.5) * 1.3;
    float life = fract(u_raw + n / u_sources + 0.07);
    vec2 d = p - centre; float r = length(d) + 1e-4;
    float front = life * 2.2;                       // radius of the packet
    float width = u_wavelength * 1.6;
    float x = r - front;
    float envelope = exp(-x * x / (width * width)) * (1.0 - life) * (1.0 - life) * smoothstep(0.0, 0.06, life);
    float wave = k * cos(k * x) - 2.0 * x / (width * width) * sin(k * x);
    slope += d / r * envelope * wave;
  }
  slope *= 0.012 * u_amplitude * u_wavelength * 6.0 * u_intro;
  vec3 normal = normalize(vec3(-slope, 1.0));
  // Refraction through the pane, shading on the lit side of each crest, and the specular line.
  vec3 colour = mosaic(p + slope * 0.22);
  vec3 light = normalize(vec3(-0.45, 0.6, 0.66));
  colour *= 1.0 + 1.4 * dot(slope, light.xy);
  float glint = pow(max(dot(normal, normalize(light + vec3(0.0, 0.0, 1.0))), 0.0), 90.0);
  float sheen = smoothstep(0.5, 0.0, abs(dot(p, vec2(0.6, 0.8)) - 0.25)) * 0.07;
  colour += u_color3 * (glint * 0.9 * smoothstep(0.02, 0.2, length(slope)) + sheen * u_intro);
  outColor = vec4(colour, 1.0);
}`,
    uniforms: (ctx) => ({ u_amplitude: ctx.params.amplitude, u_wavelength: ctx.params.wavelength, u_sources: Math.round(ctx.params.sources) }),
  }),
});
