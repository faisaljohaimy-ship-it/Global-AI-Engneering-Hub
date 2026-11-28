import { defineMotion } from '../../core/define.mjs';
import { canvas2d } from '../../engines/canvas2d.mjs';
import { camera, farToNear } from '../../engines/math3d.mjs';
import { clamp, mixColour, rgba } from '../../core/util.mjs';

const HALL = 18;

export default defineMotion({
  id: 'camera-dolly-in',
  number: 11,
  module: 'camera',
  name: { en: 'Cinematic Dolly In', ar: 'اقتراب الكاميرا السينمائي' },
  summary: {
    en: 'The camera travels down a long gallery between rows of lit panels toward a glowing portal at its end. Panels slide past at the edges of the frame, the floor lines rush underneath and the portal grows until it fills the view.',
    ar: 'تتقدّم الكاميرا في رواقٍ طويل بين صفوفٍ من اللوحات المضاءة نحو بوّابةٍ متوهّجة في نهايته. تنزلق اللوحات عند حواف الإطار، وتندفع خطوط الأرضية تحتها، وتكبر البوّابة حتى تملأ المشهد.',
  },
  meaning: {
    en: 'A walk down a corridor of separate service screens into one unified digital portal.',
    ar: 'مسيرٌ في ممرٍّ من شاشات الخدمات المتفرّقة نحو بوابةٍ رقمية موحّدة واحدة.',
  },
  engine: 'canvas2d',
  kind: 'oneshot',
  duration: 3600,
  easing: 'ease-in-out',
  colors: ['#05060c', '#94a3b8', '#38bdf8', '#fbbf24'],
  params: {
    depth: { default: 0.8, min: 0.3, max: 1, step: 0.05, label: { en: 'How far the camera travels', ar: 'المسافة التي تقطعها الكاميرا' } },
    panels: { default: 7, min: 3, max: 12, step: 1, label: { en: 'Panels on each wall', ar: 'عدد اللوحات على كل جدار' } },
  },
  camera: {
    fov: { default: 58, min: 35, max: 85, step: 1, label: { en: 'Field of view', ar: 'مجال الرؤية' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'none', cost: 'low' },
  still: 1,
  tags: ['camera', 'reveal', 'hero', 'gallery', 'intro'],
  setup: canvas2d({
    init(ctx) {
      const random = ctx.random(11);
      return Array.from({ length: 24 }, () => ({ hue: random(), height: 0.7 + random() * 0.6 }));
    },
    draw(g, s, ctx, looks) {
      const { width: w, height: h } = ctx;
      const travel = s.progress * ctx.params.depth * (HALL - 3.2);
      const view = camera({ eye: [0, 0.15, HALL - travel], target: [0, 0.1, -1], fov: ctx.camera.fov, width: w, height: h });
      const fog = (depth) => clamp(1 - depth / (HALL * 0.9));
      const items = [];
      // Floor lines across the hall, every metre.
      for (let z = 0; z <= HALL; z += 1) {
        const a = view.project([-1.6, -1, z]);
        const b = view.project([1.6, -1, z]);
        if (a && b) items.push({ depth: a.depth, kind: 'line', a, b });
      }
      // Panels on both walls.
      const count = Math.round(ctx.params.panels);
      for (let index = 0; index < count * 2; index += 1) {
        const side = index % 2 ? 1 : -1;
        const z = 1.5 + Math.floor(index / 2) * ((HALL - 3) / count);
        const look = looks[index % looks.length];
        const top = -0.2 + look.height * 0.9;
        const corners = [[side * 1.6, -0.6, z - 0.7], [side * 1.6, -0.6, z + 0.7], [side * 1.6, top, z + 0.7], [side * 1.6, top, z - 0.7]].map((point) => view.project(point));
        if (corners.every(Boolean)) items.push({ depth: (corners[0].depth + corners[1].depth) / 2, kind: 'panel', corners, look });
      }
      // The portal at the end of the hall.
      const portal = [[-0.75, -1, 0], [0.75, -1, 0], [0.75, 1.1, 0], [-0.75, 1.1, 0]].map((point) => view.project(point));
      if (portal.every(Boolean)) items.push({ depth: portal[0].depth + 0.01, kind: 'portal', corners: portal });
      // Walls and ceiling as dim gradients first.
      g.fillStyle = rgba(ctx.colors[1], 0.04);
      g.fillRect(0, 0, w, h);
      for (const item of farToNear(items)) {
        const near = fog(item.depth);
        if (item.kind === 'line') {
          g.strokeStyle = rgba(ctx.colors[1], 0.35 * near);
          g.lineWidth = Math.max(0.5, item.a.scale * 0.02);
          g.beginPath();
          g.moveTo(item.a.x, item.a.y);
          g.lineTo(item.b.x, item.b.y);
          g.stroke();
          continue;
        }
        g.beginPath();
        item.corners.forEach((point, index) => (index ? g.lineTo(point.x, point.y) : g.moveTo(point.x, point.y)));
        g.closePath();
        if (item.kind === 'portal') {
          const centre = item.corners.reduce((sum, point) => [sum[0] + point.x / 4, sum[1] + point.y / 4], [0, 0]);
          const radius = Math.abs(item.corners[1].x - item.corners[0].x);
          const glow = g.createRadialGradient(centre[0], centre[1], 0, centre[0], centre[1], Math.max(1, radius));
          glow.addColorStop(0, rgba(ctx.colors[3], 1));
          glow.addColorStop(1, rgba(ctx.colors[2], 0.6));
          g.fillStyle = glow;
          g.fill();
          g.strokeStyle = rgba(ctx.colors[3], 0.9);
          g.lineWidth = Math.max(1, item.corners[0].scale * 0.05);
          g.stroke();
        } else {
          const colour = mixColour(ctx.colors[2], ctx.colors[3], item.look.hue);
          g.fillStyle = rgba(mixColour(ctx.colors[0], colour, 0.25 + 0.6 * near), 1);
          g.fill();
          g.strokeStyle = rgba(ctx.colors[1], 0.6 * near);
          g.lineWidth = 1;
          g.stroke();
        }
      }
    },
  }),
});
