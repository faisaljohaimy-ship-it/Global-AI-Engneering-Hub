// Easing curves as pure functions. The first five are the CSS keywords.
const CURVES = {
  linear: null,
  ease: [0.25, 0.1, 0.25, 1],
  'ease-in': [0.42, 0, 1, 1],
  'ease-out': [0, 0, 0.58, 1],
  'ease-in-out': [0.42, 0, 0.58, 1],
  'ease-out-cubic': [0.215, 0.61, 0.355, 1],
  'ease-in-out-cubic': [0.645, 0.045, 0.355, 1],
  'ease-out-back': [0.34, 1.56, 0.64, 1],
};

export const EASINGS = Object.freeze(Object.keys(CURVES));

function bezier(x1, y1, x2, y2) {
  const at = (a, b, t) => ((1 - 3 * b + 3 * a) * t + (3 * b - 6 * a)) * t * t + 3 * a * t;
  const slope = (a, b, t) => 3 * (1 - 3 * b + 3 * a) * t * t + 2 * (3 * b - 6 * a) * t + 3 * a;
  return (x) => {
    if (x <= 0) return 0;
    if (x >= 1) return 1;
    let low = 0;
    let high = 1;
    let t = x;
    for (let step = 0; step < 32; step += 1) {
      const error = at(x1, x2, t) - x;
      if (Math.abs(error) < 1e-9) break;
      if (error > 0) high = t;
      else low = t;
      const gradient = slope(x1, x2, t);
      const next = gradient > 1e-6 ? t - error / gradient : (low + high) / 2;
      t = next > low && next < high ? next : (low + high) / 2;
    }
    return at(y1, y2, t);
  };
}

const solved = new Map();

/** Eased progress (0 to 1 in, eased value out; back easings may overshoot). */
export function ease(name, x) {
  if (!Object.hasOwn(CURVES, name)) throw new RangeError(`Unknown easing: ${name}`);
  if (name === 'linear') return Math.min(1, Math.max(0, x));
  if (!solved.has(name)) solved.set(name, bezier(...CURVES[name]));
  return solved.get(name)(x);
}
