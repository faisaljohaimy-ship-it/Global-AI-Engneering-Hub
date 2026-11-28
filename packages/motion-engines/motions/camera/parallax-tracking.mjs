import { defineMotion } from '../../core/define.mjs';
import { canvas2d } from '../../engines/canvas2d.mjs';
import { TAU, mixColour, rgba } from '../../core/util.mjs';

/** A seeded value for building n of a layer: the same building always has the same height and windows. */
const cell = (n, layer, salt) => {
  const v = Math.sin(n * 127.1 + layer * 311.7 + salt * 74.7) * 43758.5453;
  return v - Math.floor(v);
};

export default defineMotion({
  id: 'camera-parallax-tracking',
  number: 16,
  module: 'camera',
  name: { en: 'Multi-layer Parallax Tracking', ar: 'تتبّع المنظور متعدّد الطبقات' },
  summary: {
    en: 'The camera tracks sideways, in the reading direction, past a city at dusk built of layers: distant districts barely move, nearer blocks with lit windows slide faster, and a row of connected street lights in the foreground sweeps by, each one blinking its status up a thin link. Each layer is paler the further it is.',
    ar: 'تتحرّك الكاميرا جانبيًّا باتجاه القراءة أمام مدينةٍ عند الغسق مبنيّةٍ من طبقات: الأحياء البعيدة بالكاد تتحرّك، والمباني الأقرب بنوافذها المضاءة تنزلق أسرع، وصفٌّ من أعمدة الإنارة المتصلة في المقدّمة يمرّ مسرعًا وكلّ عمودٍ يومض بحالته عبر وصلةٍ رفيعة. وكلّ طبقةٍ أبهت كلما بعدت.',
  },
  meaning: {
    en: 'Tracking past a smart city: layered districts behind, connected street lights reporting their status in the foreground.',
    ar: 'تتبّعٌ أمام مدينةٍ ذكية: أحياءٌ متتالية في الخلف، وأعمدة إنارةٍ متصلة ترسل حالتها في المقدّمة.',
  },
  engine: 'canvas2d',
  kind: 'loop',
  duration: 16000,
  easing: 'ease-out',
  colors: ['#0f172a', '#fcd34d', '#1e3a8a', '#0f766e', '#f8fafc'],
  params: {
    layers: { default: 5, min: 3, max: 7, step: 1, label: { en: 'Layers', ar: 'عدد الطبقات' } },
    speed: { default: 1, min: 0.3, max: 3, step: 0.1, label: { en: 'Tracking speed', ar: 'سرعة التتبّع' } },
  },
  rtl: 'mirror',
  requirements: { gpu: 'none', cost: 'low' },
  still: 0.35,
  tags: ['camera', 'parallax', 'smart-city', 'iot', 'background', 'hero'],
  setup: canvas2d({
    draw(g, s, ctx) {
      const { width: w, height: h } = ctx;
      // Travelling in the reading direction: under right-to-left the whole picture is mirrored.
      if (ctx.rtl) {
        g.translate(w, 0);
        g.scale(-1, 1);
      }
      const sky = g.createLinearGradient(0, 0, 0, h);
      sky.addColorStop(0, rgba(ctx.colors[0], 1));
      sky.addColorStop(1, rgba(mixColour(ctx.colors[0], ctx.colors[1], 0.3), 1));
      g.fillStyle = sky;
      g.fillRect(0, 0, w, h);
      // A low moon on one side of the sky.
      const moonX = w * 0.74;
      const moonY = h * 0.22;
      const glow = g.createRadialGradient(moonX, moonY, 0, moonX, moonY, h * 0.4);
      glow.addColorStop(0, rgba(ctx.colors[1], 0.35 * s.intro));
      glow.addColorStop(1, rgba(ctx.colors[1], 0));
      g.fillStyle = glow;
      g.fillRect(0, 0, w, h);
      g.fillStyle = rgba(ctx.colors[1], 0.9);
      g.beginPath();
      g.arc(moonX, moonY, h * 0.05, 0, TAU);
      g.fill();
      const count = Math.round(ctx.params.layers);
      const travel = s.t * ctx.params.speed * 0.08;
      const street = h * 0.9;
      for (let layer = 0; layer < count; layer += 1) {
        const near = (layer + 1) / count;
        const offset = travel * (0.15 + near * near * 3) * w;
        const block = w * (0.05 + near * 0.06);
        const tallest = h * (0.32 + near * 0.32);
        const base = street - (1 - near) * h * 0.16;
        const colour = mixColour(mixColour(ctx.colors[2], ctx.colors[3], near), ctx.colors[1], (1 - near) * 0.3);
        const body = mixColour(colour, ctx.colors[0], 0.25 + near * 0.5);
        const first = Math.floor(offset / block);
        for (let n = first - 1; n < first + Math.ceil(w / block) + 2; n += 1) {
          const x = n * block - offset;
          const tall = tallest * (0.35 + 0.65 * cell(n, layer, 1));
          const wide = block * (0.7 + 0.28 * cell(n, layer, 2));
          g.fillStyle = rgba(body, 1);
          g.fillRect(x, base - tall, wide, tall);
          // Lit windows, on a grid; which ones are lit is fixed per building.
          if (near > 0.3) {
            const size = Math.max(1, block * 0.09);
            g.fillStyle = rgba(ctx.colors[1], 0.35 + 0.5 * near);
            for (let row = 1; row * size * 2.4 < tall - size * 2; row += 1) {
              for (let column = 0; column < 3; column += 1) {
                if (cell(n * 7 + row, layer, column + 3) < 0.55) continue;
                g.fillRect(x + wide * (0.18 + column * 0.27), base - tall + row * size * 2.4, size, size);
              }
            }
          }
        }
      }
      // The street and its connected lights: each post blinks its status and links to the next.
      const offset = travel * 3.6 * w;
      g.fillStyle = rgba(mixColour(ctx.colors[3], ctx.colors[0], 0.8), 1);
      g.fillRect(0, street, w, h - street);
      const spacing = w * 0.22;
      const first = Math.floor(offset / spacing);
      const posts = [];
      for (let n = first - 1; n < first + 7; n += 1) {
        const x = n * spacing - offset;
        const top = street - h * 0.34;
        g.fillStyle = rgba(mixColour(ctx.colors[4], ctx.colors[0], 0.55), 1);
        g.fillRect(x - 1.2, top, 2.4, street - top);
        g.fillRect(x - 1.2, top, h * 0.07, 2.2);
        const lamp = g.createRadialGradient(x + h * 0.06, top + 3, 0, x + h * 0.06, top + 3, h * 0.2);
        lamp.addColorStop(0, rgba(ctx.colors[1], 0.5));
        lamp.addColorStop(1, rgba(ctx.colors[1], 0));
        g.fillStyle = lamp;
        g.fillRect(x - h * 0.2, top - h * 0.15, h * 0.5, h * 0.5);
        const blink = (s.t * 1.3 + cell(n, 9, 4)) % 1 < 0.25;
        g.fillStyle = rgba(blink ? ctx.colors[4] : ctx.colors[3], 1);
        g.beginPath();
        g.arc(x, top - 3, 1.8, 0, TAU);
        g.fill();
        posts.push([x, top - 3]);
      }
      g.strokeStyle = rgba(ctx.colors[4], 0.3 * s.intro);
      g.lineWidth = 0.8;
      g.setLineDash([2, 3]);
      g.beginPath();
      posts.forEach(([x, y], index) => (index ? g.lineTo(x, y) : g.moveTo(x, y)));
      g.stroke();
      g.setLineDash([]);
    },
  }),
});
