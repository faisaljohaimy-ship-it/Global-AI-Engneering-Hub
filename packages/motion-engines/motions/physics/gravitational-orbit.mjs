import { defineMotion } from '../../core/define.mjs';
import { canvas2d } from '../../engines/canvas2d.mjs';
import { TAU, mixColour, rgba } from '../../core/util.mjs';

/** Eccentric anomaly E from the mean anomaly M (Kepler's equation M = E - e sin E), by Newton's method. */
function anomaly(meanAnomaly, e) {
  let E = e < 0.8 ? meanAnomaly : Math.PI;
  for (let step = 0; step < 8; step += 1) E -= (E - e * Math.sin(E) - meanAnomaly) / (1 - e * Math.cos(E));
  return E;
}

/** Position on an ellipse with semi-major axis a, eccentricity e and periapsis angle w, the star at a focus. */
function orbitPoint(a, e, w, meanAnomaly) {
  const E = anomaly(meanAnomaly, e);
  const x = a * (Math.cos(E) - e);
  const y = a * Math.sqrt(1 - e * e) * Math.sin(E);
  return [x * Math.cos(w) - y * Math.sin(w), x * Math.sin(w) + y * Math.cos(w)];
}

export default defineMotion({
  id: 'physics-gravitational-orbit',
  number: 125,
  module: 'physics',
  name: { en: 'Gravitational Orbit Simulation', ar: 'محاكاة المدارات الجاذبية' },
  summary: {
    en: 'Communication satellites circle the Earth on ellipses solved from Kepler’s equation: they race through the near point and crawl at the far one, and each beams a downlink to the ground while it is close. The outer satellite sweeps out equal shaded areas in equal times, and every orbit closes so the loop repeats exactly.',
    ar: 'أقمار اتصالاتٍ تدور حول الأرض على قطوعٍ ناقصة محسوبة من معادلة كبلر: تندفع عند أقرب نقطة وتتباطأ عند أبعدها، ويرسل كلٌّ منها وصلةً هابطة إلى الأرض ما دام قريبًا. يمسح القمر الخارجي مساحاتٍ مظلّلة متساوية في أزمنةٍ متساوية، وكلّ مدارٍ ينغلق فيتكرّر المشهد بدقة.',
  },
  meaning: {
    en: 'Satellite connectivity: communication satellites circle the Earth on elliptical orbits, fastest where they pass closest.',
    ar: 'الاتصال عبر الأقمار الصناعية: أقمار الاتصالات تدور حول الأرض في مداراتٍ إهليلجية، وتكون أسرع حيث تمرّ أقرب.',
  },
  engine: 'canvas2d',
  kind: 'loop',
  duration: 14000,
  easing: 'ease-out',
  colors: ['#04050c', '#38bdf8', '#fbbf24', '#f472b6', '#a7f3d0'],
  params: {
    eccentricity: { default: 0.45, min: 0, max: 0.8, step: 0.05, label: { en: 'Eccentricity', ar: 'الاختلاف المركزي' } },
    satellites: { default: 4, min: 2, max: 5, step: 1, label: { en: 'Satellites', ar: 'عدد الأقمار الصناعية' } },
  },
  camera: {
    tilt: { default: 0.45, min: 0, max: 1.1, step: 0.05, label: { en: 'Viewing tilt', ar: 'ميل زاوية النظر' } },
  },
  rtl: 'neutral',
  requirements: { gpu: 'none', cost: 'low' },
  still: 0.3,
  tags: ['physics', 'satellite', 'connectivity', 'orbit', 'infrastructure', 'explainer'],
  setup: canvas2d({
    init(ctx) {
      const random = ctx.random(125);
      const bodies = Array.from({ length: 5 }, () => ({ w: random() * TAU, phase: random(), size: 0.6 + random() * 0.8 }));
      const sky = ctx.random(9);
      const stars = Array.from({ length: 50 }, () => [sky(), sky()]);
      return { bodies, stars };
    },
    draw(g, s, ctx, { bodies, stars }) {
      const { width: w, height: h } = ctx;
      const count = Math.round(ctx.params.satellites);
      const unit = Math.min(w, h) * 0.46;
      const squash = Math.cos(ctx.camera.tilt);
      const cx = w / 2;
      const cy = h / 2;
      const screen = ([x, y]) => [cx + x * unit, cy + y * unit * squash];
      const grow = 0.5 + 0.5 * s.intro;
      // Background stars, fixed.
      g.fillStyle = rgba(ctx.colors[4], 0.5);
      for (const [x, y] of stars) g.fillRect(x * w, y * h, 1, 1);
      // The Earth: a lit globe with a thin atmosphere, the light coming from one side.
      const earth = unit * 0.14 * grow;
      const air = g.createRadialGradient(cx, cy, earth * 0.9, cx, cy, earth * 1.5);
      air.addColorStop(0, rgba(ctx.colors[1], 0.45));
      air.addColorStop(1, rgba(ctx.colors[1], 0));
      g.fillStyle = air;
      g.fillRect(cx - earth * 2, cy - earth * 2, earth * 4, earth * 4);
      const globe = g.createRadialGradient(cx - earth * 0.4, cy - earth * 0.4, earth * 0.1, cx, cy, earth);
      globe.addColorStop(0, rgba(mixColour(ctx.colors[1], ctx.colors[4], 0.5), 1));
      globe.addColorStop(0.6, rgba(ctx.colors[1], 1));
      globe.addColorStop(1, rgba(mixColour(ctx.colors[1], ctx.colors[0], 0.7), 1));
      g.fillStyle = globe;
      g.beginPath();
      g.arc(cx, cy, earth, 0, TAU);
      g.fill();
      for (let index = 0; index < count; index += 1) {
        const body = bodies[index];
        const a = (0.3 + 0.7 * ((index + 1) / count)) * 0.98 * grow;
        const e = Math.min(0.85, ctx.params.eccentricity * (0.6 + 0.4 * ((index + 1) / count)));
        // Whole numbers of turns per loop, inner satellites faster, so the loop closes.
        const turns = count - index;
        const mean = (s.raw * turns + body.phase) * TAU;
        const colour = mixColour(ctx.colors[2], ctx.colors[3], index / Math.max(1, count - 1));
        // The orbit.
        g.strokeStyle = rgba(colour, 0.25);
        g.lineWidth = 1;
        g.setLineDash([3, 4]);
        g.beginPath();
        for (let step = 0; step <= 72; step += 1) {
          const [x, y] = screen(orbitPoint(a, e, body.w, (step / 72) * TAU));
          if (step) g.lineTo(x, y);
          else g.moveTo(x, y);
        }
        g.stroke();
        g.setLineDash([]);
        // Kepler's second law on the outermost satellite: the area swept in each equal slice of time.
        if (index === 0) {
          for (let slice = 0; slice < 3; slice += 1) {
            const from = mean - (slice + 1) * 0.55;
            g.fillStyle = rgba(colour, 0.14 - slice * 0.035);
            g.beginPath();
            g.moveTo(cx, cy);
            for (let step = 0; step <= 10; step += 1) {
              const [x, y] = screen(orbitPoint(a, e, body.w, from + (0.55 * step) / 10));
              g.lineTo(x, y);
            }
            g.closePath();
            g.fill();
          }
        }
        // A fading trail of where it was, then the satellite with its solar panels across its path.
        for (let step = 12; step >= 1; step -= 1) {
          const [x, y] = screen(orbitPoint(a, e, body.w, mean - step * 0.05));
          g.fillStyle = rgba(colour, 0.45 * (1 - step / 13));
          g.beginPath();
          g.arc(x, y, unit * 0.018 * body.size, 0, TAU);
          g.fill();
        }
        const position = orbitPoint(a, e, body.w, mean);
        const [x, y] = screen(position);
        const [ax, ay] = screen(orbitPoint(a, e, body.w, mean + 0.01));
        const heading = Math.atan2(ay - y, ax - x);
        // The downlink: while the satellite is in the near half of its orbit it beams to the ground.
        const distance = Math.hypot(position[0], position[1]);
        if (distance < a) {
          const strength = Math.min(1, (a - distance) / (a * 0.3));
          g.strokeStyle = rgba(ctx.colors[4], 0.55 * strength);
          g.lineWidth = 1;
          g.setLineDash([2, 3]);
          g.beginPath();
          g.moveTo(x, y);
          g.lineTo(cx + ((x - cx) / Math.hypot(x - cx, y - cy || 1e-6)) * earth, cy + ((y - cy) / Math.hypot(x - cx, y - cy || 1e-6)) * earth);
          g.stroke();
          g.setLineDash([]);
        }
        const size = unit * 0.045 * body.size;
        g.save();
        g.translate(x, y);
        g.rotate(heading);
        g.fillStyle = rgba(ctx.colors[4], 0.85);
        g.fillRect(-size * 0.35, -size * 1.6, size * 0.7, size * 1.1);
        g.fillRect(-size * 0.35, size * 0.5, size * 0.7, size * 1.1);
        g.fillStyle = rgba(colour, 1);
        g.fillRect(-size * 0.55, -size * 0.55, size * 1.1, size * 1.1);
        g.restore();
      }
    },
  }),
});
