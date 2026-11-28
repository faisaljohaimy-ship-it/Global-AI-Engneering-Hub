import { defineMotion } from '../../core/define.mjs';
import { dom } from '../../engines/dom.mjs';
import { clamp, lerp, smoothstep } from '../../core/util.mjs';

/**
 * The behaviour itself, usable on any element (see adapters/behaviour.mjs).
 * `pointer` is the pointer measured from the element's centre in units of the element's
 * half-size: { x, y, down }. Returns CSS declarations for the element.
 */
export function respond(pointer, { strength = 0.35, reach = 2.2 } = {}) {
  const distance = Math.hypot(pointer.x, pointer.y);
  const pull = strength * (1 - smoothstep(reach * 0.35, reach, distance));
  const press = pointer.down && distance < 1.2 ? 0.94 : 1;
  return {
    transform: `translate(${(pointer.x * pull * 50).toFixed(2)}%, ${(pointer.y * pull * 50).toFixed(2)}%) scale(${(press * (1 + pull * 0.12)).toFixed(4)})`,
    boxShadow: `0 ${(6 + pull * 30).toFixed(1)}px ${(14 + pull * 50).toFixed(1)}px -8px var(--glow)`,
  };
}

// The scripted demonstration: the pointer drifts in from the reading-start side, circles, presses and leaves.
function script(raw, dir) {
  const approach = smoothstep(0, 0.3, raw);
  const leave = smoothstep(0.82, 1, raw);
  const angle = raw * Math.PI * 4;
  const orbit = 0.1 * approach * (1 - leave);
  const x = lerp(0.5 - dir * 0.42, 0.5, approach) + Math.cos(angle) * orbit * 1.4 + dir * leave * 0.45;
  const y = lerp(0.82, 0.5, approach) + Math.sin(angle) * orbit - leave * 0.3;
  return { x: clamp(x), y: clamp(y), down: raw > 0.56 && raw < 0.7 };
}

export default defineMotion({
  id: 'micro-magnetic-button',
  number: 91,
  module: 'micro',
  name: { en: 'Magnetic Button Attraction', ar: 'انجذاب الزر المغناطيسي' },
  summary: {
    en: 'A button leans toward the pointer as it comes near, lifts its shadow, and settles under a press. The same response can be attached to any real element.',
    ar: 'زر يميل نحو المؤشر كلما اقترب منه، يرفع ظلّه، ويستقر عند الضغط. يمكن ربط الاستجابة نفسها بأي عنصر حقيقي.',
  },
  engine: 'dom',
  kind: 'loop',
  duration: 5000,
  easing: 'ease-out',
  colors: ['#0b1020', '#6366f1', '#a5b4fc', '#f8fafc'],
  params: {
    strength: { default: 0.35, min: 0, max: 0.8, step: 0.05, label: { en: 'Pull strength', ar: 'قوة الجذب' } },
    reach: { default: 2.2, min: 1.2, max: 4, step: 0.1, label: { en: 'Reach', ar: 'مدى الجذب' } },
  },
  text: { en: { label: 'Get started' }, ar: { label: 'ابدأ الآن' } },
  interactive: {
    sample: { x: 0.62, y: 0.4, down: false },
    note: { en: 'Pointer position x, y in 0..1 of the frame and down (pressed).', ar: 'موضع المؤشر x و y من 0 إلى 1 داخل الإطار، وdown عند الضغط.' },
  },
  rtl: 'text',
  requirements: { gpu: 'none', cost: 'low' },
  still: 0.45,
  tags: ['button', 'hover', 'pointer', 'cta', 'interaction'],
  setup: dom({
    css: `
:scope .field { position: absolute; inset: 0; display: grid; place-items: center; }
:scope .button { padding: 0.75em 1.7em; border-radius: 999px; font-weight: 650; white-space: nowrap; }
:scope .cursor { position: absolute; width: 12px; height: 12px; margin: -6px 0 0 -6px; border-radius: 50%; border: 2px solid; }`,
    build(root, ctx) {
      const document = root.ownerDocument;
      const field = root.appendChild(document.createElement('div'));
      field.className = 'field';
      const button = field.appendChild(document.createElement('div'));
      button.className = 'button';
      button.textContent = ctx.text.label;
      button.style.fontSize = `${Math.max(12, Math.min(ctx.width, ctx.height) * 0.085).toFixed(1)}px`;
      button.style.background = `linear-gradient(135deg, ${ctx.css[1]}, ${ctx.css[2]})`;
      button.style.color = ctx.css[3] ?? ctx.css[0];
      button.style.setProperty('--glow', ctx.css[1]);
      const cursor = root.appendChild(document.createElement('div'));
      cursor.className = 'cursor';
      cursor.style.borderColor = ctx.css[3] ?? ctx.css[2];
      return { button, cursor, half: null };
    },
    apply(refs, s, ctx) {
      const pointer = ctx.input.live ? ctx.input : script(s.raw, ctx.dir);
      // Measured once: the button's own size does not change, only its transform.
      refs.half ??= { x: Math.max(1, refs.button.offsetWidth / 2), y: Math.max(1, refs.button.offsetHeight / 2) };
      const relative = {
        x: ((pointer.x - 0.5) * ctx.width) / refs.half.x,
        y: ((pointer.y - 0.5) * ctx.height) / refs.half.y,
        down: pointer.down,
      };
      const style = respond(relative, ctx.params);
      refs.button.style.transform = style.transform;
      refs.button.style.boxShadow = style.boxShadow;
      refs.button.style.opacity = (0.35 + 0.65 * s.intro).toFixed(3);
      refs.cursor.style.display = ctx.input.live ? 'none' : 'block';
      refs.cursor.style.left = `${(pointer.x * 100).toFixed(2)}%`;
      refs.cursor.style.top = `${(pointer.y * 100).toFixed(2)}%`;
      refs.cursor.style.transform = `scale(${pointer.down ? 0.7 : 1})`;
      refs.cursor.style.background = pointer.down ? (ctx.css[3] ?? ctx.css[2]) : 'transparent';
    },
  }),
});
