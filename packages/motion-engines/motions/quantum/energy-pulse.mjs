import { defineMotion } from '../../core/define.mjs';
import { dom, svg } from '../../engines/dom.mjs';

export default defineMotion({
  id: 'quantum-energy-pulse',
  number: 10,
  module: 'quantum',
  name: { en: 'Quantum Energy Pulse', ar: 'نبضة الطاقة الكمّية' },
  summary: {
    en: 'A core emits rings that widen and fade in turn while a crown of spikes breathes around it. Vector graphics, sharp at any size.',
    ar: 'نواة تُطلق حلقات تتّسع وتخفت تباعًا بينما يتنفّس حولها تاج من الأشواك. رسم متّجهي حادّ بأي حجم.',
  },
  engine: 'svg',
  kind: 'loop',
  duration: 2400,
  easing: 'ease-out',
  colors: ['#05060f', '#22d3ee', '#facc15'],
  params: {
    rings: { default: 4, min: 2, max: 7, step: 1, label: { en: 'Rings', ar: 'عدد الحلقات' } },
    spikes: { default: 12, min: 0, max: 24, step: 1, label: { en: 'Spikes', ar: 'عدد الأشواك' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'none', cost: 'low' },
  still: 0.4,
  tags: ['indicator', 'status', 'loading', 'accent'],
  setup: dom({
    build(root, ctx) {
      const document = root.ownerDocument;
      const view = svg(document, 'svg', { viewBox: '-100 -100 200 200', width: '100%', height: '100%', 'aria-hidden': 'true' });
      const rings = Array.from({ length: Math.round(ctx.params.rings) }, () => view.appendChild(svg(document, 'circle', { fill: 'none', stroke: ctx.css[1] })));
      const spikes = Array.from({ length: Math.round(ctx.params.spikes) }, () => view.appendChild(svg(document, 'line', { stroke: ctx.css[2], 'stroke-linecap': 'round', 'stroke-width': 1.5 })));
      const core = view.appendChild(svg(document, 'circle', { fill: ctx.css[2] }));
      root.append(view);
      return { rings, spikes, core };
    },
    apply({ rings, spikes, core }, s) {
      rings.forEach((ring, index) => {
        const phase = (s.raw + index / rings.length) % 1;
        ring.setAttribute('r', (8 + phase * 86).toFixed(2));
        ring.setAttribute('stroke-width', (3 * (1 - phase) + 0.4).toFixed(2));
        ring.setAttribute('opacity', ((1 - phase) ** 2 * s.intro).toFixed(3));
      });
      const beat = Math.sin(s.raw * Math.PI * 2) * 0.5 + 0.5;
      spikes.forEach((spike, index) => {
        const angle = (index / spikes.length) * Math.PI * 2;
        const reach = 16 + (index % 2 ? 10 : 4) * beat + 6;
        spike.setAttribute('x1', (Math.cos(angle) * 12).toFixed(2));
        spike.setAttribute('y1', (Math.sin(angle) * 12).toFixed(2));
        spike.setAttribute('x2', (Math.cos(angle) * reach).toFixed(2));
        spike.setAttribute('y2', (Math.sin(angle) * reach).toFixed(2));
        spike.setAttribute('opacity', (0.35 + 0.65 * beat * s.intro).toFixed(3));
      });
      core.setAttribute('r', (6 + 3 * beat * s.intro).toFixed(2));
    },
  }),
});
