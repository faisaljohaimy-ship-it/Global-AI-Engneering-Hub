// Global AI Engineering Hub — Motion Engines.
// One API for every motion. Motions are loaded on demand, one module each, so an
// application only ever downloads the motions it actually creates.
//
//   import { motion } from './packages/motion-engines/index.mjs';
//   const field = await motion.create('quantum-field-distortion', { container });
//   motion.play(field);
import { createMotion, mountPreview, MotionError, resolveOptions } from './core/api.mjs';
import { getCapabilities } from './core/capabilities.mjs';
import { loaders } from './registry.mjs';

export { createMotion, mountPreview, MotionError, resolveOptions, getCapabilities };
export { createVirtualClock, realClock } from './core/clock.mjs';
export { defineMotion, MODULES, ENGINES } from './core/define.mjs';
export { EASINGS, ease } from './core/easing.mjs';
export { TIERS, createGovernor, deviceTier, pickTier } from './core/capabilities.mjs';

/** Load one motion definition by id. Only that motion's module is fetched. */
export async function load(id) {
  const loader = loaders[id];
  if (!loader) throw new MotionError(`Unknown motion: ${id}`);
  return (await loader()).default;
}

const definitionOf = (target) => (typeof target === 'string' ? load(target) : target);

export const motion = {
  /** Create an instance from an id or a definition. Draws the first frame; does not start playing. */
  create: async (target, options) => createMotion(await definitionOf(target), options),
  play: (instance) => instance.play(),
  pause: (instance) => instance.pause(),
  resume: (instance) => instance.resume(),
  reverse: (instance) => instance.reverse(),
  stop: (instance) => instance.stop(),
  destroy: (instance) => instance.destroy(),
  render: (instance, at) => instance.render(at),
  export: (instance, options) => instance.export(options),
  /** Create an instance with a play button and a scrubber inside `container`. */
  preview: async (target, container, options) => mountPreview(await definitionOf(target), container, options),
  optimize: (instance, options) => instance.optimize(options),
  benchmark: (instance, options) => instance.benchmark(options),
  getCapabilities,
  load,
  /** Every motion id this build knows. */
  ids: () => Object.keys(loaders),
};

export default motion;
