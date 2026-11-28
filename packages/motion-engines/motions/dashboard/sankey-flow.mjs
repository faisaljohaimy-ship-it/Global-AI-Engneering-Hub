import { defineMotion } from '../../core/define.mjs';
import { canvas2d } from '../../engines/canvas2d.mjs';
import { TAU, mixColour, rgba } from '../../core/util.mjs';

// Three columns of nodes and seeded flows between neighbouring columns. Every node's
// height is the larger of what flows into it and out of it, so the bands always fit.
function layoutOf(random) {
  const columns = [3, 3, 4];
  const flows = [];
  for (let c = 0; c < columns.length - 1; c += 1) {
    for (let a = 0; a < columns[c]; a += 1) {
      for (let b = 0; b < columns[c + 1]; b += 1) {
        if (random() < 0.62) flows.push({ from: [c, a], to: [c + 1, b], value: 0.4 + random() * 1.6, phase: random() });
      }
    }
  }
  const size = columns.map((count) => Array(count).fill(0));
  const inflow = columns.map((count) => Array(count).fill(0));
  for (const flow of flows) {
    size[flow.from[0]][flow.from[1]] += flow.value;
    inflow[flow.to[0]][flow.to[1]] += flow.value;
  }
  columns.forEach((count, c) => {
    for (let n = 0; n < count; n += 1) size[c][n] = Math.max(size[c][n], inflow[c][n], 0.3);
  });
  return { columns, flows, size };
}

export default defineMotion({
  id: 'dashboard-sankey-flow',
  number: 106,
  module: 'dashboard',
  name: { en: 'Interactive Sankey Flow', ar: 'مخطّط سانكي التفاعلي' },
  summary: {
    en: 'Sources on one side feed stages in the middle and outcomes on the other, along bands as wide as the amount they carry. Light runs along every band in the reading direction, and one flow at a time is picked out while the rest dim; pointing at a band picks it.',
    ar: 'مصادر على جانبٍ تغذّي مراحل في الوسط ونتائج على الجانب الآخر، عبر أشرطةٍ بعرض الكمية التي تحملها. يجري الضوء على كلّ شريطٍ باتجاه القراءة، ويُبرز تدفّقٌ واحد في كلّ مرة بينما يخفت الباقي؛ والإشارة إلى شريطٍ تُبرزه.',
  },
  meaning: {
    en: 'A data pipeline (ETL): records flow from source systems through processing stages into outcomes, in proportion to their volume.',
    ar: 'خطّ معالجة البيانات (ETL): تتدفّق السجلات من الأنظمة المصدر عبر مراحل المعالجة إلى المخرجات بنسبة حجمها.',
  },
  engine: 'canvas2d',
  kind: 'loop',
  duration: 9000,
  easing: 'ease-out',
  colors: ['#0a0f1c', '#38bdf8', '#f472b6', '#facc15', '#e2e8f0'],
  params: {
    curve: { default: 0.5, min: 0.1, max: 0.9, step: 0.05, label: { en: 'Band curvature', ar: 'انحناء الأشرطة' } },
    pulses: { default: 3, min: 1, max: 8, step: 1, label: { en: 'Pulses per band', ar: 'النبضات على كل شريط' } },
  },
  interactive: {
    sample: { x: 0.3, y: 0.3 },
    note: { en: 'Pointer x, y in 0..1 of the frame: the flow under the pointer is highlighted.', ar: 'موضع المؤشر x و y من 0 إلى 1 داخل الإطار: يُبرز التدفّق الذي تحت المؤشر.' },
  },
  rtl: 'mirror',
  requirements: { gpu: 'none', cost: 'low' },
  still: 0.2,
  tags: ['dashboard', 'chart', 'flow', 'sankey', 'data', 'analytics'],
  setup: canvas2d({
    init: (ctx) => layoutOf(ctx.random(106)),
    draw(g, s, ctx, layout) {
      const { width: w, height: h } = ctx;
      // Flows run in the reading direction: under right-to-left the chart is mirrored.
      if (ctx.rtl) {
        g.translate(w, 0);
        g.scale(-1, 1);
      }
      const { columns, flows, size } = layout;
      const top = h * 0.1;
      const usable = h * 0.8;
      const gap = h * 0.04;
      const node = w * 0.025;
      const xs = columns.map((_, c) => w * (0.1 + c * 0.38));
      const totals = size.map((list) => list.reduce((sum, value) => sum + value, 0));
      const scale = Math.min(...totals.map((total, c) => (usable - gap * (columns[c] - 1)) / total));
      const nodeTop = size.map((list, c) => {
        let y = top + (usable - (totals[c] * scale + gap * (columns[c] - 1))) / 2;
        return list.map((value) => {
          const at = y;
          y += value * scale + gap;
          return at;
        });
      });
      const outCursor = nodeTop.map((list) => list.slice());
      const inCursor = nodeTop.map((list) => list.slice());
      // The highlighted flow: picked by the pointer when live, otherwise one after another.
      let chosen = Math.floor(s.raw * flows.length) % flows.length;
      const bands = flows.map((flow) => {
        const thick = flow.value * scale;
        const y0 = outCursor[flow.from[0]][flow.from[1]];
        const y1 = inCursor[flow.to[0]][flow.to[1]];
        outCursor[flow.from[0]][flow.from[1]] += thick;
        inCursor[flow.to[0]][flow.to[1]] += thick;
        return { flow, thick, x0: xs[flow.from[0]] + node, x1: xs[flow.to[0]], y0, y1 };
      });
      if (ctx.input.live) {
        const px = ctx.rtl ? (1 - ctx.input.x) * w : ctx.input.x * w;
        const py = ctx.input.y * h;
        let best = Infinity;
        bands.forEach((band, index) => {
          if (px < band.x0 || px > band.x1) return;
          const u = (px - band.x0) / (band.x1 - band.x0);
          const e = u * u * (3 - 2 * u);
          const centre = band.y0 + (band.y1 - band.y0) * e + band.thick / 2;
          const miss = Math.abs(py - centre);
          if (miss < best) {
            best = miss;
            chosen = index;
          }
        });
      }
      const pulses = Math.round(ctx.params.pulses);
      const bend = ctx.params.curve;
      bands.forEach((band, index) => {
        const { x0, x1, y0, y1, thick } = band;
        const mid = (x1 - x0) * bend;
        const lit = index === chosen;
        const colour = mixColour(ctx.colors[1], ctx.colors[2], band.flow.from[0] * 0.5 + band.flow.from[1] * 0.15);
        g.fillStyle = rgba(colour, (lit ? 0.75 : 0.22) * s.intro);
        g.beginPath();
        g.moveTo(x0, y0);
        g.bezierCurveTo(x0 + mid, y0, x1 - mid, y1, x1, y1);
        g.lineTo(x1, y1 + thick);
        g.bezierCurveTo(x1 - mid, y1 + thick, x0 + mid, y0 + thick, x0, y0 + thick);
        g.closePath();
        g.fill();
        // Light moving along the centre of the band, from source to target.
        for (let pulse = 0; pulse < pulses; pulse += 1) {
          const u = (s.t * 0.25 + band.flow.phase + pulse / pulses) % 1;
          const e = 3 * (1 - u) * (1 - u) * u;
          const f = 3 * (1 - u) * u * u;
          const x = (1 - u) ** 3 * x0 + e * (x0 + mid) + f * (x1 - mid) + u ** 3 * x1;
          const y = (1 - u) ** 3 * y0 + e * y0 + f * y1 + u ** 3 * y1 + thick / 2;
          g.fillStyle = rgba(lit ? ctx.colors[3] : ctx.colors[4], (lit ? 0.95 : 0.5) * s.intro);
          g.beginPath();
          g.arc(x, y, Math.max(1, Math.min(thick * 0.3, 3)), 0, TAU);
          g.fill();
        }
      });
      size.forEach((list, c) => list.forEach((value, n) => {
        g.fillStyle = rgba(c === 0 ? ctx.colors[1] : c === 1 ? ctx.colors[4] : ctx.colors[2], 0.95);
        g.fillRect(xs[c], nodeTop[c][n], node, value * scale);
      }));
    },
  }),
});
