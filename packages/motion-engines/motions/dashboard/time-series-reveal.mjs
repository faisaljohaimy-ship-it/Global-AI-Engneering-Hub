import { defineMotion } from '../../core/define.mjs';
import { canvas2d } from '../../engines/canvas2d.mjs';
import { TAU, clamp, rgba } from '../../core/util.mjs';
import { font } from '../../core/text.mjs';

// Two seeded series, smooth enough to read as real measurements.
function seriesOf(random, points) {
  const make = (start, drift) => {
    let value = start;
    return Array.from({ length: points }, () => {
      value = clamp(value + (random() - 0.5 + drift) * 0.16, 0.08, 0.95);
      return value;
    });
  };
  return [make(0.3, 0.06), make(0.55, -0.02)];
}

export default defineMotion({
  id: 'dashboard-time-series-reveal',
  number: 108,
  module: 'dashboard',
  name: { en: 'Time-series Progressive Reveal', ar: 'الكشف التدريجي للسلاسل الزمنية' },
  summary: {
    en: 'A line chart draws itself along the time axis, in the reading direction: the main series leads with a shaded area under it, a comparison series follows a beat behind, and a cursor with a value badge rides the leading point.',
    ar: 'رسمٌ بيانيّ خطّي يرسم نفسه على محور الزمن باتجاه القراءة: تتقدّم السلسلة الرئيسية ومساحةٌ مظلّلة تحتها، وتتبعها سلسلة المقارنة بفارقٍ بسيط، ومؤشّرٌ مع شارة القيمة يرافق النقطة المتقدّمة.',
  },
  meaning: {
    en: 'A live operations metric is plotted against a comparison period and read point by point as the data arrives.',
    ar: 'مؤشرٌ تشغيلي حيّ يُرسم مقابل فترة المقارنة، ويُقرأ نقطةً نقطة مع وصول البيانات.',
  },
  engine: 'canvas2d',
  kind: 'oneshot',
  duration: 3600,
  easing: 'ease-in-out',
  colors: ['#0b1220', '#22d3ee', '#a78bfa', '#94a3b8', '#f8fafc'],
  params: {
    points: { default: 28, min: 8, max: 60, step: 1, label: { en: 'Data points', ar: 'عدد نقاط البيانات' } },
    smoothing: { default: 0.5, min: 0, max: 1, step: 0.05, label: { en: 'Line smoothing', ar: 'تنعيم الخط' } },
  },
  rtl: 'mirror',
  requirements: { gpu: 'none', cost: 'low' },
  still: 1,
  tags: ['dashboard', 'chart', 'data', 'line', 'analytics', 'reveal'],
  setup: canvas2d({
    init: (ctx) => ({ series: seriesOf(ctx.random(108), Math.round(ctx.params.points)), format: new Intl.NumberFormat(ctx.locale, { maximumFractionDigits: 0 }) }),
    draw(g, s, ctx, { series, format }) {
      const { width: w, height: h } = ctx;
      const left = w * 0.08;
      const right = w * 0.94;
      const top = h * 0.14;
      const bottom = h * 0.84;
      // Time runs in the reading direction: u = 0 is where reading starts.
      const X = (u) => (ctx.rtl ? right - u * (right - left) : left + u * (right - left));
      const Y = (v) => bottom - v * (bottom - top);
      g.strokeStyle = rgba(ctx.colors[3], 0.18);
      g.lineWidth = 1;
      for (let line = 0; line <= 4; line += 1) {
        g.beginPath();
        g.moveTo(left, Y(line / 4));
        g.lineTo(right, Y(line / 4));
        g.stroke();
      }
      g.strokeStyle = rgba(ctx.colors[3], 0.6);
      g.beginPath();
      g.moveTo(left, bottom);
      g.lineTo(right, bottom);
      g.stroke();
      const count = series[0].length;
      for (let tick = 0; tick < count; tick += Math.max(1, Math.round(count / 8))) {
        g.fillRect(X(tick / (count - 1)) - 0.5, bottom, 1, 4);
      }
      const trace = (values, reach, close) => {
        const last = reach * (count - 1);
        const pts = [];
        for (let index = 0; index <= Math.floor(last); index += 1) pts.push([index, values[index]]);
        if (last % 1 > 0) {
          const i = Math.floor(last);
          pts.push([last, values[i] + (values[i + 1] - values[i]) * (last - i)]);
        }
        if (pts.length < 2) return null;
        g.beginPath();
        pts.forEach(([i, v], n) => {
          const x = X(i / (count - 1));
          const y = Y(v);
          if (!n) g.moveTo(x, y);
          else {
            const [pi, pv] = pts[n - 1];
            const px = X(pi / (count - 1));
            const py = Y(pv);
            const k = ctx.params.smoothing * 0.5;
            g.bezierCurveTo(px + (x - px) * k, py, x - (x - px) * k, y, x, y);
          }
        });
        if (close) {
          g.lineTo(X(pts.at(-1)[0] / (count - 1)), bottom);
          g.lineTo(X(0), bottom);
          g.closePath();
        }
        return pts.at(-1);
      };
      const lead = clamp(s.progress);
      const follow = clamp(s.progress * 1.12 - 0.12);
      if (trace(series[0], lead, true)) {
        const area = g.createLinearGradient(0, top, 0, bottom);
        area.addColorStop(0, rgba(ctx.colors[1], 0.35));
        area.addColorStop(1, rgba(ctx.colors[1], 0));
        g.fillStyle = area;
        g.fill();
      }
      g.lineWidth = 1.5;
      g.strokeStyle = rgba(ctx.colors[2], 0.85);
      g.setLineDash([4, 3]);
      if (trace(series[1], follow, false)) g.stroke();
      g.setLineDash([]);
      g.lineWidth = 2.2;
      g.strokeStyle = rgba(ctx.colors[1], 1);
      const tip = trace(series[0], lead, false);
      if (tip) {
        g.stroke();
        const x = X(tip[0] / (count - 1));
        const y = Y(tip[1]);
        g.strokeStyle = rgba(ctx.colors[4], 0.35);
        g.lineWidth = 1;
        g.beginPath();
        g.moveTo(x, top);
        g.lineTo(x, bottom);
        g.stroke();
        g.fillStyle = rgba(ctx.colors[4], 1);
        g.beginPath();
        g.arc(x, y, 3.5, 0, TAU);
        g.fill();
        // The value badge, kept inside the plot.
        const size = Math.max(9, h * 0.065);
        g.font = font(size, 650);
        const label = format.format(Math.round(tip[1] * 1000));
        const width = g.measureText(label).width + size;
        const bx = clamp(x - width / 2, left, right - width);
        const by = Math.max(top - size * 0.6, y - size * 2.4);
        g.fillStyle = rgba(ctx.colors[1], 0.95);
        g.beginPath();
        g.roundRect(bx, by, width, size * 1.6, size * 0.5);
        g.fill();
        g.fillStyle = rgba(ctx.colors[0], 1);
        g.textAlign = 'center';
        g.textBaseline = 'middle';
        g.fillText(label, bx + width / 2, by + size * 0.82);
      }
    },
  }),
});
