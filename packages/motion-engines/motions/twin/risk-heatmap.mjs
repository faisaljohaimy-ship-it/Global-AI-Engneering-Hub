import { defineMotion } from '../../core/define.mjs';
import { fragment } from '../../engines/webgl.mjs';
import { centred, hash, rotate } from '../../shaders/chunks.mjs';

export default defineMotion({
  id: 'twin-risk-heatmap',
  number: 60,
  module: 'twin',
  name: { en: 'Spatial Risk Heatmap', ar: 'خريطة المخاطر الحرارية المكانية' },
  summary: {
    en: 'A tilted floor plan of a facility, its rooms drawn as walls. Risk hotspots swell and fade over it as heat, banded by contour lines, and the room under the worst one is outlined with a pulsing ring.',
    ar: 'مخطّطٌ مائل لطابقٍ في منشأة، غرفه مرسومة بجدرانها. تنتفخ فوقه بؤر المخاطر وتخبو حرارةً مقسّمةً بخطوط الكنتور، وتُحاط الغرفة الواقعة تحت أشدّها بحلقةٍ نابضة.',
  },
  engine: 'webgl2-glsl',
  kind: 'loop',
  duration: 10000,
  easing: 'ease-out',
  colors: ['#060b14', '#22c55e', '#facc15', '#ef4444', '#94a3b8'],
  params: {
    hotspots: { default: 5, min: 2, max: 8, step: 1, label: { en: 'Hotspots', ar: 'عدد البؤر' } },
    contours: { default: 0.6, min: 0, max: 1, step: 0.05, label: { en: 'Contour lines', ar: 'خطوط الكنتور' } },
  },
  camera: {
    tilt: { default: 0.55, min: 0.1, max: 0.9, step: 0.05, label: { en: 'Tilt of the plan', ar: 'ميل المخطّط' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'webgl2', cost: 'low' },
  still: 0.4,
  tags: ['dashboard', 'map', 'risk', 'twin', 'heatmap', 'facility'],
  setup: fragment({
    fragment: `
uniform float u_hotspots;
uniform float u_contours;
uniform float u_tilt;
${hash}${centred}${rotate}
vec2 hotspot(int i) { vec3 h = hash31(float(i) * 3.3 + 2.0); return vec2(h.x * 2.4 - 1.2, h.y * 1.6 - 0.8); }
float strength(int i) { vec3 h = hash31(float(i) * 3.3 + 2.0); return 0.5 + 0.5 * sin(u_time * (0.5 + h.z) + h.x * 9.0); }
void main() {
  vec2 p = centredUv();
  // Undo the tilt: rows nearer the top of the frame are further away.
  float scale = 1.0 + u_tilt * p.y * 0.9;
  vec2 plan = vec2(p.x * scale, (p.y + 0.05) * (1.0 + u_tilt * 1.2) * scale);
  plan = rot(0.12) * plan * 1.15;
  bool onPlan = abs(plan.x) < 1.5 && abs(plan.y) < 1.0;
  vec3 colour = u_color0;
  if (onPlan) {
    float heat = 0.0; float worst = -1.0; int worstIndex = 0;
    for (int i = 0; i < 8; i++) {
      if (float(i) >= u_hotspots) break;
      float s = strength(i);
      vec2 d = plan - hotspot(i);
      heat += s * exp(-dot(d, d) * 7.0);
      if (s > worst) { worst = s; worstIndex = i; }
    }
    heat *= u_intro;
    vec3 ramp = heat < 0.5 ? mix(u_color1, u_color2, heat * 2.0) : mix(u_color2, u_color3, min(1.0, heat * 2.0 - 1.0));
    colour = u_color0 * 1.4 + ramp * smoothstep(0.05, 0.6, heat) * 0.75;
    float band = abs(fract(heat * 6.0) - 0.5);
    colour += ramp * smoothstep(0.08, 0.0, band - 0.02) * u_contours * smoothstep(0.08, 0.2, heat) * 0.6;
    // Walls: the plan is divided into rooms on an uneven grid, with doorways left open.
    vec2 room = plan * vec2(2.2, 2.4);
    vec2 cell = floor(room);
    vec2 f = fract(room);
    float doorX = step(0.35, abs(f.y - 0.5)) ;
    float doorY = step(0.35, abs(f.x - 0.5));
    float wall = max(smoothstep(0.035, 0.0, f.x) * (hash21(cell) > 0.25 ? 1.0 : doorX), smoothstep(0.035, 0.0, f.y) * (hash21(cell + 5.0) > 0.25 ? 1.0 : doorY));
    float outer = smoothstep(0.02, 0.0, min(1.5 - abs(plan.x), 1.0 - abs(plan.y)));
    colour = mix(colour, u_color4, max(wall * 0.55, outer * 0.9));
    // The room under the worst hotspot gets a pulsing outline.
    vec2 worstRoom = floor(hotspot(worstIndex) * vec2(2.2, 2.4));
    float pulse = 0.5 + 0.5 * sin(u_time * 5.0);
    vec2 local = abs(room - worstRoom - 0.5);
    float outline = smoothstep(0.05, 0.0, abs(max(local.x, local.y) - 0.5 - 0.06 * pulse));
    colour += u_color3 * outline * (0.5 + 0.5 * pulse) * u_intro;
  }
  outColor = vec4(colour, 1.0);
}`,
    uniforms: (ctx) => ({ u_hotspots: Math.round(ctx.params.hotspots), u_contours: ctx.params.contours, u_tilt: ctx.camera.tilt }),
  }),
});
