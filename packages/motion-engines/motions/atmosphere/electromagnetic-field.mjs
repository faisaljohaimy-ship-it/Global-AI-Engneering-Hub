import { defineMotion } from '../../core/define.mjs';
import { fragment } from '../../engines/webgl.mjs';
import { hash } from '../../shaders/chunks.mjs';

export default defineMotion({
  id: 'atmosphere-electromagnetic-field',
  number: 177,
  module: 'atmosphere',
  name: { en: 'Electromagnetic Field Visualization', ar: 'تصوير المجال الكهرومغناطيسي' },
  summary: {
    en: 'Field lines leave a positive pole, curve through space and return to a negative one. Pulses of energy run along every line, dashed equipotentials cross them at right angles, and the pair slowly rocks.',
    ar: 'خطوط المجال تخرج من قطب موجب وتنحني في الفضاء لتعود إلى قطب سالب. نبضات من الطاقة تجري على كل خط، وخطوط تساوي الجهد المتقطّعة تقطعها بزوايا قائمة، والقطبان يتأرجحان ببطء.',
  },
  engine: 'webgl2-glsl',
  kind: 'loop',
  duration: 8000,
  easing: 'ease-out',
  colors: ['#04070e', '#49e6c8', '#ff6a5c', '#5c9dff', '#fff4d2'],
  params: {
    lines: { default: 16, min: 6, max: 32, step: 2, label: { en: 'Field lines', ar: 'عدد خطوط المجال' } },
    separation: { default: 0.45, min: 0.2, max: 0.75, step: 0.01, label: { en: 'Distance between poles', ar: 'المسافة بين القطبين' } },
    flow: { default: 1, min: 0, max: 3, step: 0.1, label: { en: 'Pulse speed', ar: 'سرعة النبضات' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'webgl2', cost: 'low' },
  still: 0.5,
  tags: ['science', 'diagram', 'energy', 'background', 'education'],
  setup: fragment({
    fragment: `
uniform float u_lines;
uniform float u_separation;
uniform float u_flow;
${hash}
float bar(vec2 p, vec2 size, float px) { return smoothstep(px, -px, max(abs(p.x) - size.x, abs(p.y) - size.y)); }
void main() {
  float unit = min(u_resolution.x, u_resolution.y);
  vec2 p = (2.0 * gl_FragCoord.xy - u_resolution) / unit;
  float px = 2.0 / unit;
  float t = u_time;
  float tilt = 0.4 * sin(t * 0.35);
  vec2 axis = vec2(cos(tilt), sin(tilt)) * u_separation;
  vec2 a = p - axis;
  vec2 b = p + axis;
  float la = length(a);
  float lb = length(b);
  // In two dimensions the field lines of a pair of poles are the level sets of the angle
  // between them, and the equipotentials are the level sets of the ratio of distances.
  float psi = atan(a.y, a.x) - atan(b.y, b.x);
  float phi = log((lb + 1e-4) / (la + 1e-4));
  float strength = 2.0 * u_separation / (la * lb + 1e-4);
  float count = floor(u_lines + 0.5);
  float s = psi * count / 6.2831853;
  float id = mod(floor(s + 0.5) + 2.0 * count, count);
  float away = abs(fract(s + 0.5) - 0.5) / (strength * count / 6.2831853);
  float line = smoothstep(px * 1.7, px * 0.3, away);
  float glow = exp(-away / 0.014);
  float pulse = pow(0.5 + 0.5 * sin(phi * 5.0 + t * u_flow * 2.5 + hash11(id + 1.0) * 6.2831853), 6.0);
  float level = abs(fract(phi * 1.5 + 0.5) - 0.5) / (strength * 1.5);
  float contour = smoothstep(px * 1.3, px * 0.2, level) * smoothstep(0.2, 0.3, abs(fract(s * 2.0) - 0.5) + 0.05);
  float reveal = smoothstep(-0.6, 0.0, abs(phi) - 2.6 * (1.0 - u_intro));
  vec3 polarity = mix(u_color3, u_color2, smoothstep(-2.0, 2.0, phi));
  vec3 colour = u_color1 * (line * 0.7 + glow * 0.16) + u_color4 * (line * 1.2 + glow * 0.5) * pulse;
  colour += polarity * (contour * 0.45 + clamp(strength * 0.012, 0.0, 0.5));
  colour *= reveal;
  colour += u_color2 * 0.006 / (la * la + 0.006) + u_color3 * 0.006 / (lb * lb + 0.006);
  float mark = max(max(bar(a, vec2(0.034, 0.008), px), bar(a, vec2(0.008, 0.034), px)), bar(b, vec2(0.034, 0.008), px));
  outColor = vec4(mix(u_color0 + colour, u_color0, mark), 1.0);
}`,
    uniforms: (ctx) => ({ u_lines: ctx.params.lines, u_separation: ctx.params.separation, u_flow: ctx.params.flow }),
  }),
});
