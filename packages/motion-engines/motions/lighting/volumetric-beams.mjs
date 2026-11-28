import { defineMotion } from '../../core/define.mjs';
import { fragment } from '../../engines/webgl.mjs';
import { fbm, finish, hash, noise } from '../../shaders/chunks.mjs';

export default defineMotion({
  id: 'lighting-volumetric-beams',
  number: 71,
  module: 'lighting',
  name: { en: 'Volumetric Light Beams', ar: 'حزم الضوء الحجمية' },
  summary: {
    en: 'Sunlight pours through a slatted skylight into a dusty room: the shafts fan out and soften with distance, catch drifting haze and glinting motes, and leave pools of light on a polished floor.',
    ar: 'ضوء الشمس ينسكب من كوّة ذات شرائح إلى غرفة يملؤها الغبار: تتباعد الحزم وتلين حوافها كلما ابتعدت، ويظهر فيها الضباب المتحرك وذرّات الغبار اللامعة، ثم تترك بقعًا من الضوء على أرضية مصقولة.',
  },
  engine: 'webgl2-glsl',
  kind: 'loop',
  duration: 8000,
  easing: 'ease-out',
  colors: ['#080a11', '#ffd9a0', '#c9763c', '#35527a'],
  params: {
    beams: { default: 6, min: 2, max: 12, step: 1, label: { en: 'Beam count', ar: 'عدد الحزم' } },
    angle: { default: 22, min: -45, max: 45, step: 1, label: { en: 'Sun angle', ar: 'زاوية الشمس' } },
    haze: { default: 1, min: 0.2, max: 2, step: 0.05, label: { en: 'Haze density', ar: 'كثافة الضباب' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'webgl2', cost: 'low' },
  still: 0.3,
  tags: ['background', 'ambient', 'hero', 'cinematic', 'god-rays'],
  setup: fragment({
    fragment: `
uniform float u_beams;
uniform float u_angle;
uniform float u_haze;
${hash}${noise}${fbm}${finish}
float g_top; float g_span; float g_centre; vec2 g_sun;
// Sunlight reaching a point through the slats: x is how lit it is, y its place across the skylight in slat widths.
vec2 shaft(vec2 p) {
  float k = (g_top - g_sun.y) / min(p.y - g_sun.y, -0.001);
  float across = (g_sun.x + (p.x - g_sun.x) * k - g_centre) / (2.0 * g_span) + 0.5;
  float blur = (0.012 + 0.05 * max(g_top - p.y, 0.0)) / (2.0 * g_span);   // the penumbra widens away from the slats
  float soft = blur * u_beams;
  float gap = smoothstep(0.27 + soft, 0.27 - soft, abs(fract(across * u_beams) - 0.5));
  float inside = smoothstep(0.0, 2.0 * blur + 0.004, across) * smoothstep(1.0, 0.996 - 2.0 * blur, across);
  return vec2(gap * inside, across * u_beams);
}
float motes(vec2 p, float t, float scale) {
  vec2 g = p * scale + vec2(0.9, 0.5) * t * 0.012 * scale;
  vec2 cell = floor(g);
  float size = 0.1 + 0.12 * hash21(cell + 3.1);
  float twinkle = 0.5 + 0.5 * sin(t * (0.8 + 2.0 * hash21(cell + 4.1)) + 6.2831853 * hash21(cell + 9.3));
  return step(0.5, hash21(cell + 1.7)) * smoothstep(size, 0.0, length(fract(g) - 0.15 - 0.7 * hash22(cell))) * twinkle;
}
void main() {
  float unit = min(u_resolution.x, u_resolution.y);
  vec2 asp = u_resolution / unit;
  vec2 p = (2.0 * gl_FragCoord.xy - u_resolution) / unit;
  float t = u_time;
  float lean = radians(u_angle) + 0.07 * sin(6.2831853 * u_raw);          // the sun drifts a few degrees
  g_top = asp.y - 0.2;
  g_span = 0.66 * asp.x;
  g_sun = vec2(0.0, g_top) + vec2(-sin(lean), cos(lean)) * 2.6;
  g_centre = -tan(lean) * g_top / (1.0 + g_top / (2.6 * cos(lean)));       // the middle shaft crosses the middle of the frame
  float floorY = -0.66 * asp.y;
  float depth = clamp((floorY - p.y) / (asp.y + floorY), 0.0, 1.0);        // 0 at the foot of the wall, 1 at the bottom edge
  float onFloor = step(p.y, floorY);
  vec2 q = vec2(p.x, mix(p.y, 2.0 * floorY - p.y, onFloor));               // the floor shows the shafts mirrored in its polish
  vec2 s = shaft(q);
  float along = max(g_top - q.y, 0.0) / cos(lean);
  float smoke = fbm(q * 1.7 + vec2(t * 0.05, -t * 0.08));
  float threads = 0.7 + 0.6 * noise(vec2(s.y * 3.0, 0.5));
  float reach = smoothstep(0.0, 0.6, u_intro * 4.6 - along) * u_intro;     // the light arrives from the skylight downward
  float air = (0.3 + 0.7 * u_haze) * exp(-along * (0.14 + 0.2 * u_haze)) / (0.7 + 0.42 * along);
  float beam = s.x * air * mix(0.7, 2.1 * smoke, 0.65) * threads * reach;
  vec3 scatter = (u_color1 * 0.95 + u_color2 * 0.6 * smoke) * beam;
  float y01 = gl_FragCoord.y / u_resolution.y;
  vec3 room = u_color0 * (0.7 + 0.5 * y01) + u_color3 * (0.04 + 0.1 * (1.0 - y01));   // cool fill gathers low in the room
  // Wall and air.
  vec3 col = room + scatter;
  col += u_color1 * (motes(p, t, 8.0) + 0.7 * motes(p + 3.7, t * 1.3, 15.0)) * s.x * reach * 0.9;
  float bar = smoothstep(-0.012, 0.012, p.y - g_top);                      // the skylight itself: bright gaps between dark slats
  col = mix(col, u_color0 * 0.45 + u_color1 * 2.6 * s.x * u_intro, bar);
  col += u_color1 * 0.22 * u_intro * exp(-max(g_top - p.y, 0.0) * 7.0) * smoothstep(0.0, 0.1, s.y / u_beams) * smoothstep(1.0, 0.9, s.y / u_beams);
  // Floor: pools where the shafts land, and their reflection.
  vec2 foot = shaft(vec2(p.x - tan(lean) * depth * 0.3 * asp.y, floorY));
  float landAir = (0.3 + 0.7 * u_haze) * exp(-(g_top - floorY) * (0.14 + 0.2 * u_haze));
  float pool = foot.x * smoothstep(0.0, 0.1, depth) * smoothstep(0.95, 0.3, depth) * (0.5 + 0.5 / (0.3 + landAir));
  vec3 ground = u_color0 * (0.85 + 0.5 * depth) + u_color3 * 0.07 * depth
    + (u_color1 * 0.55 + u_color2 * 0.25) * pool * u_intro * smoothstep(0.0, 0.6, u_intro * 4.6 - (g_top - floorY))
    + scatter * 0.3 * (1.0 - depth) * (1.0 - depth);
  col = mix(col, ground, onFloor);
  col *= 1.0 - 0.55 * smoothstep(0.014, 0.0, abs(p.y - floorY));           // the foot of the wall
  outColor = vec4(tonemap(col) + (hash21(gl_FragCoord.xy) - 0.5) / 255.0, 1.0);
}`,
    uniforms: (ctx) => ({ u_beams: Math.round(ctx.params.beams), u_angle: ctx.params.angle, u_haze: ctx.params.haze }),
  }),
});
