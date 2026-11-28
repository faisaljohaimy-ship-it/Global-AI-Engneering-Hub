import { defineMotion } from '../../core/define.mjs';
import { points } from '../../engines/webgl.mjs';
import { hash } from '../../shaders/chunks.mjs';

export default defineMotion({
  id: 'neural-embedding-space',
  number: 50,
  module: 'neural',
  name: { en: 'Embedding Space Exploration', ar: 'استكشاف فضاء التضمين' },
  summary: {
    en: 'A shapeless cloud of points, the vectors of many items, turns in three dimensions while it sorts itself: items of the same kind drift together into coloured clusters, and the clusters settle at their own places in the space.',
    ar: 'سحابةٌ بلا شكل من النقاط، هي متّجهات عناصر كثيرة، تدور في ثلاثة أبعاد وهي تفرز نفسها: تتقارب عناصر النوع الواحد في عناقيد ملوّنة، وتستقرّ العناقيد كلٌّ في موضعه من الفضاء.',
  },
  engine: 'webgl2-points',
  kind: 'oneshot',
  duration: 5000,
  easing: 'ease-in-out',
  colors: ['#05060c', '#60a5fa', '#f472b6', '#34d399', '#fbbf24'],
  params: {
    clusters: { default: 6, min: 2, max: 9, step: 1, label: { en: 'Clusters', ar: 'عدد العناقيد' } },
    spread: { default: 0.16, min: 0.05, max: 0.35, step: 0.01, label: { en: 'Cluster spread', ar: 'انتشار العنقود' } },
  },
  camera: {
    turn: { default: 1, min: 0, max: 2.5, step: 0.1, label: { en: 'Camera turn', ar: 'دوران الكاميرا' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'webgl2', cost: 'medium' },
  still: 1,
  tags: ['ai', 'data', 'clusters', 'vectors', 'science', 'hero'],
  setup: points({
    count: 9000,
    vertex: `
uniform float u_clusters;
uniform float u_spread;
uniform float u_turn;
${hash}
vec3 gauss(vec3 h) {
  float r = sqrt(-2.0 * log(max(h.x, 1e-4)));
  return vec3(r * cos(6.2831853 * h.y), r * sin(6.2831853 * h.y), r * cos(6.2831853 * h.z)) * 0.6;
}
void main() {
  float id = float(gl_VertexID);
  vec3 h = hash31(id * 1.13 + 7.0);
  vec3 g = hash31(id * 2.91 + 1.0);
  float cluster = floor(h.x * u_clusters);
  // Cluster centres sit on a twisted shell so they never overlap.
  vec3 c = hash31(cluster * 17.0 + 3.0);
  float theta = c.x * 6.2831853; float phi = acos(c.y * 1.6 - 0.8);
  vec3 centre = vec3(sin(phi) * cos(theta), cos(phi), sin(phi) * sin(theta)) * 0.75;
  vec3 start = (hash31(id * 0.37 + 5.0) * 2.0 - 1.0) * 0.95;
  // Each point sorts itself at its own pace.
  float s = clamp((u_progress - g.x * 0.35) / 0.65, 0.0, 1.0);
  s = s * s * (3.0 - 2.0 * s);
  vec3 pos = mix(start, centre + gauss(g) * u_spread, s);
  float a = u_progress * u_turn * 3.14159265 + 0.4;
  pos.xz = mat2(cos(a), -sin(a), sin(a), cos(a)) * pos.xz;
  float tilt = 0.35;
  pos.yz = mat2(cos(tilt), -sin(tilt), sin(tilt), cos(tilt)) * pos.yz;
  float perspective = 1.0 / (2.6 - pos.z);
  vec2 screen = pos.xy * perspective * 2.4;
  screen.x *= u_resolution.y / u_resolution.x;
  gl_Position = vec4(screen, 0.0, 1.0);
  gl_PointSize = max(1.0, (1.4 + 1.8 * g.z) * perspective * u_resolution.y / 100.0);
  int k = int(mod(cluster, 4.0));
  vec3 tint = k == 0 ? u_color1 : (k == 1 ? u_color2 : (k == 2 ? u_color3 : u_color4));
  vec3 grey = vec3(dot(tint, vec3(0.3, 0.5, 0.2))) * 0.7;
  v_color = vec4(mix(grey, tint, s), 0.35 + 0.45 * s);
}`,
    fragment: `
void main() {
  float falloff = smoothstep(0.5, 0.1, length(gl_PointCoord - 0.5));
  outColor = vec4(v_color.rgb, v_color.a * falloff);
}`,
    uniforms: (ctx) => ({ u_clusters: Math.round(ctx.params.clusters), u_spread: ctx.params.spread, u_turn: ctx.camera.turn }),
  }),
});
