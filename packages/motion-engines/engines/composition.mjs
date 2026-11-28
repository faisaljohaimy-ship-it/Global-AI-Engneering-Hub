// Composition engine: several layers, each drawn by its own engine, on one shared
// timeline. A layer is a setup function (canvas2d, fragment, points, dom ...) or a whole
// motion definition; it gets a window of the timeline, fades, a blend mode and, when it
// is another motion, its own parameters. The result is still a pure function of time.
import { clamp, hexToRgb, smoothstep } from '../core/util.mjs';
import { INTRO_MS } from '../core/constants.mjs';

function values(schema, given) {
  const result = {};
  for (const [name, spec] of Object.entries(schema ?? {})) result[name] = clamp(given?.[name] ?? spec.default, spec.min, spec.max);
  return result;
}

/**
 * layers: an array, or (ctx) => array, of
 *   {
 *     use,                      // a setup(ctx) function, or a motion definition
 *     at: [from, to],           // the part of the timeline the layer lives in (0..1, default all of it)
 *     fade: [in, out],          // fade lengths as fractions of the timeline (default none)
 *     blend,                    // CSS mix-blend-mode; 'screen' adds a dark-backed layer's light to what is below
 *     params, camera,           // (ctx) => values for a definition's own parameters
 *     colors,                   // (css) => palette for the layer, from the composition's palette
 *     cycles,                   // a looping layer inside a window: how many loops it plays there
 *     eager: true,              // build a windowed layer up front (needed when its setup is asynchronous)
 *     opacity,                  // (state, ctx) => extra 0..1 multiplier
 *     transform,                // (state, ctx) => CSS transform for the whole layer (a camera move)
 *   }
 * The first layer is opaque; later ones are transparent unless they set `opaque: true`.
 */
export function composition({ layers }) {
  return async function setup(ctx) {
    const specs = typeof layers === 'function' ? layers(ctx) : layers;
    const built = [];
    for (const [index, spec] of specs.entries()) {
      const definition = typeof spec.use === 'function' ? null : spec.use;
      if (definition?.engine === 'webgpu-wgsl') throw new Error('A WGSL motion cannot be a layer: its device and fallback belong to a motion of its own. Use WebGL2 layers.');
      const surface = ctx.surface.layer({ blend: spec.blend ?? 'normal' });
      const css = spec.colors ? spec.colors(ctx.css) : ctx.css;
      const child = {
        ...ctx,
        surface,
        css,
        colors: css.map(hexToRgb),
        params: definition ? values(definition.params, spec.params?.(ctx)) : { ...ctx.params, ...(spec.params?.(ctx) ?? {}) },
        camera: definition ? values(definition.camera, spec.camera?.(ctx)) : { ...ctx.camera, ...(spec.camera?.(ctx) ?? {}) },
        text: definition?.text ? { ...definition.text[ctx.locale.toLowerCase().startsWith('ar') ? 'ar' : 'en'] } : ctx.text,
        transparent: index > 0 && !spec.opaque,
        random: (salt = 0) => ctx.random(salt + 7919 * (index + 1)),
      };
      const [from, to] = spec.at ?? [0, 1];
      const item = { spec, surface, node: surface.root, child, run: definition ? definition.setup : spec.use, loop: definition?.kind === 'loop', whole: from <= 0 && to >= 1, impl: null };
      // A layer that is always there is built now. One that lives in a window is built when
      // the window opens and released when it closes, so a long sequence never holds more
      // than the GPU contexts of the one or two chapters on screen.
      if (item.whole || spec.eager) item.impl = await item.run(child);
      built.push(item);
    }
    const mount = (item) => {
      const impl = item.run(item.child);
      if (typeof impl?.then === 'function') throw new Error('A windowed layer must set up synchronously; give it eager: true');
      item.impl = impl;
    };
    const unmount = (item) => {
      item.impl?.dispose?.();
      item.impl = null;
      item.surface.clear();
    };
    return {
      render(state) {
        for (const item of built) {
          const { spec, node } = item;
          const [from, to] = spec.at ?? [0, 1];
          const [fadeIn, fadeOut] = spec.fade ?? [0, 0];
          let opacity = 1;
          if (!item.whole) {
            const inside = state.raw >= from && state.raw <= to;
            opacity = inside ? (fadeIn > 0 ? smoothstep(from, from + fadeIn, state.raw) : 1) * (fadeOut > 0 ? 1 - smoothstep(to - fadeOut, to, state.raw) : 1) : 0;
          }
          if (spec.opacity) opacity *= clamp(spec.opacity(state, ctx));
          if (opacity <= 0.001) {
            node.style.visibility = 'hidden';
            if (item.impl && !item.whole && !spec.eager) unmount(item);
            continue;
          }
          if (!item.impl) mount(item);
          node.style.visibility = 'visible';
          node.style.opacity = opacity.toFixed(4);
          node.style.transform = spec.transform ? spec.transform(state, ctx) : '';
          if (item.whole && !spec.cycles) {
            item.impl.render(state);
            continue;
          }
          // The layer's own clock starts when its window opens.
          const span = Math.max(1e-6, to - from);
          const local = clamp((state.raw - from) / span);
          const ms = local * span * state.duration;
          const raw = spec.cycles ? (local * spec.cycles) % 1 : local;
          item.impl.render({
            time: ms, t: (ms / 1000) * state.rate, dt: state.dt, duration: span * state.duration, rate: state.rate, raw,
            progress: item.loop || spec.cycles ? raw : ctx.ease(local),
            intro: ctx.ease(ms / INTRO_MS),
          });
        }
      },
      dispose() {
        for (const item of built) item.impl?.dispose?.();
      },
      info: () => ({ layers: built.length, mounted: built.filter((item) => item.impl).length }),
    };
  };
}
