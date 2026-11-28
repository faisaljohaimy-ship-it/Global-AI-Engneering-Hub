import { defineMotion } from '../../core/define.mjs';
import { canvas2d } from '../../engines/canvas2d.mjs';
import { mixColour, rgba } from '../../core/util.mjs';
import { spring } from '../../core/spring.mjs';

// Each weight hangs from its own spring, stiffer and less damped from first to last.
function springsOf(count, stiffness, damping) {
  return Array.from({ length: count }, (_, index) => ({
    frequency: (0.9 + 0.45 * index) * stiffness,
    damping: Math.min(1.2, damping * (0.45 + 0.35 * index)),
  }));
}

// A coil from (x, top) to (x, bottom): a zigzag with a fixed number of turns, so it stretches and squeezes.
function coil(g, x, top, bottom, width, turns) {
  g.beginPath();
  g.moveTo(x, top);
  const lead = (bottom - top) * 0.1;
  g.lineTo(x, top + lead);
  const span = bottom - top - lead * 2;
  for (let step = 1; step < turns * 2; step += 1) g.lineTo(x + (step % 2 ? width : -width), top + lead + (span * step) / (turns * 2));
  g.lineTo(x, bottom - lead);
  g.lineTo(x, bottom);
  g.stroke();
}

export default defineMotion({
  id: 'physics-spring-motion',
  number: 127,
  module: 'physics',
  name: { en: 'Spring-based Object Motion', ar: 'حركة الأجسام على النوابض' },
  summary: {
    en: 'Four weights are pulled up and let go together. Each hangs on a coil of its own stiffness and damping, so one settles at once, one bounces lazily and one rings for a long time; beside each, a trace records its height over time.',
    ar: 'أربعة أثقال تُرفع ثم تُفلت معًا. كلٌّ منها معلّقٌ على نابضٍ له صلابته وتخميده، فواحدٌ يستقرّ فورًا، وآخر يرتدّ متكاسلًا، وثالثٌ يظلّ يهتزّ طويلًا؛ وبجانب كلٍّ منها أثرٌ يسجّل ارتفاعه عبر الزمن.',
  },
  meaning: {
    en: 'Tuning interface motion for a digital product: spring presets are compared side by side before they enter the design system.',
    ar: 'ضبط حركة الواجهة لمنتجٍ رقمي: تُقارن إعدادات النوابض جنبًا إلى جنب قبل اعتمادها في نظام التصميم.',
  },
  engine: 'canvas2d',
  kind: 'oneshot',
  duration: 3600,
  easing: 'linear',
  colors: ['#0b1020', '#38bdf8', '#f472b6', '#e2e8f0'],
  params: {
    stiffness: { default: 1, min: 0.4, max: 2, step: 0.05, label: { en: 'Stiffness', ar: 'الصلابة' } },
    damping: { default: 0.35, min: 0.05, max: 1, step: 0.05, label: { en: 'Damping', ar: 'التخميد' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'none', cost: 'low' },
  still: 1,
  tags: ['physics', 'spring', 'easing', 'explainer', 'ui'],
  setup: canvas2d({
    draw(g, s, ctx) {
      const { width: w, height: h } = ctx;
      const seconds = s.progress * 3.2;
      const count = 4;
      const springs = springsOf(count, ctx.params.stiffness, ctx.params.damping);
      const bar = h * 0.1;
      const rest = h * 0.6;
      const lift = h * 0.32;
      const lane = w / count;
      const size = Math.min(lane * 0.32, h * 0.13);
      g.fillStyle = rgba(ctx.colors[3], 0.8);
      g.fillRect(w * 0.04, bar - 3, w * 0.92, 4);
      springs.forEach((spec, index) => {
        const x = lane * (index + 0.35);
        const at = (time) => rest - lift * (1 - spring(time, spec));
        const y = at(seconds);
        const colour = mixColour(ctx.colors[1], ctx.colors[2], index / (count - 1));
        // The trace: height against time, from release to now, drawn to the right of the weight.
        g.strokeStyle = rgba(colour, 0.45);
        g.lineWidth = 1.2;
        g.beginPath();
        const traceWidth = lane * 0.5;
        const steps = 60;
        for (let step = 0; step <= steps; step += 1) {
          const time = (seconds * step) / steps;
          const px = x + size * 0.9 + (traceWidth * step) / steps;
          const py = at(time);
          if (step) g.lineTo(px, py);
          else g.moveTo(px, py);
        }
        g.stroke();
        g.strokeStyle = rgba(ctx.colors[3], 0.15);
        g.beginPath();
        g.moveTo(x + size * 0.9, rest);
        g.lineTo(x + size * 0.9 + traceWidth, rest);
        g.stroke();
        // The coil and the weight; the weight squashes a little when moving fast.
        g.strokeStyle = rgba(ctx.colors[3], 0.85);
        g.lineWidth = 1.4;
        coil(g, x, bar, y - size / 2, size * 0.28, 7);
        const speed = (at(seconds + 0.01) - y) / 0.01 / h;
        const stretch = 1 + Math.max(-0.25, Math.min(0.25, speed * 0.08));
        g.fillStyle = rgba(colour, 1);
        g.beginPath();
        g.roundRect(x - (size / 2) / stretch, y - size / 2, size / stretch, size * stretch, size * 0.22);
        g.fill();
        g.fillStyle = rgba(ctx.colors[3], 0.35);
        g.fillRect(x - size * 0.3 / stretch, y - size * 0.38, size * 0.6 / stretch, size * 0.1);
      });
    },
  }),
});
