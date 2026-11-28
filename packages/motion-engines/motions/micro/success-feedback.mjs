import { defineMotion } from '../../core/define.mjs';
import { dom, svg } from '../../engines/dom.mjs';
import { clamp, lerp, stage } from '../../core/util.mjs';
import { spring } from '../../core/spring.mjs';

export default defineMotion({
  id: 'micro-success-feedback',
  number: 100,
  module: 'micro',
  name: { en: 'Context-aware Success Feedback', ar: 'تأكيد النجاح بحسب السياق' },
  summary: {
    en: 'A completed transaction answers with a receipt: the paper slip rolls out line by line, a reference barcode prints at its foot, and a round approval stamp lands on it with a spring, drawing its tick as a ring of light spreads from the impact. Vector graphics, sharp at any size.',
    ar: 'معاملةٌ مكتملة تجيب بإيصال: تخرج القسيمة سطرًا بعد سطر، ويُطبع في أسفلها رمزٌ شريطي مرجعي، ثم يهبط عليها ختم موافقةٍ دائري بارتدادٍ نابضي ويرسم علامة الصح بينما تنتشر حلقةٌ من الضوء من موضع الختم. رسمٌ متّجهي حادّ بأي حجم.',
  },
  meaning: {
    en: 'Audit trail: a completed digital transaction issues a receipt with a reference code and an approval stamp.',
    ar: 'سجلّ التدقيق: معاملةٌ رقمية مكتملة تُصدر إيصالًا برقمٍ مرجعي وختم اعتماد.',
  },
  engine: 'svg',
  kind: 'oneshot',
  duration: 3000,
  easing: 'ease-out',
  colors: ['#0b1220', '#f8fafc', '#22c55e', '#64748b'],
  params: {
    lines: { default: 5, min: 2, max: 8, step: 1, label: { en: 'Receipt lines', ar: 'أسطر الإيصال' } },
    bounce: { default: 0.45, min: 0.15, max: 1, step: 0.05, label: { en: 'Stamp spring damping', ar: 'تخميد نابض الختم' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'none', cost: 'low' },
  still: 1,
  tags: ['feedback', 'success', 'receipt', 'payment', 'confirmation', 'audit'],
  setup: dom({
    build(root, ctx) {
      const document = root.ownerDocument;
      const view = svg(document, 'svg', { viewBox: '-100 -60 200 120', width: '100%', height: '100%', preserveAspectRatio: 'xMidYMid meet', 'aria-hidden': 'true' });
      const slip = svg(document, 'g');
      const paper = slip.appendChild(svg(document, 'path', { fill: ctx.css[1] }));
      const rows = Array.from({ length: Math.round(ctx.params.lines) }, (_, index) => slip.appendChild(svg(document, 'rect', { x: -30, height: 3, rx: 1.5, fill: ctx.css[3], width: index % 3 === 0 ? 44 : index % 3 === 1 ? 52 : 36 })));
      const barcode = Array.from({ length: 22 }, (_, index) => slip.appendChild(svg(document, 'rect', { x: -28 + index * 2.6, width: (index * 7) % 3 === 0 ? 1.6 : 0.8, height: 9, fill: ctx.css[0] })));
      view.append(slip);
      const ring = view.appendChild(svg(document, 'circle', { fill: 'none', stroke: ctx.css[2], 'stroke-width': 1.5 }));
      const stamp = view.appendChild(svg(document, 'g'));
      stamp.appendChild(svg(document, 'circle', { r: 17, fill: 'none', stroke: ctx.css[2], 'stroke-width': 3 }));
      stamp.appendChild(svg(document, 'circle', { r: 13, fill: 'none', stroke: ctx.css[2], 'stroke-width': 0.8, 'stroke-dasharray': '2 2' }));
      const tick = stamp.appendChild(svg(document, 'path', { d: 'M -8 0 L -2 6 L 9 -6', fill: 'none', stroke: ctx.css[2], 'stroke-width': 3.2, 'stroke-linecap': 'round', 'stroke-linejoin': 'round', pathLength: 1, 'stroke-dasharray': '1 1' }));
      root.append(view);
      return { paper, rows, barcode, ring, stamp, tick };
    },
    apply(refs, s, ctx) {
      const roll = stage(s.progress, 0, 0.5);
      const height = 96 * roll;
      // The slip with a torn, zigzag foot.
      const foot = -50 + height;
      let d = `M -40 -50 L 40 -50 L 40 ${foot.toFixed(2)}`;
      for (let step = 0; step < 16; step += 1) d += ` L ${(40 - (step + 0.5) * 5).toFixed(2)} ${(foot - (step % 2 ? 0 : 2.5)).toFixed(2)}`;
      d += ` L -40 ${foot.toFixed(2)} Z`;
      refs.paper.setAttribute('d', d);
      refs.rows.forEach((row, index) => {
        const y = -40 + index * (52 / refs.rows.length);
        row.setAttribute('y', y.toFixed(2));
        row.setAttribute('opacity', clamp((foot - y) / 8).toFixed(3));
      });
      const printed = stage(s.progress, 0.38, 0.55);
      refs.barcode.forEach((bar, index) => {
        bar.setAttribute('y', '30');
        bar.setAttribute('opacity', (printed > index / refs.barcode.length && foot > 40 ? 1 : 0).toString());
      });
      // The stamp falls from above and settles on a spring.
      const since = Math.max(0, s.progress - 0.55) * 3;
      const land = s.progress < 0.55 ? 0 : spring(since, { frequency: 2.4, damping: ctx.params.bounce });
      const scale = lerp(2.6, 1, land);
      refs.stamp.setAttribute('transform', `translate(18 8) rotate(-14) scale(${scale.toFixed(4)})`);
      refs.stamp.setAttribute('opacity', (s.progress < 0.55 ? 0 : clamp(since * 4)).toFixed(3));
      refs.tick.setAttribute('stroke-dashoffset', (1 - stage(s.progress, 0.7, 0.9)).toFixed(4));
      const spread = stage(s.progress, 0.62, 1);
      refs.ring.setAttribute('cx', '18');
      refs.ring.setAttribute('cy', '8');
      refs.ring.setAttribute('r', (17 + spread * 40).toFixed(2));
      refs.ring.setAttribute('opacity', (spread > 0 ? (1 - spread) * 0.8 : 0).toFixed(3));
    },
  }),
});
