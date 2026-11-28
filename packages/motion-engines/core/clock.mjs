// The source of time for a playing motion. Tests and frame-exact rendering use the
// virtual clock, which only moves when told to.

export function realClock(view = globalThis) {
  return {
    now: () => view.performance.now(),
    request: (callback) => view.requestAnimationFrame(callback),
    cancel: (id) => view.cancelAnimationFrame(id),
  };
}

export function createVirtualClock(stepMs = 1000 / 60) {
  let now = 0;
  let nextId = 0;
  let frames = 0;
  const queue = new Map();
  return {
    now: () => now,
    request(callback) {
      nextId += 1;
      queue.set(nextId, callback);
      return nextId;
    },
    cancel: (id) => queue.delete(id),
    /** Move time forward, running the scheduled frame callbacks one step at a time. */
    advance(ms) {
      const end = now + ms;
      while (now + stepMs <= end + 1e-6) {
        now += stepMs;
        const pending = [...queue.values()];
        queue.clear();
        frames += pending.length;
        for (const callback of pending) callback(now);
      }
    },
    get pending() {
      return queue.size;
    },
    get framesRun() {
      return frames;
    },
  };
}
