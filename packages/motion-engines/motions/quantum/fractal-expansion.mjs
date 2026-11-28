import { defineMotion } from '../../core/define.mjs';
import { canvas2d } from '../../engines/canvas2d.mjs';
import { clamp, mixColour, rgba } from '../../core/util.mjs';

export default defineMotion({
  id: 'quantum-fractal-expansion',
  number: 9,
  module: 'quantum',
  name: { en: 'Quantum Fractal Expansion', ar: 'التمدّد الكسيري الكمّي' },
  summary: {
    en: 'A six-armed fractal grows from the centre one generation at a time, every branch splitting in two.',
    ar: 'بنية كسيرية بستة أذرع تنمو من المركز جيلًا بعد جيل، وكل فرع ينقسم إلى اثنين.',
  },
  engine: 'canvas2d',
  kind: 'oneshot',
  duration: 3000,
  easing: 'ease-out',
  colors: ['#060814', '#34d399', '#e879f9'],
  params: {
    depth: { default: 5, min: 2, max: 7, step: 1, label: { en: 'Generations', ar: 'عدد الأجيال' } },
    angle: { default: 32, min: 10, max: 60, step: 1, label: { en: 'Branch angle', ar: 'زاوية التفرّع' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'none', cost: 'medium' },
  still: 1,
  tags: ['reveal', 'generative', 'science', 'logo'],
  setup: canvas2d({
    draw(g, s, ctx) {
      const generations = Math.min(Math.round(ctx.params.depth), 4 + ctx.quality.level);
      const spread = (ctx.params.angle * Math.PI) / 180;
      const reach = Math.min(ctx.width, ctx.height) * 0.2;
      g.lineCap = 'round';
      const branch = (x, y, heading, size, level) => {
        const grown = clamp(s.progress * generations - level);
        if (grown <= 0) return;
        const [ex, ey] = [x + Math.cos(heading) * size * grown, y + Math.sin(heading) * size * grown];
        g.strokeStyle = rgba(mixColour(ctx.colors[1], ctx.colors[2], level / generations), 0.9 - level * 0.08);
        g.lineWidth = Math.max(0.6, 3 - level * 0.45);
        g.beginPath();
        g.moveTo(x, y);
        g.lineTo(ex, ey);
        g.stroke();
        if (level + 1 < generations && grown >= 1) {
          branch(ex, ey, heading - spread, size * 0.68, level + 1);
          branch(ex, ey, heading + spread, size * 0.68, level + 1);
        }
      };
      for (let arm = 0; arm < 6; arm += 1) branch(ctx.width / 2, ctx.height / 2, (arm / 6) * Math.PI * 2 - Math.PI / 2, reach, 0);
    },
  }),
});
