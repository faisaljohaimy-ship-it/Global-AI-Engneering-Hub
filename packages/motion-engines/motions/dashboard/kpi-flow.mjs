import { defineMotion } from '../../core/define.mjs';
import { canvas2d } from '../../engines/canvas2d.mjs';
import { mixColour, rgba } from '../../core/util.mjs';
import { font } from '../../core/text.mjs';

const KEYS = ['first', 'second', 'third'];

// Each indicator is a smooth function of time, so any moment shows consistent numbers.
function valueAt(index, t) {
  const base = [48200, 99.2, 1320][index];
  const swing = [3600, 0.6, 180][index];
  return base + swing * (0.6 * Math.sin(t * (0.7 + index * 0.3) + index) + 0.4 * Math.sin(t * (1.9 + index * 0.5) + index * 2));
}

export default defineMotion({
  id: 'dashboard-kpi-flow',
  number: 101,
  module: 'dashboard',
  name: { en: 'Real-time KPI Flow', ar: 'تدفّق مؤشرات الأداء اللحظي' },
  summary: {
    en: 'Three indicator cards update live: each number rolls to its new value, a sparkline of the last moments scrolls beneath it, and an arrow and colour show whether it is rising or falling. Labels and digits follow the reader’s language and direction.',
    ar: 'ثلاث بطاقات مؤشرات تتحدّث لحظيًّا: يتدحرج كلّ رقمٍ إلى قيمته الجديدة، ويمرّ تحته خطٌّ بيانيّ صغير للّحظات الأخيرة، ويبيّن سهمٌ ولونٌ هل يرتفع أم ينخفض. وتتبع العناوين والأرقام لغة القارئ واتجاهه.',
  },
  meaning: {
    en: 'The KPI counters of a digital service update in real time, each with its recent trend.',
    ar: 'عدّادات مؤشرات الأداء لخدمةٍ رقمية تتحدّث لحظيًّا، ولكلٍّ منها اتجاهه الأخير.',
  },
  engine: 'canvas2d',
  kind: 'loop',
  duration: 8000,
  easing: 'ease-out',
  colors: ['#0b1020', '#22c55e', '#f43f5e', '#38bdf8', '#e2e8f0'],
  params: {
    history: { default: 6, min: 2, max: 12, step: 0.5, label: { en: 'Seconds of history in the sparkline', ar: 'ثوانٍ من التاريخ في الخط الصغير' } },
    pace: { default: 1, min: 0.3, max: 3, step: 0.1, label: { en: 'Pace of change', ar: 'وتيرة التغيّر' } },
  },
  text: {
    en: { first: 'Revenue', second: 'Uptime', third: 'Orders' },
    ar: { first: 'الإيرادات', second: 'التوافر', third: 'الطلبات' },
  },
  rtl: 'text',
  requirements: { gpu: 'none', cost: 'low' },
  still: 0.4,
  tags: ['dashboard', 'kpi', 'numbers', 'live', 'cards', 'analytics'],
  setup: canvas2d({
    init: (ctx) => ({
      formats: [
        new Intl.NumberFormat(ctx.locale, { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }),
        new Intl.NumberFormat(ctx.locale, { style: 'percent', minimumFractionDigits: 2, maximumFractionDigits: 2 }),
        new Intl.NumberFormat(ctx.locale, { maximumFractionDigits: 0 }),
      ],
    }),
    draw(g, s, ctx, { formats }) {
      const { width: w, height: h } = ctx;
      const tall = h > w;
      const gap = Math.min(w, h) * 0.04;
      const cardW = tall ? w - gap * 2 : (w - gap * 4) / 3;
      const cardH = tall ? (h - gap * 4) / 3 : h * 0.72;
      const t = s.t * ctx.params.pace;
      g.direction = ctx.rtl ? 'rtl' : 'ltr';
      KEYS.forEach((key, index) => {
        // Cards are laid out in reading order.
        const slot = ctx.rtl ? 2 - index : index;
        const x = tall ? gap : gap + slot * (cardW + gap);
        const y = tall ? gap + index * (cardH + gap) : (h - cardH) / 2;
        const rise = 1 - (1 - s.intro) * (1 + index * 0.4);
        g.globalAlpha = Math.max(0, Math.min(1, rise));
        g.fillStyle = rgba(mixColour(ctx.colors[0], ctx.colors[4], 0.07), 1);
        g.beginPath();
        g.roundRect(x, y + (1 - g.globalAlpha) * cardH * 0.2, cardW, cardH, Math.min(cardW, cardH) * 0.08);
        g.fill();
        const pad = Math.min(cardW, cardH) * 0.1;
        const start = ctx.rtl ? x + cardW - pad : x + pad;
        g.textAlign = 'start';
        g.textBaseline = 'top';
        g.fillStyle = rgba(ctx.colors[4], 0.7);
        g.font = font(Math.max(8, Math.min(cardH * 0.13, cardW * 0.1)), 500);
        g.fillText(ctx.text[key], start, y + pad);
        const value = valueAt(index, t);
        const before = valueAt(index, t - 0.4);
        const up = value >= before;
        const shown = index === 1 ? value / 100 : value;
        g.font = font(Math.max(10, Math.min(cardH * 0.24, cardW * 0.15)), 700);
        g.fillStyle = rgba(ctx.colors[4], 1);
        g.fillText(formats[index].format(shown), start, y + pad + cardH * 0.17);
        // Trend arrow.
        const arrowX = ctx.rtl ? x + pad * 1.2 : x + cardW - pad * 1.2;
        const arrowY = y + pad * 1.5;
        g.fillStyle = rgba(up ? ctx.colors[1] : ctx.colors[2], 1);
        g.beginPath();
        const size = pad * 0.6;
        g.moveTo(arrowX, arrowY + (up ? -size : size));
        g.lineTo(arrowX + size, arrowY + (up ? size : -size) * 0.6);
        g.lineTo(arrowX - size, arrowY + (up ? size : -size) * 0.6);
        g.closePath();
        g.fill();
        // Sparkline of the last seconds, oldest at the reading-start side.
        const history = ctx.params.history;
        const samples = 40;
        const values = Array.from({ length: samples }, (_, n) => valueAt(index, t - history * (1 - n / (samples - 1))));
        const low = Math.min(...values);
        const high = Math.max(...values);
        const lineTop = y + cardH * 0.62;
        const lineBottom = y + cardH - pad;
        g.strokeStyle = rgba(index === 1 ? ctx.colors[3] : up ? ctx.colors[1] : ctx.colors[2], 0.9);
        g.lineWidth = 1.5;
        g.beginPath();
        values.forEach((v, n) => {
          const u = n / (samples - 1);
          const px = ctx.rtl ? x + cardW - pad - u * (cardW - pad * 2) : x + pad + u * (cardW - pad * 2);
          const py = lineBottom - ((v - low) / (high - low || 1)) * (lineBottom - lineTop);
          if (n) g.lineTo(px, py);
          else g.moveTo(px, py);
        });
        g.stroke();
      });
      g.globalAlpha = 1;
    },
  }),
});
