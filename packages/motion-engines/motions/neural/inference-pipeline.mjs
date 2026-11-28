import { defineMotion } from '../../core/define.mjs';
import { canvas2d } from '../../engines/canvas2d.mjs';
import { TAU, clamp, mixColour, rgba, smoothstep } from '../../core/util.mjs';

// A small feed-forward network: layer sizes and fixed, seeded weights between neighbours.
function networkOf(random, hidden) {
  const sizes = [5, hidden, hidden, 3];
  const weights = sizes.slice(1).map((size, layer) => Array.from({ length: size }, () => Array.from({ length: sizes[layer] }, () => random() * 2 - 1)));
  return { sizes, weights };
}

// Activations of every layer for one input case, computed exactly (tanh hidden, softmax-like output).
function activate(network, input) {
  const values = [input];
  network.weights.forEach((layer, index) => {
    const before = values[index];
    const out = layer.map((row) => Math.tanh(row.reduce((sum, weight, n) => sum + weight * before[n], 0) * 1.4));
    values.push(index === network.weights.length - 1 ? out.map((v) => (v + 1) / 2) : out.map((v) => Math.abs(v)));
  });
  return values;
}

export default defineMotion({
  id: 'neural-inference-pipeline',
  number: 48,
  module: 'neural',
  name: { en: 'AI Inference Pipeline', ar: 'مسار الاستدلال بالذكاء الاصطناعي' },
  summary: {
    en: 'Incoming cases enter a model one after another. Each case is a column of input values; the signal passes layer by layer through the network, every connection glowing by its weight, and the strongest output is chosen as the decision and handed on.',
    ar: 'حالاتٌ واردة تدخل نموذجًا واحدةً بعد أخرى. كلّ حالةٍ عمودٌ من القيم المدخلة؛ تعبر الإشارة الشبكة طبقةً طبقة، وتتوهّج كلّ وصلةٍ بقدر وزنها، ثم يُختار أقوى مُخرَجٍ قرارًا ويُسلَّم إلى ما بعده.',
  },
  meaning: {
    en: 'AI inference: input data goes into a trained model, passes through its layers and comes out as one decision.',
    ar: 'الاستدلال بالذكاء الاصطناعي: تدخل البيانات نموذجًا مدرَّبًا وتعبر طبقاته ثم تخرج قرارًا واحدًا.',
  },
  engine: 'canvas2d',
  kind: 'loop',
  duration: 7500,
  easing: 'ease-out',
  colors: ['#060a16', '#38bdf8', '#a78bfa', '#22c55e', '#e2e8f0'],
  params: {
    cases: { default: 3, min: 1, max: 5, step: 1, label: { en: 'Cases per cycle', ar: 'عدد الحالات في كل دورة' } },
    hidden: { default: 6, min: 3, max: 9, step: 1, label: { en: 'Neurons per hidden layer', ar: 'عدد العصبونات في كل طبقة مخفيّة' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'none', cost: 'low' },
  still: 0.3,
  tags: ['ai', 'model', 'inference', 'decision', 'pipeline', 'explainer'],
  setup: canvas2d({
    init(ctx) {
      const random = ctx.random(48);
      const network = networkOf(random, Math.round(ctx.params.hidden));
      const inputs = Array.from({ length: 5 }, () => Array.from({ length: 5 }, () => random()));
      return { network, runs: inputs.map((input) => activate(network, input)) };
    },
    draw(g, s, ctx, { network, runs }) {
      const { width: w, height: h } = ctx;
      const cases = Math.round(ctx.params.cases);
      const position = s.raw * cases;
      const current = Math.min(cases - 1, Math.floor(position));
      const local = position - current;
      const values = runs[current];
      const { sizes } = network;
      const left = w * 0.2;
      const right = w * 0.8;
      const xs = sizes.map((_, layer) => left + ((right - left) * layer) / (sizes.length - 1));
      const ys = sizes.map((size) => Array.from({ length: size }, (_, n) => h * 0.5 + (n - (size - 1) / 2) * Math.min(h * 0.13, (h * 0.78) / size)));
      // The signal front moves across the layers during the first 70% of each case.
      const front = clamp(local / 0.7) * (sizes.length - 1);
      const radius = Math.min(w, h) * 0.028;
      // Connections, glowing once the signal has passed them.
      network.weights.forEach((layer, index) => {
        const lit = clamp(front - index);
        layer.forEach((row, to) => row.forEach((weight, from) => {
          const strength = Math.abs(weight) * values[index][from];
          g.strokeStyle = rgba(weight > 0 ? ctx.colors[1] : ctx.colors[2], (0.06 + 0.5 * strength * lit) * s.intro);
          g.lineWidth = 0.6 + 1.4 * strength * lit;
          g.beginPath();
          g.moveTo(xs[index], ys[index][from]);
          g.lineTo(xs[index] + (xs[index + 1] - xs[index]) * (lit > 0 ? 1 : 0.0001), ys[index][from] + (ys[index + 1][to] - ys[index][from]) * (lit > 0 ? 1 : 0.0001));
          g.stroke();
        }));
        // The pulse travelling along this layer's connections.
        if (lit > 0 && lit < 1) {
          g.fillStyle = rgba(ctx.colors[4], 0.9);
          for (let to = 0; to < layer.length; to += 1) {
            const from = to % sizes[index];
            g.beginPath();
            g.arc(xs[index] + (xs[index + 1] - xs[index]) * lit, ys[index][from] + (ys[index + 1][to] - ys[index][from]) * lit, 1.6, 0, TAU);
            g.fill();
          }
        }
      });
      // Neurons, brightness by activation once reached.
      const output = values[sizes.length - 1];
      const decision = output.indexOf(Math.max(...output));
      sizes.forEach((size, layer) => {
        for (let n = 0; n < size; n += 1) {
          const reached = clamp(front - layer + 1);
          const level = values[layer][n] * reached;
          const chosen = layer === sizes.length - 1 && n === decision && local > 0.72;
          g.fillStyle = rgba(mixColour(mixColour(ctx.colors[0], ctx.colors[1], 0.35), chosen ? ctx.colors[3] : ctx.colors[4], 0.15 + 0.85 * level), 1);
          g.beginPath();
          g.arc(xs[layer], ys[layer][n], radius * (chosen ? 1.5 : 1), 0, TAU);
          g.fill();
        }
      });
      // The input case arrives from the side as a column of bars; the decision leaves on the other.
      const arrive = smoothstep(0, 0.12, local);
      values[0].forEach((value, n) => {
        g.fillStyle = rgba(ctx.colors[1], 0.8 * arrive);
        g.fillRect(xs[0] - radius * 3 - value * w * 0.08 - (1 - arrive) * w * 0.1, ys[0][n] - radius * 0.6, value * w * 0.08, radius * 1.2);
      });
      const leave = smoothstep(0.72, 0.95, local);
      if (leave > 0) {
        const y = ys[sizes.length - 1][decision];
        const x = xs[sizes.length - 1] + radius * 2.5 + leave * w * 0.06;
        g.fillStyle = rgba(ctx.colors[3], leave);
        g.beginPath();
        g.roundRect(x, y - radius * 1.3, w * 0.1, radius * 2.6, radius);
        g.fill();
        g.strokeStyle = rgba(ctx.colors[0], leave);
        g.lineWidth = 2;
        g.beginPath();
        g.moveTo(x + w * 0.03, y);
        g.lineTo(x + w * 0.045, y + radius * 0.7);
        g.lineTo(x + w * 0.07, y - radius * 0.7);
        g.stroke();
      }
      // Case counter: one dot per case in this cycle.
      for (let n = 0; n < cases; n += 1) {
        g.fillStyle = rgba(n === current ? ctx.colors[3] : ctx.colors[4], n <= current ? 0.9 : 0.25);
        g.beginPath();
        g.arc(w / 2 + (n - (cases - 1) / 2) * 10, h * 0.94, 2.5, 0, TAU);
        g.fill();
      }
    },
  }),
});
