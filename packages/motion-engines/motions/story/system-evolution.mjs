import { defineMotion } from '../../core/define.mjs';
import { canvas2d } from '../../engines/canvas2d.mjs';
import { TAU, clamp, lerp, mixColour, rgba, stage } from '../../core/util.mjs';

// A soft cloud outline made of overlapping circles, centred at (x, y) with width w.
function cloud(g, x, y, w) {
  const bumps = [[-0.32, 0.08, 0.2], [-0.12, -0.08, 0.27], [0.15, -0.05, 0.24], [0.33, 0.1, 0.18], [0, 0.13, 0.22]];
  g.beginPath();
  for (const [dx, dy, r] of bumps) {
    g.moveTo(x + dx * w + r * w, y + dy * w);
    g.arc(x + dx * w, y + dy * w, r * w, 0, TAU);
  }
}

export default defineMotion({
  id: 'story-system-evolution',
  number: 184,
  module: 'story',
  name: { en: 'Before-and-After System Evolution', ar: 'تطوّر النظام قبل وبعد' },
  summary: {
    en: 'Three server racks hum in a machine room, their lights blinking. Workloads lift off them one by one and arc up into a cloud that brightens as it fills; the emptied racks power down and the cloud settles into an orderly grid of the same workloads.',
    ar: 'ثلاث خزائن خوادم تعمل في غرفة الأجهزة وأضواؤها تومض. ترتفع أحمال العمل عنها واحدًا تلو الآخر وتنتقل في أقواسٍ إلى سحابةٍ تزداد إشراقًا كلما امتلأت؛ ثم تنطفئ الخزائن الفارغة وتستقرّ الأحمال في السحابة في شبكةٍ مرتّبة.',
  },
  meaning: {
    en: 'Cloud migration: workloads move from on-premise servers to the cloud, and the old racks are retired.',
    ar: 'الانتقال إلى السحابة: تنتقل أحمال العمل من الخوادم المحلية إلى السحابة، وتُحال الخزائن القديمة إلى التقاعد.',
  },
  engine: 'canvas2d',
  kind: 'oneshot',
  duration: 5000,
  easing: 'ease-in-out',
  colors: ['#060b16', '#64748b', '#38bdf8', '#a78bfa', '#f8fafc'],
  params: {
    workloads: { default: 9, min: 3, max: 15, step: 1, label: { en: 'Workloads to migrate', ar: 'أحمال العمل المنقولة' } },
    arc: { default: 0.6, min: 0.2, max: 1.2, step: 0.05, label: { en: 'Height of the migration arc', ar: 'ارتفاع قوس الانتقال' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'none', cost: 'low' },
  still: 1,
  tags: ['story', 'cloud', 'migration', 'infrastructure', 'modernisation'],
  setup: canvas2d({
    draw(g, s, ctx) {
      const { width: w, height: h } = ctx;
      const unit = Math.min(w, h);
      const count = Math.round(ctx.params.workloads);
      const racks = [0, 1, 2].map((n) => [w * (0.12 + n * 0.12), h * 0.86]);
      const rackW = unit * 0.16;
      const rackH = unit * 0.5;
      const cloudX = w * 0.72;
      const cloudY = h * 0.34;
      const cloudW = Math.min(w * 0.42, unit * 0.95);
      const filled = stage(s.progress, 0.1, 0.85);
      const powerDown = stage(s.progress, 0.8, 1);
      // The cloud: glows more the more it holds.
      g.fillStyle = rgba(mixColour(ctx.colors[0], ctx.colors[2], 0.12 + 0.35 * filled), 1);
      cloud(g, cloudX, cloudY, cloudW);
      g.fill();
      g.strokeStyle = rgba(ctx.colors[2], 0.4 + 0.6 * filled);
      g.lineWidth = 1.5;
      cloud(g, cloudX, cloudY, cloudW);
      g.stroke();
      // Racks with blinking lights that go out when emptied.
      racks.forEach(([x, foot], n) => {
        g.fillStyle = rgba(mixColour(ctx.colors[0], ctx.colors[1], 0.45 - 0.25 * powerDown), 1);
        g.fillRect(x - rackW / 2, foot - rackH, rackW, rackH);
        for (let slot = 0; slot < 6; slot += 1) {
          const sy = foot - rackH + rackH * (0.08 + slot * 0.15);
          g.fillStyle = rgba(ctx.colors[0], 0.6);
          g.fillRect(x - rackW * 0.4, sy, rackW * 0.8, rackH * 0.1);
          const blink = Math.sin(s.t * (6 + slot) + n * 3 + slot * 1.7) > 0;
          g.fillStyle = rgba(blink ? ctx.colors[2] : ctx.colors[1], (1 - powerDown) * (blink ? 1 : 0.6));
          g.fillRect(x + rackW * 0.22, sy + rackH * 0.03, 2, 2);
        }
      });
      // Workloads: each lifts from its rack slot, arcs over and lands in its cloud cell.
      const columns = Math.ceil(Math.sqrt(count * 1.6));
      for (let n = 0; n < count; n += 1) {
        const rack = racks[n % 3];
        const from = [rack[0] - rackW * 0.2, rack[1] - rackH * (0.85 - Math.floor(n / 3) * 0.16)];
        const column = n % columns;
        const row = Math.floor(n / columns);
        const to = [cloudX - cloudW * 0.28 + (column + 0.5) * ((cloudW * 0.56) / columns), cloudY - cloudW * 0.06 + row * unit * 0.07];
        const t = clamp((filled - (n / count) * 0.7) / 0.3);
        const lift = Math.sin(Math.PI * t) * h * 0.3 * ctx.params.arc;
        const x = lerp(from[0], to[0], t);
        const y = lerp(from[1], to[1], t) - lift;
        const size = unit * 0.045;
        g.fillStyle = rgba(mixColour(ctx.colors[3], ctx.colors[4], t * 0.4), 1);
        g.beginPath();
        g.roundRect(x - size / 2, y - size / 2, size, size, size * 0.25);
        g.fill();
        if (t > 0 && t < 1) {
          g.strokeStyle = rgba(ctx.colors[3], 0.35);
          g.lineWidth = 1;
          g.setLineDash([2, 3]);
          g.beginPath();
          for (let step = 0; step <= 10; step += 1) {
            const u = (t * step) / 10;
            const px = lerp(from[0], to[0], u);
            const py = lerp(from[1], to[1], u) - Math.sin(Math.PI * u) * h * 0.3 * ctx.params.arc;
            if (step) g.lineTo(px, py);
            else g.moveTo(px, py);
          }
          g.stroke();
          g.setLineDash([]);
        }
      }
      // A floor line under the machine room.
      g.fillStyle = rgba(ctx.colors[1], 0.4);
      g.fillRect(w * 0.04, h * 0.86, w * 0.4, 1.5);
    },
  }),
});
