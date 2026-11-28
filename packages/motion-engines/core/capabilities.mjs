// What the device can do, the quality tier that follows from it, and the governor that
// lowers quality while a motion runs slowly. Lowering quality never stops the motion.

export const TIERS = Object.freeze({
  high: Object.freeze({ level: 3, scale: 1, density: 1 }),
  medium: Object.freeze({ level: 2, scale: 0.75, density: 0.5 }),
  low: Object.freeze({ level: 1, scale: 0.5, density: 0.25 }),
});
export const TIER_ORDER = Object.freeze(['low', 'medium', 'high']);

export function getCapabilities(view = globalThis) {
  const nav = view.navigator ?? {};
  const doc = view.document;
  const media = (query) => Boolean(view.matchMedia && view.matchMedia(query).matches);
  let webgl2 = false;
  try {
    webgl2 = Boolean(doc && doc.createElement('canvas').getContext('webgl2'));
  } catch {
    webgl2 = false;
  }
  const agent = String(nav.userAgent ?? '');
  const engine = /firefox/i.test(agent) ? 'firefox' : /chrome|chromium|edg\//i.test(agent) ? 'chromium' : /safari|applewebkit/i.test(agent) ? 'webkit' : 'unknown';
  const viewport = { width: view.innerWidth ?? 0, height: view.innerHeight ?? 0 };
  const capabilities = {
    webgl2,
    webgpu: Boolean(nav.gpu),
    offscreenCanvas: typeof view.OffscreenCanvas !== 'undefined',
    webAnimations: Boolean(doc && typeof doc.createElement('div').animate === 'function'),
    viewTransitions: Boolean(doc && doc.startViewTransition),
    segmenter: typeof Intl !== 'undefined' && Boolean(Intl.Segmenter),
    reducedMotion: media('(prefers-reduced-motion: reduce)'),
    coarsePointer: media('(pointer: coarse)'),
    saveData: Boolean(nav.connection && nav.connection.saveData),
    deviceMemory: nav.deviceMemory ?? null,
    cores: nav.hardwareConcurrency ?? null,
    dpr: view.devicePixelRatio ?? 1,
    viewport,
    engine,
  };
  capabilities.tier = deviceTier(capabilities);
  return capabilities;
}

/** 'high', 'medium' or 'low' from memory, cores, pointer and viewport. Unknown values count as capable. */
export function deviceTier({ deviceMemory, cores, coarsePointer, viewport, saveData, webgl2 }) {
  const memory = deviceMemory ?? 8;
  const threads = cores ?? 8;
  const small = Boolean(viewport && viewport.width && Math.min(viewport.width, viewport.height) < 500);
  if (saveData || memory <= 2 || threads <= 2 || webgl2 === false) return 'low';
  if (memory <= 4 || threads <= 4 || (coarsePointer && small)) return 'medium';
  return 'high';
}

/** Starting tier for one motion: a costly motion starts one step lower on anything but a high-tier device. */
export function pickTier(capabilities, cost = 'medium') {
  const index = TIER_ORDER.indexOf(capabilities.tier ?? 'high');
  const drop = cost === 'high' && index < 2 ? 1 : 0;
  return TIER_ORDER[Math.max(0, index - drop)];
}

/**
 * Feed it the time each frame took. It answers with a new tier when the average over a
 * window is over budget (step down) or well under it for three windows (step back up,
 * never above the starting tier). Otherwise it answers null.
 */
export function createGovernor({ start = 'high', targetMs = 1000 / 50, window = 24 } = {}) {
  const ceiling = TIER_ORDER.indexOf(start);
  let index = ceiling;
  let samples = [];
  let calm = 0;
  return {
    get tier() {
      return TIER_ORDER[index];
    },
    sample(frameMs) {
      samples.push(frameMs);
      if (samples.length < window) return null;
      const average = samples.reduce((sum, value) => sum + value, 0) / samples.length;
      samples = [];
      if (average > targetMs * 1.2 && index > 0) {
        index -= 1;
        calm = 0;
        return TIER_ORDER[index];
      }
      calm = average < targetMs * 0.5 ? calm + 1 : 0;
      if (calm >= 3 && index < ceiling) {
        index += 1;
        calm = 0;
        return TIER_ORDER[index];
      }
      return null;
    },
  };
}
