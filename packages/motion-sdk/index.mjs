// SPDX-License-Identifier: MIT
// Original, dependency-free motion tooling. Optional engines are never installed here.
const VERSION = '1.0.0';
const MAX_DIMENSION = 4096;
const COLOR = /^(?:#[a-f\d]{3,8}|rgba?\([\d\s.,%]+\)|hsla?\([\d\s.,%]+\)|transparent|none)$/i;
const ID = /^[a-z][a-z0-9-]{1,95}$/;
const fail = (message) => { throw new Error(message); };
const finite = (value, name, min = -1e7, max = 1e7) => {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < min || value > max) fail(`Invalid ${name}`);
  return value;
};
const clamp = (value, low = 0, high = 1) => Math.min(high, Math.max(low, value));
const clock = () => globalThis.performance?.now?.() ?? Date.now();
const color = (value, fallback) => {
  if (value == null) return fallback;
  if (typeof value !== 'string' || !COLOR.test(value)) fail('Unsafe color');
  return value;
};
const escape = (value) => String(value).replace(/[&<>"']/g, (character) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;'}[character]));
const copy = (value) => JSON.parse(JSON.stringify(value));
function frozenCopy(value) {
  const result = copy(value);
  const freeze = (item) => {
    if (item && typeof item === 'object') { Object.values(item).forEach(freeze); Object.freeze(item); }
    return item;
  };
  return freeze(result);
}

function validateDefinition(definition) {
  if (!definition || !ID.test(definition.id ?? '')) fail('Invalid motion definition');
  finite(definition.duration_ms ?? 1600, 'duration_ms', 1, 10000);
  return definition;
}

/** Accept only the documented finite scene schema before drawing or exporting. */
export function validateScene(scene) {
  if (!scene || !Array.isArray(scene.primitives) || scene.primitives.length > 4096) fail('Invalid scene');
  finite(scene.width, 'scene width', 1, MAX_DIMENSION);
  finite(scene.height, 'scene height', 1, MAX_DIMENSION);
  color(scene.background, '#08111f');
  for (const primitive of scene.primitives) {
    if (!primitive || !['circle', 'line', 'polyline', 'rect', 'text'].includes(primitive.type)) fail('Unknown primitive');
    finite(primitive.opacity ?? 1, 'opacity', 0, 1);
    finite(primitive.lineWidth ?? 1, 'lineWidth', 0, 128);
    color(primitive.fill, 'none'); color(primitive.stroke, 'none');
    if (primitive.type === 'line') {
      for (const field of ['x1', 'y1', 'x2', 'y2']) finite(primitive[field], field);
    } else if (primitive.type === 'polyline') {
      if (!Array.isArray(primitive.points) || primitive.points.length < 2 || primitive.points.length > 4096) fail('Invalid polyline');
      for (const point of primitive.points) { finite(point.x, 'point x'); finite(point.y, 'point y'); }
    } else {
      finite(primitive.x, 'x'); finite(primitive.y, 'y');
      if (primitive.type === 'circle') finite(primitive.r, 'radius', 0, 8192);
      if (primitive.type === 'rect') {
        finite(primitive.width, 'rect width', 0, 8192); finite(primitive.height, 'rect height', 0, 8192);
        finite(primitive.radius ?? 0, 'corner radius', 0, 4096); finite(primitive.rotation ?? 0, 'rotation');
      }
      if (primitive.type === 'text') {
        if (typeof primitive.text !== 'string' || primitive.text.length > 512) fail('Invalid text');
        finite(primitive.size, 'text size', 1, 512);
        if (primitive.align && !['start', 'end', 'left', 'right', 'center'].includes(primitive.align)) fail('Invalid text alignment');
      }
    }
  }
  return scene;
}

/** Draw pixel-space catalog primitives; text never reaches HTML. */
export function drawScene(context, input, {pixelRatio = 1} = {}) {
  const scene = validateScene(input);
  finite(pixelRatio, 'pixel ratio', 0.25, 2);
  if (!context) fail('Canvas2D context required');
  context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
  context.clearRect(0, 0, scene.width, scene.height);
  context.fillStyle = color(scene.background, '#08111f');
  context.fillRect(0, 0, scene.width, scene.height);
  for (const item of scene.primitives) {
    context.save();
    context.globalAlpha = item.opacity ?? 1;
    context.fillStyle = color(item.fill, 'transparent');
    context.strokeStyle = color(item.stroke, 'transparent');
    context.lineWidth = item.lineWidth ?? 1;
    context.lineCap = 'round'; context.lineJoin = 'round';
    const fill = item.fill && item.fill !== 'none' && item.fill !== 'transparent';
    const stroke = item.stroke && item.stroke !== 'none' && item.stroke !== 'transparent';
    context.beginPath();
    if (item.type === 'circle') context.arc(item.x, item.y, item.r, 0, Math.PI * 2);
    if (item.type === 'line') { context.moveTo(item.x1, item.y1); context.lineTo(item.x2, item.y2); }
    if (item.type === 'polyline') {
      context.moveTo(item.points[0].x, item.points[0].y);
      for (const point of item.points.slice(1)) context.lineTo(point.x, point.y);
      if (item.closed) context.closePath();
    }
    if (item.type === 'rect') {
      if (item.rotation) {
        context.translate(item.x + item.width / 2, item.y + item.height / 2);
        context.rotate(item.rotation);
        context.translate(-item.x - item.width / 2, -item.y - item.height / 2);
      }
      if (context.roundRect && item.radius) context.roundRect(item.x, item.y, item.width, item.height, item.radius);
      else context.rect(item.x, item.y, item.width, item.height);
    }
    if (item.type === 'text') {
      context.font = `${item.size}px system-ui, sans-serif`;
      context.textAlign = item.align ?? 'center';
      context.textBaseline = 'middle';
      if (fill) context.fillText(item.text, item.x, item.y);
      if (stroke) context.strokeText(item.text, item.x, item.y);
    } else {
      if (fill) context.fill();
      if (stroke) context.stroke();
    }
    context.restore();
  }
  return scene;
}

/** Standalone vector snapshot, not an encoded video or an optional-engine render. */
export function sceneToSVG(input) {
  const scene = validateScene(input);
  const nodes = [`<rect width="100%" height="100%" fill="${escape(scene.background ?? '#08111f')}"/>`];
  for (const item of scene.primitives) {
    const attributes = `fill="${escape(item.fill ?? 'none')}" stroke="${escape(item.stroke ?? 'none')}" stroke-width="${item.lineWidth ?? 1}" opacity="${item.opacity ?? 1}" stroke-linecap="round" stroke-linejoin="round"`;
    if (item.type === 'circle') nodes.push(`<circle cx="${item.x}" cy="${item.y}" r="${item.r}" ${attributes}/>`);
    if (item.type === 'line') nodes.push(`<line x1="${item.x1}" y1="${item.y1}" x2="${item.x2}" y2="${item.y2}" ${attributes}/>`);
    if (item.type === 'polyline') nodes.push(`<${item.closed ? 'polygon' : 'polyline'} points="${item.points.map((p) => `${p.x},${p.y}`).join(' ')}" ${attributes}/>`);
    if (item.type === 'rect') nodes.push(`<rect x="${item.x}" y="${item.y}" width="${item.width}" height="${item.height}" rx="${item.radius ?? 0}" transform="rotate(${(item.rotation ?? 0) * 180 / Math.PI} ${item.x + item.width / 2} ${item.y + item.height / 2})" ${attributes}/>`);
    if (item.type === 'text') {
      const alignment = {left: 'start', right: 'end', start: 'start', end: 'end', center: 'middle'}[item.align ?? 'center'];
      nodes.push(`<text x="${item.x}" y="${item.y}" font-family="system-ui, sans-serif" font-size="${item.size}" text-anchor="${alignment}" dominant-baseline="middle" ${attributes}>${escape(item.text)}</text>`);
    }
  }
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${scene.width}" height="${scene.height}" viewBox="0 0 ${scene.width} ${scene.height}">${nodes.join('')}</svg>`;
}

function validOptions(options, definition) {
  const width = options.width ?? 640, height = options.height ?? 360;
  finite(width, 'width', 1, MAX_DIMENSION); finite(height, 'height', 1, MAX_DIMENSION);
  const duration = options.duration_ms ?? definition.duration_ms ?? 1600;
  finite(duration, 'duration_ms', 1, 10000);
  const pixelRatio = options.pixelRatio ?? Math.min(globalThis.devicePixelRatio ?? 1, 2);
  finite(pixelRatio, 'pixel ratio', 0.25, 2);
  if (width * height * pixelRatio * pixelRatio > 4_194_304) fail('Canvas pixel budget exceeded');
  const intensity = options.intensity ?? 1, detail = options.detail ?? 12, seed = options.seed ?? 1;
  finite(intensity, 'intensity', 0, 1); finite(detail, 'detail', 6, 24); finite(seed, 'seed', 0, 2 ** 32 - 1);
  if (!Number.isInteger(detail) || !Number.isInteger(seed)) fail('detail and seed must be integers');
  const interaction = options.interaction ?? {x: 0, y: 0};
  finite(interaction.x, 'interaction x', -1, 1); finite(interaction.y, 'interaction y', -1, 1);
  if (options.rtl != null && typeof options.rtl !== 'boolean') fail('rtl must be boolean');
  const reduced = options.reducedMotion ?? 'auto';
  if (![true, false, 'auto', 'reduce', 'full'].includes(reduced)) fail('Invalid reduced-motion setting');
  return {width, height, duration_ms: duration, pixelRatio, intensity, detail, seed,
          interaction: {...interaction}, rtl: options.rtl ?? false, reducedMotion: reduced};
}

function reduced(options, view) {
  return options.reducedMotion === true || options.reducedMotion === 'reduce' ||
    (options.reducedMotion === 'auto' && Boolean(view?.matchMedia?.('(prefers-reduced-motion: reduce)').matches));
}

function safeKeyframes(frames) {
  if (!Array.isArray(frames) || frames.length < 2 || frames.length > 64) fail('Two to64 WAAPI keyframes required');
  for (const frame of frames) {
    if (!frame || Object.keys(frame).some((key) => !['offset', 'opacity', 'transform'].includes(key))) fail('Unsupported WAAPI property');
    if ('offset' in frame) finite(frame.offset, 'offset', 0, 1);
    if ('opacity' in frame) finite(frame.opacity, 'opacity', 0, 1);
    if ('transform' in frame && (typeof frame.transform !== 'string' || !/^(?:none|(?:(?:translate[XYZ]?\(-?[\d.]+(?:px|%)?\)|scale[XYZ]?\([\d.]+\)|rotate[XYZ]?\(-?[\d.]+deg\))\s*)+)$/.test(frame.transform))) fail('Unsafe WAAPI transform');
  }
  const offsets = frames.filter((frame) => 'offset' in frame).map((frame) => frame.offset);
  if (offsets.some((value, index) => index > 0 && value < offsets[index - 1])) fail('Unordered WAAPI offsets');
  return copy(frames);
}

export function createMotionSystem() {
  const registry = new Map();
  let catalogSampler;
  const instances = new Set();

  function registerCatalog(catalog) {
    if (!catalog || !Array.isArray(catalog.definitions) || typeof (catalog.sampleMotion ?? catalog.sampleScene) !== 'function') fail('Catalog needs definitions and a sampler');
    const pending = new Map();
    for (const definition of catalog.definitions) {
      validateDefinition(definition);
      if (pending.has(definition.id) || registry.has(definition.id)) fail(`Duplicate motion: ${definition.id}`);
      pending.set(definition.id, frozenCopy(definition));
    }
    for (const [id, definition] of pending) registry.set(id, definition);
    catalogSampler = catalog.sampleMotion ?? catalog.sampleScene;
    return {registered: pending.size, total: registry.size};
  }

  async function loadCatalog(url = new URL('../../motion-library/expansion/catalog.mjs', import.meta.url)) {
    const target = new URL(url, import.meta.url), source = new URL(import.meta.url);
    if (target.protocol !== source.protocol || (target.protocol !== 'file:' && target.origin !== source.origin)) fail('Catalog code must be local or same-origin reviewed code');
    return registerCatalog(await import(target.href));
  }

  function create(value, input = {}) {
    const definition = frozenCopy(validateDefinition(typeof value === 'string' ? registry.get(value) : value));
    const engine = definition.engine ?? definition.rendering_engine ?? 'canvas2d';
    if (!['canvas2d', 'waapi'].includes(engine)) fail('Optional engine is not installed');
    let options = validOptions(input, definition);
    const view = input.view ?? globalThis;
    const request = input.requestFrame ?? view.requestAnimationFrame?.bind(view);
    const cancel = input.cancelFrame ?? view.cancelAnimationFrame?.bind(view);
    const now = input.now ?? clock;
    const sampler = input.sampler ?? catalogSampler;
    if (engine === 'canvas2d' && typeof sampler !== 'function') fail('Register a reviewed catalog or provide a local sampler');
    let canvas = input.canvas, owned = false, context, waapi, frame, lastTime, scene;
    let state = 'idle', progress = 0, direction = 1;
    let previousCanvas;
    if (engine === 'canvas2d') {
      if (!canvas && input.container) {
        canvas = input.container.ownerDocument.createElement('canvas');
        canvas.setAttribute('role', 'img');
        canvas.setAttribute('aria-label', definition.name_en ?? definition.id);
        input.container.append(canvas); owned = true;
      }
      if (canvas) {
        previousCanvas = {width: canvas.width, height: canvas.height, style: canvas.getAttribute?.('style')};
        context = canvas.getContext('2d');
        if (!context) { if (owned) canvas.remove(); fail('Canvas2D is unavailable'); }
      }
    } else {
      if (typeof input.target?.animate !== 'function') fail('WAAPI target is unavailable');
      const frames = safeKeyframes(definition.keyframes ?? input.keyframes);
      waapi = input.target.animate(frames, {duration: options.duration_ms, fill: 'both', easing: 'linear'});
      waapi.pause(); waapi.currentTime = 0;
    }

    const alive = () => { if (state === 'destroyed') fail('Motion was destroyed'); };
    const unschedule = () => { if (frame != null && cancel) cancel(frame); frame = undefined; };
    function render(value = progress) {
      alive(); finite(value, 'progress'); progress = clamp(value);
      const useReduced = reduced(options, view);
      if (engine === 'waapi') {
        waapi.currentTime = (useReduced ? 1 : progress) * options.duration_ms;
        scene = {meta: {id: definition.id, engine, progress, reducedMotion: useReduced}, keyframes: copy(definition.keyframes ?? input.keyframes)};
      } else {
        scene = validateScene(sampler(definition, useReduced ? 1 : progress, {...options, reducedMotion: useReduced}));
        if (canvas) {
          const width = Math.round(options.width * options.pixelRatio), height = Math.round(options.height * options.pixelRatio);
          if (canvas.width !== width) canvas.width = width;
          if (canvas.height !== height) canvas.height = height;
          if (canvas.style) { canvas.style.width = `${options.width}px`; canvas.style.height = `${options.height}px`; }
          drawScene(context, scene, {pixelRatio: options.pixelRatio});
        }
      }
      return copy(scene);
    }
    function tick(timestamp) {
      if (state !== 'playing') return;
      frame = undefined;
      const next = progress + Math.max(0, timestamp - lastTime) / options.duration_ms * direction;
      lastTime = timestamp;
      render(next);
      if ((direction > 0 && next >= 1) || (direction < 0 && next <= 0)) {
        if (input.loop === true && !reduced(options, view)) render(direction > 0 ? 0 : 1);
        else { state = 'finished'; return; }
      }
      if (reduced(options, view)) { state = 'finished'; return; }
      frame = request(tick);
    }
    function play() {
      alive(); if (state === 'playing') return api;
      if (state === 'finished') render(direction > 0 ? 0 : 1);
      if (reduced(options, view)) { render(1); state = 'finished'; return api; }
      if (!request || !cancel) fail('Animation scheduling is unavailable; use render(progress)');
      state = 'playing'; lastTime = now(); frame = request(tick); return api;
    }
    function pause() { alive(); unschedule(); if (state === 'playing') state = 'paused'; return api; }
    function resume() { alive(); return play(); }
    function reverse() {
      alive(); direction *= -1;
      if ((state === 'idle' || state === 'finished') && progress === 0 && direction < 0) render(1);
      lastTime = now(); return api;
    }
    function stop() { alive(); unschedule(); state = 'idle'; direction = 1; render(0); return api; }
    function destroy() {
      if (state === 'destroyed') return;
      unschedule(); waapi?.cancel();
      if (owned) canvas.remove();
      else if (canvas && previousCanvas) {
        canvas.width = previousCanvas.width; canvas.height = previousCanvas.height;
        if (canvas.setAttribute && previousCanvas.style != null) canvas.setAttribute('style', previousCanvas.style);
        else canvas.removeAttribute?.('style');
      }
      state = 'destroyed'; instances.delete(api);
    }
    function exportMotion(format = 'json', at = progress) {
      alive(); const result = render(at);
      if (format === 'json') return JSON.stringify({sdk_version: VERSION, definition: copy(definition), scene: result}, null, 2);
      if (engine !== 'canvas2d') fail('WAAPI supports structured JSON export only');
      if (format === 'svg') return sceneToSVG(result);
      if (format === 'png' && typeof canvas?.toDataURL === 'function') return canvas.toDataURL('image/png');
      fail('Unsupported export format; encoded video requires a separately reviewed renderer');
    }
    function optimize({profile = 'balanced'} = {}) {
      alive(); if (!['mobile', 'balanced', 'quality'].includes(profile)) fail('Unknown rendering profile');
      const detail = {mobile: 6, balanced: 12, quality: 24}[profile];
      options = validOptions({...options, detail, pixelRatio: profile === 'mobile' ? 1 : options.pixelRatio}, definition);
      render(); return {profile, detail, pixelRatio: options.pixelRatio, width: options.width, height: options.height};
    }
    function configure(parameters) {
      alive();
      if (!parameters || typeof parameters !== 'object' || Object.keys(parameters).some((key) => !['width','height','duration_ms','pixelRatio','intensity','detail','seed','interaction','rtl','reducedMotion'].includes(key))) fail('Unknown configuration parameter');
      const previous = options;
      options = validOptions({...options, ...parameters}, definition);
      try { render(); } catch (error) { options = previous; render(); throw error; }
      if (engine === 'waapi') waapi.effect?.updateTiming?.({duration: options.duration_ms});
      lastTime = now(); return api;
    }
    function benchmark({frames = 120, budget_ms = 1000 / 60} = {}) {
      alive(); finite(frames, 'frames', 2, 2000); finite(budget_ms, 'budget_ms', 0.1, 1000);
      if (!Number.isInteger(frames)) fail('frames must be an integer');
      const previous = progress, times = [];
      for (let i = 0; i < frames; i++) { const start = now(); render(i / (frames - 1)); times.push(Math.max(0, now() - start)); }
      render(previous); times.sort((a, b) => a - b);
      const p95 = times[Math.ceil(times.length * .95) - 1];
      return {kind: 'synchronous-sampling-and-draw', frames, median_ms: times[Math.floor(times.length / 2)], p95_ms: p95,
              max_ms: times.at(-1), budget_ms, within_cpu_budget: p95 <= budget_ms,
              production_fps_verified: false, engine, detail: options.detail, pixelRatio: options.pixelRatio};
    }
    function getCapabilities() { return {...capabilities(view), engine, definition_id: definition.id, reduced_motion: reduced(options, view)}; }
    const api = {definition, canvas, play, pause, resume, reverse, stop, destroy, render,
      export: exportMotion, preview: render, optimize, configure, benchmark, getCapabilities,
      get state() { return state; }, get progress() { return progress; }, get direction() { return direction; }};
    try { render(0); } catch (error) { destroy(); throw error; }
    instances.add(api); return api;
  }

  function capabilities(view = globalThis) {
    return {sdk_version: VERSION, registered: registry.size, live_instances: instances.size,
      canvas2d: 'implemented', waapi: typeof view.Element?.prototype?.animate === 'function' ? 'available' : 'adapter-implemented-host-unavailable',
      deterministic_sampling: true, export_formats: ['json', 'svg', 'png-with-canvas'],
      encoded_video: false, webgpu: 'not-enabled', three: 'not-installed', remotion: 'not-installed',
      worker_rendering: false, gpu_required: false};
  }
  const facade = {registerCatalog, loadCatalog, create, getCapabilities: capabilities,
    definitions: () => [...registry.values()].map(copy), destroyAll: () => [...instances].forEach((instance) => instance.destroy())};
  for (const method of ['play', 'pause', 'resume', 'reverse', 'stop', 'destroy', 'render', 'export', 'preview', 'optimize', 'benchmark']) {
    facade[method] = (instance, ...args) => { if (!instance || typeof instance[method] !== 'function') fail('Motion instance required'); return instance[method](...args); };
  }
  return Object.freeze(facade);
}

export const motion = createMotionSystem();
export const create = (...args) => motion.create(...args);
export const registerCatalog = (...args) => motion.registerCatalog(...args);
export const loadCatalog = (...args) => motion.loadCatalog(...args);
export const getCapabilities = (...args) => motion.getCapabilities(...args);
export default motion;
