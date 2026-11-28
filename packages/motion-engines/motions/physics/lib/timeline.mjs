// Stored states of a simulation. A physics motion runs its simulation once, in init, with a
// fixed step for the whole timeline and writes every state here; drawing then reads the
// state for any moment, so a frame stays a pure function of time.
import { clamp } from '../../../core/util.mjs';

/** `frames` snapshots of `stride` numbers each. */
export function timeline(frames, stride) {
  const data = new Float32Array(frames * stride);
  const state = new Float32Array(stride);
  return {
    data, frames, stride,
    /** Keep `values` (any array-like of `stride` numbers) as snapshot `frame`. */
    write(frame, values) {
      data.set(values, frame * stride);
    },
    /** The state at `progress` 0..1, interpolated between the two nearest snapshots. The array returned is reused. */
    read(progress) {
      const position = clamp(progress) * (frames - 1);
      const first = Math.min(frames - 2, Math.floor(position));
      const blend = position - first;
      const base = first * stride;
      for (let index = 0; index < stride; index += 1) state[index] = data[base + index] + (data[base + stride + index] - data[base + index]) * blend;
      return state;
    },
    /** One number of snapshot `frame`, without interpolation: for trails drawn from the stored states. */
    value: (frame, index) => data[frame * stride + index],
  };
}
