import { defineMotion } from '../../core/define.mjs';
import { fragment } from '../../engines/webgl.mjs';
import { frame } from '../../shaders/chunks.mjs';

export default defineMotion({
  id: 'quantum-wave-propagation',
  number: 4,
  module: 'quantum',
  name: { en: 'Quantum Wave Propagation', ar: 'انتشار الموجة الكمّية' },
  summary: {
    en: 'A wave packet travels along the reading direction and spreads as it goes, over a haze of probability density.',
    ar: 'حزمة موجية تنتقل في اتجاه القراءة وتتّسع أثناء سيرها فوق هالة من كثافة الاحتمال.',
  },
  engine: 'webgl2-glsl',
  kind: 'oneshot',
  duration: 3200,
  easing: 'ease-in-out',
  colors: ['#070b1a', '#5eead4', '#818cf8'],
  params: {
    wavelength: { default: 0.16, min: 0.08, max: 0.4, step: 0.01, label: { en: 'Wavelength', ar: 'الطول الموجي' } },
    spread: { default: 1, min: 0, max: 2, step: 0.1, label: { en: 'Dispersion', ar: 'التشتّت' } },
  },
  rtl: 'mirror',
  requirements: { gpu: 'webgl2', cost: 'low' },
  still: 0.5,
  tags: ['explainer', 'science', 'directional', 'transition'],
  setup: fragment({
    fragment: `
uniform float u_wavelength;
uniform float u_spread;
${frame}
void main() {
  vec2 p = frameUv();
  float reach = u_resolution.x / min(u_resolution.x, u_resolution.y) * 0.8;
  float centre = mix(-reach, reach, u_progress);
  float sigma = 0.14 + u_spread * 0.3 * u_progress;
  float envelope = exp(-pow((p.x - centre) / sigma, 2.0));
  float psi = envelope * cos((p.x - centre) * 6.2831853 / u_wavelength);
  float line = smoothstep(0.03, 0.0, abs(p.y - psi * 0.5));
  float density = envelope * envelope * smoothstep(0.75, 0.0, abs(p.y)) * 0.55;
  float axis = smoothstep(0.006, 0.0, abs(p.y)) * 0.25;
  outColor = vec4(u_color0 + u_color1 * (line + axis) + u_color2 * density, 1.0);
}`,
    uniforms: (ctx) => ({ u_wavelength: ctx.params.wavelength, u_spread: ctx.params.spread }),
  }),
});
