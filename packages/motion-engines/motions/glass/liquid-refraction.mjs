import { defineMotion } from '../../core/define.mjs';
import { fragment } from '../../engines/webgl.mjs';
import { centred } from '../../shaders/chunks.mjs';

export default defineMotion({
  id: 'glass-liquid-refraction',
  number: 31,
  module: 'glass',
  name: { en: 'Liquid Glass Refraction', ar: 'انكسار الزجاج السائل' },
  summary: {
    en: 'Drops of liquid glass drift over a striped poster, merge and part. Each one is a thick lens: it magnifies the stripes, squeezes them at its rim, and carries a wet highlight and a colour fringe.',
    ar: 'قطرات من زجاج سائل تنساب فوق ملصق مخطّط، تلتحم ثم تفترق. كل قطرة عدسة سميكة تكبّر الخطوط وتضغطها عند حافتها، وتعلوها لمعة رطبة وهُدب لوني.',
  },
  engine: 'webgl2-glsl',
  kind: 'loop',
  duration: 10000,
  easing: 'ease-out',
  colors: ['#0b1026', '#22d3ee', '#a78bfa', '#fb7185', '#f8fafc'],
  params: {
    ior: { default: 1.45, min: 1, max: 2, step: 0.01, label: { en: 'Index of refraction', ar: 'معامل الانكسار' } },
    dispersion: { default: 0.35, min: 0, max: 1, step: 0.05, label: { en: 'Dispersion', ar: 'التشتّت اللوني' } },
    merging: { default: 0.6, min: 0, max: 1, step: 0.05, label: { en: 'Merging', ar: 'الالتحام' } },
    drops: { default: 4, min: 2, max: 5, step: 1, label: { en: 'Drops', ar: 'عدد القطرات' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'webgl2', cost: 'low' },
  still: 0.4,
  tags: ['glass', 'liquid', 'refraction', 'hero', 'background'],
  setup: fragment({
    fragment: `
uniform float u_ior;
uniform float u_dispersion;
uniform float u_merging;
uniform float u_drops;
${centred}
// The poster under the glass: diagonal bars in a two-colour gradient and one flat disc.
vec3 poster(vec2 p) {
  float bar = smoothstep(0.17, 0.21, abs(fract(dot(p, vec2(0.515, 0.857)) * 2.6) - 0.5));
  vec3 colour = mix(mix(u_color1, u_color2, smoothstep(-1.3, 1.3, dot(p, vec2(0.857, -0.515)))), u_color0, bar * 0.92);
  float disc = smoothstep(0.02, -0.02, length(p - vec2(0.62, 0.18)) - 0.42);
  return mix(colour, mix(u_color3, u_color0, bar * 0.3), disc);
}
// All drops as one smooth dome: xy leans away from the nearest centre (in radii), z is the
// height squared (above 0 inside), w the local radius. Every centre rides a closed path, so the loop is seamless.
vec4 dome(vec2 p) {
  vec2 span = u_resolution / min(u_resolution.x, u_resolution.y);
  float a = u_raw * 6.2831853;
  float sharp = mix(10.0, 2.0, u_merging);
  float sum = 0.0; float radius = 0.0; vec2 lean = vec2(0.0);
  for (int i = 0; i < 5; i++) {
    float k = float(i);
    if (k >= u_drops) break;
    float odd = mod(k, 2.0);
    float r = (0.54 - 0.06 * k) * mix(0.45, 1.0, u_intro);
    vec2 q = (p - span * (0.3 + 0.07 * k) * vec2(1.25 * cos(a * (1.0 + odd) + k * 2.4), 0.8 * sin(a * (2.0 - odd) + k * 1.9 + 0.6))) / r;
    float w = exp(max(sharp * (1.0 - dot(q, q)), -40.0));
    sum += w; lean += w * q; radius += w * r;
  }
  return vec4(lean / sum, log(sum) / sharp, radius / sum);
}
void main() {
  vec2 p = centredUv();
  float px = 2.0 / min(u_resolution.x, u_resolution.y);
  vec4 drop = dome(p);
  float edge = -drop.z * drop.w * 0.5 / max(length(drop.xy), 0.3);
  vec3 normal = normalize(vec3(drop.xy, sqrt(max(drop.z, 0.0))));
  vec3 light = normalize(vec3(-0.5, 0.62, 0.6));
  // Outside: the poster, darker where the drops cast their shadow.
  vec3 colour = poster(p) * (1.0 - 0.5 * smoothstep(-0.3, 0.12, dome(p + vec2(-0.05, 0.07)).z));
  // Inside: the view ray is refracted at the dome and followed down to the poster, once for each colour.
  float height = normal.z * drop.w * 0.9;
  vec3 seen;
  for (int c = 0; c < 3; c++) {
    vec3 t = refract(vec3(0.0, 0.0, -1.0), normal, 1.0 / (1.0 + (u_ior - 1.0) * (1.0 + (float(c) - 1.0) * 0.4 * u_dispersion)));
    seen[c] = poster(p + t.xy * height / max(-t.z, 0.2))[c];
  }
  float side = dot(normalize(drop.xy + 1e-5), normalize(light.xy));
  seen *= 1.05 - 0.3 * side * (1.0 - normal.z);
  float glint = pow(max(dot(normal, normalize(light + vec3(0.0, 0.0, 1.0))), 0.0), 120.0);
  float bounce = pow(max(dot(normal, normalize(vec3(0.5, -0.6, 0.62))), 0.0), 24.0);
  float fresnel = pow(1.0 - normal.z, 3.0);
  seen += u_color4 * (glint + 0.16 * bounce + fresnel * (0.25 + 0.6 * max(side, 0.0)) + 0.3 * (1.0 - normal.z) * (1.0 - normal.z) * max(-side, 0.0));
  outColor = vec4(mix(colour, seen, smoothstep(px, -px, edge)), 1.0);
}`,
    uniforms: (ctx) => ({ u_ior: ctx.params.ior, u_dispersion: ctx.params.dispersion, u_merging: ctx.params.merging, u_drops: Math.round(ctx.params.drops) }),
  }),
});
