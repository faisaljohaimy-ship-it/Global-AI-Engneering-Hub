// GLSL ES 3.00 building blocks. Interpolate the ones a shader needs into its source:
//   fragment({ fragment: `${hash}${noise}${fbm} void main() { ... }` })
// They are plain strings, so the same chunks work in a Three.js ShaderMaterial.

export const hash = `
float hash11(float p) { p = fract(p * 0.1031); p *= p + 33.33; p *= p + p; return fract(p); }
float hash21(vec2 p) { vec3 q = fract(vec3(p.xyx) * 0.1031); q += dot(q, q.yzx + 33.33); return fract((q.x + q.y) * q.z); }
vec2 hash22(vec2 p) { vec3 q = fract(vec3(p.xyx) * vec3(0.1031, 0.1030, 0.0973)); q += dot(q, q.yzx + 33.33); return fract((q.xx + q.yz) * q.zy); }
vec3 hash31(float p) { vec3 q = fract(vec3(p) * vec3(0.1031, 0.1030, 0.0973)); q += dot(q, q.yzx + 33.33); return fract((q.xxy + q.yzz) * q.zyx); }
`;

/** Value noise in 2D, 0..1. Needs \`hash\`. */
export const noise = `
float noise(vec2 p) {
  vec2 i = floor(p); vec2 f = fract(p); vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash21(i), hash21(i + vec2(1.0, 0.0)), u.x), mix(hash21(i + vec2(0.0, 1.0)), hash21(i + vec2(1.0, 1.0)), u.x), u.y);
}
`;

/** Fractal noise; octaves follow u_quality. Needs \`hash\` and \`noise\`. */
export const fbm = `
float fbm(vec2 p) {
  float value = 0.0; float amplitude = 0.5;
  for (int i = 0; i < 2 + u_quality; i++) { value += amplitude * noise(p); p = p * 2.03 + vec2(17.1, 9.2); amplitude *= 0.5; }
  return value;
}
`;

export const rotate = `
mat2 rot(float a) { float c = cos(a); float s = sin(a); return mat2(c, -s, s, c); }
`;

/** Centred coordinates with the short side spanning -1..1; x follows the reading direction. */
export const frame = `
vec2 frameUv() { vec2 p = (2.0 * gl_FragCoord.xy - u_resolution) / min(u_resolution.x, u_resolution.y); p.x *= u_dir; return p; }
`;

export const sdf = `
float sdCircle(vec2 p, float r) { return length(p) - r; }
float sdBox(vec2 p, vec2 b) { vec2 d = abs(p) - b; return length(max(d, 0.0)) + min(max(d.x, d.y), 0.0); }
float sdSegment(vec2 p, vec2 a, vec2 b) { vec2 pa = p - a; vec2 ba = b - a; return length(pa - ba * clamp(dot(pa, ba) / dot(ba, ba), 0.0, 1.0)); }
float sdSphere(vec3 p, float r) { return length(p) - r; }
float sdTorus(vec3 p, vec2 t) { return length(vec2(length(p.xz) - t.x, p.y)) - t.y; }
float sdRoundBox(vec3 p, vec3 b, float r) { vec3 q = abs(p) - b; return length(max(q, 0.0)) + min(max(q.x, max(q.y, q.z)), 0.0) - r; }
float smin(float a, float b, float k) { float h = clamp(0.5 + 0.5 * (b - a) / k, 0.0, 1.0); return mix(b, a, h) - k * h * (1.0 - h); }
`;

/** A three-stop gradient through the palette, t in 0..1. */
export const palette = `
vec3 palette(float t) { t = clamp(t, 0.0, 1.0); return t < 0.5 ? mix(u_color0, u_color1, t * 2.0) : mix(u_color1, u_color2, t * 2.0 - 1.0); }
`;

export const fresnel = `
float fresnel(vec3 normal, vec3 view, float power) { return pow(1.0 - clamp(dot(normalize(normal), normalize(view)), 0.0, 1.0), power); }
`;

/** Value noise in 3D, 0..1. Needs \`hash\`. */
export const noise3 = `
float hash13(vec3 p) { p = fract(p * 0.1031); p += dot(p, p.zyx + 31.32); return fract((p.x + p.y) * p.z); }
float noise3(vec3 p) {
  vec3 i = floor(p); vec3 f = fract(p); vec3 u = f * f * (3.0 - 2.0 * f);
  return mix(mix(mix(hash13(i), hash13(i + vec3(1, 0, 0)), u.x), mix(hash13(i + vec3(0, 1, 0)), hash13(i + vec3(1, 1, 0)), u.x), u.y),
             mix(mix(hash13(i + vec3(0, 0, 1)), hash13(i + vec3(1, 0, 1)), u.x), mix(hash13(i + vec3(0, 1, 1)), hash13(i + vec3(1, 1, 1)), u.x), u.y), u.z);
}
`;

/** Fractal noise in 3D; octaves follow u_quality. Needs \`hash\` and \`noise3\`. */
export const fbm3 = `
float fbm3(vec3 p) {
  float value = 0.0; float amplitude = 0.5;
  for (int i = 0; i < 1 + u_quality; i++) { value += amplitude * noise3(p); p = p * 2.02 + vec3(11.3, 5.7, 3.1); amplitude *= 0.5; }
  return value;
}
`;

/** Cellular noise: x is the distance to the nearest cell point, y to the second nearest, z a random value for the nearest cell. Needs \`hash\`. */
export const voronoi = `
vec3 voronoi(vec2 p) {
  vec2 cell = floor(p); vec2 f = fract(p); float nearest = 8.0; float second = 8.0; float id = 0.0;
  for (int y = -1; y <= 1; y++) for (int x = -1; x <= 1; x++) {
    vec2 offset = vec2(float(x), float(y)); vec2 point = hash22(cell + offset);
    float d = length(offset + point - f);
    if (d < nearest) { second = nearest; nearest = d; id = hash21(cell + offset + 7.7); } else if (d < second) { second = d; }
  }
  return vec3(nearest, second, id);
}
`;

/** Centred coordinates with the short side spanning -1..1, without any mirroring: for direction-neutral shaders. */
export const centred = `
vec2 centredUv() { return (2.0 * gl_FragCoord.xy - u_resolution) / min(u_resolution.x, u_resolution.y); }
`;

/** Filmic tone curve and a soft vignette, for finishing a lit scene. */
export const finish = `
vec3 tonemap(vec3 c) { c = max(c, 0.0); return (c * (2.51 * c + 0.03)) / (c * (2.43 * c + 0.59) + 0.14); }
float vignette(vec2 uv01, float strength) { vec2 q = uv01 - 0.5; return 1.0 - strength * dot(q, q) * 2.0; }
`;

/** A camera ray for ray marching: origin \`eye\`, looking at \`target\`, through centred coordinates \`p\`. */
export const ray = `
vec3 cameraRay(vec3 eye, vec3 target, vec2 p, float zoom) {
  vec3 forward = normalize(target - eye); vec3 right = normalize(cross(forward, vec3(0.0, 1.0, 0.0))); vec3 up = cross(right, forward);
  return normalize(forward * zoom + right * p.x + up * p.y);
}
`;
