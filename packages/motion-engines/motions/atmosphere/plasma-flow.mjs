import { defineMotion } from '../../core/define.mjs';
import { fragment } from '../../engines/webgl.mjs';
import { frame, hash, noise } from '../../shaders/chunks.mjs';

export default defineMotion({
  id: 'atmosphere-plasma-flow',
  number: 173,
  module: 'atmosphere',
  name: { en: 'Plasma Flow Animation', ar: 'حركة تدفّق البلازما' },
  summary: {
    en: 'A current of plasma streams along the reading direction: glowing filaments weave past one another through a violet haze and carry bright packets of charge downstream.',
    ar: 'تيار من البلازما يجري في اتجاه القراءة: خيوط متوهّجة تتضافر وسط هالة بنفسجية وتحمل معها دفعات ساطعة من الشحنة.',
  },
  engine: 'webgl2-glsl',
  kind: 'loop',
  duration: 8000,
  easing: 'ease-out',
  colors: ['#0a0316', '#8f2cf5', '#ff4d9d', '#ffe9c7'],
  params: {
    filaments: { default: 11, min: 4, max: 16, step: 1, label: { en: 'Filaments', ar: 'عدد الخيوط' } },
    turbulence: { default: 1, min: 0, max: 2.5, step: 0.05, label: { en: 'Turbulence', ar: 'الاضطراب' } },
    speed: { default: 1, min: 0.2, max: 3, step: 0.1, label: { en: 'Flow speed', ar: 'سرعة التدفّق' } },
    glow: { default: 1, min: 0.4, max: 2.2, step: 0.05, label: { en: 'Filament glow', ar: 'توهّج الخيوط' } },
  },
  rtl: 'mirror',
  requirements: { gpu: 'webgl2', cost: 'medium' },
  still: 0.45,
  tags: ['background', 'energy', 'directional', 'hero', 'science'],
  setup: fragment({
    fragment: `
uniform float u_filaments;
uniform float u_turbulence;
uniform float u_speed;
uniform float u_glow;
${hash}${noise}${frame}
void main() {
  vec2 p = frameUv();
  vec2 flow = vec2(cos(0.32), sin(0.32));
  float along = dot(p, flow);
  float across = dot(p, vec2(-flow.y, flow.x));
  vec2 halfSize = u_resolution / min(u_resolution.x, u_resolution.y);
  float reach = flow.y * halfSize.x + flow.x * halfSize.y;
  float t = u_time * u_speed;
  float haze = 0.6 * noise(vec2(along * 0.7 - t * 0.6, across * 2.6)) + 0.4 * noise(vec2(along * 1.6 - t * 1.2, across * 6.0 + 3.0));
  vec3 colour = u_color1 * pow(haze, 3.0) * 0.55;
  float count = floor(u_filaments + 0.5);
  for (int i = 0; i < 16; i++) {
    if (float(i) >= count) break;
    float k = float(i);
    vec3 r = hash31(k * 7.31 + 2.0);
    float lane = (2.0 * (k + 0.5) / count - 1.0) * 0.8 + (r.x - 0.5) * 0.3;
    float pace = 0.6 + 0.9 * r.y;
    float y = lane * reach + 0.2 * sin(along * (0.9 + r.z) + t * 0.5 * pace + k * 2.4) + 0.08 * sin(along * (2.3 + 1.7 * r.y) - t * 0.9 + k * 5.1);
    y += u_turbulence * (0.3 * (noise(vec2(along * 1.7 - t * pace, k * 9.1)) - 0.5) + 0.08 * (noise(vec2(along * 5.3 - t * pace * 2.2, k * 3.3)) - 0.5));
    float width = (0.006 + 0.009 * r.z) * u_glow;
    float line = width / (abs(across - y) + width);
    float packet = 0.35 + 0.65 * pow(0.5 + 0.5 * sin(along * (2.0 + 3.0 * r.x) - t * (2.5 + 2.0 * r.y) + k), 3.0);
    colour += u_color1 * line * (0.35 + 0.3 * packet) + u_color2 * pow(line, 3.0) * packet * 1.2 + u_color3 * pow(line, 8.0) * packet * 1.3;
  }
  vec2 v = gl_FragCoord.xy / u_resolution - 0.5;
  outColor = vec4(u_color0 + colour * u_intro * (1.0 - 0.8 * dot(v, v)), 1.0);
}`,
    uniforms: (ctx) => ({ u_filaments: ctx.params.filaments, u_turbulence: ctx.params.turbulence, u_speed: ctx.params.speed, u_glow: ctx.params.glow }),
  }),
});
