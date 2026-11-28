import { defineMotion } from '../../core/define.mjs';
import { canvas2d } from '../../engines/canvas2d.mjs';
import { clamp, rgba, smoothstep } from '../../core/util.mjs';
import { font, isArabic } from '../../core/text.mjs';

// One line in one language is wiped away along its own reading direction while the line
// in the other language is wiped in along its own. Whole words stay intact throughout.
function wipe(g, ctx, text, size, y, amount, leaving, colour) {
  if (amount <= 0) return null;
  const rtl = isArabic(text);
  g.font = font(size, 700);
  g.direction = rtl ? 'rtl' : 'ltr';
  g.textAlign = 'center';
  g.textBaseline = 'middle';
  const width = g.measureText(text).width;
  const left = ctx.width / 2 - width / 2;
  const shown = width * clamp(amount);
  // Entering text grows from where reading starts; leaving text shrinks toward where reading ends.
  const fromRight = rtl !== leaving;
  g.save();
  g.beginPath();
  g.rect(fromRight ? left + width - shown : left, y - size, shown, size * 2);
  g.clip();
  g.fillStyle = colour;
  g.fillText(text, ctx.width / 2, y);
  g.restore();
  return { left, width, edge: fromRight ? left + width - shown : left + shown };
}

export default defineMotion({
  id: 'typography-bilingual-transition',
  number: 88,
  module: 'typography',
  name: { en: 'Bilingual Typography Transition', ar: 'انتقال طباعي ثنائي اللغة' },
  summary: {
    en: 'A headline hands over to its translation: each language is wiped along its own reading direction, with a light bar riding the moving edge.',
    ar: 'عنوان يسلّم مكانه لترجمته: تُمسح كل لغة وفق اتجاه قراءتها، مع شريط ضوئي يرافق الحافة المتحركة.',
  },
  engine: 'canvas2d',
  kind: 'oneshot',
  duration: 3200,
  easing: 'ease-in-out',
  colors: ['#0a0f1e', '#f8fafc', '#38bdf8'],
  params: {
    size: { default: 0.9, min: 0.5, max: 1, step: 0.05, label: { en: 'Text size (share of the widest that fits)', ar: 'حجم النص (نسبةً إلى أعرض ما يتّسع)' } },
    overlap: { default: 0.2, min: 0, max: 0.4, step: 0.02, label: { en: 'Overlap of the two lines', ar: 'تداخل السطرين' } },
  },
  text: {
    en: { first: 'Engineering in motion', second: 'هندسة تتحرك' },
    ar: { first: 'هندسة تتحرك', second: 'Engineering in motion' },
  },
  rtl: 'text',
  requirements: { gpu: 'none', cost: 'low' },
  still: 0.9,
  tags: ['text', 'headline', 'arabic', 'bilingual', 'title'],
  setup: canvas2d({
    draw(g, s, ctx) {
      // The larger of the two lines fills 88% of the width at size 1, within a height limit.
      g.font = font(100, 700);
      const widest = Math.max(g.measureText(ctx.text.first).width, g.measureText(ctx.text.second).width);
      const size = Math.min((ctx.width * 0.88 * 100) / widest, ctx.height * 0.3) * ctx.params.size;
      const y = ctx.height / 2;
      const split = 0.5;
      const half = ctx.params.overlap / 2;
      const leaving = 1 - smoothstep(split - 0.3 - half, split + half, s.progress);
      const entering = smoothstep(split - half, split + 0.3 + half, s.progress);
      const out = wipe(g, ctx, ctx.text.first, size, y - size * 0.15 * entering, leaving, true, rgba(ctx.colors[1], 0.35 + 0.65 * leaving));
      const into = wipe(g, ctx, ctx.text.second, size, y + size * 0.15 * (1 - entering), entering, false, rgba(ctx.colors[1], 1));
      // The light bar rides whichever edge is moving.
      const edge = entering > 0 && entering < 1 ? into : leaving > 0 && leaving < 1 ? out : null;
      if (edge) {
        g.fillStyle = rgba(ctx.colors[2], 0.9);
        g.fillRect(edge.edge - 1.5, y - size * 0.75, 3, size * 1.5);
      }
      // A rule under the line fills as the handover completes, from where reading starts.
      const rule = ctx.width * 0.5 * s.progress;
      g.fillStyle = rgba(ctx.colors[2], 0.6);
      g.fillRect(ctx.rtl ? ctx.width * 0.75 - rule : ctx.width * 0.25, y + size * 1.05, rule, Math.max(2, size * 0.08));
    },
  }),
});
