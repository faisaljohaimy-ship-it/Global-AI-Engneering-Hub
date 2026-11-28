import { defineMotion } from '../../core/define.mjs';
import { fragment } from '../../engines/webgl.mjs';
import { hash } from '../../shaders/chunks.mjs';

export default defineMotion({
  id: 'atmosphere-energy-shield',
  number: 176,
  module: 'atmosphere',
  name: { en: 'Dynamic Energy Shield', ar: 'درع الطاقة الديناميكي' },
  summary: {
    en: 'A dome of hexagonal energy cells rises around a bright core. Strikes land on it, flash, and send rings rippling across the cells while the rim glows and bands of charge climb the dome.',
    ar: 'قبّة من خلايا الطاقة السداسية ترتفع حول نواة مضيئة. تسقط عليها الضربات فتومض وترسل حلقات تتموّج عبر الخلايا، بينما تتوهّج حافتها وتصعد عليها أحزمة من الشحنة.',
  },
  engine: 'webgl2-glsl',
  kind: 'loop',
  duration: 7000,
  easing: 'ease-out',
  colors: ['#04060f', '#34e5ff', '#2b59ff', '#ffb648', '#f2f7ff'],
  params: {
    cells: { default: 6, min: 3, max: 11, step: 0.5, label: { en: 'Cell density', ar: 'كثافة الخلايا' } },
    impacts: { default: 3, min: 1, max: 5, step: 1, label: { en: 'Strikes at once', ar: 'الضربات المتزامنة' } },
    rim: { default: 1, min: 0.4, max: 2.5, step: 0.05, label: { en: 'Rim glow', ar: 'توهّج الحافة' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'webgl2', cost: 'low' },
  still: 0.45,
  tags: ['energy', 'defence', 'hero', 'science-fiction', 'accent'],
  setup: fragment({
    fragment: `
uniform float u_cells;
uniform float u_impacts;
uniform float u_rim;
${hash}
// x: 0 at the centre of a hexagon, 0.5 on its edge; yz: the cell.
vec3 hexGrid(vec2 p) {
  const vec2 s = vec2(1.0, 1.7320508);
  vec4 centre = floor(vec4(p, p - vec2(0.5, 1.0)) / s.xyxy) + 0.5;
  vec4 offset = vec4(p - centre.xy * s, p - (centre.zw + 0.5) * s);
  vec4 pick = dot(offset.xy, offset.xy) < dot(offset.zw, offset.zw) ? vec4(offset.xy, centre.xy) : vec4(offset.zw, centre.zw + 0.5);
  vec2 a = abs(pick.xy);
  return vec3(max(dot(a, s * 0.5), a.x), pick.zw);
}
void main() {
  float unit = min(u_resolution.x, u_resolution.y);
  vec2 p = (2.0 * gl_FragCoord.xy - u_resolution) / unit;
  float t = u_time;
  float px = 2.0 / unit;
  // What the shield protects: a small lit sphere.
  float coreR = 0.17;
  float cd = length(p);
  float coreZ = sqrt(max(0.0, 1.0 - cd * cd / (coreR * coreR)));
  float lit = max(dot(vec3(p / coreR, coreZ), normalize(vec3(-0.5, 0.6, 0.62))), 0.0);
  vec3 colour = u_color0 + u_color4 * (0.12 + 0.88 * lit) * smoothstep(coreR + px, coreR - px, cd);
  colour += u_color2 * 0.012 / (cd * cd + 0.03);
  // The dome, raised from the ground up during the intro.
  vec2 q = p / 0.8;
  float rr = dot(q, q);
  float top = -1.0 + 2.3 * u_intro;
  float raised = smoothstep(top, top - 0.25, q.y);
  float crest = exp(-pow((q.y - top + 0.12) / 0.05, 2.0)) * (1.0 - u_intro);
  if (rr < 1.0) {
    float z = sqrt(1.0 - rr);
    vec3 n = vec3(q, z);
    vec3 hex = hexGrid(q / (0.45 + z) * u_cells + vec2(0.0, t * 0.12));
    float wall = smoothstep(0.4, 0.49, hex.x);
    float cellRandom = hash21(hex.yz + 3.0);
    float flicker = pow(0.5 + 0.5 * sin(t * (0.6 + 2.0 * cellRandom) + 30.0 * cellRandom), 6.0);
    float glance = pow(1.0 - z, 3.0 / u_rim);
    float band = pow(0.5 + 0.5 * sin(n.y * 9.0 - t * 1.6), 8.0);
    vec3 shield = u_color1 * ((0.05 + 0.5 * glance + 0.12 * band) * (0.3 + 0.7 * wall) + glance * 0.6)
      + u_color2 * (flicker * 0.4 * (1.0 - wall) + 0.2 * wall + 0.07);
    float hits = floor(u_impacts + 0.5);
    for (int i = 0; i < 5; i++) {
      if (float(i) >= hits) break;
      float k = float(i);
      float beat = t * (0.55 + 0.11 * k) + hash11(k * 3.7 + 1.0);
      float phase = fract(beat);
      vec2 place = hash22(vec2(floor(beat), k * 5.3 + 2.0));
      float off = 0.78 * sqrt(place.y);
      vec3 at = vec3(off * cos(place.x * 6.2831853), off * sin(place.x * 6.2831853), sqrt(1.0 - off * off));
      float d = acos(clamp(dot(n, at), -1.0, 1.0));
      float spread = phase * 1.3;
      float decay = (1.0 - phase) * (1.0 - phase);
      float ringWidth = 0.03 + 0.05 * phase;
      float ripple = exp(-pow((d - spread) / ringWidth, 2.0)) + 0.5 * exp(-pow((d - spread * 0.6) / ringWidth, 2.0));
      float charged = smoothstep(spread, spread - 0.35, d);
      shield += u_color3 * (ripple * (0.6 + 0.8 * wall) + charged * (0.3 * wall + 0.12 * flicker)) * decay
        + u_color4 * exp(-d * d / 0.012) * exp(-phase * 7.0) * 1.6;
    }
    colour += shield * raised * smoothstep(1.0, 1.0 - 2.0 * px, sqrt(rr));
  }
  colour += u_color1 * (exp(-max(sqrt(rr) - 1.0, 0.0) * 14.0) * 0.3 * raised * step(1.0, rr) + crest * smoothstep(1.15, 0.9, sqrt(rr)));
  outColor = vec4(colour, 1.0);
}`,
    uniforms: (ctx) => ({ u_cells: ctx.params.cells, u_impacts: ctx.params.impacts, u_rim: ctx.params.rim }),
  }),
});
