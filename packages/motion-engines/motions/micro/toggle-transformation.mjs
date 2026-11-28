import { defineMotion } from '../../core/define.mjs';
import { dom } from '../../engines/dom.mjs';
import { clamp, lerp, smoothstep } from '../../core/util.mjs';
import { spring } from '../../core/spring.mjs';

/**
 * The response of the knob itself, usable on a real switch (see adapters/behaviour.mjs):
 * the knob stretches toward its travel while pressed and glows on hover or keyboard focus.
 * `input`: { down, hover, focus, since } (since: ms since the last change).
 */
export function respond(input, { stretch = 0.35 } = {}) {
  const pressed = input.down ? spring((input.since ?? 0) / 1000, { frequency: 5, damping: 1 }) : 1 - spring((input.since ?? 0) / 1000, { frequency: 3, damping: 0.45 });
  const glow = input.focus || input.hover ? 1 : 0;
  return {
    transform: `scaleX(${(1 + stretch * clamp(pressed, -0.2, 1.2)).toFixed(4)})`,
    boxShadow: `0 0 0 ${(glow * 3).toFixed(1)}px var(--ring), 0 2px 6px -2px rgba(0, 0, 0, 0.6)`,
  };
}

// The scripted demonstration: switched on, held a moment, switched off again, every cycle.
function script(raw) {
  const on = raw > 0.2 && raw < 0.7;
  const changedAt = raw > 0.7 ? 0.7 : raw > 0.2 ? 0.2 : 0;
  return { on, since: (raw - changedAt) * 4 };
}

export default defineMotion({
  id: 'micro-toggle-transformation',
  number: 96,
  module: 'micro',
  name: { en: 'Dynamic Toggle Transformation', ar: 'تحوّل مفتاح التبديل الديناميكي' },
  summary: {
    en: 'A settings row turns two-step sign-in on and off. The knob springs across its track, stretching as it travels and overshooting a little; the track fills with colour from the knob’s side, and the padlock beside the label closes when the protection is on.',
    ar: 'صفّ إعداداتٍ يشغّل التحقق بخطوتين ويطفئه. يقفز مقبض المفتاح عبر مساره بنابض، يتمدّد وهو يتحرّك ويتجاوز قليلًا؛ ويمتلئ المسار باللون من جهة المقبض، ويُغلق القفل بجانب العنوان حين تكون الحماية مفعّلة.',
  },
  meaning: {
    en: 'Turning on two-step verification: a digital account setting switches its security protection on and off.',
    ar: 'تفعيل التحقق بخطوتين: إعدادٌ في الحساب الرقمي يشغّل حماية الأمان ويطفئها.',
  },
  engine: 'dom',
  kind: 'loop',
  duration: 4000,
  easing: 'ease-out',
  colors: ['#0b1020', '#1e293b', '#22c55e', '#f8fafc', '#94a3b8'],
  params: {
    stretch: { default: 0.35, min: 0, max: 0.8, step: 0.05, label: { en: 'Knob stretch in travel', ar: 'تمدّد المقبض أثناء الحركة' } },
    bounce: { default: 0.45, min: 0.15, max: 1, step: 0.05, label: { en: 'Spring damping', ar: 'تخميد النابض' } },
  },
  text: { en: { label: 'Two-step sign-in' }, ar: { label: 'التحقق بخطوتين' } },
  rtl: 'text',
  requirements: { gpu: 'none', cost: 'low' },
  still: 0.5,
  tags: ['toggle', 'switch', 'settings', 'security', '2fa', 'interaction'],
  setup: dom({
    css: `
:scope .row { position: absolute; inset-inline: 8%; top: 50%; transform: translateY(-50%); display: flex; align-items: center; gap: 0.8em; padding: 0.9em 1.1em; border-radius: 0.8em; }
:scope .label { flex: 1; font-weight: 600; white-space: nowrap; text-align: start; }
:scope .lock { position: relative; width: 1.1em; height: 1.3em; flex: none; }
:scope .shackle { position: absolute; inset-inline-start: 0.17em; width: 0.76em; height: 0.8em; border: 0.14em solid; border-bottom: none; border-radius: 0.4em 0.4em 0 0; }
:scope .body { position: absolute; inset-inline: 0; bottom: 0; height: 0.65em; border-radius: 0.15em; }
:scope .track { position: relative; width: 2.8em; height: 1.5em; border-radius: 999px; flex: none; overflow: hidden; }
:scope .fill { position: absolute; top: 0; bottom: 0; inset-inline-start: 0; border-radius: 999px; }
:scope .knob { position: absolute; top: 0.15em; width: 1.2em; height: 1.2em; border-radius: 999px; }`,
    build(root, ctx) {
      const document = root.ownerDocument;
      const make = (parent, name) => {
        const node = parent.appendChild(document.createElement('div'));
        node.className = name;
        return node;
      };
      const row = make(root, 'row');
      row.style.fontSize = `${Math.max(9, Math.min(ctx.width * 0.042, ctx.height * 0.085)).toFixed(1)}px`;
      row.style.background = ctx.css[1];
      row.style.color = ctx.css[3];
      const lock = make(row, 'lock');
      const shackle = make(lock, 'shackle');
      const body = make(lock, 'body');
      const label = make(row, 'label');
      label.textContent = ctx.text.label;
      const track = make(row, 'track');
      const fill = make(track, 'fill');
      fill.style.background = ctx.css[2];
      const knob = make(track, 'knob');
      knob.style.background = ctx.css[3];
      knob.style.setProperty('--ring', ctx.css[2]);
      return { row, shackle, body, track, fill, knob };
    },
    apply(refs, s, ctx) {
      const { on, since } = script(s.raw);
      const travel = spring(since, { frequency: 2.2, damping: ctx.params.bounce });
      const position = on ? travel : 1 - travel;
      const moving = clamp(1 - Math.abs(since - 0.12) / 0.25);
      const style = respond({ down: moving > 0.3, since: since * 1000, focus: false, hover: false }, { stretch: ctx.params.stretch });
      refs.row.style.opacity = (0.3 + 0.7 * s.intro).toFixed(3);
      refs.track.style.background = ctx.css[4];
      // The knob travels from the reading-start end of the track to the other.
      const offset = lerp(0.15, 1.45, position);
      refs.knob.style.insetInlineStart = `${offset.toFixed(3)}em`;
      refs.knob.style.transform = style.transform;
      refs.knob.style.boxShadow = style.boxShadow;
      refs.fill.style.width = `${(offset + 1.2).toFixed(3)}em`;
      refs.fill.style.opacity = clamp(position).toFixed(3);
      const closed = smoothstep(0.3, 0.9, position);
      refs.shackle.style.borderColor = on ? ctx.css[2] : ctx.css[4];
      refs.shackle.style.top = `${lerp(-0.25, 0, closed).toFixed(3)}em`;
      refs.body.style.background = on ? ctx.css[2] : ctx.css[4];
    },
  }),
});
