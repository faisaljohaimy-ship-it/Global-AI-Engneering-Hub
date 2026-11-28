import { defineMotion } from '../../core/define.mjs';
import { canvas2d } from '../../engines/canvas2d.mjs';
import { camera, farToNear, rotateX, rotateY } from '../../engines/math3d.mjs';
import { TAU, rgba } from '../../core/util.mjs';

export default defineMotion({
  id: 'quantum-orbital-matrix',
  number: 5,
  module: 'quantum',
  name: { en: 'Quantum Orbital Matrix', ar: 'مصفوفة المدارات الكمّية' },
  summary: {
    en: 'A cubic matrix of nuclei, each circled by an electron on its own tilted orbit, seen from an orbiting camera.',
    ar: 'مصفوفة مكعّبة من الأنوية، يدور حول كلٍّ منها إلكترون في مدار مائل خاص به، تُرى من كاميرا تدور حولها.',
  },
  engine: 'canvas2d',
  kind: 'loop',
  duration: 12000,
  easing: 'ease-out',
  colors: ['#05070f', '#93c5fd', '#fbbf24'],
  params: {
    grid: { default: 3, min: 2, max: 4, step: 1, label: { en: 'Nuclei per side', ar: 'عدد الأنوية في كل ضلع' } },
    orbit: { default: 0.32, min: 0.15, max: 0.45, step: 0.01, label: { en: 'Orbit size', ar: 'حجم المدار' } },
  },
  camera: {
    distance: { default: 5.2, min: 3.5, max: 8, step: 0.1, label: { en: 'Camera distance', ar: 'بُعد الكاميرا' } },
    elevation: { default: 0.45, min: -0.2, max: 1.1, step: 0.05, label: { en: 'Camera elevation', ar: 'ارتفاع الكاميرا' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'none', cost: 'medium' },
  still: 0.25,
  tags: ['spatial', 'science', 'hero', 'diagram'],
  setup: canvas2d({
    init: (ctx) => {
      const random = ctx.random(5);
      return Array.from({ length: 64 }, () => ({ tiltX: random() * Math.PI, tiltY: random() * Math.PI, speed: 1 + random() * 2, phase: random() * TAU }));
    },
    draw(g, s, ctx, orbits) {
      const side = Math.round(ctx.params.grid);
      const turn = s.raw * TAU;
      const { distance, elevation } = ctx.camera;
      const view = camera({ eye: [Math.sin(turn) * distance, elevation * distance * 0.6, Math.cos(turn) * distance], fov: 46, width: ctx.width, height: ctx.height });
      const items = [];
      let index = 0;
      for (let x = 0; x < side; x += 1) for (let y = 0; y < side; y += 1) for (let z = 0; z < side; z += 1) {
        const centre = [x, y, z].map((value) => (value - (side - 1) / 2) * 1.1);
        const orbit = orbits[index % orbits.length];
        index += 1;
        const nucleus = view.project(centre);
        if (nucleus) items.push({ ...nucleus, kind: 'nucleus' });
        const ring = [];
        for (let step = 0; step <= 28; step += 1) {
          const angle = (step / 28) * TAU;
          const local = rotateY(rotateX([Math.cos(angle) * ctx.params.orbit, 0, Math.sin(angle) * ctx.params.orbit], orbit.tiltX), orbit.tiltY);
          ring.push(view.project(centre.map((value, axis) => value + local[axis])));
        }
        if (nucleus) items.push({ depth: nucleus.depth + 0.001, kind: 'ring', ring });
        const where = s.t * orbit.speed + orbit.phase;
        const local = rotateY(rotateX([Math.cos(where) * ctx.params.orbit, 0, Math.sin(where) * ctx.params.orbit], orbit.tiltX), orbit.tiltY);
        const electron = view.project(centre.map((value, axis) => value + local[axis]));
        if (electron) items.push({ ...electron, kind: 'electron' });
      }
      for (const item of farToNear(items)) {
        const fade = Math.min(1, 3.2 / item.depth) * s.intro;
        if (item.kind === 'ring') {
          g.strokeStyle = rgba(ctx.colors[1], 0.22 * fade);
          g.lineWidth = 1;
          g.beginPath();
          item.ring.forEach((point, step) => point && (step ? g.lineTo(point.x, point.y) : g.moveTo(point.x, point.y)));
          g.stroke();
        } else {
          g.fillStyle = rgba(item.kind === 'nucleus' ? ctx.colors[1] : ctx.colors[2], fade);
          g.beginPath();
          g.arc(item.x, item.y, Math.max(0.8, item.scale * (item.kind === 'nucleus' ? 0.07 : 0.045)), 0, TAU);
          g.fill();
        }
      }
    },
  }),
});
