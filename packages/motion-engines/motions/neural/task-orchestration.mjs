import { defineMotion } from '../../core/define.mjs';
import { canvas2d } from '../../engines/canvas2d.mjs';
import { TAU, clamp, lerp, mixColour, rgba, smoothstep } from '../../core/util.mjs';

// Where one task card is at local time u (0..1 of its own trip): queue, agent, gate, then done or back.
function trip(u, lanes, layout, rejected) {
  const { queueX, agentX, gateX, doneX, laneY } = layout;
  const lane = laneY[lanes];
  if (u < 0.25) return { x: lerp(queueX, agentX, smoothstep(0, 0.25, u)), y: lerp(layout.midY, lane, smoothstep(0, 0.25, u)), phase: 'to-agent' };
  if (u < 0.45) return { x: agentX, y: lane, phase: 'working', work: (u - 0.25) / 0.2 };
  if (u < 0.6) return { x: lerp(agentX, gateX - layout.card, smoothstep(0.45, 0.6, u)), y: lerp(lane, layout.midY, smoothstep(0.45, 0.6, u)), phase: 'to-gate' };
  if (u < 0.75) return { x: gateX - layout.card, y: layout.midY, phase: 'waiting', wait: (u - 0.6) / 0.15 };
  const out = smoothstep(0.75, 1, u);
  if (rejected) return { x: lerp(gateX - layout.card, agentX, out), y: lerp(layout.midY, layout.laneY[0] - layout.card * 1.5, out), phase: 'returned', out };
  return { x: lerp(gateX - layout.card, doneX, out), y: layout.midY, phase: 'done', out };
}

export default defineMotion({
  id: 'neural-task-orchestration',
  number: 47,
  module: 'neural',
  name: { en: 'Agent Task Orchestration', ar: 'تنسيق مهام الوكلاء' },
  summary: {
    en: 'Task cards leave a queue and are shared out to three AI agents, whose rings fill as they work. Every finished card then waits at a gate until a reviewer approves it: approved cards pass to done with a tick, and one card in each round is sent back with a cross.',
    ar: 'بطاقات مهامٍ تغادر قائمة الانتظار وتُوزَّع على ثلاثة وكلاء ذكاءٍ اصطناعي تمتلئ حلقاتهم وهم يعملون. ثم تنتظر كلّ بطاقةٍ منجزة عند بوابةٍ حتى يعتمدها مراجعٌ بشري: البطاقات المعتمدة تعبر إلى المنجز بعلامة صح، وتُعاد بطاقةٌ واحدة في كل جولة بعلامة خطأ.',
  },
  meaning: {
    en: 'Human approval gate: AI agents do the work, but nothing is released until a person approves it.',
    ar: 'بوابة الاعتماد البشري: ينجز وكلاء الذكاء الاصطناعي العمل، لكن لا يُعتمد شيءٌ حتى يوافق عليه إنسان.',
  },
  engine: 'canvas2d',
  kind: 'loop',
  duration: 9000,
  easing: 'ease-out',
  colors: ['#070b18', '#818cf8', '#22c55e', '#f43f5e', '#e2e8f0'],
  params: {
    tasks: { default: 5, min: 2, max: 8, step: 1, label: { en: 'Tasks per round', ar: 'عدد المهام في كل جولة' } },
    spacing: { default: 0.12, min: 0.05, max: 0.2, step: 0.01, label: { en: 'Gap between tasks', ar: 'الفاصل بين المهام' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'none', cost: 'low' },
  still: 0.62,
  tags: ['ai', 'agents', 'workflow', 'approval', 'human-in-the-loop', 'governance'],
  setup: canvas2d({
    draw(g, s, ctx) {
      const { width: w, height: h } = ctx;
      const card = Math.min(w, h) * 0.06;
      const layout = { queueX: w * 0.08, agentX: w * 0.36, gateX: w * 0.66, doneX: w * 0.9, midY: h * 0.52, laneY: [h * 0.24, h * 0.52, h * 0.8], card };
      const intro = 0.3 + 0.7 * s.intro;
      // Agents: rings on three lanes. The gate: two posts with a reviewer above.
      const tasks = Math.round(ctx.params.tasks);
      const span = 1 - ctx.params.spacing * (tasks - 1);
      const trips = Array.from({ length: tasks }, (_, n) => ({ n, u: clamp((s.raw - n * ctx.params.spacing) / Math.max(0.2, span)), lane: n % 3, rejected: n === 1 }));
      layout.laneY.forEach((y, lane) => {
        const working = trips.map((item) => ({ item, at: trip(item.u, item.lane, layout, item.rejected) })).find(({ item, at }) => item.lane === lane && at.phase === 'working');
        g.strokeStyle = rgba(ctx.colors[1], 0.3 * intro);
        g.lineWidth = 3;
        g.beginPath();
        g.arc(layout.agentX, y, card * 1.6, 0, TAU);
        g.stroke();
        if (working) {
          g.strokeStyle = rgba(ctx.colors[1], intro);
          g.beginPath();
          g.arc(layout.agentX, y, card * 1.6, -Math.PI / 2, -Math.PI / 2 + TAU * working.at.work);
          g.stroke();
        }
        g.fillStyle = rgba(ctx.colors[1], 0.8 * intro);
        g.beginPath();
        g.arc(layout.agentX, y, card * 0.5, 0, TAU);
        g.fill();
      });
      const waiting = trips.some((item) => trip(item.u, item.lane, layout, item.rejected).phase === 'waiting');
      const gateTop = h * 0.36;
      const gateBottom = h * 0.68;
      g.fillStyle = rgba(ctx.colors[4], 0.7 * intro);
      g.fillRect(layout.gateX - 2, gateTop, 4, gateBottom - gateTop);
      // The reviewer: head and shoulders above the gate, highlighted while a card waits.
      const reviewer = waiting ? ctx.colors[2] : ctx.colors[4];
      g.fillStyle = rgba(reviewer, intro);
      g.beginPath();
      g.arc(layout.gateX, gateTop - card * 1.8, card * 0.5, 0, TAU);
      g.fill();
      g.beginPath();
      g.ellipse(layout.gateX, gateTop - card * 0.5, card * 0.9, card * 0.6, 0, Math.PI, TAU);
      g.fill();
      // Columns: queue and done.
      g.strokeStyle = rgba(ctx.colors[4], 0.2);
      g.lineWidth = 1;
      g.strokeRect(layout.queueX - card * 1.3, h * 0.12, card * 2.6, h * 0.8);
      g.strokeRect(layout.doneX - card * 1.3, h * 0.12, card * 2.6, h * 0.8);
      // Cards.
      for (const item of trips) {
        const at = item.u <= 0 ? { x: layout.queueX, y: layout.midY - (item.n - tasks / 2) * card * 0.5, phase: 'queued' } : trip(item.u, item.lane, layout, item.rejected);
        let colour = ctx.colors[4];
        if (at.phase === 'done') colour = mixColour(ctx.colors[4], ctx.colors[2], at.out);
        if (at.phase === 'returned') colour = mixColour(ctx.colors[4], ctx.colors[3], at.out);
        const alpha = at.phase === 'returned' ? 1 - at.out * 0.6 : 1;
        g.fillStyle = rgba(colour, alpha * intro);
        g.beginPath();
        g.roundRect(at.x - card, at.y - card * 0.7, card * 2, card * 1.4, card * 0.25);
        g.fill();
        g.fillStyle = rgba(ctx.colors[0], 0.5 * alpha);
        g.fillRect(at.x - card * 0.7, at.y - card * 0.25, card * 1.2, card * 0.18);
        g.fillRect(at.x - card * 0.7, at.y + card * 0.1, card * 0.8, card * 0.18);
        if (at.phase === 'waiting' && at.wait > 0.6) {
          g.strokeStyle = rgba(item.rejected ? ctx.colors[3] : ctx.colors[2], 1);
          g.lineWidth = 2;
          g.beginPath();
          if (item.rejected) {
            g.moveTo(at.x + card * 0.6, at.y - card * 1.4);
            g.lineTo(at.x + card * 1.2, at.y - card * 0.8);
            g.moveTo(at.x + card * 1.2, at.y - card * 1.4);
            g.lineTo(at.x + card * 0.6, at.y - card * 0.8);
          } else {
            g.moveTo(at.x + card * 0.5, at.y - card * 1.1);
            g.lineTo(at.x + card * 0.8, at.y - card * 0.8);
            g.lineTo(at.x + card * 1.3, at.y - card * 1.4);
          }
          g.stroke();
        }
      }
    },
  }),
});
