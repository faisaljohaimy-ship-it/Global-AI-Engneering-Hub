import { defineMotion } from '../../core/define.mjs';
import { dom, svg } from '../../engines/dom.mjs';
import { clamp, smoothstep } from '../../core/util.mjs';

// The monitored signal: a steady heartbeat with an incident spike once per cycle.
function signal(x, t, incident) {
  const beat = ((x + t * 0.4) % 0.25 + 0.25) % 0.25;
  const pulse = Math.exp(-((beat - 0.12) ** 2) / 0.00008) * 0.9 - Math.exp(-((beat - 0.135) ** 2) / 0.00004) * 0.4;
  return pulse + incident * Math.exp(-((x - 0.78) ** 2) / 0.0015) * 1.2 * Math.sin(x * 120);
}

export default defineMotion({
  id: 'dashboard-signal-pulse',
  number: 109,
  module: 'dashboard',
  name: { en: 'Live Operational Signal Pulse', ar: 'نبض الإشارة التشغيلية الحيّة' },
  summary: {
    en: 'A monitoring panel: a live signal trace scrolls over a grid beside an availability ring. Once per cycle an incident spike appears on the trace, the ring turns to the alert colour and dips, then recovers and turns healthy again. Vector graphics, sharp at any size.',
    ar: 'لوحة مراقبة: خطّ إشارةٍ حيّة يمرّ فوق شبكةٍ بجانب حلقة التوافر. مرّةً في كلّ دورة تظهر قفزة حادثٍ على الخط، فتتحوّل الحلقة إلى لون التنبيه وتنخفض، ثم تتعافى وتعود سليمة. رسمٌ متّجهي حادّ بأي حجم.',
  },
  meaning: {
    en: 'Real-time monitoring: a live service signal is watched continuously, and an incident raises an alert until the service recovers.',
    ar: 'المراقبة اللحظية: تُراقب إشارة الخدمة الحيّة باستمرار، ويرفع أيّ حادثٍ تنبيهًا حتى تتعافى الخدمة.',
  },
  engine: 'svg',
  kind: 'loop',
  duration: 6000,
  easing: 'ease-out',
  colors: ['#050b14', '#22c55e', '#f59e0b', '#1e293b', '#e2e8f0'],
  params: {
    samples: { default: 120, min: 40, max: 200, step: 10, label: { en: 'Trace detail', ar: 'دقّة خطّ الإشارة' } },
    severity: { default: 0.8, min: 0.2, max: 1, step: 0.05, label: { en: 'Incident severity', ar: 'شدّة الحادث' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'none', cost: 'low' },
  still: 0.55,
  tags: ['dashboard', 'monitoring', 'status', 'alert', 'operations', 'live'],
  setup: dom({
    build(root, ctx) {
      const document = root.ownerDocument;
      const view = svg(document, 'svg', { viewBox: '0 0 320 180', width: '100%', height: '100%', preserveAspectRatio: 'xMidYMid meet', 'aria-hidden': 'true' });
      for (let line = 0; line <= 6; line += 1) view.appendChild(svg(document, 'line', { x1: 20, x2: 220, y1: 30 + line * 20, y2: 30 + line * 20, stroke: ctx.css[3], 'stroke-width': 1 }));
      for (let line = 0; line <= 10; line += 1) view.appendChild(svg(document, 'line', { x1: 20 + line * 20, x2: 20 + line * 20, y1: 30, y2: 150, stroke: ctx.css[3], 'stroke-width': 1 }));
      const trace = view.appendChild(svg(document, 'polyline', { fill: 'none', 'stroke-width': 2, 'stroke-linejoin': 'round' }));
      const head = view.appendChild(svg(document, 'circle', { r: 3.5, cx: 220 }));
      view.appendChild(svg(document, 'circle', { cx: 270, cy: 90, r: 30, fill: 'none', stroke: ctx.css[3], 'stroke-width': 8 }));
      const ring = view.appendChild(svg(document, 'circle', { cx: 270, cy: 90, r: 30, fill: 'none', 'stroke-width': 8, 'stroke-linecap': 'round', transform: 'rotate(-90 270 90)', pathLength: 100 }));
      const dot = view.appendChild(svg(document, 'circle', { cx: 270, cy: 90, r: 7 }));
      root.append(view);
      return { trace, head, ring, dot, samples: Math.round(ctx.params.samples) };
    },
    apply(refs, s, ctx) {
      // The incident: rises at 40% of the cycle, peaks, and is resolved by 75%.
      const incident = smoothstep(0.35, 0.45, s.raw) * (1 - smoothstep(0.62, 0.75, s.raw)) * ctx.params.severity;
      const points = [];
      for (let n = 0; n <= refs.samples; n += 1) {
        const x = n / refs.samples;
        const y = 90 - signal(x, s.t, incident) * 45 * s.intro;
        points.push(`${(20 + x * 200).toFixed(1)},${clamp(y, 24, 156).toFixed(1)}`);
      }
      const alert = incident > 0.15;
      const colour = alert ? ctx.css[2] : ctx.css[1];
      refs.trace.setAttribute('points', points.join(' '));
      refs.trace.setAttribute('stroke', colour);
      refs.head.setAttribute('cy', points.at(-1).split(',')[1]);
      refs.head.setAttribute('fill', colour);
      const availability = 99.9 - incident * 35;
      refs.ring.setAttribute('stroke', colour);
      refs.ring.setAttribute('stroke-dasharray', `${(availability * s.intro).toFixed(2)} 100`);
      refs.dot.setAttribute('fill', colour);
      refs.dot.setAttribute('r', (6 + 2 * Math.sin(s.t * (alert ? 12 : 4))).toFixed(2));
    },
  }),
});
