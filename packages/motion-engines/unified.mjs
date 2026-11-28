// One entry point for every motion in the hub. Ids that belong to this package run on
// their own engine; ids of the portable Canvas2D reference catalog (os-…) are handed to
// the Universal Motion SDK next door, when that part of the hub is present. Both kinds
// of instance answer to the same verbs: play, pause, resume, reverse, stop, render,
// export, optimize, benchmark, destroy.
import { load, motion as engines } from './index.mjs';

const REFERENCE_SDK = new URL('../motion-sdk/index.mjs', import.meta.url).href;
const REFERENCE_CATALOG = new URL('../../motion-library/expansion/catalog.mjs', import.meta.url).href;

export function createUnifiedMotion({ referenceSdk = REFERENCE_SDK, referenceCatalog = REFERENCE_CATALOG } = {}) {
  let reference = null;
  async function references() {
    if (!reference) {
      reference = Promise.all([import(referenceSdk), import(referenceCatalog)]).then(([sdk, catalog]) => {
        const system = sdk.createMotionSystem();
        system.registerCatalog(catalog);
        return { system, ids: new Set(catalog.definitions.map((definition) => definition.id)) };
      });
      // A missing reference catalog is not an error for projects that installed engine motions only.
      reference.catch(() => {
        reference = null;
      });
    }
    return reference;
  }
  const native = new Set(engines.ids());
  return {
    /** 'engine' for a motion of this package, 'reference' for the Canvas2D catalog, null when unknown. */
    async kindOf(id) {
      if (native.has(id)) return 'engine';
      try {
        return (await references()).ids.has(id) ? 'reference' : null;
      } catch {
        return null;
      }
    },
    async create(id, options = {}) {
      if (native.has(id)) return engines.create(id, options);
      const { system, ids } = await references();
      if (!ids.has(id)) throw new RangeError(`Unknown motion: ${id}`);
      return system.create(id, { ...options, rtl: options.rtl ?? options.direction === 'rtl' });
    },
    load,
    engineIds: () => [...native],
    async referenceIds() {
      return [...(await references()).ids];
    },
  };
}
