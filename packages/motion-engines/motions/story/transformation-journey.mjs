import { defineMotion } from '../../core/define.mjs';
import { canvas2d } from '../../engines/canvas2d.mjs';
import { TAU, clamp, lerp, mixColour, rgba, smoothstep, stage } from '../../core/util.mjs';

// The paper form: a slightly tilted sheet with handwritten-looking lines and boxes.
function paper(g, ctx, x, y, w, h, tilt, alpha, lines) {
  g.save();
  g.globalAlpha = alpha;
  g.translate(x + w / 2, y + h / 2);
  g.rotate(tilt);
  g.fillStyle = rgba(mixColour(ctx.colors[4], ctx.colors[3], 0.15), 1);
  g.fillRect(-w / 2, -h / 2, w, h);
  g.strokeStyle = rgba(ctx.colors[0], 0.55);
  g.lineWidth = 1;
  lines.forEach((wobble, row) => {
    const ly = -h / 2 + h * (0.2 + row * 0.13);
    g.beginPath();
    for (let step = 0; step <= 12; step += 1) {
      const lx = -w / 2 + w * 0.12 + (w * 0.7 * step) / 12;
      const dy = Math.sin(step * 1.7 + wobble * 9) * h * 0.008;
      if (step) g.lineTo(lx, ly + dy);
      else g.moveTo(lx, ly + dy);
    }
    g.stroke();
  });
  g.strokeRect(-w / 2 + w * 0.12, h / 2 - h * 0.18, w * 0.1, w * 0.1);
  g.restore();
}

// The digital form: a screen with labelled fields that fill in one by one, then a submit bar.
function screen(g, ctx, x, y, w, h, filled, fields) {
  g.fillStyle = rgba(mixColour(ctx.colors[0], ctx.colors[1], 0.18), 1);
  g.beginPath();
  g.roundRect(x, y, w, h, Math.min(w, h) * 0.06);
  g.fill();
  g.strokeStyle = rgba(ctx.colors[1], 0.9);
  g.lineWidth = 1.5;
  g.stroke();
  const pad = w * 0.1;
  for (let field = 0; field < fields; field += 1) {
    const fy = y + h * 0.14 + field * ((h * 0.6) / fields);
    const fh = (h * 0.6) / fields - h * 0.04;
    g.strokeStyle = rgba(ctx.colors[1], 0.5);
    g.lineWidth = 1;
    g.strokeRect(x + pad, fy, w - pad * 2, fh);
    const amount = clamp(filled * fields - field);
    if (amount > 0) {
      g.fillStyle = rgba(ctx.colors[1], 0.85);
      g.fillRect(x + pad * 1.4, fy + fh * 0.35, (w - pad * 2.8) * amount * (0.55 + 0.4 * ((field * 7) % 3) / 2), fh * 0.3);
    }
  }
  g.fillStyle = rgba(ctx.colors[2], 0.35 + 0.65 * smoothstep(0.9, 1, filled));
  g.beginPath();
  g.roundRect(x + pad, y + h * 0.8, w - pad * 2, h * 0.1, h * 0.03);
  g.fill();
}

export default defineMotion({
  id: 'story-transformation-journey',
  number: 189,
  module: 'story',
  name: { en: 'Digital Transformation Journey', ar: 'رحلة التحوّل الرقمي' },
  summary: {
    en: 'A handwritten paper form slides under a scanning bar and turns into a screen form: its fields fill in one by one, the submit bar lights, and an approval stamp lands with a ring that spreads out. A progress line underneath marks the three stages.',
    ar: 'نموذجٌ ورقي مكتوب بخط اليد ينزلق تحت شريط مسح فيتحوّل إلى نموذجٍ على الشاشة: تمتلئ حقوله واحدًا تلو الآخر، ويضيء زرّ الإرسال، ثم يهبط ختم الموافقة مع حلقةٍ تتّسع حوله. وخطّ تقدّمٍ في الأسفل يعلّم المراحل الثلاث.',
  },
  meaning: {
    en: 'Paper to digital: a paper application is scanned into a digital form, completed and approved in one flow.',
    ar: 'من الورق إلى الرقمي: يُمسح طلبٌ ورقي ليصبح نموذجًا رقميًّا يُستكمل ويُعتمد في مسارٍ واحد.',
  },
  engine: 'canvas2d',
  kind: 'oneshot',
  duration: 5200,
  easing: 'ease-in-out',
  colors: ['#0b1324', '#38bdf8', '#22c55e', '#f59e0b', '#f8fafc'],
  params: {
    fields: { default: 4, min: 2, max: 7, step: 1, label: { en: 'Form fields', ar: 'عدد حقول النموذج' } },
    stamp: { default: 1, min: 0.5, max: 1.6, step: 0.05, label: { en: 'Stamp size', ar: 'حجم الختم' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'none', cost: 'low' },
  still: 1,
  tags: ['story', 'digital-transformation', 'form', 'approval', 'e-service'],
  setup: canvas2d({
    init(ctx) {
      const random = ctx.random(189);
      return Array.from({ length: 5 }, () => random());
    },
    draw(g, s, ctx, lines) {
      const { width: w, height: h } = ctx;
      const p = s.progress;
      const scan = stage(p, 0.05, 0.42);
      const fill = stage(p, 0.42, 0.75);
      const approve = stage(p, 0.78, 0.92);
      const fh = Math.min(h * 0.7, w * 0.55);
      const fw = fh * 0.74;
      const cx = w / 2;
      const top = h * 0.08;
      // The paper rises into the scanner and fades as the screen form appears in its place.
      const paperY = lerp(top + h * 0.08, top, scan);
      const reveal = smoothstep(0.2, 1, scan);
      if (reveal < 1) paper(g, ctx, cx - fw / 2, paperY, fw, fh, lerp(-0.08, 0, scan), 1 - reveal, lines);
      if (reveal > 0) {
        g.save();
        g.beginPath();
        g.rect(cx - fw, top - 2, fw * 2, (fh + 4) * reveal);
        g.clip();
        screen(g, ctx, cx - fw / 2, top, fw, fh, fill, Math.round(ctx.params.fields));
        g.restore();
      }
      // The scanning bar travels down the sheet.
      if (scan > 0 && scan < 1) {
        const by = top + fh * scan;
        const beam = g.createLinearGradient(0, by - 10, 0, by + 2);
        beam.addColorStop(0, rgba(ctx.colors[1], 0));
        beam.addColorStop(1, rgba(ctx.colors[1], 0.8));
        g.fillStyle = beam;
        g.fillRect(cx - fw * 0.7, by - 10, fw * 1.4, 12);
      }
      // The approval stamp: drops from above, lands with a ring.
      if (approve > 0) {
        const r = fw * 0.22 * ctx.params.stamp;
        const sx = cx + fw * 0.28;
        const sy = top + fh * 0.62;
        const scale = lerp(2.2, 1, approve);
        g.save();
        g.translate(sx, sy);
        g.rotate(-0.25);
        g.scale(scale, scale);
        g.globalAlpha = approve;
        g.strokeStyle = rgba(ctx.colors[2], 1);
        g.lineWidth = Math.max(2, r * 0.14);
        g.beginPath();
        g.arc(0, 0, r, 0, TAU);
        g.stroke();
        g.beginPath();
        g.moveTo(-r * 0.45, 0);
        g.lineTo(-r * 0.1, r * 0.35);
        g.lineTo(r * 0.5, -r * 0.35);
        g.stroke();
        g.restore();
        const ring = stage(p, 0.9, 1);
        if (ring > 0 && ring < 1) {
          g.strokeStyle = rgba(ctx.colors[2], 0.6 * (1 - ring));
          g.lineWidth = 2;
          g.beginPath();
          g.arc(sx, sy, r * (1 + ring * 1.6), 0, TAU);
          g.stroke();
        }
      }
      // The journey line: paper, digital, approved.
      const ly = h * 0.93;
      const lx = [w * 0.25, w * 0.5, w * 0.75];
      g.strokeStyle = rgba(ctx.colors[4], 0.25);
      g.lineWidth = 2;
      g.beginPath();
      g.moveTo(lx[0], ly);
      g.lineTo(lx[2], ly);
      g.stroke();
      const reached = [1, scan, approve];
      g.strokeStyle = rgba(ctx.colors[1], 0.9);
      g.beginPath();
      g.moveTo(lx[0], ly);
      g.lineTo(lerp(lx[0], lx[1], scan) + (lx[2] - lx[1]) * (scan >= 1 ? fill : 0), ly);
      g.stroke();
      lx.forEach((x, index) => {
        g.fillStyle = rgba(index === 2 ? ctx.colors[2] : index === 1 ? ctx.colors[1] : ctx.colors[3], 0.3 + 0.7 * reached[index]);
        g.beginPath();
        g.arc(x, ly, 3.5 + 1.5 * reached[index], 0, TAU);
        g.fill();
      });
    },
  }),
});
