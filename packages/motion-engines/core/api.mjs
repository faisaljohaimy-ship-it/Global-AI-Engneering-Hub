// The universal motion API. Every motion, whatever draws it, is driven through the
// same instance: create, play, pause, resume, reverse, stop, destroy, render, export,
// preview, optimize, benchmark. A motion is a pure function of time, so any frame can
// be drawn on demand and the same frame always looks the same.
import { INTRO_MS } from './constants.mjs';
import { EASINGS, ease } from './easing.mjs';
import { clamp, hexToRgb, mulberry32 } from './util.mjs';
import { TIERS, TIER_ORDER, createGovernor, getCapabilities, pickTier } from './capabilities.mjs';
import { realClock } from './clock.mjs';
import { analyze, createSurface } from './surface.mjs';

export { INTRO_MS };
export class MotionError extends Error {}

function pick(schema, given, what) {
  const values = {};
  for (const [name, spec] of Object.entries(schema)) {
    const value = given?.[name] ?? spec.default;
    if (!Number.isFinite(value)) throw new MotionError(`${what} ${name} must be a number`);
    values[name] = clamp(value, spec.min, spec.max);
  }
  for (const name of Object.keys(given ?? {})) {
    if (!Object.hasOwn(schema, name)) throw new MotionError(`Unknown ${what}: ${name}`);
  }
  return values;
}

/** The settings a motion runs with: the definition's defaults overridden by valid options. */
export function resolveOptions(definition, options = {}) {
  const duration = options.duration ?? definition.duration;
  if (!Number.isFinite(duration) || duration < 100 || duration > 120000) throw new MotionError('duration must be 100 to 120000 ms');
  const easing = options.easing ?? definition.easing;
  if (!EASINGS.includes(easing)) throw new MotionError(`easing must be one of ${EASINGS.join(', ')}`);
  const colors = definition.colors.map((fallback, index) => options.colors?.[index] ?? fallback);
  colors.forEach(hexToRgb);
  if (options.quality !== undefined && options.quality !== 'auto' && !Object.hasOwn(TIERS, options.quality)) throw new MotionError("quality must be 'auto', 'high', 'medium' or 'low'");
  if (options.gpu !== undefined && !['auto', 'readback', 'off'].includes(options.gpu)) throw new MotionError("gpu must be 'auto', 'readback' or 'off'");
  const arabic = String(options.locale ?? (options.direction === 'rtl' ? 'ar' : 'en')).toLowerCase().startsWith('ar');
  const text = { ...(definition.text ? definition.text[arabic ? 'ar' : 'en'] : {}) };
  for (const [key, value] of Object.entries(options.text ?? {})) {
    if (!Object.hasOwn(text, key)) throw new MotionError(`Unknown text: ${key}`);
    if (typeof value !== 'string' || !value.length || value.length > 200) throw new MotionError(`text ${key} must be a string of 1 to 200 characters`);
    text[key] = value;
  }
  return {
    duration: Math.round(duration),
    easing,
    colors,
    params: pick(definition.params, options.params, 'parameter'),
    camera: pick(definition.camera, options.camera, 'camera setting'),
    seed: (options.seed ?? 1) >>> 0,
    loop: options.loop ?? definition.kind === 'loop',
    text,
    gpu: options.gpu ?? 'auto',
  };
}

/** Used when a device cannot run a motion at all: a still gradient in the motion's own colours. */
function poster(ctx) {
  const { g } = ctx.surface.canvas2d();
  return {
    render() {
      g.setTransform(ctx.pixelRatio, 0, 0, ctx.pixelRatio, 0, 0);
      const gradient = g.createLinearGradient(0, 0, ctx.width, ctx.height);
      ctx.css.forEach((colour, index) => gradient.addColorStop(index / (ctx.css.length - 1), colour));
      g.fillStyle = gradient;
      g.fillRect(0, 0, ctx.width, ctx.height);
    },
  };
}

export async function createMotion(definition, options = {}) {
  const container = options.container;
  if (!container || !container.ownerDocument) throw new MotionError('options.container must be an element');
  const view = container.ownerDocument.defaultView;
  const capabilities = getCapabilities(view);
  const clock = options.clock ?? realClock(view);
  const reduced = options.reducedMotion === true || (options.reducedMotion !== false && capabilities.reducedMotion);
  const direction = options.direction === 'rtl' || options.direction === 'ltr' ? options.direction : view.getComputedStyle(container).direction || 'ltr';
  const locale = options.locale ?? (direction === 'rtl' ? 'ar' : 'en');
  const settings = resolveOptions(definition, { ...options, direction, locale });
  // Live input (a pointer, audio levels, a value) for motions that react to it. While
  // `live` is false a motion plays its own scripted demonstration of the interaction.
  const input = { live: false, x: 0.5, y: 0.5, down: false };
  const box = container.getBoundingClientRect();
  const width = Math.round(options.width ?? (box.width || 640));
  const height = Math.round(options.height ?? (box.height || 360));
  const adaptive = (options.quality ?? 'auto') === 'auto';
  let tier = adaptive ? pickTier(capabilities, definition.requirements.cost) : options.quality;
  let governor = adaptive ? createGovernor({ start: tier, targetMs: options.targetFrameMs }) : null;

  let surface = null;
  let impl = null;
  let fellBack = null;
  let state = 'idle';
  let time = 0;
  let travel = 1;
  let last = null;
  let frame = null;
  let framesDrawn = 0;
  let busy = false;
  let gpuLost = false;
  let release = null;
  const listeners = new Map();
  const emit = (event, detail) => (listeners.get(event) ?? []).forEach((listener) => listener(detail));

  async function build() {
    const quality = TIERS[tier];
    const make = () => {
      surface = createSurface(container, {
        width, height, dir: direction, background: settings.colors[0],
        pixelRatio: Math.min(options.pixelRatio ?? capabilities.dpr ?? 1, 2) * quality.scale,
      });
      return {
        surface, width, height, pixelRatio: surface.pixelRatio, duration: settings.duration,
        quality: { tier, level: quality.level, scale: quality.scale },
        /** Scale a particle, node or step count to the quality tier. */
        count: (full, floor = 1) => Math.max(floor, Math.round(full * quality.density)),
        params: settings.params, camera: settings.camera,
        colors: settings.colors.map(hexToRgb), css: settings.colors,
        dir: direction === 'rtl' ? -1 : 1, rtl: direction === 'rtl',
        locale, text: settings.text,
        /** The chosen easing, for staging parts of a motion: ease(0..1) -> eased 0..1. */
        ease: (x) => ease(settings.easing, clamp(x)),
        random: (salt = 0) => mulberry32((settings.seed + Math.imul(salt + 1, 0x9e3779b1)) >>> 0),
        input, transparent: false,
        /** How WebGPU frames reach the screen: 'auto' (the canvas), 'readback' (through a 2D canvas) or 'off'. */
        gpu: settings.gpu,
        capabilities, reduced,
      };
    };
    const second = async (reason) => {
      const ctx = make();
      impl = definition.fallback ? await definition.fallback(ctx) : poster(ctx);
      fellBack = reason;
    };
    // WebGPU that was switched off, or lost once already, is not tried again.
    const skip = definition.engine === 'webgpu-wgsl' && (settings.gpu === 'off' ? 'webgpu-off' : gpuLost ? 'webgpu-lost' : null);
    if (skip) await second(skip);
    else {
      try {
        impl = await definition.setup(make());
        fellBack = null;
      } catch (error) {
        if (!error || !error.unsupported) throw error;
        surface?.dispose();
        await second(error.unsupported);
      }
    }
    if (!impl || typeof impl.render !== 'function') throw new MotionError(`${definition.id}: setup must return { render }`);
    // A GPU device can vanish while a motion runs (driver reset, a tab moved to another
    // adapter, a browser that cannot show the canvas). The motion then carries on with its fallback.
    const built = impl;
    built.lost?.then(async () => {
      if (state === 'destroyed' || impl !== built) return;
      gpuLost = true;
      busy = true;
      built.dispose?.();
      surface.dispose();
      await build();
      busy = false;
      if (state !== 'destroyed') draw();
      emit('fallback', fellBack);
    });
  }

  // `t` is the motion's own clock in seconds: it runs at the speed the duration control
  // sets, so doubling the duration slows every part of a motion, not only its timeline.
  const rate = definition.duration / settings.duration;
  function frameState(ms, dt = 0) {
    const d = settings.duration;
    const raw = definition.kind === 'loop' ? (((ms % d) + d) % d) / d : clamp(ms / d);
    return {
      time: ms, t: (ms / 1000) * rate, dt: (dt / 1000) * rate, duration: d, rate, raw,
      progress: definition.kind === 'loop' ? raw : ease(settings.easing, raw),
      intro: ease(settings.easing, clamp(ms / INTRO_MS)),
    };
  }

  function draw(dt = 0) {
    impl.render(frameState(time, dt));
    framesDrawn += 1;
  }

  function cancel() {
    if (frame !== null) clock.cancel(frame);
    frame = null;
    last = null;
  }

  function schedule() {
    frame = clock.request(tick);
  }

  async function applyTier(next) {
    if (next === tier || state === 'destroyed') return;
    busy = true;
    tier = next;
    impl.dispose?.();
    surface.dispose();
    await build();
    busy = false;
    if (state !== 'destroyed') draw();
    emit('quality', tier);
  }

  function tick(now) {
    frame = null;
    if (state !== 'playing') return;
    const dt = last === null ? 0 : now - last;
    last = now;
    time += dt * travel;
    const d = settings.duration;
    let done = false;
    if (definition.kind === 'oneshot') {
      if (travel > 0 && time >= d) {
        if (settings.loop) time %= d;
        else [time, done] = [d, true];
      } else if (travel < 0 && time <= 0) {
        if (settings.loop) time = d + (time % d);
        else [time, done] = [0, true];
      }
    }
    if (!busy) {
      const started = view.performance.now();
      draw(dt);
      if (governor) {
        surface.flush();
        const next = governor.sample(view.performance.now() - started);
        if (next) applyTier(next);
      }
    }
    if (done) {
      state = 'finished';
      emit('finish', instance);
    } else schedule();
  }

  const alive = () => {
    if (state === 'destroyed') throw new MotionError(`${definition.id} was destroyed`);
  };

  const instance = {
    definition,
    get state() {
      return state;
    },
    /** Linear position in the timeline, 0..1. */
    get progress() {
      return frameState(time).raw;
    },
    get time() {
      return time;
    },
    get direction() {
      return travel;
    },
    /** The canvas, when the whole picture is one canvas: use it as a texture or a video source. Otherwise null. */
    get canvas() {
      return surface.canvas;
    },
    on(event, listener) {
      listeners.set(event, [...(listeners.get(event) ?? []), listener]);
      return instance;
    },
    /** Start from the current position. Under reduced motion the still frame is already shown and stays. */
    play() {
      alive();
      if (reduced) return instance;
      if (state === 'playing') return instance;
      if (state === 'finished') time = travel > 0 ? 0 : settings.duration;
      state = 'playing';
      schedule();
      return instance;
    },
    pause() {
      alive();
      if (state === 'playing') {
        cancel();
        state = 'paused';
      }
      return instance;
    },
    resume() {
      alive();
      if (state === 'paused') {
        state = 'playing';
        schedule();
      }
      return instance;
    },
    /** Flip the direction of travel; a motion that is not playing starts playing backwards. */
    reverse() {
      alive();
      if (reduced) return instance;
      travel = -travel;
      if (state !== 'playing') {
        if (definition.kind === 'oneshot' && travel < 0 && time <= 0) time = settings.duration;
        if (definition.kind === 'oneshot' && travel > 0 && time >= settings.duration) time = 0;
        state = 'playing';
        cancel();
        schedule();
      }
      return instance;
    },
    /** Back to the first frame, forwards, not playing. */
    stop() {
      alive();
      if (reduced) return instance;
      cancel();
      time = 0;
      travel = 1;
      state = 'idle';
      draw();
      return instance;
    },
    seek(progress) {
      alive();
      time = clamp(progress) * settings.duration;
      draw();
      return instance;
    },
    /**
     * Feed live input to a motion that reacts to it: { x, y } in 0..1 of the frame, { down },
     * { levels: [0..1, ...] } for sound, or whatever its `interactive` note names.
     * input(null) hands control back to the motion's own demonstration.
     */
    input(values) {
      alive();
      if (values === null) {
        for (const key of Object.keys(input)) if (!['live', 'x', 'y', 'down'].includes(key)) delete input[key];
        Object.assign(input, { live: false, x: 0.5, y: 0.5, down: false });
      } else Object.assign(input, values, { live: true });
      if (state !== 'playing') draw();
      return instance;
    },
    /** Draw one frame: { progress } in 0..1 or { time } in milliseconds. Does not start playback. */
    render(at = {}) {
      alive();
      if (Number.isFinite(at.time)) time = at.time;
      else if (Number.isFinite(at.progress)) time = at.progress * settings.duration;
      draw();
      return instance;
    },
    /**
     * Resolves when the frame last asked for is on screen. Immediate for every engine
     * except WebGPU in readback mode, whose frames arrive a moment after render().
     */
    settled() {
      return impl.settled ? impl.settled() : Promise.resolve();
    },
    /** Facts about the pixels now on screen. Null for layered and DOM pictures, which need a screenshot. */
    capture() {
      alive();
      const pixels = surface.read();
      return pixels ? { ...analyze(pixels), data: pixels.data } : null;
    },
    /** Draw a frame and report on its pixels (see capture). */
    snapshot(at) {
      instance.render(at);
      return instance.capture();
    },
    /**
     * Change quality while keeping the position. { tier } sets it; { targetFrameMs } lets the
     * governor lower it when frames take longer than that and raise it again when they do not.
     */
    async optimize({ tier: wanted, targetFrameMs } = {}) {
      alive();
      if (wanted !== undefined) {
        if (!Object.hasOwn(TIERS, wanted)) throw new MotionError("tier must be 'high', 'medium' or 'low'");
        governor = null;
        await applyTier(wanted);
      } else {
        governor = createGovernor({ start: TIER_ORDER.at(-1), targetMs: targetFrameMs });
      }
      return instance.info();
    },
    /** Time frames spread over the timeline, each one until it is really drawn. Leaves the position where it was. */
    async benchmark({ frames = 30 } = {}) {
      alive();
      const kept = time;
      const times = [];
      for (let index = 0; index < frames; index += 1) {
        time = ((index + 0.5) / frames) * settings.duration;
        const started = view.performance.now();
        draw();
        surface.flush();
        if (impl.settled) await impl.settled();
        surface.read();
        times.push(view.performance.now() - started);
        if (state === 'destroyed') throw new MotionError(`${definition.id} was destroyed`);
      }
      time = kept;
      draw();
      const sorted = [...times].sort((a, b) => a - b);
      const average = times.reduce((sum, value) => sum + value, 0) / frames;
      return {
        frames, tier, pixels: surface.pixels,
        averageMs: Number(average.toFixed(3)),
        p95Ms: Number(sorted[Math.min(frames - 1, Math.floor(frames * 0.95))].toFixed(3)),
        maxMs: Number(sorted.at(-1).toFixed(3)),
        framesPerSecond: Number((1000 / average).toFixed(1)),
      };
    },
    /** Frames as image blobs, drawn at exact times. DOM and layered pictures export through the CLI renderer. */
    async export({ frames = 30, fps = 30, type = 'image/png', quality } = {}) {
      alive();
      const canvas = surface.canvas;
      if (!canvas) return { supported: false, reason: 'This motion is drawn with DOM nodes or several layers; export it with the CLI renderer.' };
      const kept = time;
      const blobs = [];
      for (let index = 0; index < frames; index += 1) {
        time = (index * 1000) / fps;
        draw();
        if (impl.settled) await impl.settled();
        blobs.push(await new Promise((done) => canvas.toBlob(done, type, quality)));
      }
      time = kept;
      draw();
      return { supported: true, frames: blobs, fps, width: canvas.width, height: canvas.height, type };
    },
    info() {
      return {
        id: definition.id, engine: definition.engine, state, tier, adaptive: Boolean(governor), reduced,
        direction, locale, width, height, pixels: surface.pixels, framesDrawn, fallback: fellBack, interactive: Boolean(release),
        duration: settings.duration, easing: settings.easing, colors: [...settings.colors],
        params: { ...settings.params }, camera: { ...settings.camera }, ...(impl.info?.() ?? {}),
      };
    },
    destroy() {
      if (state === 'destroyed') return;
      cancel();
      state = 'destroyed';
      release?.();
      impl.dispose?.();
      surface.dispose();
      listeners.clear();
    },
  };

  await build();
  // options.interactive wires the pointer to input(); the listeners sit on the container, so they survive a quality change.
  if (options.interactive && !reduced) {
    const move = (event) => {
      const area = container.getBoundingClientRect();
      instance.input({ x: clamp((event.clientX - area.left) / (area.width || 1)), y: clamp((event.clientY - area.top) / (area.height || 1)), down: event.buttons > 0 });
    };
    const leave = () => instance.input(null);
    const events = [['pointermove', move], ['pointerdown', move], ['pointerup', move], ['pointerleave', leave], ['pointercancel', leave]];
    for (const [name, handler] of events) container.addEventListener(name, handler);
    release = () => events.forEach(([name, handler]) => container.removeEventListener(name, handler));
  }
  if (reduced) {
    // Reduced motion: one representative frame, and nothing is ever scheduled.
    time = definition.still * settings.duration;
    state = 'still';
  }
  draw();
  if (options.autoplay) instance.play();
  return instance;
}

/**
 * A motion with a transport bar: play or pause, and a scrubber. Returns the instance;
 * destroy() removes the bar as well.
 */
export async function mountPreview(definition, container, options = {}) {
  const doc = container.ownerDocument;
  const frame = doc.createElement('div');
  frame.className = 'hub-motion-preview';
  const stage = doc.createElement('div');
  const bar = doc.createElement('div');
  bar.style.cssText = 'display:flex;gap:8px;align-items:center;padding:6px 0;font:13px/1.2 system-ui,sans-serif;';
  const arabic = (options.locale ?? '').startsWith('ar');
  const labels = arabic ? { play: 'تشغيل', pause: 'إيقاف مؤقت', seek: 'موضع الحركة' } : { play: 'Play', pause: 'Pause', seek: 'Position' };
  const button = doc.createElement('button');
  button.type = 'button';
  button.textContent = labels.play;
  const scrub = doc.createElement('input');
  scrub.type = 'range';
  scrub.min = '0';
  scrub.max = '1000';
  scrub.value = '0';
  scrub.setAttribute('aria-label', labels.seek);
  scrub.style.flex = '1';
  bar.append(button, scrub);
  frame.append(stage, bar);
  container.append(frame);
  const instance = await createMotion(definition, { ...options, container: stage });
  const sync = () => {
    button.textContent = instance.state === 'playing' ? labels.pause : labels.play;
  };
  button.addEventListener('click', () => {
    if (instance.state === 'playing') instance.pause();
    else if (instance.state === 'paused') instance.resume();
    else instance.play();
    sync();
  });
  scrub.addEventListener('input', () => {
    instance.pause();
    instance.seek(Number(scrub.value) / 1000);
    sync();
  });
  instance.on('finish', sync);
  const destroy = instance.destroy;
  instance.destroy = () => {
    destroy();
    frame.remove();
  };
  instance.controls = { button, scrub };
  return instance;
}
