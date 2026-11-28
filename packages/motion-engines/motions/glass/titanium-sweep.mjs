import { defineMotion } from '../../core/define.mjs';
import { fragment } from '../../engines/webgl.mjs';
import { frame, hash, noise, sdf } from '../../shaders/chunks.mjs';

export default defineMotion({
  id: 'glass-titanium-sweep',
  number: 36,
  module: 'glass',
  name: { en: 'Titanium Reflection Sweep', ar: 'مسحة الانعكاس على التيتانيوم' },
  summary: {
    en: 'A band of reflected light crosses a brushed titanium plate in the reading direction and leaves it lit. The brushing breaks the band into fine streaks, and the circular-brushed medallion answers with a turning bow tie of light.',
    ar: 'شريط من الضوء المنعكس يعبر لوحًا من التيتانيوم المصقول بالفرشاة في اتجاه القراءة ويتركه مضاءً. خطوط الصقل تفتّت الشريط إلى شُعيرات دقيقة، والقرص المصقول دائريًا في الوسط يردّ بربطة ضوء تدور.',
  },
  engine: 'webgl2-glsl',
  kind: 'oneshot',
  duration: 2600,
  easing: 'ease-in-out',
  colors: ['#0a0c10', '#7b8794', '#f1f5f9', '#5b8def'],
  params: {
    width: { default: 0.3, min: 0.1, max: 0.8, step: 0.02, label: { en: 'Band width', ar: 'عرض الشريط' } },
    angle: { default: 20, min: -40, max: 40, step: 1, label: { en: 'Band angle', ar: 'ميل الشريط' } },
    grain: { default: 0.6, min: 0, max: 1, step: 0.05, label: { en: 'Brushing', ar: 'خشونة الصقل' } },
  },
  rtl: 'mirror',
  requirements: { gpu: 'webgl2', cost: 'low' },
  still: 1,
  tags: ['metal', 'titanium', 'sweep', 'reveal', 'premium', 'highlight'],
  setup: fragment({
    fragment: `
uniform float u_width;
uniform float u_angle;
uniform float u_grain;
${frame}${hash}${noise}${sdf}
void main() {
  vec2 p = frameUv();
  vec2 span = u_resolution / min(u_resolution.x, u_resolution.y);
  float px = 2.0 / min(u_resolution.x, u_resolution.y);
  vec2 size = span * vec2(0.88, 0.76);
  float d = sdBox(p, size - 0.1) - 0.1;
  float plate = smoothstep(px, -px, d);
  // Two finishes: straight brushing on the plate, circular brushing on the medallion.
  float rows = 0.38 / px;
  float r = length(p); float theta = atan(p.y, p.x);
  float disc = min(span.x, span.y) * 0.46;
  float medal = smoothstep(px, -px, r - disc);
  float straight = 0.6 * noise(vec2(p.x * 2.5, p.y * rows)) + 0.4 * noise(vec2(p.x * 9.0 + 5.0, p.y * rows * 0.5 + 3.0));
  float turned = 0.6 * noise(vec2(r * rows, abs(theta) * 2.5)) + 0.4 * noise(vec2(r * rows * 0.5 + 7.0, abs(theta) * 9.0));
  float fibre = 1.0 + u_grain * (mix(straight, turned, medal) - 0.5) * 1.6;
  // The band of light and where it stands now. Behind it the metal stays lit.
  float tilt = radians(u_angle);
  vec2 axis = vec2(cos(tilt), sin(tilt));
  float reach = span.x * abs(axis.x) + span.y * abs(axis.y) + u_width * 2.0;
  float x = dot(p, axis) - mix(-reach, reach, u_progress);
  float lit = smoothstep(u_width, -u_width, x);
  float band = exp(-x * x / (u_width * u_width * 0.2));
  float fringe = exp(-pow((abs(x) - u_width * 0.85) / (u_width * 0.3), 2.0));
  float streak = exp(-pow((x + u_width * 1.25) / 0.025, 2.0));
  vec3 metal = u_color1 * (0.2 + 0.62 * lit) * fibre;
  metal += u_color3 * (0.2 * lit * smoothstep(-size.y, size.y, p.y) + 0.35 * fringe) * fibre;
  // On straight brushing the band is a band; on circular brushing it becomes a bow tie that turns as the light passes.
  float passing = exp(-x * x / (u_width * u_width + 0.5));
  float tie = pow(abs(cos(theta - tilt - 1.5708 - (u_progress - 0.5) * 2.4)), 16.0) * (0.3 + 0.7 * passing) * smoothstep(0.0, 0.25, u_progress);
  metal += u_color2 * mix(band * 0.85 + streak * 0.5, tie * 0.9 + band * 0.12, medal) * fibre * fibre;
  // The groove around the medallion and the bevel of the plate.
  metal *= 1.0 - 0.55 * smoothstep(2.5 * px, 0.0, abs(r - disc));
  metal += u_color2 * 0.25 * (0.3 + 0.7 * lit) * smoothstep(2.0 * px, 0.0, abs(r - disc + 3.0 * px)) * max(dot(normalize(p + 1e-5), vec2(-0.5, 0.866)), 0.0);
  float bevel = smoothstep(0.035, 0.0, -d);
  float facing = dot(normalize(p / size + 1e-5), vec2(-0.2, 0.98));
  metal = mix(metal, u_color2 * (0.1 + 0.55 * lit + 0.5 * band) * max(facing, 0.0) + u_color1 * 0.12 * max(-facing, 0.0), bevel * 0.85);
  vec3 backdrop = u_color0 * (1.25 - 0.35 * length(p / span));
  backdrop *= 1.0 - 0.5 * smoothstep(0.12, -0.02, sdBox(p - vec2(0.0, -0.05), size - 0.1) - 0.1);
  outColor = vec4(mix(backdrop, metal, plate), 1.0);
}`,
    uniforms: (ctx) => ({ u_width: ctx.params.width, u_angle: ctx.params.angle, u_grain: ctx.params.grain }),
  }),
});
