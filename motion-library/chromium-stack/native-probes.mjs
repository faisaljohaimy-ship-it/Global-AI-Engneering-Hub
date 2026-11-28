// This function executes inside the isolated browser page, with no provider access.
export async function inspectNative({ frames, frameBudgetMs }) {
  const assert = (condition, description) => { if (!condition) throw new Error(description); };
  const close = (a, b, epsilon = 0.02) => Math.abs(a - b) <= epsilon;
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const rtl = document.documentElement.dir === 'rtl';
  const checks = {};
  const canvas = document.getElementById('canvas-probe');
  const context = canvas.getContext('2d', { willReadFrequently: true });
  assert(context, 'Canvas2D context unavailable');
  context.fillStyle = 'rgb(240,80,40)'; context.fillRect(0, 0, 32, 32);
  const pixel = [...context.getImageData(8, 8, 1, 1).data];
  checks.canvas_pixel = pixel.join(',') === '240,80,40,255';
  assert(checks.canvas_pixel, 'Canvas2D rendered pixel mismatch');

  const css = document.getElementById('css-probe');
  const cssPlayer = css.getAnimations()[0];
  if (reduced) {
    checks.css_reduced_motion = getComputedStyle(css).animationName === 'none' && !cssPlayer;
    assert(checks.css_reduced_motion, 'CSS reduced-motion fallback failed');
  } else {
    assert(cssPlayer, 'CSS animation was not created');
    cssPlayer.pause(); cssPlayer.currentTime = 50;
    checks.css_interpolation = close(Number(getComputedStyle(css).opacity), 0.5);
    assert(checks.css_interpolation, 'CSS midpoint did not interpolate');
  }
  const target = document.getElementById('waapi-probe');
  if (reduced) {
    target.style.opacity = '1';
    checks.waapi_reduced_motion = target.getAnimations().length === 0 && getComputedStyle(target).opacity === '1';
    assert(checks.waapi_reduced_motion, 'WAAPI static alternative failed');
  } else {
    const distance = rtl ? -20 : 20;
    const player = target.animate([{ opacity: 0, transform: 'translateX(0px)' }, { opacity: 1, transform: `translateX(${distance}px)` }], { duration: 100, easing: 'linear', fill: 'both' });
    player.pause(); player.currentTime = 50;
    const style = getComputedStyle(target);
    checks.waapi_interpolation = close(Number(style.opacity), 0.5) && close(new DOMMatrix(style.transform).m41, distance / 2);
    assert(checks.waapi_interpolation, 'WAAPI logical-direction midpoint failed');
  }

  const gl = document.getElementById('gl-probe').getContext('webgl', { preserveDrawingBuffer: true, antialias: false });
  assert(gl, 'WebGL context unavailable; shader rendering is not operational');
  const shader = (type, source) => {
    const value = gl.createShader(type); gl.shaderSource(value, source); gl.compileShader(value);
    assert(gl.getShaderParameter(value, gl.COMPILE_STATUS), 'WebGL shader compilation failed'); return value;
  };
  const vertex = shader(gl.VERTEX_SHADER, 'attribute vec2 position; void main(){gl_Position=vec4(position,0.0,1.0);}');
  const fragment = shader(gl.FRAGMENT_SHADER, 'precision mediump float; uniform float phase; void main(){gl_FragColor=vec4(0.25+0.25*phase,0.5,0.75,1.0);}');
  const program = gl.createProgram(); gl.attachShader(program, vertex); gl.attachShader(program, fragment); gl.linkProgram(program);
  assert(gl.getProgramParameter(program, gl.LINK_STATUS), 'WebGL shader link failed'); gl.useProgram(program);
  const buffer = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
  const location = gl.getAttribLocation(program, 'position'); gl.enableVertexAttribArray(location); gl.vertexAttribPointer(location, 2, gl.FLOAT, false, 0, 0);
  const uniform = gl.getUniformLocation(program, 'phase');
  const draw = (phase) => {
    gl.uniform1f(uniform, phase); gl.drawArrays(gl.TRIANGLES, 0, 3);
    const result = new Uint8Array(4); gl.readPixels(8, 8, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, result); return [...result];
  };
  const start = draw(0), end = draw(0.75);
  checks.webgl_shader_pixels = Math.abs(start[0] - 64) <= 2 && Math.abs(start[1] - 128) <= 2 && Math.abs(start[2] - 191) <= 2 && end[0] > start[0] + 30 && end[3] === 255;
  assert(checks.webgl_shader_pixels && gl.getError() === gl.NO_ERROR, 'WebGL animated-uniform pixel assertion failed');
  const renderer = String(gl.getParameter(gl.RENDERER));
  const debug = gl.getExtension('WEBGL_debug_renderer_info');
  const rendererDetail = debug ? String(gl.getParameter(debug.UNMASKED_RENDERER_WEBGL)) : renderer;
  gl.deleteBuffer(buffer); gl.deleteProgram(program); gl.deleteShader(vertex); gl.deleteShader(fragment);

  const wasmBytes = new Uint8Array([0,97,115,109,1,0,0,0,1,7,1,96,2,127,127,1,127,3,2,1,0,7,7,1,3,97,100,100,0,0,10,9,1,7,0,32,0,32,1,106,11]);
  const wasm = await WebAssembly.instantiate(wasmBytes);
  checks.wasm_execution = wasm.instance.exports.add(19, 23) === 42;
  assert(checks.wasm_execution, 'WebAssembly execution failed');
  let offscreen = { status: 'unavailable', rendered: false };
  if (typeof OffscreenCanvas === 'function') {
    const surface = new OffscreenCanvas(2, 2), ctx = surface.getContext('2d');
    if (ctx) {
      ctx.fillStyle = 'rgb(10,200,20)'; ctx.fillRect(0, 0, 2, 2);
      offscreen = { status: 'tested', rendered: [...ctx.getImageData(0, 0, 1, 1).data].join(',') === '10,200,20,255' };
      assert(offscreen.rendered, 'OffscreenCanvas pixel assertion failed');
    }
  }

  // Adapter availability is not a rendering test and is never counted as one.
  const webgpu = { api_present: Boolean(navigator.gpu), adapter_acquired: false, rendering_tested: false };
  if (navigator.gpu) {
    try {
      const adapter = await Promise.race([navigator.gpu.requestAdapter(), new Promise((done) => setTimeout(() => done(null), 1500))]);
      webgpu.adapter_acquired = Boolean(adapter);
    } catch { webgpu.adapter_acquired = false; }
  }
  const intervals = [], drawTimes = [];
  const benchmarkTarget = document.getElementById('benchmark-probe');
  let previous;
  for (let index = 0; index < frames + 3; index++) {
    const timestamp = await new Promise(requestAnimationFrame);
    const before = performance.now();
    // A reduced-motion run measures the same static alternative without movement.
    if (!reduced) benchmarkTarget.style.transform = `translateX(${Math.sin(index / 8) * (rtl ? -8 : 8)}px)`;
    context.fillStyle = reduced ? 'rgb(240,80,40)' : `rgb(${index % 255},80,40)`;
    context.fillRect(0, 0, 32, 32);
    if (index >= 3) { intervals.push(timestamp - previous); drawTimes.push(performance.now() - before); }
    previous = timestamp;
  }
  const percentile = (values, fraction) => [...values].sort((a, b) => a - b)[Math.min(values.length - 1, Math.floor(values.length * fraction))];
  const p95 = percentile(intervals, 0.95), median = percentile(intervals, 0.5);
  assert(intervals.length === frames && intervals.every((value) => Number.isFinite(value) && value > 0), 'Benchmark produced invalid frame timings');
  if (reduced) {
    checks.reduced_canvas_static = [...context.getImageData(8, 8, 1, 1).data].join(',') === '240,80,40,255';
    checks.reduced_transform_static = getComputedStyle(benchmarkTarget).transform === 'none';
    assert(checks.reduced_canvas_static && checks.reduced_transform_static, 'Reduced-motion benchmark alternative was not static');
  }
  return {
    checks, direction: rtl ? 'rtl' : 'ltr', reduced_motion: reduced,
    viewport: { width: innerWidth, height: innerHeight, device_pixel_ratio: devicePixelRatio },
    rendered: { canvas2d: true, webgl_shader: true, css_animation: !reduced, waapi: !reduced, offscreen_canvas: offscreen.rendered },
    gl: { renderer: rendererDetail, software_renderer: /swiftshader|llvmpipe|software/i.test(rendererDetail), start_pixel: start, end_pixel: end },
    offscreen_canvas: offscreen, webgpu,
    availability_only: { view_transitions: typeof document.startViewTransition === 'function', scroll_timeline: typeof ScrollTimeline === 'function', canvas_capture_stream: typeof canvas.captureStream === 'function' },
    benchmark: { scope: 'lab-only bounded Canvas2D and transform workload; not product or all-motion performance', frames, intervals_ms: intervals, median_interval_ms: median, p95_interval_ms: p95, median_draw_ms: percentile(drawTimes, 0.5), observed_median_fps: 1000 / median, frame_budget_ms: frameBudgetMs, within_configured_budget: p95 <= frameBudgetMs }
  };
}
