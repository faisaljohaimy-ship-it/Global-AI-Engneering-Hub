// Small pure helpers shared by the core and by motions.

export const clamp = (value, low = 0, high = 1) => Math.min(high, Math.max(low, value));
export const lerp = (a, b, t) => a + (b - a) * t;
export const smoothstep = (a, b, x) => {
  const t = clamp((x - a) / (b - a));
  return t * t * (3 - 2 * t);
};
export const TAU = Math.PI * 2;
/** Position inside one stage of a timeline: 0 before \`from\`, 1 after \`to\`, linear between. */
export const stage = (progress, from, to) => clamp((progress - from) / (to - from));
/** Triangle wave 0..1..0 over one unit: for motions that go out and come back. */
export const pingPong = (x) => 1 - Math.abs(((x % 1) + 1) % 1 * 2 - 1);

/** '#rgb' or '#rrggbb' to [r, g, b] in 0..1. */
export function hexToRgb(hex) {
  const match = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(String(hex).trim());
  if (!match) throw new RangeError(`Colours must be #rgb or #rrggbb: ${hex}`);
  const digits = match[1].length === 3 ? [...match[1]].map((digit) => digit + digit).join('') : match[1];
  return [0, 2, 4].map((index) => parseInt(digits.slice(index, index + 2), 16) / 255);
}

/** CSS colour from an [r, g, b] triple in 0..1. */
export function rgba(colour, alpha = 1) {
  const [r, g, b] = colour.map((channel) => Math.round(clamp(channel) * 255));
  return `rgba(${r}, ${g}, ${b}, ${clamp(alpha)})`;
}

export const mixColour = (a, b, t) => a.map((channel, index) => lerp(channel, b[index], t));

/** Seeded generator: the same seed always yields the same sequence. */
export function mulberry32(seed) {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let value = state;
    value = Math.imul(value ^ (value >>> 15), value | 1);
    value ^= value + Math.imul(value ^ (value >>> 7), value | 61);
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
  };
}

/** FNV-1a over bytes, as eight hex digits. */
export function fnv1a(bytes) {
  let hash = 0x811c9dc5;
  for (let index = 0; index < bytes.length; index += 1) {
    hash ^= bytes[index];
    hash = Math.imul(hash, 0x01000193);
  }
  return (hash >>> 0).toString(16).padStart(8, '0');
}

/** Deterministic value noise in one dimension, 0..1. */
export function noise1(x, seed = 0) {
  const cell = Math.floor(x);
  const at = (n) => {
    const s = Math.sin((n + seed * 57.13) * 127.1) * 43758.5453;
    return s - Math.floor(s);
  };
  const f = x - cell;
  return lerp(at(cell), at(cell + 1), f * f * (3 - 2 * f));
}
