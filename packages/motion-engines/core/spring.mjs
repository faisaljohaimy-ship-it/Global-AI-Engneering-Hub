// Springs in closed form, so that a spring response is a function of elapsed time and
// needs no state between frames.

/**
 * Position of a spring released at 0 toward 1, `seconds` after release.
 * `frequency` is in oscillations per second; `damping` is the damping ratio
 * (below 1 it overshoots and rings, at 1 it settles as fast as possible without overshoot).
 */
export function spring(seconds, { frequency = 3, damping = 0.5 } = {}) {
  if (seconds <= 0) return 0;
  const omega = 2 * Math.PI * frequency;
  if (damping >= 1) return 1 - Math.exp(-omega * seconds) * (1 + omega * seconds);
  const ringing = omega * Math.sqrt(1 - damping * damping);
  const decay = Math.exp(-damping * omega * seconds);
  return 1 - decay * (Math.cos(ringing * seconds) + ((damping * omega) / ringing) * Math.sin(ringing * seconds));
}

/** A spring that is knocked and comes back to rest: 0 at first, a swing, then 0 again. */
export function wobble(seconds, { frequency = 4, damping = 0.35 } = {}) {
  if (seconds <= 0) return 0;
  const omega = 2 * Math.PI * frequency;
  return Math.exp(-damping * omega * seconds) * Math.sin(omega * Math.sqrt(1 - damping * damping) * seconds);
}

/** Seconds after which spring() stays within `tolerance` of 1. */
export function settleTime({ frequency = 3, damping = 0.5 } = {}, tolerance = 0.002) {
  return -Math.log(tolerance) / (Math.min(1, damping) * 2 * Math.PI * frequency);
}
