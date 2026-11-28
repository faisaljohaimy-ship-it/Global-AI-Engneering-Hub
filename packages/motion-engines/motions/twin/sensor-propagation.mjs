import { defineMotion } from '../../core/define.mjs';
import { fragment } from '../../engines/webgl.mjs';
import { centred, hash } from '../../shaders/chunks.mjs';

export default defineMotion({
  id: 'twin-sensor-propagation',
  number: 57,
  module: 'twin',
  name: { en: 'Spatial Sensor Propagation', ar: 'انتشار إشارات المستشعرات المكانية' },
  summary: {
    en: 'A tilted grid of city blocks seen from above. Sensors at street corners report in turn: each report runs outward along the streets only, so its front is a diamond, and it lights the gateway at the centre when it arrives. Blocks glow faintly where reports have recently passed.',
    ar: 'شبكةٌ مائلة من مربّعات المدينة تُرى من الأعلى. تُرسل المستشعرات عند تقاطعات الشوارع تقاريرها تباعًا: يجري كلّ تقريرٍ على امتداد الشوارع وحدها فتكون جبهته معيّنًا، ويضيء البوابة في المركز حين يصل. وتتوهّج المربّعات قليلًا حيث مرّت التقارير حديثًا.',
  },
  meaning: {
    en: 'An IoT smart-city grid: street sensors report their readings, and each report travels the street network to the central gateway.',
    ar: 'شبكة إنترنت الأشياء في المدينة الذكية: ترسل مستشعرات الشوارع قراءاتها، ويعبر كلّ تقريرٍ شبكة الشوارع إلى البوابة المركزية.',
  },
  engine: 'webgl2-glsl',
  kind: 'loop',
  duration: 8000,
  easing: 'ease-out',
  colors: ['#030712', '#0ea5e9', '#a3e635', '#f472b6', '#334155'],
  params: {
    sensors: { default: 6, min: 2, max: 10, step: 1, label: { en: 'Reporting sensors', ar: 'عدد المستشعرات المُبلِّغة' } },
    blocks: { default: 7, min: 4, max: 12, step: 1, label: { en: 'Blocks across', ar: 'عدد المربّعات عرضًا' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'webgl2', cost: 'low' },
  still: 0.4,
  tags: ['iot', 'smart-city', 'sensors', 'network', 'twin', 'monitoring'],
  setup: fragment({
    fragment: `
uniform float u_sensors;
uniform float u_blocks;
${hash}${centred}
void main() {
  vec2 p = centredUv();
  // Tilt the ground plane: rows near the top of the frame are further away.
  float depth = 1.0 / (1.0 - p.y * 0.35);
  vec2 ground = vec2(p.x * depth, (p.y + 0.1) * depth * 1.5) * u_blocks * 0.5;
  vec2 cell = floor(ground);
  vec2 f = fract(ground);
  float street = min(min(f.x, 1.0 - f.x), min(f.y, 1.0 - f.y));
  float road = smoothstep(0.12, 0.06, street);
  vec3 colour = u_color0;
  // Blocks: a raised roof tone; recently passed blocks glow.
  float glow = 0.0;
  float gateway = 0.0;
  float fronts = 0.0;
  float sensorDots = 0.0;
  for (int i = 0; i < 10; i++) {
    if (float(i) >= u_sensors) break;
    vec3 h = hash31(float(i) * 5.17 + 3.0);
    vec2 sensor = floor((h.xy - 0.5) * u_blocks * 0.9) + 0.0;
    // Each sensor reports at its own moment in the cycle; the report spreads at a fixed speed.
    float start = h.z;
    float age = fract(u_raw - start) * 8.0;
    float travelled = age * 2.2;
    float manhattan = abs(ground.x - sensor.x) + abs(ground.y - sensor.y);
    float front = smoothstep(0.25, 0.0, abs(manhattan - travelled)) * road * exp(-age * 0.35);
    fronts += front;
    glow += smoothstep(travelled, travelled - 1.5, manhattan) * smoothstep(travelled - 3.0, travelled - 1.5, manhattan) * exp(-age * 0.5);
    float reach = abs(sensor.x) + abs(sensor.y);
    gateway += smoothstep(0.6, 0.0, abs(travelled - reach)) * exp(-age * 0.2);
    float pulse = 0.5 + 0.5 * sin(u_time * 6.0 + h.x * 20.0);
    sensorDots += smoothstep(0.22, 0.12, length(ground - sensor)) * (0.5 + 0.5 * pulse);
  }
  vec3 roof = mix(u_color4 * 0.45, u_color4 * 0.8, hash21(cell));
  colour = mix(roof * (0.8 + 0.6 * glow), u_color0 * 1.6, road);
  colour += u_color1 * min(1.0, fronts) * 1.2 * u_intro;
  colour += u_color1 * glow * 0.12 * (1.0 - road);
  colour += u_color3 * sensorDots * u_intro;
  // The gateway at the centre crossing: brighter when reports arrive.
  float g = smoothstep(0.35, 0.2, length(ground));
  colour = mix(colour, u_color2 * (0.5 + 0.8 * min(1.0, gateway)), g * u_intro);
  colour += u_color2 * smoothstep(0.9, 0.0, length(ground)) * min(1.0, gateway) * 0.3;
  // Fade the far distance into the background.
  colour = mix(colour, u_color0, smoothstep(0.55, 1.1, p.y));
  outColor = vec4(colour, 1.0);
}`,
    uniforms: (ctx) => ({ u_sensors: Math.round(ctx.params.sensors), u_blocks: Math.round(ctx.params.blocks) }),
  }),
});
