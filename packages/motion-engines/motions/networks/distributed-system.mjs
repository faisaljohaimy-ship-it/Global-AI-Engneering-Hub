import { defineMotion } from '../../core/define.mjs';
import { canvas2d } from '../../engines/canvas2d.mjs';
import { TAU, clamp, lerp, mixColour, rgba, smoothstep } from '../../core/util.mjs';

// A small shield with a tick (verified) or a cross (refused).
function shield(g, x, y, size, colour, ink, refused) {
  g.fillStyle = colour;
  g.beginPath();
  g.moveTo(x, y - size);
  g.lineTo(x + size * 0.85, y - size * 0.6);
  g.quadraticCurveTo(x + size * 0.8, y + size * 0.6, x, y + size);
  g.quadraticCurveTo(x - size * 0.8, y + size * 0.6, x - size * 0.85, y - size * 0.6);
  g.closePath();
  g.fill();
  g.strokeStyle = ink;
  g.lineWidth = Math.max(1, size * 0.22);
  g.beginPath();
  if (refused) {
    g.moveTo(x - size * 0.35, y - size * 0.3);
    g.lineTo(x + size * 0.35, y + size * 0.4);
    g.moveTo(x + size * 0.35, y - size * 0.3);
    g.lineTo(x - size * 0.35, y + size * 0.4);
  } else {
    g.moveTo(x - size * 0.4, y);
    g.lineTo(x - size * 0.1, y + size * 0.35);
    g.lineTo(x + size * 0.45, y - size * 0.35);
  }
  g.stroke();
}

export default defineMotion({
  id: 'networks-distributed-system',
  number: 169,
  module: 'networks',
  name: { en: 'Distributed System Visualization', ar: 'تصوير الأنظمة الموزّعة' },
  summary: {
    en: 'A ring of services exchanges calls across its middle. Every call is stopped at the door of the service it reaches and checked: a shield flashes with a tick and the call is let in, or, for the one call each cycle that carries no valid identity, a red shield with a cross turns it back.',
    ar: 'حلقةٌ من الخدمات تتبادل الاستدعاءات عبر وسطها. يُوقف كلّ استدعاءٍ عند باب الخدمة التي يصلها ويُفحص: يومض درعٌ بعلامة صحٍّ فيُسمح له بالدخول، أو يردّه درعٌ أحمر بعلامة خطأ إن كان الاستدعاء الوحيد في الدورة الذي لا يحمل هويةً صالحة.',
  },
  meaning: {
    en: 'Zero trust: no call between services is trusted by default; each one is verified at the service it reaches, and an unverified call is refused.',
    ar: 'انعدام الثقة الافتراضية: لا يُوثق بأي استدعاءٍ بين الخدمات تلقائيًّا؛ يُتحقّق من كلٍّ منها عند الخدمة التي يصلها، ويُرفض أيّ استدعاءٍ غير موثّق.',
  },
  engine: 'canvas2d',
  kind: 'loop',
  duration: 8000,
  easing: 'ease-out',
  colors: ['#050914', '#38bdf8', '#22c55e', '#ef4444', '#e2e8f0'],
  params: {
    services: { default: 7, min: 4, max: 10, step: 1, label: { en: 'Services in the ring', ar: 'عدد الخدمات في الحلقة' } },
    calls: { default: 6, min: 2, max: 10, step: 1, label: { en: 'Calls per cycle', ar: 'عدد الاستدعاءات في كل دورة' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'none', cost: 'low' },
  still: 0.5,
  tags: ['security', 'zero-trust', 'microservices', 'network', 'identity'],
  setup: canvas2d({
    init(ctx) {
      const random = ctx.random(169);
      return Array.from({ length: 10 }, () => ({ from: random(), hop: 1 + Math.floor(random() * 3), lift: random() }));
    },
    draw(g, s, ctx, plan) {
      const { width: w, height: h } = ctx;
      const count = Math.round(ctx.params.services);
      const radius = Math.min(w, h) * 0.36;
      const cx = w / 2;
      const cy = h / 2;
      const nodes = Array.from({ length: count }, (_, n) => {
        const a = (n / count) * TAU - Math.PI / 2;
        return [cx + Math.cos(a) * radius * 1.25, cy + Math.sin(a) * radius];
      });
      const node = Math.min(w, h) * 0.055;
      const intro = 0.3 + 0.7 * s.intro;
      // The ring itself.
      g.strokeStyle = rgba(ctx.colors[1], 0.18);
      g.lineWidth = 1;
      g.beginPath();
      g.ellipse(cx, cy, radius * 1.25, radius, 0, 0, TAU);
      g.stroke();
      const calls = Math.round(ctx.params.calls);
      const verdicts = new Map();
      for (let call = 0; call < calls; call += 1) {
        const step = plan[call % plan.length];
        const from = Math.floor(step.from * count) % count;
        const to = (from + step.hop + (count > 5 ? 1 : 0)) % count;
        const start = call / calls;
        // Wrapped around the cycle, so a call that starts late finishes at the start of the next loop.
        const local = clamp(((((s.raw - start) % 1) + 1) % 1) / (1.6 / calls));
        if (local <= 0 || local >= 1) continue;
        const refused = call === Math.floor(calls / 2);
        const a = nodes[from];
        const b = nodes[to];
        const bend = [cx + (step.lift - 0.5) * radius * 0.6, cy + (step.lift - 0.5) * radius * 0.4];
        // Travel to the door (first 60%), stop to be checked, then enter or bounce back.
        const travel = smoothstep(0, 0.6, local);
        const back = refused ? smoothstep(0.75, 1, local) : 0;
        const u = clamp(travel * 0.88 - back * 0.4);
        const x = (1 - u) ** 2 * a[0] + 2 * (1 - u) * u * bend[0] + u * u * b[0];
        const y = (1 - u) ** 2 * a[1] + 2 * (1 - u) * u * bend[1] + u * u * b[1];
        g.strokeStyle = rgba(ctx.colors[1], 0.35 * intro);
        g.setLineDash([3, 3]);
        g.beginPath();
        g.moveTo(...a);
        g.quadraticCurveTo(bend[0], bend[1], b[0], b[1]);
        g.stroke();
        g.setLineDash([]);
        g.fillStyle = rgba(refused ? mixColour(ctx.colors[4], ctx.colors[3], back) : ctx.colors[4], 1 - (refused ? back * 0.7 : smoothstep(0.85, 1, local)));
        g.beginPath();
        g.arc(x, y, node * 0.3, 0, TAU);
        g.fill();
        const checking = smoothstep(0.55, 0.7, local) * (1 - smoothstep(0.9, 1, local));
        if (checking > 0) verdicts.set(to, { refused, strength: checking });
      }
      // Services, each with its door check.
      nodes.forEach(([x, y], n) => {
        const verdict = verdicts.get(n);
        g.fillStyle = rgba(mixColour(ctx.colors[0], ctx.colors[1], 0.35), intro);
        g.beginPath();
        g.roundRect(x - node, y - node, node * 2, node * 2, node * 0.35);
        g.fill();
        g.strokeStyle = rgba(verdict ? (verdict.refused ? ctx.colors[3] : ctx.colors[2]) : ctx.colors[1], intro);
        g.lineWidth = verdict ? 2 : 1.2;
        g.stroke();
        if (verdict) shield(g, x + node * 1.1, y - node * 1.1, node * 0.7 * (0.7 + 0.3 * verdict.strength), rgba(verdict.refused ? ctx.colors[3] : ctx.colors[2], verdict.strength), rgba(ctx.colors[0], 0.85 * verdict.strength), verdict.refused);
      });
      // The identity provider at the centre: every check consults it.
      g.fillStyle = rgba(ctx.colors[2], 0.25 + 0.5 * (verdicts.size > 0 ? 1 : 0));
      g.beginPath();
      g.arc(cx, cy, node * 0.7, 0, TAU);
      g.fill();
      g.strokeStyle = rgba(ctx.colors[2], 0.8);
      g.lineWidth = 1.5;
      g.beginPath();
      g.arc(cx, cy - node * 0.15, node * 0.28, 0, TAU);
      g.moveTo(cx - node * 0.4, cy + node * 0.45);
      g.quadraticCurveTo(cx, cy + node * 0.05, cx + node * 0.4, cy + node * 0.45);
      g.stroke();
      for (const [n] of verdicts) {
        g.strokeStyle = rgba(ctx.colors[2], 0.25);
        g.beginPath();
        g.moveTo(cx, cy);
        g.lineTo(lerp(cx, nodes[n][0], 0.8), lerp(cy, nodes[n][1], 0.8));
        g.stroke();
      }
    },
  }),
});
