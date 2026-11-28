import { defineMotion } from '../../core/define.mjs';
import { canvas2d } from '../../engines/canvas2d.mjs';
import { TAU, clamp, mixColour, noise1, rgba, stage } from '../../core/util.mjs';

export default defineMotion({
  id: 'hologram-scanline-reveal',
  number: 22,
  module: 'hologram',
  name: { en: 'Hologram Scanline Reveal', ar: 'الكشف الهولوغرافي بخط المسح' },
  summary: {
    en: 'A generic identity card floats as a hologram. A bright scan line travels down it and, above the line, the card resolves from flickering scanlines into a solid image: portrait, chip and data fields. Each field gets a tick as the line passes, and a verified badge closes the check.',
    ar: 'بطاقة هويةٍ عامة تطفو كصورةٍ هولوغرافية. يهبط عليها خطّ مسحٍ مضيء، وفوق الخط تتجلّى البطاقة من خطوط مسحٍ متذبذبة إلى صورةٍ واضحة: الصورة الشخصية والشريحة وحقول البيانات. ينال كلّ حقلٍ علامة صحٍّ حين يعبره الخط، وتختم شارة التحقق الفحص.',
  },
  meaning: {
    en: 'Identity verification: a digital ID is scanned field by field and confirmed before access is granted.',
    ar: 'التحقق من الهوية: تُمسح الهوية الرقمية حقلًا بعد حقل وتُؤكَّد قبل منح الوصول.',
  },
  engine: 'canvas2d',
  kind: 'oneshot',
  duration: 3800,
  easing: 'ease-in-out',
  colors: ['#020617', '#22d3ee', '#a78bfa', '#22c55e', '#e0f2fe'],
  params: {
    fields: { default: 4, min: 2, max: 6, step: 1, label: { en: 'Data fields checked', ar: 'عدد حقول البيانات المفحوصة' } },
    flicker: { default: 0.5, min: 0, max: 1, step: 0.05, label: { en: 'Hologram flicker', ar: 'تذبذب الصورة الهولوغرافية' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'none', cost: 'low' },
  still: 1,
  tags: ['identity', 'verification', 'security', 'hologram', 'onboarding', 'kyc'],
  setup: canvas2d({
    draw(g, s, ctx) {
      const { width: w, height: h } = ctx;
      const cardW = Math.min(w * 0.7, h * 1.15);
      const cardH = cardW * 0.62;
      const x = (w - cardW) / 2;
      const y = (h - cardH) / 2 - h * 0.03;
      const scan = stage(s.progress, 0.08, 0.82);
      const lineY = y + cardH * scan;
      const flicker = ctx.params.flicker * (0.5 + 0.5 * noise1(s.t * 14, 3));
      // The projector beam under the card.
      const beam = g.createLinearGradient(0, y + cardH, 0, h);
      beam.addColorStop(0, rgba(ctx.colors[1], 0.18));
      beam.addColorStop(1, rgba(ctx.colors[1], 0));
      g.fillStyle = beam;
      g.beginPath();
      g.moveTo(x, y + cardH);
      g.lineTo(x + cardW, y + cardH);
      g.lineTo(w / 2 + cardW * 0.12, h);
      g.lineTo(w / 2 - cardW * 0.12, h);
      g.closePath();
      g.fill();
      const draw = (solid) => {
        const ink = solid ? 1 : 0.35 - 0.2 * flicker;
        g.strokeStyle = rgba(ctx.colors[1], ink);
        g.lineWidth = 1.5;
        g.beginPath();
        g.roundRect(x, y, cardW, cardH, cardW * 0.05);
        g.stroke();
        if (solid) {
          g.fillStyle = rgba(mixColour(ctx.colors[0], ctx.colors[1], 0.14), 1);
          g.fill();
        }
        // Portrait: a head and shoulders in a frame.
        const px = x + cardW * 0.07;
        const py = y + cardH * 0.18;
        const pw = cardW * 0.26;
        const ph = cardH * 0.64;
        g.strokeStyle = rgba(ctx.colors[2], ink);
        g.strokeRect(px, py, pw, ph);
        g.fillStyle = rgba(ctx.colors[2], ink * 0.7);
        g.beginPath();
        g.arc(px + pw / 2, py + ph * 0.38, pw * 0.2, 0, TAU);
        g.fill();
        g.beginPath();
        g.ellipse(px + pw / 2, py + ph * 0.95, pw * 0.38, ph * 0.3, 0, Math.PI, TAU);
        g.fill();
        // Chip.
        g.strokeStyle = rgba(ctx.colors[4], ink);
        g.strokeRect(x + cardW * 0.4, y + cardH * 0.18, cardW * 0.11, cardH * 0.15);
        g.beginPath();
        g.moveTo(x + cardW * 0.4, y + cardH * 0.255);
        g.lineTo(x + cardW * 0.51, y + cardH * 0.255);
        g.stroke();
      };
      // Not yet scanned: faint scanlines that flicker.
      g.save();
      g.beginPath();
      g.rect(0, lineY, w, h);
      g.clip();
      draw(false);
      g.fillStyle = rgba(ctx.colors[1], 0.08 + 0.08 * flicker);
      for (let row = Math.floor(lineY); row < y + cardH; row += 3) g.fillRect(x, row, cardW, 1);
      g.restore();
      // Scanned: solid.
      g.save();
      g.beginPath();
      g.rect(0, 0, w, lineY);
      g.clip();
      draw(true);
      g.restore();
      // Data fields, each ticked when the scan line has passed it.
      const fields = Math.round(ctx.params.fields);
      for (let field = 0; field < fields; field += 1) {
        const fy = y + cardH * (0.42 + (field * 0.42) / fields);
        const passed = clamp((lineY - fy) / (cardH * 0.08));
        g.fillStyle = rgba(ctx.colors[4], (passed > 0 ? 0.85 : 0.25 - 0.1 * flicker));
        g.fillRect(x + cardW * 0.4, fy - 2, cardW * (0.3 + 0.12 * ((field * 5) % 3) / 2), 3.5);
        if (passed > 0) {
          const tx = x + cardW * 0.88;
          g.strokeStyle = rgba(ctx.colors[3], passed);
          g.lineWidth = 2;
          g.beginPath();
          g.moveTo(tx - 5, fy);
          g.lineTo(tx - 2, fy + 3);
          g.lineTo(tx + 4, fy - 4);
          g.stroke();
        }
      }
      // The scan line itself.
      if (scan > 0 && scan < 1) {
        const glow = g.createLinearGradient(0, lineY - 12, 0, lineY + 2);
        glow.addColorStop(0, rgba(ctx.colors[1], 0));
        glow.addColorStop(1, rgba(ctx.colors[1], 0.7));
        g.fillStyle = glow;
        g.fillRect(x - 8, lineY - 12, cardW + 16, 14);
        g.fillStyle = rgba(ctx.colors[4], 1);
        g.fillRect(x - 8, lineY - 1, cardW + 16, 2);
      }
      // Verified badge.
      const verified = stage(s.progress, 0.84, 1);
      if (verified > 0) {
        const bx = x + cardW;
        const by = y;
        const r = cardH * 0.17 * (0.6 + 0.4 * verified);
        g.fillStyle = rgba(ctx.colors[3], verified);
        g.beginPath();
        g.arc(bx, by, r, 0, TAU);
        g.fill();
        g.strokeStyle = rgba(ctx.colors[0], verified);
        g.lineWidth = 2.4;
        g.beginPath();
        g.moveTo(bx - r * 0.45, by);
        g.lineTo(bx - r * 0.1, by + r * 0.35);
        g.lineTo(bx + r * 0.5, by - r * 0.35);
        g.stroke();
      }
    },
  }),
});
