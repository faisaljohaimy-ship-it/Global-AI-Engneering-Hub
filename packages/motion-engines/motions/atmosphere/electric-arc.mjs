import { defineMotion } from '../../core/define.mjs';
import { canvas2d } from '../../engines/canvas2d.mjs';
import { TAU, mixColour, rgba } from '../../core/util.mjs';

// A repeatable random number for one arc, one strike and one purpose.
const pick = (seed, a, b, c) => {
  const s = Math.sin(seed + a * 127.1 + b * 311.7 + c * 74.7) * 43758.5453;
  return s - Math.floor(s);
};
// Noise with corners, -0.5..0.5: straight runs between random knots, as a discharge has.
const zig = (x, seed) => {
  const knot = Math.floor(x);
  const from = pick(seed, knot, 1, 0);
  return from + (pick(seed, knot + 1, 1, 0) - from) * (x - knot) - 0.5;
};

export default defineMotion({
  id: 'atmosphere-electric-arc',
  number: 172,
  module: 'atmosphere',
  name: { en: 'Electric Energy Arc', ar: 'قوس الطاقة الكهربائي' },
  summary: {
    en: 'Arcs leap between two electrodes, fork into branches that die in the air, and strike again on a new path many times a second while sparks fly from the tips.',
    ar: 'أقواس كهربائية تقفز بين قطبين وتتفرّع إلى شُعَب تخبو في الهواء، ثم تضرب من جديد في مسار مختلف عدة مرات في الثانية والشرر يتطاير من الطرفين.',
  },
  engine: 'canvas2d',
  kind: 'loop',
  duration: 4000,
  easing: 'ease-out',
  colors: ['#05060f', '#5b7cff', '#e4f1ff', '#8c96ad', '#ffb561'],
  params: {
    arcs: { default: 2, min: 1, max: 4, step: 1, label: { en: 'Arcs', ar: 'عدد الأقواس' } },
    branches: { default: 4, min: 0, max: 8, step: 1, label: { en: 'Branches per arc', ar: 'الشُّعَب في كل قوس' } },
    chaos: { default: 1, min: 0.3, max: 2, step: 0.05, label: { en: 'Jaggedness', ar: 'شدة التعرّج' } },
    rate: { default: 6, min: 2, max: 14, step: 1, label: { en: 'Strikes per second', ar: 'عدد الضربات في الثانية' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'none', cost: 'low' },
  still: 0.5,
  tags: ['energy', 'electric', 'accent', 'loading', 'science'],
  setup: canvas2d({
    init(ctx) {
      const random = ctx.random(172);
      const sparks = Array.from({ length: ctx.count(40, 12) }, () => ({ side: random() < 0.5 ? 0 : 1, angle: (random() - 0.5) * 2.6, speed: 0.35 + random() * 0.9, offset: random(), rate: 0.8 + random() * 1.4 }));
      return { seed: random() * 900, sparks, steps: ctx.count(56, 20), twigs: ctx.count(14, 6) };
    },
    draw(g, s, ctx, data) {
      const { width: w, height: h, colors } = ctx;
      const unit = Math.min(w, h);
      const wide = w >= h;
      const [ax, ay, bx, by] = wide ? [w * 0.16, h * 0.56, w * 0.84, h * 0.56] : [w * 0.5, h * 0.84, w * 0.5, h * 0.16];
      const gap = Math.hypot(bx - ax, by - ay);
      const [nx, ny] = [(bx - ax) / gap, (by - ay) / gap];
      const [px, py] = wide ? [0, -1] : [1, 0];
      const radius = unit * 0.07;
      const reach = Math.min(gap * 0.19, unit * 0.34) * ctx.params.chaos;
      const arcs = [];
      let power = 0;
      for (let k = 0; k < Math.round(ctx.params.arcs); k += 1) {
        const beat = s.t * ctx.params.rate * (1 - k * 0.13) + pick(data.seed, k, 0, 9) * 7;
        const strike = Math.floor(beat);
        const level = (0.45 + 0.55 * Math.exp(-(beat - strike) * 5)) * (0.86 + 0.14 * Math.sin(s.t * 83 + k * 2.1));
        const bow = (pick(data.seed, k, strike, 1) - 0.5) * 1.5 + (wide ? 0.35 : 0);
        const lean = (pick(data.seed, k, strike, 2) - 0.5) * 1.1;
        const [sx, sy] = [ax + (nx * Math.cos(lean) + px * Math.sin(lean)) * radius, ay + (ny * Math.cos(lean) + py * Math.sin(lean)) * radius];
        const [ex, ey] = [bx - (nx * Math.cos(lean) - px * Math.sin(lean)) * radius, by - (ny * Math.cos(lean) - py * Math.sin(lean)) * radius];
        const points = [];
        for (let i = 0; i <= data.steps; i += 1) {
          const u = i / data.steps;
          let jag = 0;
          for (let octave = 0; octave < 4; octave += 1) jag += zig(u * [4, 9, 19, 41][octave] + s.t * (1 + octave), data.seed + strike * 13.7 + k * 101.3 + octave * 7.9) / (1 << octave);
          const off = Math.sin(Math.PI * u) ** 0.7 * reach * (bow + jag * 1.9);
          points.push([sx + (ex - sx) * u + px * off, sy + (ey - sy) * u + py * off]);
        }
        const twigs = [];
        for (let j = 0; j < Math.round(ctx.params.branches); j += 1) {
          const from = points[Math.floor((0.12 + 0.76 * pick(data.seed + j, k, strike, 3)) * data.steps)];
          const turn = (0.35 + 0.75 * pick(data.seed + j, k, strike, 4)) * (pick(data.seed + j, k, strike, 5) < 0.5 ? -1 : 1);
          const [dx, dy] = [nx * Math.cos(turn) - ny * Math.sin(turn), nx * Math.sin(turn) + ny * Math.cos(turn)];
          const length = gap * (0.1 + 0.2 * pick(data.seed + j, k, strike, 6));
          const twig = [from];
          for (let m = 1; m <= data.twigs; m += 1) {
            const v = m / data.twigs;
            const wander = (zig(v * 5 + s.t * 2, data.seed + strike * 7.3 + j * 31.1 + k * 3.7) + 0.5 * zig(v * 11, data.seed + strike + j)) * length * 0.5 * ctx.params.chaos * v;
            twig.push([from[0] + dx * length * v - dy * wander, from[1] + dy * length * v + dx * wander]);
          }
          twigs.push(twig);
        }
        arcs.push({ points, twigs, level, sx, sy, ex, ey });
        power += level / Math.round(ctx.params.arcs);
      }
      const shown = s.intro;
      // Air lit by the discharge.
      const air = g.createRadialGradient(w / 2, h / 2, 0, w / 2, h / 2, Math.max(w, h) * 0.6);
      air.addColorStop(0, rgba(colors[1], 0.2 * power * shown));
      air.addColorStop(1, rgba(colors[1], 0));
      g.fillStyle = air;
      g.fillRect(0, 0, w, h);
      // The electrodes: a rod from the edge of the frame ending in a ball.
      for (const [cx, cy, sign] of [[ax, ay, -1], [bx, by, 1]]) {
        const [rx, ry] = [cx + nx * sign * gap, cy + ny * sign * gap];
        const rod = g.createLinearGradient(cx - px * radius * 0.45, cy - py * radius * 0.45, cx + px * radius * 0.45, cy + py * radius * 0.45);
        rod.addColorStop(0, rgba(mixColour(colors[0], colors[3], 0.25)));
        rod.addColorStop(0.45, rgba(mixColour(colors[3], colors[2], 0.2 * power)));
        rod.addColorStop(1, rgba(mixColour(colors[0], colors[3], 0.15)));
        g.strokeStyle = rod;
        g.lineWidth = radius * 0.9;
        g.beginPath();
        g.moveTo(cx, cy);
        g.lineTo(rx, ry);
        g.stroke();
        const ball = g.createRadialGradient(cx - nx * sign * radius * 0.5, cy - ny * sign * radius * 0.5, radius * 0.1, cx, cy, radius);
        ball.addColorStop(0, rgba(mixColour(colors[3], colors[2], 0.35 + 0.6 * power * shown)));
        ball.addColorStop(0.55, rgba(colors[3]));
        ball.addColorStop(1, rgba(mixColour(colors[0], colors[3], 0.3)));
        g.fillStyle = ball;
        g.beginPath();
        g.arc(cx, cy, radius, 0, TAU);
        g.fill();
      }
      g.globalCompositeOperation = 'lighter';
      g.lineCap = 'round';
      g.lineJoin = 'round';
      const trace = (line, upTo) => {
        g.beginPath();
        g.moveTo(line[0][0], line[0][1]);
        for (let index = 1; index <= Math.min(upTo, line.length - 1); index += 1) g.lineTo(line[index][0], line[index][1]);
      };
      for (const arc of arcs) {
        const upTo = Math.ceil(shown * data.steps);
        for (const [width, colour, alpha] of [[0.085, colors[1], 0.1], [0.032, colors[1], 0.32], [0.011, colors[2], 1]]) {
          g.lineWidth = unit * width * (0.7 + 0.3 * arc.level);
          g.strokeStyle = rgba(colour, alpha * arc.level);
          trace(arc.points, upTo);
          g.stroke();
          if (shown < 1) continue;
          for (const twig of arc.twigs) {
            const [last] = twig.slice(-1);
            const fade = g.createLinearGradient(twig[0][0], twig[0][1], last[0], last[1]);
            fade.addColorStop(0, rgba(colour, alpha * arc.level * 0.8));
            fade.addColorStop(1, rgba(colour, 0));
            g.strokeStyle = fade;
            g.lineWidth = unit * width * 0.55;
            trace(twig, twig.length);
            g.stroke();
          }
        }
        for (const [x, y] of [[arc.sx, arc.sy], [arc.ex, arc.ey]].slice(0, shown < 1 ? 1 : 2)) {
          const flare = g.createRadialGradient(x, y, 0, x, y, radius * 1.5);
          flare.addColorStop(0, rgba(colors[2], 0.9 * arc.level));
          flare.addColorStop(0.3, rgba(colors[1], 0.45 * arc.level));
          flare.addColorStop(1, rgba(colors[1], 0));
          g.fillStyle = flare;
          g.fillRect(x - radius * 1.5, y - radius * 1.5, radius * 3, radius * 3);
        }
      }
      // Sparks thrown from the tips fall away and cool.
      g.lineWidth = Math.max(0.7, unit * 0.006);
      for (const spark of data.sparks) {
        const life = (s.t * spark.rate + spark.offset) % 1;
        const sign = spark.side ? -1 : 1;
        const [cx, cy] = spark.side ? [bx, by] : [ax, ay];
        const heading = [(nx * Math.cos(spark.angle) - ny * Math.sin(spark.angle)) * sign, (nx * Math.sin(spark.angle) + ny * Math.cos(spark.angle)) * sign];
        const at = (time) => [cx + heading[0] * (radius + unit * 0.42 * spark.speed * time), cy + heading[1] * (radius + unit * 0.42 * spark.speed * time) + unit * 0.3 * time * time];
        const [head, tail] = [at(life), at(Math.max(0, life - 0.06))];
        g.strokeStyle = rgba(mixColour(colors[4], colors[2], 1 - life), (1 - life) ** 1.5 * power * shown);
        g.beginPath();
        g.moveTo(tail[0], tail[1]);
        g.lineTo(head[0], head[1]);
        g.stroke();
      }
    },
  }),
});
