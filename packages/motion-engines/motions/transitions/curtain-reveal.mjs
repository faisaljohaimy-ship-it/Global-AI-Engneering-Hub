import { defineMotion } from '../../core/define.mjs';
import { canvas2d } from '../../engines/canvas2d.mjs';
import { TAU, clamp, mixColour, rgba, smoothstep } from '../../core/util.mjs';

// One curtain: vertical folds whose number stays fixed, so they bunch up as the curtain is drawn back.
function curtain(g, ctx, side, open, folds) {
  const { width: w, height: h } = ctx;
  const half = w / 2;
  const covered = half * (1 - open * 0.86);
  const edge = side < 0 ? covered : w - covered;
  const steps = 48;
  g.beginPath();
  g.moveTo(side < 0 ? 0 : w, 0);
  for (let step = 0; step <= steps; step += 1) {
    const y = (h * step) / steps;
    // The hem is gathered toward the side: the bottom of the edge swings out more than the top.
    const swag = open * half * 0.12 * Math.sin((Math.PI * step) / steps) * (step / steps);
    g.lineTo(edge - side * swag, y);
  }
  g.lineTo(side < 0 ? 0 : w, h);
  g.closePath();
  const left = side < 0 ? 0 : edge;
  const right = side < 0 ? edge : w;
  const shade = g.createLinearGradient(left, 0, right, 0);
  for (let fold = 0; fold <= folds * 2; fold += 1) {
    const light = fold % 2 ? 0.25 : 1;
    shade.addColorStop(fold / (folds * 2), rgba(mixColour(ctx.colors[0], ctx.colors[1], 0.35 + 0.65 * light), 1));
  }
  g.fillStyle = shade;
  g.fill();
  g.strokeStyle = rgba(ctx.colors[2], 0.6);
  g.lineWidth = 1.5;
  g.stroke();
}

// The stage behind: a spotlit floor and, on it, the new service's app screen.
function stage(g, ctx, open) {
  const { width: w, height: h } = ctx;
  g.fillStyle = rgba(mixColour(ctx.colors[0], ctx.colors[3], 0.15), 1);
  g.fillRect(0, 0, w, h);
  const light = g.createRadialGradient(w / 2, h * 0.75, 0, w / 2, h * 0.75, h * 0.8);
  light.addColorStop(0, rgba(ctx.colors[3], 0.25 + 0.45 * open));
  light.addColorStop(1, rgba(ctx.colors[3], 0));
  g.fillStyle = light;
  g.fillRect(0, 0, w, h);
  // A phone standing on the stage, its screen showing the service: a header, a progress ring and two cards.
  const tall = h * 0.66;
  const wide = tall * 0.5;
  const x = w / 2 - wide / 2;
  const y = h * 0.17;
  g.fillStyle = rgba(mixColour(ctx.colors[0], ctx.colors[2], 0.25), 1);
  g.beginPath();
  g.roundRect(x, y, wide, tall, wide * 0.14);
  g.fill();
  g.strokeStyle = rgba(ctx.colors[2], 0.9);
  g.lineWidth = 2;
  g.stroke();
  const pad = wide * 0.1;
  g.fillStyle = rgba(ctx.colors[2], 0.9);
  g.fillRect(x + pad, y + pad * 1.4, wide - pad * 2, tall * 0.06);
  g.strokeStyle = rgba(ctx.colors[3], 0.95);
  g.lineWidth = Math.max(2, wide * 0.06);
  g.beginPath();
  g.arc(w / 2, y + tall * 0.38, wide * 0.2, -Math.PI / 2, -Math.PI / 2 + TAU * (0.25 + 0.6 * open));
  g.stroke();
  g.fillStyle = rgba(ctx.colors[3], 0.35);
  for (let card = 0; card < 2; card += 1) {
    g.beginPath();
    g.roundRect(x + pad, y + tall * (0.62 + card * 0.16), wide - pad * 2, tall * 0.11, 3);
    g.fill();
  }
}

export default defineMotion({
  id: 'transitions-curtain-reveal',
  number: 118,
  module: 'transitions',
  name: { en: 'Interactive Curtain Reveal', ar: 'الكشف التفاعلي بالستارة' },
  summary: {
    en: 'Two heavy stage curtains part from the middle, their folds bunching as they are drawn aside and their hems swinging out, to reveal a lit stage with the new service on a phone screen, its progress ring filling as the curtains open. Dragging sideways opens them by hand: the further from the centre, the wider the opening.',
    ar: 'ستارتا مسرحٍ ثقيلتان تنفرجان من الوسط، تتجمّع طيّاتهما وهما تُسحبان جانبًا وتتأرجح أطرافهما السفلى، لتكشفا مسرحًا مضاءً عليه الخدمة الجديدة على شاشة هاتف، وحلقة التقدّم فيها تمتلئ مع انفتاح الستارتين. السحب جانبًا يفتحهما باليد: كلما ابتعد المؤشر عن المركز اتّسعت الفتحة.',
  },
  meaning: {
    en: 'Launch day: a new digital service is unveiled and its app screen appears from behind the curtains.',
    ar: 'يوم الإطلاق: تُكشف خدمةٌ رقمية جديدة وتظهر شاشة تطبيقها من خلف الستار.',
  },
  engine: 'canvas2d',
  kind: 'oneshot',
  duration: 3000,
  easing: 'ease-in-out',
  colors: ['#12040a', '#b91c1c', '#fbbf24', '#fde68a'],
  params: {
    folds: { default: 7, min: 3, max: 14, step: 1, label: { en: 'Folds per curtain', ar: 'طيّات كل ستارة' } },
    gather: { default: 0.8, min: 0.4, max: 1, step: 0.05, label: { en: 'How far they open', ar: 'مدى الانفتاح' } },
  },
  interactive: {
    sample: { x: 0.95, y: 0.5, down: true },
    note: { en: 'Pointer x in 0..1 of the frame: the distance from the centre sets how far the curtains are open.', ar: 'موضع المؤشر x من 0 إلى 1 داخل الإطار: بُعده عن المركز يحدّد مقدار انفتاح الستارتين.' },
  },
  rtl: 'neutral',
  requirements: { gpu: 'none', cost: 'low' },
  still: 0.85,
  tags: ['transition', 'reveal', 'stage', 'launch', 'interaction'],
  setup: canvas2d({
    draw(g, s, ctx) {
      const open = ctx.input.live ? clamp(Math.abs(ctx.input.x - 0.5) * 2) : clamp(s.progress);
      const amount = open * ctx.params.gather;
      stage(g, ctx, amount);
      const folds = Math.round(ctx.params.folds);
      curtain(g, ctx, -1, amount, folds);
      curtain(g, ctx, 1, amount, folds);
      // The valance across the top.
      g.fillStyle = rgba(mixColour(ctx.colors[0], ctx.colors[1], 0.8), 1);
      g.fillRect(0, 0, ctx.width, ctx.height * 0.09);
      g.fillStyle = rgba(ctx.colors[2], 0.8);
      g.fillRect(0, ctx.height * 0.09, ctx.width, 2);
      g.fillStyle = rgba(ctx.colors[3], 0.15 * smoothstep(0.6, 1, open));
      g.fillRect(0, 0, ctx.width, ctx.height);
    },
  }),
});
