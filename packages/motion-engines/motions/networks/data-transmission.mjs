import { defineMotion } from '../../core/define.mjs';
import { canvas2d } from '../../engines/canvas2d.mjs';
import { TAU, clamp, lerp, mixColour, rgba, stage } from '../../core/util.mjs';

// A packet: a small rounded block moving along a straight link.
function packet(g, from, to, t, size, colour) {
  if (t <= 0 || t >= 1) return;
  const x = lerp(from[0], to[0], t);
  const y = lerp(from[1], to[1], t);
  g.fillStyle = colour;
  g.beginPath();
  g.roundRect(x - size, y - size * 0.6, size * 2, size * 1.2, size * 0.4);
  g.fill();
}

export default defineMotion({
  id: 'networks-data-transmission',
  number: 162,
  module: 'networks',
  name: { en: 'Data Transmission Through Nodes', ar: 'نقل البيانات عبر العُقد' },
  summary: {
    en: 'A client and an API gateway first shake hands: a request, a challenge and a token cross the link and a padlock closes on it. Then data packets flow through the gateway to a mesh of services, and each service answers with an acknowledgement that runs back to the client.',
    ar: 'يتصافح العميل وبوابة الواجهات البرمجية أولًا: يعبر الوصلةَ طلبٌ ثم تحدٍّ ثم رمزُ وصول، فيُغلق قفلٌ عليها. بعد ذلك تتدفّق حزم البيانات عبر البوابة إلى شبكةٍ من الخدمات، وتردّ كلّ خدمةٍ بإشعار استلامٍ يعود إلى العميل.',
  },
  meaning: {
    en: 'An API handshake: the client is authenticated by the gateway before its data is routed across the service mesh and acknowledged.',
    ar: 'مصافحة الواجهات البرمجية: توثّق البوابةُ العميلَ قبل أن تُوجَّه بياناته عبر شبكة الخدمات ويُؤكَّد استلامها.',
  },
  engine: 'canvas2d',
  kind: 'loop',
  duration: 7000,
  easing: 'ease-out',
  colors: ['#050a16', '#38bdf8', '#f59e0b', '#22c55e', '#e2e8f0'],
  params: {
    services: { default: 4, min: 2, max: 6, step: 1, label: { en: 'Services in the mesh', ar: 'عدد الخدمات في الشبكة' } },
    packets: { default: 3, min: 1, max: 6, step: 1, label: { en: 'Packets per service', ar: 'الحزم لكل خدمة' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'none', cost: 'low' },
  still: 0.75,
  tags: ['network', 'api', 'handshake', 'security', 'integration', 'mesh'],
  setup: canvas2d({
    draw(g, s, ctx) {
      const { width: w, height: h } = ctx;
      const r = Math.min(w, h) * 0.07;
      const client = [w * 0.13, h * 0.5];
      const gateway = [w * 0.45, h * 0.5];
      const count = Math.round(ctx.params.services);
      const services = Array.from({ length: count }, (_, n) => [w * 0.82, h * 0.5 + (n - (count - 1) / 2) * Math.min(h * 0.2, (h * 0.8) / count)]);
      const handshake = stage(s.raw, 0, 0.4);
      const flow = stage(s.raw, 0.42, 1);
      const intro = 0.3 + 0.7 * s.intro;
      // Links.
      g.lineWidth = 1.5;
      g.strokeStyle = rgba(mixColour(ctx.colors[4], ctx.colors[3], handshake >= 1 ? 0.6 : 0), 0.35 * intro);
      g.beginPath();
      g.moveTo(...client);
      g.lineTo(...gateway);
      g.stroke();
      g.strokeStyle = rgba(ctx.colors[1], 0.3 * intro);
      for (const service of services) {
        g.beginPath();
        g.moveTo(...gateway);
        g.lineTo(...service);
        g.stroke();
      }
      // The handshake: request (client to gateway), challenge (back), token (forward).
      const legs = [[client, gateway, ctx.colors[1]], [gateway, client, ctx.colors[2]], [client, gateway, ctx.colors[3]]];
      legs.forEach(([from, to, colour], leg) => packet(g, from, to, clamp(handshake * 3 - leg) * 1.0001 - 0.00005, r * 0.32, rgba(colour, 1)));
      for (let step = 0; step < 3; step += 1) {
        g.fillStyle = rgba(legs[step][2], handshake * 3 > step + 1 ? 1 : 0.2);
        g.beginPath();
        g.arc(lerp(client[0], gateway[0], 0.35 + step * 0.15), client[1] + r * 1.3, 2.4, 0, TAU);
        g.fill();
      }
      // The padlock on the link closes when the token has arrived.
      const lock = clamp(handshake * 3 - 2.6) * 2.5;
      const lx = lerp(client[0], gateway[0], 0.5);
      const ly = client[1] - r * 1.1;
      g.strokeStyle = rgba(lock >= 1 ? ctx.colors[3] : ctx.colors[4], 0.9 * intro);
      g.lineWidth = 1.6;
      g.beginPath();
      g.arc(lx, ly - r * 0.25 - (1 - clamp(lock)) * r * 0.25, r * 0.22, Math.PI, TAU);
      g.stroke();
      g.fillStyle = rgba(lock >= 1 ? ctx.colors[3] : ctx.colors[4], 0.9 * intro);
      g.fillRect(lx - r * 0.32, ly - r * 0.25, r * 0.64, r * 0.48);
      // Data flows to each service and acknowledgements return.
      const packets = Math.round(ctx.params.packets);
      services.forEach((service, n) => {
        for (let k = 0; k < packets; k += 1) {
          const t = flow * 1.6 - (k / packets) * 0.5 - n * 0.06;
          packet(g, client, gateway, clamp(t * 2), r * 0.25, rgba(ctx.colors[1], 0.9));
          packet(g, gateway, service, clamp(t * 2 - 1) * 0.9999 + (t * 2 - 1 >= 1 ? 1 : 0), r * 0.25, rgba(ctx.colors[1], 0.9));
        }
        const ack = clamp(flow * 1.6 - 1 - n * 0.06);
        packet(g, service, gateway, clamp(ack * 2), r * 0.2, rgba(ctx.colors[3], 0.95));
        packet(g, gateway, client, clamp(ack * 2 - 1), r * 0.2, rgba(ctx.colors[3], 0.95));
        // The service node, lit once its data has arrived.
        const lit = clamp(flow * 1.6 - 0.5 - n * 0.06) > 0 ? 1 : 0;
        g.fillStyle = rgba(mixColour(ctx.colors[0], lit ? ctx.colors[3] : ctx.colors[1], 0.45 + 0.3 * lit), intro);
        g.beginPath();
        g.arc(service[0], service[1], r * 0.62, 0, TAU);
        g.fill();
        g.strokeStyle = rgba(ctx.colors[1], intro);
        g.lineWidth = 1.2;
        g.stroke();
      });
      // The client: a laptop. The gateway: a hexagon.
      g.fillStyle = rgba(mixColour(ctx.colors[0], ctx.colors[4], 0.25), intro);
      g.fillRect(client[0] - r, client[1] - r * 0.75, r * 2, r * 1.3);
      g.strokeStyle = rgba(ctx.colors[4], intro);
      g.strokeRect(client[0] - r, client[1] - r * 0.75, r * 2, r * 1.3);
      g.fillRect(client[0] - r * 1.25, client[1] + r * 0.6, r * 2.5, r * 0.22);
      g.fillStyle = rgba(mixColour(ctx.colors[0], ctx.colors[2], 0.35 + 0.4 * clamp(lock)), intro);
      g.beginPath();
      for (let corner = 0; corner < 6; corner += 1) {
        const a = (corner / 6) * TAU + Math.PI / 6;
        g.lineTo(gateway[0] + Math.cos(a) * r, gateway[1] + Math.sin(a) * r);
      }
      g.closePath();
      g.fill();
      g.strokeStyle = rgba(ctx.colors[2], intro);
      g.stroke();
    },
  }),
});
