// Attach a micro-interaction to a real element. The motion files in motions/micro export
// `respond(input, params)`, the response itself, which this adapter feeds from pointer
// and focus events:
//
//   import { attach } from 'motion-sdk/adapters/behaviour.mjs';
//   import { respond } from 'motion-sdk/motions/micro/magnetic-button.mjs';
//   const detach = attach(document.querySelector('button'), respond, { params: { strength: 0.4 } });
//
// Only inline styles of that element are touched, and detach() puts them back.

const ALLOWED = new Set(['transform', 'opacity', 'filter', 'boxShadow', 'borderRadius', 'letterSpacing', 'outline', 'outlineOffset']);
const FAR = 9;

/** The declarations a response may set: a short list of visual properties and custom properties. */
export function safeDeclarations(style) {
  const safe = {};
  for (const [name, value] of Object.entries(style ?? {})) {
    if (!(ALLOWED.has(name) || name.startsWith('--'))) continue;
    if (typeof value !== 'string' && typeof value !== 'number') continue;
    if (/url\(|expression\(|[;{}<>]/i.test(String(value))) continue;
    safe[name] = String(value);
  }
  return safe;
}

/**
 * `area` is the element whose pointer events drive the response (default: the element
 * itself; give a larger parent for effects that start before the pointer arrives).
 * `settleMs` is how long the response keeps being redrawn after the last change, so that
 * springs can come to rest. Under reduced motion nothing is attached.
 */
export function attach(element, respond, { params = {}, area = element, settleMs = 1500, reducedMotion } = {}) {
  const view = element.ownerDocument.defaultView;
  if (reducedMotion ?? view.matchMedia('(prefers-reduced-motion: reduce)').matches) return () => {};
  const input = { x: FAR, y: FAR, down: false, hover: false, focus: false, since: settleMs };
  const before = new Map();
  let box = null;
  let frame = null;
  let changed = view.performance.now() - settleMs;

  const measure = () => {
    const kept = element.style.transform;
    element.style.transform = 'none';
    box = element.getBoundingClientRect();
    element.style.transform = kept;
  };
  const paint = () => {
    frame = null;
    input.since = view.performance.now() - changed;
    for (const [name, value] of Object.entries(safeDeclarations(respond({ ...input }, params)))) {
      const custom = name.startsWith('--');
      if (!before.has(name)) before.set(name, custom ? element.style.getPropertyValue(name) : element.style[name]);
      if (custom) element.style.setProperty(name, value);
      else element.style[name] = value;
    }
    if (input.since < settleMs) frame = view.requestAnimationFrame(paint);
  };
  const set = (values, restart) => {
    Object.assign(input, values);
    if (restart) changed = view.performance.now();
    if (frame === null) frame = view.requestAnimationFrame(paint);
  };
  const where = (event) => {
    if (!box) measure();
    return { x: (event.clientX - (box.left + box.width / 2)) / (box.width / 2 || 1), y: (event.clientY - (box.top + box.height / 2)) / (box.height / 2 || 1) };
  };
  const handlers = [
    [area, 'pointerenter', (event) => { measure(); set({ hover: true, ...where(event) }, true); }],
    [area, 'pointermove', (event) => set(where(event), false)],
    [area, 'pointerleave', () => set({ hover: false, down: false, x: FAR, y: FAR }, true)],
    [area, 'pointerdown', (event) => set({ down: true, ...where(event) }, true)],
    [area, 'pointerup', () => set({ down: false }, true)],
    [element, 'focus', () => set({ focus: true }, true)],
    [element, 'blur', () => set({ focus: false }, true)],
  ];
  for (const [target, name, handler] of handlers) target.addEventListener(name, handler);

  return function detach() {
    for (const [target, name, handler] of handlers) target.removeEventListener(name, handler);
    if (frame !== null) view.cancelAnimationFrame(frame);
    for (const [name, value] of before) {
      if (name.startsWith('--')) {
        if (value) element.style.setProperty(name, value);
        else element.style.removeProperty(name);
      } else element.style[name] = value;
    }
  };
}
