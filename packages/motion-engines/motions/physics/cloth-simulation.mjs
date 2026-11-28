import { defineMotion } from '../../core/define.mjs';
import { canvas2d } from '../../engines/canvas2d.mjs';
import { clamp, mixColour, rgba, smoothstep } from '../../core/util.mjs';
import { fittedCamera } from './lib/scene.mjs';
import { timeline } from './lib/timeline.mjs';

const SECONDS = 5; // simulated time behind the whole timeline
const STEP = 1 / 60;
const LIGHT = [-0.36, 0.52, 0.77];
const WIND = [0.38, 0.06, 0.92];
const WALL = -0.4;

/** Verlet cloth: particles joined by stretch, shear and bend links, pinned along the top row. */
function simulate(ctx) {
  const tall = 1.25;
  const wide = clamp(tall * (ctx.width / ctx.height) * 0.74, 0.8, 2.4);
  const rows = ctx.count(16, 9);
  const cols = Math.max(6, Math.round(((rows - 1) * wide) / tall) + 1);
  const total = cols * rows;
  const [dx, dy] = [wide / (cols - 1), tall / (rows - 1)];
  const slack = ctx.params.slack;
  // Gathered on the rail, the cloth is narrower than its fabric: the spare width hangs as pleats.
  const turn = (2 * Math.PI * Math.max(2, Math.round(wide / 0.45))) / (cols - 1);
  const pleat = (dx * Math.sqrt(2 * (2 * slack - slack * slack))) / turn;
  const at = new Float64Array(total * 3);
  for (let k = 0; k < total; k += 1) at.set([((k % cols) / (cols - 1) - 0.5) * wide * (1 - slack), tall / 2 - Math.floor(k / cols) * dy, pleat * Math.sin((k % cols) * turn)], k * 3);
  const before = at.slice();
  const links = [];
  const link = (a, b, stiffness) => links.push([a, b, Math.hypot(((a % cols) - (b % cols)) * dx, (Math.floor(a / cols) - Math.floor(b / cols)) * dy), stiffness]);
  for (let k = 0; k < total; k += 1) {
    const [c, r] = [k % cols, Math.floor(k / cols)];
    if (c + 1 < cols) link(k, k + 1, 1);
    if (r + 1 < rows) link(k, k + cols, 1);
    if (c + 1 < cols && r + 1 < rows) link(k, k + cols + 1, 0.7), link(k + 1, k + cols, 0.7);
    if (c + 2 < cols) link(k, k + 2, 0.22);
    if (r + 2 < rows) link(k, k + 2 * cols, 0.22);
  }
  const steps = Math.round(SECONDS / STEP);
  const states = timeline(steps / 2 + 1, total * 3);
  states.write(0, at);
  const normal = [0, 0, 1];
  for (let step = 1; step <= steps; step += 1) {
    const t = step * STEP;
    const gust = ctx.params.wind * 7.5 * smoothstep(0.2, 0.85, t) * (1 - smoothstep(1.6, 2.9, t));
    const keep = 0.992 - 0.05 * smoothstep(3.5, SECONDS, t);
    for (let k = cols; k < total; k += 1) {
      const [c, r, i] = [k % cols, Math.floor(k / cols), k * 3];
      const [e, w, n, s] = [(c + 1 < cols ? k + 1 : k) * 3, (c > 0 ? k - 1 : k) * 3, (k - cols) * 3, (r + 1 < rows ? k + cols : k) * 3];
      const [ux, uy, uz, vx, vy, vz] = [at[e] - at[w], at[e + 1] - at[w + 1], at[e + 2] - at[w + 2], at[s] - at[n], at[s + 1] - at[n + 1], at[s + 2] - at[n + 2]];
      normal[0] = uy * vz - uz * vy;
      normal[1] = uz * vx - ux * vz;
      normal[2] = ux * vy - uy * vx;
      const size = Math.hypot(normal[0], normal[1], normal[2]) || 1;
      // The air pushes along the cloth's normal, by how fast the air meets it: a sail, not a rigid sheet.
      const puff = gust * (1 + 0.4 * Math.sin(2.6 * at[i] + 1.9 * at[i + 1] - 7 * t));
      let meet = 0;
      for (let axis = 0; axis < 3; axis += 1) meet += (normal[axis] / size) * (WIND[axis] * puff - (at[i + axis] - before[i + axis]) / STEP);
      for (let axis = 0; axis < 3; axis += 1) {
        const here = at[i + axis];
        const push = (normal[axis] / size) * meet * 2.2 - (axis === 1 ? 9.8 : 0);
        at[i + axis] = here + (here - before[i + axis]) * keep + push * STEP * STEP;
        before[i + axis] = here;
      }
    }
    for (let pass = 0; pass < 5; pass += 1) {
      for (const [a, b, rest, stiffness] of links) {
        const [i, j] = [a * 3, b * 3];
        const [lx, ly, lz] = [at[j] - at[i], at[j + 1] - at[i + 1], at[j + 2] - at[i + 2]];
        const [freeA, freeB] = [a >= cols ? 1 : 0, b >= cols ? 1 : 0];
        if (freeA + freeB === 0) continue;
        const pull = ((1 - rest / (Math.hypot(lx, ly, lz) || 1)) * stiffness) / (freeA + freeB);
        at[i] += lx * pull * freeA; at[i + 1] += ly * pull * freeA; at[i + 2] += lz * pull * freeA;
        at[j] -= lx * pull * freeB; at[j + 1] -= ly * pull * freeB; at[j + 2] -= lz * pull * freeB;
      }
    }
    if (step % 2 === 0) states.write(step / 2, at);
  }
  return { cols, rows, total, wide, tall, slack, states };
}

export default defineMotion({
  id: 'physics-cloth-simulation',
  number: 121,
  module: 'physics',
  name: { en: 'Cloth Simulation', ar: 'محاكاة القماش' },
  summary: {
    en: 'A striped cloth pinned along its top edge hangs in pleats, billows when a gust hits it, then swings back and settles. Verlet particles with stretch, shear and bend links.',
    ar: 'قطعة قماش مخطّطة مثبّتة من حافتها العليا تتدلّى في طيّات، تنتفخ حين تضربها هبّة ريح ثم تتأرجح عائدةً حتى تسكن. جسيمات Verlet تربطها قيود الشدّ والقصّ والانحناء.',
  },
  engine: 'canvas2d',
  kind: 'oneshot',
  duration: 5000,
  easing: 'linear',
  colors: ['#20263a', '#d9482b', '#f4c95d', '#fff1d0', '#8b96ad'],
  params: {
    wind: { default: 1, min: 0.3, max: 2, step: 0.05, label: { en: 'Gust strength', ar: 'شدة هبّة الريح' } },
    slack: { default: 0.12, min: 0, max: 0.3, step: 0.01, label: { en: 'Gathered fabric', ar: 'مقدار القماش المجموع' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'none', cost: 'medium' },
  still: 0.36,
  tags: ['physics', 'simulation', 'fabric', 'hero', 'reveal'],
  setup: canvas2d({
    init(ctx) {
      const cloth = simulate(ctx);
      const [x, y] = [(cloth.wide / 2) * 1.04, cloth.tall / 2];
      const view = fittedCamera({
        eye: [cloth.wide * 0.3, -0.12, 3.4], target: [0, -0.05, 0], fov: 38, width: ctx.width, height: ctx.height,
        corners: [[-x, y + 0.05, 0], [x, y + 0.05, 0], [-x, -y, 0], [x, -y, 0], [-x, -y * 0.2, 0.62], [x * 1.12, -y * 0.2, 0.62]],
      });
      const quads = (cloth.cols - 1) * (cloth.rows - 1);
      return { ...cloth, view, quads, screen: new Float32Array(cloth.total * 3), cast: new Float32Array(cloth.total * 3), order: Array.from({ length: quads }, (_, q) => q), depth: new Float32Array(quads) };
    },
    draw(g, s, ctx, cloth) {
      const { cols, rows, total, view, screen, cast, order, depth } = cloth;
      const p = cloth.states.read(s.progress);
      for (let k = 0; k < total; k += 1) {
        const [x, y, z] = [p[k * 3], p[k * 3 + 1], p[k * 3 + 2]];
        view.project(x, y, z, screen, k * 3);
        const fall = (z - WALL) / LIGHT[2];
        view.project(x - LIGHT[0] * fall, y - LIGHT[1] * fall, WALL, cast, k * 3);
      }
      const corner = (q) => {
        const k = Math.floor(q / (cols - 1)) * cols + (q % (cols - 1));
        return [k, k + 1, k + cols + 1, k + cols];
      };
      const trace = (points, [a, b, c, d]) => {
        g.beginPath();
        g.moveTo(points[a * 3], points[a * 3 + 1]);
        for (const k of [b, c, d]) g.lineTo(points[k * 3], points[k * 3 + 1]);
        g.closePath();
      };
      // The shadow on the wall behind: every quad in one flat tone, so overlaps do not show.
      g.fillStyle = g.strokeStyle = rgba(ctx.colors[0].map((channel) => channel * 0.62));
      g.lineWidth = 0.8;
      for (let q = 0; q < cloth.quads; q += 1) {
        trace(cast, corner(q));
        g.fill();
        g.stroke();
        depth[q] = corner(q).reduce((sum, k) => sum + screen[k * 3 + 2], 0);
      }
      order.sort((a, b) => depth[b] - depth[a]);
      for (const q of order) {
        const [a, b, c, d] = corner(q);
        const [ux, uy, uz, vx, vy, vz] = [p[c * 3] - p[a * 3], p[c * 3 + 1] - p[a * 3 + 1], p[c * 3 + 2] - p[a * 3 + 2], p[d * 3] - p[b * 3], p[d * 3 + 1] - p[b * 3 + 1], p[d * 3 + 2] - p[b * 3 + 2]];
        let normal = [uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx];
        const size = Math.hypot(...normal) || 1;
        normal = normal.map((value) => value / size);
        const toEye = [0, 1, 2].reduce((sum, axis) => sum + normal[axis] * (view.eye[axis] - p[a * 3 + axis]), 0);
        const lit = Math.abs(normal[0] * LIGHT[0] + normal[1] * LIGHT[1] + normal[2] * LIGHT[2]);
        const stripe = Math.floor((q % (cols - 1)) / 2) % 2 ? ctx.colors[2] : ctx.colors[1];
        // The side facing away from the room is the duller lining.
        const base = toEye < 0 ? stripe : mixColour(stripe, ctx.colors[4], 0.55);
        const tone = mixColour(base.map((channel) => channel * (0.3 + 0.7 * lit)), ctx.colors[3], 0.3 * lit ** 10);
        g.fillStyle = g.strokeStyle = rgba(tone);
        trace(screen, [a, b, c, d]);
        g.fill();
        g.stroke();
      }
      // The rail the cloth hangs from, with a ring at every other pin.
      const rail = [[0, 0, 0], [0, 0, 0]].map((end, side) => view.project((side - 0.5) * (cloth.wide * (1 - cloth.slack) + 0.16), cloth.tall / 2 + 0.012, 0.03, end));
      const thick = Math.max(2, Math.abs(rail[1][0] - rail[0][0]) * 0.014);
      g.strokeStyle = g.fillStyle = rgba(ctx.colors[4]);
      g.lineCap = 'round';
      g.lineWidth = thick;
      g.beginPath();
      g.moveTo(rail[0][0], rail[0][1]);
      g.lineTo(rail[1][0], rail[1][1]);
      g.stroke();
      g.fillStyle = rgba(ctx.colors[3]);
      for (let k = 0; k < cols; k += 2) g.fillRect(screen[k * 3] - thick * 0.3, screen[k * 3 + 1] - thick * 0.9, thick * 0.6, thick * 1.5);
    },
  }),
});
