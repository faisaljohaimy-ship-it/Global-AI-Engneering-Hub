import { defineMotion } from '../../core/define.mjs';
import { canvas2d } from '../../engines/canvas2d.mjs';
import { TAU, rgba } from '../../core/util.mjs';

export default defineMotion({
  id: 'quantum-particle-entanglement',
  number: 3,
  module: 'quantum',
  name: { en: 'Quantum Particle Entanglement Visualization', ar: 'تصوير التشابك الكمّي للجسيمات' },
  summary: {
    en: 'Pairs of particles orbit on opposite sides of the centre; when one flips state its partner flips in the same instant.',
    ar: 'أزواج من الجسيمات تدور على جانبين متقابلين من المركز؛ إذا انقلبت حالة أحدها انقلب شريكه في اللحظة نفسها.',
  },
  engine: 'canvas2d',
  kind: 'loop',
  duration: 8000,
  easing: 'ease-out',
  colors: ['#060913', '#22d3ee', '#f59e0b'],
  params: {
    pairs: { default: 9, min: 3, max: 18, step: 1, label: { en: 'Entangled pairs', ar: 'عدد الأزواج المتشابكة' } },
    separation: { default: 0.8, min: 0.4, max: 1, step: 0.05, label: { en: 'Separation', ar: 'التباعد' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'none', cost: 'low' },
  still: 0.5,
  tags: ['explainer', 'science', 'diagram', 'ambient'],
  setup: canvas2d({
    init(ctx) {
      const random = ctx.random(3);
      return Array.from({ length: 18 }, () => ({ angle: random() * TAU, speed: 0.15 + random() * 0.35, reach: 0.35 + random() * 0.65, rate: 0.25 + random() * 0.5, offset: random() * 10 }));
    },
    draw(g, s, ctx, pairs) {
      const [cx, cy] = [ctx.width / 2, ctx.height / 2];
      const reach = Math.min(ctx.width * 0.48, ctx.height * 0.9) * ctx.params.separation;
      const total = Math.round(ctx.params.pairs);
      g.globalCompositeOperation = 'lighter';
      for (let index = 0; index < total; index += 1) {
        const pair = pairs[index];
        const angle = pair.angle + s.t * pair.speed;
        const x = Math.cos(angle) * reach * pair.reach;
        const y = Math.sin(angle) * reach * pair.reach * 0.5;
        const beat = s.t * pair.rate + pair.offset;
        const flipped = Math.sin(Math.floor(beat) * 12.9898 + index) > 0;
        const flash = Math.max(0, 1 - (beat - Math.floor(beat)) * 5);
        const [a, b] = flipped ? [ctx.colors[1], ctx.colors[2]] : [ctx.colors[2], ctx.colors[1]];
        g.strokeStyle = rgba(ctx.colors[1], (0.12 + flash * 0.6) * s.intro);
        g.lineWidth = 1 + flash * 1.5;
        g.beginPath();
        g.moveTo(cx + x, cy + y);
        g.lineTo(cx - x, cy - y);
        g.stroke();
        for (const [px, py, colour] of [[cx + x, cy + y, a], [cx - x, cy - y, b]]) {
          const size = 3 + flash * 5;
          const glow = g.createRadialGradient(px, py, 0, px, py, size * 3);
          glow.addColorStop(0, rgba(colour, s.intro));
          glow.addColorStop(1, rgba(colour, 0));
          g.fillStyle = glow;
          g.beginPath();
          g.arc(px, py, size * 3, 0, TAU);
          g.fill();
        }
      }
    },
  }),
});
