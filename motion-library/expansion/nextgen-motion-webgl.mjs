// SPDX-License-Identifier: MIT
// Fixed WebGL2 programs for the original motion brief. No fallback renderer.

const MAX_FRAMEBUFFER_EDGE = 416;
const MAX_FRAMEBUFFER_PIXELS = 131_072;
const PARTICLES = 2048;
const BACKGROUND = [8 / 255, 17 / 255, 31 / 255];
const activeCanvases = new WeakSet();
const clamp = (value) => Math.min(1, Math.max(0, value));

const TRIANGLE = `#version 300 es
out vec2 uv;
void main() {
  vec2 vertex = vec2(float((gl_VertexID << 1) & 2), float(gl_VertexID & 2));
  uv = vertex;
  gl_Position = vec4(vertex * 2.0 - 1.0, 0.0, 1.0);
}`;

const COMMON = `#version 300 es
precision highp float;
in vec2 uv;
out vec4 pixel;
uniform vec2 resolution;
uniform float time;
uniform float mirror;
const vec3 ink = vec3(8.0, 17.0, 31.0) / 255.0;
const vec3 cyan = vec3(0.31, 0.84, 0.97);
const vec3 violet = vec3(0.59, 0.39, 0.92);
const vec3 ice = vec3(0.86, 0.95, 1.0);
const vec3 amber = vec3(1.0, 0.71, 0.36);
vec2 coordinates() {
  vec2 p = (uv * 2.0 - 1.0) * resolution / min(resolution.x, resolution.y);
  return vec2(mirror * p.x + 0.096, p.y);
}
mat2 turn(float angle) {
  float c = cos(angle), s = sin(angle);
  return mat2(c, s, -s, c);
}
float hash2(vec2 cell) {
  return fract(sin(dot(cell, vec2(127.1, 311.7))) * 43758.5453);
}
float valueNoise(vec2 p) {
  vec2 a = floor(p), f = fract(p);
  f = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash2(a), hash2(a + vec2(1, 0)), f.x),
    mix(hash2(a + vec2(0, 1)), hash2(a + 1.0), f.x), f.y);
}
float fbm(vec2 p) {
  return valueNoise(p) * .57 + valueNoise(turn(.39) * p * 2.07) * .29
    + valueNoise(turn(.61) * p * 4.13) * .14;
}
float fillShape(float distance) {
  return 1.0 - smoothstep(-.003, .005, distance);
}
float rectSdf(vec2 p, vec2 halfSize, float roundness) {
  vec2 q = abs(p) - halfSize + roundness;
  return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - roundness;
}
void writeColor(vec3 rgb) {
  pixel = vec4(clamp(rgb, 0.0, 1.0), 1.0);
}
`;

const noiseDisplacement = `
void main() {
  vec2 p = coordinates();
  vec2 distortion = vec2(fbm(p * 4.6 + vec2(time * 1.8, 0.0)),
    fbm(p.yx * 4.8 + vec2(0.0, time * 2.4))) - .5;
  vec2 q = p + distortion * (.34 + time * .43);
  float distance = length(q) - .49;
  float ripple = .5 + .5 * cos(distance * 22.0 - time * 6.0);
  float coverage = fillShape(distance);
  vec3 material = mix(violet * .38, cyan, pow(ripple, 4.0));
  vec3 result = mix(ink, material, coverage * .7) + violet * exp(-abs(distance) * 19.0) * .27;
  writeColor(result);
}`;

const raymarchedGeometry = `
float sphereAndBox(vec3 p) {
  p.xz = turn(time * 1.74 - .7) * p.xz;
  p.yz = turn(.39 + time * .51) * p.yz;
  vec3 q = abs(p) - vec3(.43, .41, .39);
  float box = length(max(q, 0.0)) + min(0.0, max(q.x, max(q.y, q.z))) - .064;
  float hole = length(p - vec3(.22, .13, -.3)) - .33;
  return max(box, -hole);
}
vec3 normalAt(vec3 p) {
  const float e = .002;
  return normalize(vec3(
    sphereAndBox(p + vec3(e, 0, 0)) - sphereAndBox(p - vec3(e, 0, 0)),
    sphereAndBox(p + vec3(0, e, 0)) - sphereAndBox(p - vec3(0, e, 0)),
    sphereAndBox(p + vec3(0, 0, e)) - sphereAndBox(p - vec3(0, 0, e))));
}
void main() {
  vec2 p = coordinates();
  vec3 origin = vec3(0, 0, -2.85), ray = normalize(vec3(p * .71, 1));
  float travel = .01;
  bool hit = false;
  for (int step = 0; step < 40; step++) {
    float distance = sphereAndBox(origin + ray * travel);
    if (distance < .0025) { hit = true; break; }
    travel += distance;
    if (travel > 5.0) break;
  }
  vec3 result = ink + violet * exp(-dot(p,p) * 2.2) * .12;
  if (hit) {
    vec3 point = origin + ray * travel;
    vec3 n = normalAt(point);
    vec3 light = normalize(vec3(-.67, 1.0, -.87));
    float diffuse = max(0.0, dot(n, light));
    float rim = pow(1.0 - max(0.0, dot(n, -ray)), 3.0);
    vec3 base = mix(violet, cyan, smoothstep(-.36, .31, point.y));
    result = base * (.18 + .72 * diffuse) + ice * rim * .27;
  }
  writeColor(result);
}`;

const sdfMorph = `
void main() {
  vec2 p = turn(time * 1.05) * coordinates();
  float circle = length(p) - .51;
  float diamond = (abs(p.x) + abs(p.y) - .67) * .7071;
  float square = rectSdf(p, vec2(.45, .39), .10);
  float distance = time < .5 ? mix(circle, diamond, smoothstep(0.0, .5, time))
                            : mix(diamond, square, smoothstep(.5, 1.0, time));
  float contour = exp(-abs(distance) * 33.0);
  float inner = .5 + .5 * sin(p.y * 11.5 + p.x * 6.6 - time * 4.3);
  vec3 material = mix(violet, cyan, inner) * (.27 + .48 * inner);
  writeColor(mix(ink, material, fillShape(distance)) + contour * ice * .56);
}`;

const ripple = `
void main() {
  vec2 p = coordinates() - vec2(-.26 + .40 * time, .11);
  float radius = length(p);
  float ring = radius - (.10 + time * .83);
  float wave = sin(ring * 30.0) * exp(-abs(ring) * 6.7);
  vec2 q = p + p / max(radius, .07) * wave * .049;
  vec2 line = abs(fract(q * 7.0) - .5);
  float grid = 1.0 - smoothstep(.01, .056, min(line.x, line.y));
  vec3 result = ink + cyan * grid * .26 * exp(-radius * .62);
  result += violet * max(wave, 0.0) * .49 + cyan * exp(-abs(ring) * 43.0) * .28;
  writeColor(result);
}`;

const chromaticAberration = `
float imagePlane(vec2 p) {
  float edge = exp(-abs(rectSdf(turn(.24) * p, vec2(.47,.31), .115)) * 37.0);
  float circle = exp(-abs(length(p - vec2(.03, -.015)) - .18) * 33.0);
  float bars = fillShape(rectSdf(p + vec2(.04,.01), vec2(.35,.025), .014));
  return max(max(edge, circle), bars * .84);
}
void main() {
  vec2 p = coordinates() * (1.12 - .24 * time);
  float spread = .015 + .15 * sin(time * 2.66);
  vec2 drift = vec2(spread, -spread * .34);
  vec3 lenses = vec3(imagePlane(p + drift), imagePlane(p), imagePlane(p - drift));
  writeColor(ink + lenses * vec3(.81, .73, .97));
}`;

const fractal = `
void main() {
  vec2 p = coordinates();
  vec2 z = p * (1.49 - .37 * time);
  vec2 c = vec2(-.77 + .082 * cos(time * 4.35), .12 + .23 * sin(time * 4.35));
  float count = 0.0;
  for (int i = 0; i < 38; i++) {
    if (dot(z,z) > 22.0) break;
    z = vec2(z.x*z.x-z.y*z.y, 2.0*z.x*z.y) + c;
    count += 1.0;
  }
  float band = (.5 + .5 * sin(count * .75 + time * 1.6)) * smoothstep(1.0, 13.0, count);
  vec3 result = ink + mix(violet, cyan, clamp(count / 20.0, 0.0, 1.0)) * band * .8;
  if (count >= 38.0) result *= .46;
  writeColor(result);
}`;

const waveInterference = `
void main() {
  vec2 p = coordinates();
  vec2 a = vec2(-.39, .17 * sin(time * 3.2));
  vec2 b = vec2(.32, -.22 * cos(time * 3.8));
  float ra = length(p - a), rb = length(p - b);
  float wa = sin(20.0 * ra - time * 12.0) * exp(-ra * .85);
  float wb = sin(20.0 * rb - time * 12.0 + time * 5.3) * exp(-rb * .85);
  float amplitude = .5 * (wa + wb);
  vec3 energy = amplitude > 0.0 ? cyan : violet;
  vec3 result = ink + energy * pow(abs(amplitude), 1.55) * .96;
  result += amber * (exp(-ra * 52.0) + exp(-rb * 52.0));
  writeColor(result);
}`;

const fresnel = `
void main() {
  vec2 p = coordinates() - vec2(.12 * sin(time * 3.6), -.03);
  vec2 disk = p / .57;
  float radius2 = dot(disk, disk);
  vec3 result = ink + violet * .11 * exp(-abs(radius2 - 1.0) * 3.0);
  if (radius2 < 1.0) {
    vec3 normal = vec3(disk, sqrt(1.0 - radius2));
    vec3 light = normalize(vec3(mix(-.64, .75, time), .37, 1.0));
    float cosine = clamp(dot(normal, vec3(0,0,1)), 0.0, 1.0);
    float f0 = mix(.046, .47, time);
    float reflection = f0 + (1.0 - f0) * pow(1.0 - cosine, 5.0);
    float diffuse = max(dot(normal, light), 0.0);
    float highlight = pow(max(dot(normal, normalize(light+vec3(0,0,1))),0.0), 18.0);
    result = violet * (.13 + .4 * diffuse) + cyan * reflection * .77 + ice * highlight * .64;
  }
  writeColor(result);
}`;

const materialDissolve = `
void main() {
  vec2 p = turn(.14 - time * .28) * coordinates();
  float surface = rectSdf(p, vec2(.60, .41), .14);
  float grain = fbm(p * 13.0 + vec2(time * 1.27, -time * 1.62));
  float threshold = mix(.11, .69, time);
  float intact = fillShape(surface) * smoothstep(threshold, threshold+.018, grain);
  float edge = fillShape(surface) * exp(-abs(grain-threshold) * 69.0);
  float seam = .35 + .3 * sin(p.y * 22.0 + p.x * 9.0);
  vec3 material = mix(violet * .31, cyan * .84, grain * seam + .24);
  writeColor(mix(ink, material, intact) + edge * amber * .91);
}`;

const gpuInterface = `
vec4 plane(vec2 p, float index) {
  float spread = smoothstep(.05, .82, time);
  float offset = index - 1.0;
  p.x -= offset * mix(.085, .32, spread);
  p.y -= offset * mix(.15, .045, spread);
  float yaw = offset * mix(.57, -.29, spread) + sin(time * 3.4 + index) * .26;
  float perspective = max(.70, 1.0 + p.x * sin(yaw));
  vec2 q = vec2(p.x / max(.55, cos(yaw)), p.y) / perspective;
  float frame = rectSdf(q, vec2(.43 - index*.02, .28), .055);
  float mask = fillShape(frame);
  float window = fillShape(rectSdf(q - vec2(-.12, .116), vec2(.21, .043), .015));
  float first = fillShape(rectSdf(q - vec2(.01, -.045), vec2(.30, .024), .011));
  float second = fillShape(rectSdf(q - vec2(-.10, -.13), vec2(.19, .023), .011));
  vec3 light = mix(violet, cyan, index / 2.0);
  vec3 base = ink * 1.82 + light * .18 + light * (window * .57 + first * .30 + second * .20);
  base += light * exp(-abs(frame) * 41.0) * .52;
  return vec4(base, mask * (.86 + index * .05));
}
void main() {
  vec2 p = coordinates();
  vec3 result = ink + violet * exp(-dot(p,p)*2.4) * .12;
  for (int i = 0; i < 3; i++) {
    vec4 layer = plane(p, float(i));
    result = mix(result, layer.rgb, layer.a);
  }
  writeColor(result);
}`;

const composite = `
uniform sampler2D overlay;
void main() {
  vec2 p = coordinates();
  float halo = exp(-abs(length(p) - .49 - .085 * sin(time * 5.0)) * 10.0);
  float grid = 1.0 - smoothstep(.022, .052, abs(fract(p.y * 13.0 + time * .75) - .5));
  vec3 result = ink + mix(cyan, violet, .5 + .5 * cos(p.x * 4.5 + time * 2.0)) * halo * .41;
  result += violet * grid * exp(-dot(p,p)) * .19;
  vec2 panelUv = p * .55 + .5;
  if (all(greaterThanEqual(panelUv, vec2(0))) && all(lessThanEqual(panelUv, vec2(1)))) {
    float readableX = mirror < 0.0 ? 1.0 - panelUv.x : panelUv.x;
    vec4 layer = texture(overlay, vec2(readableX, 1.0 - panelUv.y));
    result = mix(result, layer.rgb, layer.a);
  }
  writeColor(result);
}`;

const SWARM_VERTEX = `#version 300 es
precision highp float;
uniform vec2 resolution;
uniform float time;
uniform float mirror;
out vec3 tint;
float random(float id) { return fract(sin(id * 78.233) * 43758.5453); }
void main() {
  float id = float(gl_VertexID) + 1.0;
  float noiseA = random(id), noiseB = random(id + 734.5);
  float angle = noiseA * 6.28318 + time * (2.0 + 4.4 * noiseB) - noiseB * 2.4;
  float radius = sqrt(noiseB) * (.63 + .15 * sin(angle * 2.0 - time * 4.1));
  float swirl = 1.0 + .16 * sin(angle * 3.0 + time * 5.0);
  vec2 point = vec2(cos(angle) * radius * swirl, sin(angle) * radius * (.77 + .22 * noiseA));
  point.x = mirror * (point.x - .096 + .16 * sin(time * 4.4));
  point *= min(resolution.x, resolution.y) / resolution;
  gl_Position = vec4(point, 0.0, 1.0);
  gl_PointSize = 1.5 + noiseA * 3.0;
  tint = mix(vec3(.23,.62,1.0), vec3(.66,.32,.94), noiseB);
}`;

const SWARM_FRAGMENT = `#version 300 es
precision highp float;
in vec3 tint;
out vec4 pixel;
void main() {
  float radius = length(gl_PointCoord - .5);
  float intensity = 1.0 - smoothstep(.05, .5, radius);
  pixel = vec4(tint, intensity * .59);
}`;

const motionSpecs = [
  ['shaders-noise-displacement', 'GLSL Noise Displacement', 'إزاحة بضوضاء GLSL', 'Fractal noise displaces a GPU surface contour along two independent axes.', noiseDisplacement],
  ['shaders-raymarched-geometry', 'Ray-marched Geometry', 'هندسة بتتبع الشعاع', 'A bounded sphere-tracing loop shades a rotated signed-distance solid.', raymarchedGeometry],
  ['shaders-sdf-morph', 'Signed Distance Field Morph', 'تحول حقل المسافة الموقّعة', 'Smooth interpolation changes the zero contour of three signed distance functions.', sdfMorph],
  ['shaders-ripple', 'Shader-based Ripple', 'تموج بالمظلّل', 'A damped traveling ripple radially displaces a procedural grid.', ripple],
  ['shaders-chromatic-aberration', 'Chromatic Aberration Transition', 'انتقال الانحراف اللوني', 'The shader samples individual color channels at separate spatial offsets.', chromaticAberration],
  ['shaders-fractal', 'Procedural Fractal Shader', 'مظلّل كسيري إجرائي', 'A bounded Julia iteration evolves its complex parameter through time.', fractal],
  ['shaders-wave-interference', 'GPU Wave Interference', 'تداخل موجات بالمعالج الرسومي', 'Signed fields from two changing sources combine constructively and destructively.', waveInterference],
  ['shaders-fresnel', 'Dynamic Fresnel Effect', 'تأثير فرينل ديناميكي', 'Analytic surface normals drive a Schlick Fresnel rim and moving light.', fresnel],
  ['shaders-material-dissolve', 'Shader-based Material Dissolve', 'تلاشي مادة بالمظلّل', 'An advancing noise threshold removes material and illuminates the discontinuity.', materialDissolve],
  ['particles-gpu-swarm', 'GPU Particle Swarm', 'سرب جسيمات بالمعالج الرسومي', 'A vertex program derives 2048 animated particle positions from vertex identity.', null],
  ['compositions-gpu-interface-transformation', 'Multi-layer GPU Interface Transformation', 'تحول واجهة رسومية متعددة الطبقات', 'Three GPU projected planes transform their perspective and blend in depth order.', gpuInterface],
  ['compositions-multi-engine-cinematic', 'Multi-engine Cinematic Composition', 'تركيب سينمائي متعدد المحركات', 'A Canvas2D title and timeline are composited as a texture over a WebGL2 scene.', composite],
];

const specs = new Map(motionSpecs.map((spec) => [spec[0], spec]));
const SWARM = 'particles-gpu-swarm';
const COMPOSITE = 'compositions-multi-engine-cinematic';

export const definitions = Object.freeze(motionSpecs.map(([id, name_en, name_ar, mechanism]) => Object.freeze({
  id, name_en, name_ar, mechanism, engine: 'webgl2',
  renderers: Object.freeze(id === COMPOSITE ? ['webgl2', 'canvas2d'] : ['webgl2']),
  duration_ms: 3600, license: 'MIT', license_file: 'motion-library/expansion/LICENSE',
  source: Object.freeze({module: 'motion-library/expansion/nextgen-motion-webgl.mjs'}),
  implementation_status: 'implemented-source', runtime_status: 'requires-current-source-bound-proof',
  reduced_motion: Object.freeze({mode: 'static-poster', progress: .55}),
})));

function bounded(value, minimum, maximum, label) {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < minimum || value > maximum) {
    throw new RangeError('Invalid ' + label);
  }
  return value;
}

function compile(gl, type, source) {
  const shader = gl.createShader(type);
  if (!shader) throw new Error('WebGL2 shader allocation failed');
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    const reason = gl.getShaderInfoLog(shader);
    gl.deleteShader(shader);
    throw new Error('WebGL2 shader compilation failed: ' + reason);
  }
  return shader;
}

function link(gl, vertexSource, fragmentSource) {
  const program = gl.createProgram();
  if (!program) throw new Error('WebGL2 program allocation failed');
  const shaders = [];
  try {
    shaders.push(compile(gl, gl.VERTEX_SHADER, vertexSource));
    shaders.push(compile(gl, gl.FRAGMENT_SHADER, fragmentSource));
    for (const shader of shaders) gl.attachShader(program, shader);
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      throw new Error('WebGL2 program link failed: ' + gl.getProgramInfoLog(program));
    }
    for (const shader of shaders) gl.detachShader(program, shader);
    return program;
  } catch (error) {
    gl.deleteProgram(program);
    throw error;
  } finally {
    for (const shader of shaders) gl.deleteShader(shader);
  }
}

function makeOverlay(canvas) {
  const overlay = canvas.ownerDocument?.createElement('canvas')
    ?? (globalThis.OffscreenCanvas ? new OffscreenCanvas(192, 192) : null);
  if (!overlay) throw new Error('Canvas2D composition surface unavailable');
  overlay.width = 192;
  overlay.height = 192;
  const context = overlay.getContext('2d');
  if (!context) throw new Error('Canvas2D composition context unavailable');
  return {overlay, context};
}

function composeOverlay(surface, context, time, rtl) {
  context.clearRect(0, 0, surface.width, surface.height);
  const progress = 4 + time * 134;
  context.fillStyle = '#a78bfa';
  context.fillRect(24, 143, 144, 2);
  context.fillStyle = '#67e8f9';
  context.fillRect(rtl ? 168 - progress : 24, 142, progress, 4);
  context.beginPath();
  context.arc(rtl ? 168 - progress : 24 + progress, 144, 5, 0, Math.PI * 2);
  context.fill();
  context.fillStyle = '#f1f5f9';
  context.font = '17px system-ui, sans-serif';
  context.textAlign = 'center';
  context.fillText(rtl ? 'تركيب سينمائي' : 'CINEMATIC', 96, 97);
  context.fillStyle = '#aac5df';
  context.font = '10px system-ui, sans-serif';
  context.fillText(rtl ? 'مرحلة العرض' : 'COMPOSITION', 96, 114);
}

export function createMotion(canvas, id, options = {}) {
  const spec = specs.get(id);
  if (!spec) throw new RangeError('Unknown WebGL2 motion');
  if (!canvas || typeof canvas.getContext !== 'function') throw new TypeError('A canvas is required');
  if (activeCanvases.has(canvas)) throw new Error('Canvas already has an active motion');
  const width = bounded(options.width ?? canvas.width, 120, 4096, 'width');
  const height = bounded(options.height ?? canvas.height, 90, 4096, 'height');
  const scale = Math.min(1, MAX_FRAMEBUFFER_EDGE / Math.max(width, height),
    Math.sqrt(MAX_FRAMEBUFFER_PIXELS / (width * height)));
  const pixels = Object.freeze({width: Math.floor(width * scale), height: Math.floor(height * scale)});
  let rtl = options.rtl ?? false, reducedMotion = options.reducedMotion ?? false;
  if (typeof rtl !== 'boolean' || typeof reducedMotion !== 'boolean') throw new RangeError('Invalid motion preferences');
  const gl = canvas.getContext('webgl2', {
    alpha: false, antialias: false, depth: false, stencil: false, preserveDrawingBuffer: true,
  });
  if (!gl) throw new Error('WebGL2 context unavailable');
  const previous = {width: canvas.width, height: canvas.height, style: canvas.getAttribute?.('style') ?? null};
  const swarm = id === SWARM, compositeMode = id === COMPOSITE;
  let program, vao, texture, layer, destroyed = false;

  const restore = () => {
    gl.useProgram(null);
    gl.bindVertexArray(null);
    gl.bindTexture(gl.TEXTURE_2D, null);
    if (texture) gl.deleteTexture(texture);
    if (vao) gl.deleteVertexArray(vao);
    if (program) gl.deleteProgram(program);
    canvas.width = previous.width;
    canvas.height = previous.height;
    if (canvas.style) {
      if (previous.style === null) canvas.removeAttribute('style');
      else canvas.setAttribute('style', previous.style);
    }
    activeCanvases.delete(canvas);
  };

  try {
    program = link(gl, swarm ? SWARM_VERTEX : TRIANGLE, swarm ? SWARM_FRAGMENT : COMMON + spec[4]);
    vao = gl.createVertexArray();
    if (!vao) throw new Error('WebGL2 vertex array allocation failed');
    if (compositeMode) {
      layer = makeOverlay(canvas);
      texture = gl.createTexture();
      if (!texture) throw new Error('WebGL2 overlay texture allocation failed');
      gl.bindTexture(gl.TEXTURE_2D, texture);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    }
    canvas.width = pixels.width;
    canvas.height = pixels.height;
    if (canvas.style) {
      canvas.style.width = width + 'px';
      canvas.style.height = height + 'px';
    }
    activeCanvases.add(canvas);
  } catch (error) {
    restore();
    throw error;
  }

  const resolutionUniform = gl.getUniformLocation(program, 'resolution');
  const timeUniform = gl.getUniformLocation(program, 'time');
  const mirrorUniform = gl.getUniformLocation(program, 'mirror');
  const overlayUniform = compositeMode ? gl.getUniformLocation(program, 'overlay') : null;
  const debugRenderer = gl.getExtension('WEBGL_debug_renderer_info');
  const renderer = debugRenderer ? gl.getParameter(debugRenderer.UNMASKED_RENDERER_WEBGL) : null;

  function alive() {
    if (destroyed) throw new Error('Motion was destroyed');
    if (gl.isContextLost()) throw new Error('WebGL2 context was lost');
  }
  function render(value) {
    alive();
    const requested = bounded(value, -1e7, 1e7, 'progress');
    const time = reducedMotion ? .55 : clamp(requested);
    gl.viewport(0, 0, pixels.width, pixels.height);
    gl.useProgram(program);
    gl.bindVertexArray(vao);
    gl.uniform2f(resolutionUniform, pixels.width, pixels.height);
    gl.uniform1f(timeUniform, time);
    gl.uniform1f(mirrorUniform, rtl ? -1 : 1);
    if (compositeMode) {
      composeOverlay(layer.overlay, layer.context, time, rtl);
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, texture);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, layer.overlay);
      gl.uniform1i(overlayUniform, 0);
    }
    if (swarm) {
      gl.clearColor(...BACKGROUND, 1);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.enable(gl.BLEND);
      gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
      gl.drawArrays(gl.POINTS, 0, PARTICLES);
      gl.disable(gl.BLEND);
    } else {
      gl.disable(gl.BLEND);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    }
    if (gl.getError() !== gl.NO_ERROR) throw new Error('WebGL2 rendering error');
    return {progress: time, reducedMotion, ...pixels};
  }
  function readPixels() {
    alive();
    const data = new Uint8Array(pixels.width * pixels.height * 4);
    gl.readPixels(0, 0, pixels.width, pixels.height, gl.RGBA, gl.UNSIGNED_BYTE, data);
    if (gl.getError() !== gl.NO_ERROR) throw new Error('WebGL2 readback error');
    return data;
  }
  return Object.freeze({
    render,
    readPixels,
    configure(update = {}) {
      alive();
      const nextRtl = update.rtl ?? rtl, nextReduced = update.reducedMotion ?? reducedMotion;
      if (typeof nextRtl !== 'boolean' || typeof nextReduced !== 'boolean') throw new RangeError('Invalid motion preferences');
      rtl = nextRtl;
      reducedMotion = nextReduced;
    },
    runtimeInfo() {
      alive();
      return {engine: 'webgl2', renderers: compositeMode ? ['webgl2', 'canvas2d'] : ['webgl2'],
        renderer, software_renderer: renderer ? /swiftshader|llvmpipe|software/i.test(renderer) : null,
        source_framebuffer: {...pixels}, viewport: {width, height}, particles: swarm ? PARTICLES : null,
        production_fps_verified: false, hardware_verified: false};
    },
    benchmark({frames = 16, budget_ms = 25} = {}) {
      bounded(frames, 8, 120, 'benchmark frames');
      bounded(budget_ms, .1, 500, 'benchmark budget');
      if (!Number.isInteger(frames)) throw new RangeError('Benchmark frames must be an integer');
      const timings = [];
      for (let i = 0; i < frames; i++) {
        const start = performance.now();
        render((i + .5) / frames);
        gl.finish();
        timings.push(performance.now() - start);
      }
      timings.sort((a, b) => a - b);
      const p95 = timings[Math.ceil(frames * .95) - 1];
      return {kind: 'webgl2-draw-and-finish', frames, budget_ms, p95_ms: p95,
        median_ms: timings[Math.floor(frames / 2)], max_ms: timings.at(-1),
        within_cpu_budget: p95 <= budget_ms, production_fps_verified: false};
    },
    destroy() {
      if (!destroyed) {
        destroyed = true;
        restore();
      }
    },
  });
}
