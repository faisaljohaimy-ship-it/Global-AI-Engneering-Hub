import { defineMotion } from '../../core/define.mjs';
import { canvas2d } from '../../engines/canvas2d.mjs';
import { TAU, clamp, mixColour, rgba } from '../../core/util.mjs';

// The outgoing picture, painted once into its own canvas so that every shard can carry a piece of it.
function paintOutgoing(ctx) {
  const canvas = ctx.surface.root.ownerDocument.createElement('canvas');
  const ratio = ctx.pixelRatio;
  canvas.width = Math.max(1, Math.round(ctx.width * ratio));
  canvas.height = Math.max(1, Math.round(ctx.height * ratio));
  const g = canvas.getContext('2d');
  g.scale(ratio, ratio);
  const { width: w, height: h } = ctx;
  const back = g.createLinearGradient(0, 0, w, h);
  back.addColorStop(0, rgba(ctx.colors[1], 1));
  back.addColorStop(1, rgba(mixColour(ctx.colors[1], ctx.colors[0], 0.6), 1));
  g.fillStyle = back;
  g.fillRect(0, 0, w, h);
  g.strokeStyle = rgba(ctx.colors[4], 0.35);
  g.lineWidth = 1;
  for (let ring = 1; ring <= 6; ring += 1) {
    g.beginPath();
    g.arc(w * 0.3, h * 0.55, ring * Math.min(w, h) * 0.08, 0, TAU);
    g.stroke();
  }
  g.fillStyle = rgba(ctx.colors[4], 0.85);
  g.fillRect(w * 0.55, h * 0.3, w * 0.32, h * 0.08);
  g.fillRect(w * 0.55, h * 0.45, w * 0.24, h * 0.05);
  g.fillRect(w * 0.55, h * 0.56, w * 0.28, h * 0.05);
  return canvas;
}

// Shards: a jittered grid split into triangles, each with its own flight.
function shardsOf(ctx, columns) {
  const random = ctx.random(119);
  const rows = Math.max(2, Math.round((columns * ctx.height) / ctx.width));
  const point = [];
  for (let row = 0; row <= rows; row += 1) {
    for (let column = 0; column <= columns; column += 1) {
      const inner = row > 0 && row < rows && column > 0 && column < columns;
      point.push([
        (column + (inner ? (random() - 0.5) * 0.7 : 0)) * (ctx.width / columns),
        (row + (inner ? (random() - 0.5) * 0.7 : 0)) * (ctx.height / rows),
      ]);
    }
  }
  const at = (row, column) => point[row * (columns + 1) + column];
  const shards = [];
  for (let row = 0; row < rows; row += 1) {
    for (let column = 0; column < columns; column += 1) {
      const quad = [at(row, column), at(row, column + 1), at(row + 1, column + 1), at(row + 1, column)];
      const split = random() < 0.5;
      const triangles = split ? [[quad[0], quad[1], quad[2]], [quad[0], quad[2], quad[3]]] : [[quad[0], quad[1], quad[3]], [quad[1], quad[2], quad[3]]];
      for (const corners of triangles) {
        const centre = [(corners[0][0] + corners[1][0] + corners[2][0]) / 3, (corners[0][1] + corners[1][1] + corners[2][1]) / 3];
        shards.push({ corners, centre, spin: (random() - 0.5) * 6, push: 0.6 + random() * 0.8, delay: random() * 0.25 });
      }
    }
  }
  return shards;
}

export default defineMotion({
  id: 'transitions-fragment-transition',
  number: 119,
  module: 'transitions',
  name: { en: 'Geometric Fragment Transition', ar: 'الانتقال بالشظايا الهندسية' },
  summary: {
    en: 'The outgoing screen cracks into triangles from a point of impact. Each shard carries its piece of the picture, tumbles away from the impact, falls and fades, uncovering the next screen beneath; shard edges catch the light as they turn.',
    ar: 'تتشقّق الشاشة المغادرة إلى مثلّثات من نقطة ارتطام. تحمل كلّ شظيةٍ قطعتها من الصورة، وتتقلّب مبتعدةً عن موضع الارتطام وتسقط وتتلاشى، فتنكشف الشاشة التالية تحتها؛ وتلتقط حوافّ الشظايا الضوء وهي تدور.',
  },
  meaning: {
    en: 'Breaking out of a legacy screen: the old interface shatters and the new digital interface is waiting underneath.',
    ar: 'الخروج من الشاشة القديمة: تتحطّم الواجهة القديمة لتظهر تحتها الواجهة الرقمية الجديدة.',
  },
  engine: 'canvas2d',
  kind: 'oneshot',
  duration: 2800,
  easing: 'ease-in',
  colors: ['#060814', '#0ea5e9', '#a3e635', '#f472b6', '#f8fafc'],
  params: {
    shards: { default: 9, min: 4, max: 16, step: 1, label: { en: 'Shards across', ar: 'عدد الشظايا عرضًا' } },
    force: { default: 1, min: 0.3, max: 2, step: 0.05, label: { en: 'Force of the break', ar: 'قوة الكسر' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'none', cost: 'medium' },
  still: 0.5,
  tags: ['transition', 'page', 'break', 'shatter', 'dramatic'],
  setup: canvas2d({
    init: (ctx) => ({ picture: paintOutgoing(ctx), shards: shardsOf(ctx, Math.round(ctx.params.shards)) }),
    draw(g, s, ctx, { picture, shards }) {
      const { width: w, height: h } = ctx;
      const impact = [w * 0.42, h * 0.48];
      // The incoming screen, beneath.
      const next = g.createRadialGradient(w / 2, h / 2, 0, w / 2, h / 2, Math.hypot(w, h) / 2);
      next.addColorStop(0, rgba(mixColour(ctx.colors[2], ctx.colors[0], 0.55), 1));
      next.addColorStop(1, rgba(ctx.colors[0], 1));
      g.fillStyle = next;
      g.fillRect(0, 0, w, h);
      g.fillStyle = rgba(ctx.colors[3], 0.85);
      g.beginPath();
      g.roundRect(w * 0.3, h * 0.36, w * 0.4, h * 0.28, 8);
      g.fill();
      g.fillStyle = rgba(ctx.colors[4], 0.9);
      g.fillRect(w * 0.36, h * 0.46, w * 0.28, h * 0.04);
      // Cracks appear first, then the shards fly.
      const crack = clamp(s.progress / 0.18);
      for (const shard of shards) {
        const dx = shard.centre[0] - impact[0];
        const dy = shard.centre[1] - impact[1];
        const distance = Math.hypot(dx, dy) || 1;
        const local = clamp((s.progress - 0.12 - shard.delay * (distance / Math.hypot(w, h))) / 0.7);
        if (local >= 1) continue;
        const fly = local * local;
        const away = ctx.params.force * shard.push * fly * Math.min(w, h) * 0.9;
        const fall = fly * fly * h * 0.9;
        const x = (dx / distance) * away;
        const y = (dy / distance) * away + fall;
        const angle = shard.spin * fly;
        const scale = 1 - 0.3 * fly;
        g.save();
        g.globalAlpha = 1 - fly;
        g.translate(shard.centre[0] + x, shard.centre[1] + y);
        g.rotate(angle);
        g.scale(scale, scale);
        g.translate(-shard.centre[0], -shard.centre[1]);
        g.beginPath();
        shard.corners.forEach(([px, py], index) => (index ? g.lineTo(px, py) : g.moveTo(px, py)));
        g.closePath();
        g.save();
        g.clip();
        g.drawImage(picture, 0, 0, w, h);
        g.restore();
        g.strokeStyle = rgba(ctx.colors[4], 0.15 + 0.6 * crack * (0.4 + 0.6 * Math.abs(Math.sin(angle))));
        g.lineWidth = 1;
        g.stroke();
        g.restore();
      }
    },
  }),
});
