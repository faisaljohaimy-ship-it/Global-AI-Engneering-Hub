import { defineMotion } from '../../core/define.mjs';
import { canvas2d } from '../../engines/canvas2d.mjs';
import { TAU, mixColour, rgba, smoothstep } from '../../core/util.mjs';

// The outgoing page: a dark dashboard of cards.
function pageA(g, ctx) {
  const { width: w, height: h } = ctx;
  g.fillStyle = rgba(mixColour(ctx.colors[0], ctx.colors[1], 0.12), 1);
  g.fillRect(0, 0, w, h);
  g.fillStyle = rgba(ctx.colors[1], 0.35);
  g.fillRect(w * 0.05, h * 0.07, w * 0.9, h * 0.09);
  for (let column = 0; column < 3; column += 1) {
    for (let row = 0; row < 2; row += 1) {
      g.fillStyle = rgba(ctx.colors[1], 0.18 + 0.08 * ((column + row) % 2));
      g.beginPath();
      g.roundRect(w * (0.05 + column * 0.31), h * (0.24 + row * 0.38), w * 0.28, h * 0.32, 6);
      g.fill();
    }
  }
}

// The incoming page: a bright hero with a large disc and lines of copy.
function pageB(g, ctx) {
  const { width: w, height: h } = ctx;
  const sky = g.createLinearGradient(0, 0, w, h);
  sky.addColorStop(0, rgba(ctx.colors[2], 1));
  sky.addColorStop(1, rgba(ctx.colors[3], 1));
  g.fillStyle = sky;
  g.fillRect(0, 0, w, h);
  g.fillStyle = rgba(ctx.colors[4], 0.9);
  g.beginPath();
  g.arc(w * 0.5, h * 0.42, Math.min(w, h) * 0.22, 0, TAU);
  g.fill();
  g.fillStyle = rgba(ctx.colors[0], 0.55);
  for (let line = 0; line < 3; line += 1) g.fillRect(w * (0.3 + line * 0.04), h * (0.74 + line * 0.07), w * (0.4 - line * 0.08), h * 0.035);
}

// A rounded polygon whose corners soften into a circle as it opens.
function shape(g, cx, cy, radius, corners, roundness, turn) {
  g.beginPath();
  const steps = 96;
  for (let step = 0; step <= steps; step += 1) {
    const a = (step / steps) * TAU + turn;
    const polygon = Math.cos(Math.PI / corners) / Math.cos(((a % (TAU / corners)) + TAU / corners) % (TAU / corners) - Math.PI / corners);
    const r = radius * (polygon * (1 - roundness) + roundness);
    const x = cx + Math.cos(a) * r;
    const y = cy + Math.sin(a) * r;
    if (step) g.lineTo(x, y);
    else g.moveTo(x, y);
  }
  g.closePath();
}

export default defineMotion({
  id: 'transitions-mask-reveal',
  number: 113,
  module: 'transitions',
  name: { en: 'Cinematic Mask Reveal', ar: 'الكشف السينمائي بالقناع' },
  summary: {
    en: 'A dark dashboard gives way to a bright hero page through a turning, many-sided aperture that opens from the centre. Its corners soften into a circle as it grows, a bright ring rides its edge and a second ring follows a beat later.',
    ar: 'لوحةُ متابعةٍ داكنة تفسح المجال لصفحةٍ رئيسية مشرقة عبر فتحةٍ متعدّدة الأضلاع تدور وتنفتح من المركز. تلين زواياها حتى تصير دائرة وهي تكبر، وحلقةٌ مضيئة تركب حافّتها وتتبعها حلقةٌ ثانية بعد لحظة.',
  },
  meaning: {
    en: 'Moving from the operations dashboard to a citizen-facing service page in one continuous step.',
    ar: 'الانتقال من لوحة متابعة العمليات إلى صفحة خدمةٍ موجّهة للمستفيد في خطوةٍ واحدة متصلة.',
  },
  engine: 'canvas2d',
  kind: 'oneshot',
  duration: 2600,
  easing: 'ease-in-out',
  colors: ['#0b1020', '#6366f1', '#f472b6', '#fb923c', '#fff7ed'],
  params: {
    corners: { default: 6, min: 3, max: 10, step: 1, label: { en: 'Aperture sides', ar: 'أضلاع الفتحة' } },
    turn: { default: 0.5, min: 0, max: 1.5, step: 0.05, label: { en: 'Turn while opening', ar: 'الدوران أثناء الانفتاح' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'none', cost: 'low' },
  still: 1,
  tags: ['transition', 'page', 'reveal', 'mask', 'iris'],
  setup: canvas2d({
    draw(g, s, ctx) {
      const { width: w, height: h } = ctx;
      const p = s.progress;
      const reach = Math.hypot(w, h) * 0.62;
      const radius = reach * p;
      const roundness = smoothstep(0.2, 0.9, p);
      const corners = Math.round(ctx.params.corners);
      const turn = p * ctx.params.turn * TAU * 0.5;
      pageA(g, ctx);
      // The outgoing page darkens and recedes slightly as the aperture opens.
      g.fillStyle = rgba(ctx.colors[0], 0.5 * p);
      g.fillRect(0, 0, w, h);
      if (radius > 0.5) {
        g.save();
        shape(g, w / 2, h / 2, radius, corners, roundness, turn);
        g.clip();
        const zoom = 1.15 - 0.15 * p;
        g.translate(w / 2, h / 2);
        g.scale(zoom, zoom);
        g.translate(-w / 2, -h / 2);
        pageB(g, ctx);
        g.restore();
        g.strokeStyle = rgba(ctx.colors[4], 0.9 * (1 - smoothstep(0.85, 1, p)));
        g.lineWidth = 2.5;
        shape(g, w / 2, h / 2, radius, corners, roundness, turn);
        g.stroke();
        const trailing = reach * Math.max(0, p - 0.12);
        if (trailing > 0.5) {
          g.strokeStyle = rgba(ctx.colors[3], 0.6 * (1 - p));
          g.lineWidth = 1.5;
          shape(g, w / 2, h / 2, trailing, corners, roundness, turn * 0.8);
          g.stroke();
        }
      }
    },
  }),
});
