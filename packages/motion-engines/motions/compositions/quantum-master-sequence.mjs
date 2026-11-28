import { defineMotion } from '../../core/define.mjs';
import { composition } from '../../engines/composition.mjs';
import { dom } from '../../engines/dom.mjs';
import { clamp, smoothstep } from '../../core/util.mjs';
import lightTunnel from '../quantum/light-tunnel.mjs';
import singularity from '../quantum/singularity-reveal.mjs';
import cloud from '../quantum/probability-cloud.mjs';
import matrix from '../quantum/orbital-matrix.mjs';
import collapse from '../quantum/energy-collapse.mjs';

// Five chapters on one timeline, each drawn by the motion it names, with a caption track on top.
const CHAPTERS = [
  { use: lightTunnel, at: [0, 0.22], key: 'one' },
  { use: singularity, at: [0.18, 0.42], key: 'two' },
  { use: cloud, at: [0.38, 0.62], key: 'three' },
  { use: matrix, at: [0.58, 0.82], key: 'four' },
  { use: collapse, at: [0.78, 1], key: 'five' },
];

const captions = dom({
  css: `
:scope .caption { position: absolute; inset-inline-start: 6%; bottom: 9%; font-weight: 650; letter-spacing: 0.01em; }
:scope .rule { position: absolute; inset-inline-start: 6%; bottom: 6%; height: 2px; }
:scope .count { position: absolute; inset-inline-end: 6%; top: 8%; font-variant-numeric: tabular-nums; opacity: 0.7; }`,
  build(root, ctx) {
    const document = root.ownerDocument;
    const size = Math.max(11, Math.min(ctx.width, ctx.height * 1.6) * 0.05) * ctx.params.caption;
    const lines = CHAPTERS.map(({ key }) => {
      const line = root.appendChild(document.createElement('div'));
      line.className = 'caption';
      line.textContent = ctx.text[key];
      line.style.cssText = `color:${ctx.css[3] ?? ctx.css[1]};font-size:${size.toFixed(1)}px;`;
      return line;
    });
    const rule = root.appendChild(document.createElement('div'));
    rule.className = 'rule';
    rule.style.background = ctx.css[2];
    const count = root.appendChild(document.createElement('div'));
    count.className = 'count';
    count.style.cssText = `color:${ctx.css[1]};font-size:${(size * 0.8).toFixed(1)}px;`;
    return { lines, rule, count };
  },
  apply({ lines, rule, count }, s, ctx) {
    let current = 0;
    lines.forEach((line, index) => {
      const [from, to] = CHAPTERS[index].at;
      // A caption is only up while its chapter has the screen to itself, so two never overlap.
      const shown = smoothstep(from + 0.04, from + 0.07, s.raw) * (1 - smoothstep(to - 0.07, to - 0.04, s.raw));
      if (s.raw >= from) current = index;
      line.style.opacity = shown.toFixed(3);
      line.style.transform = `translateY(${((1 - shown) * 0.6).toFixed(3)}em)`;
    });
    rule.style.width = `${(clamp(s.raw) * 88).toFixed(2)}%`;
    count.textContent = new Intl.NumberFormat(ctx.locale, { minimumIntegerDigits: 2 }).format(current + 1);
  },
});

export default defineMotion({
  id: 'compositions-quantum-master-sequence',
  number: 200,
  module: 'compositions',
  name: { en: 'Quantum-inspired Cinematic Master Sequence', ar: 'التتابع السينمائي الرئيس المستوحى من الكم' },
  summary: {
    en: 'A five-chapter film on one timeline: tunnel, singularity, probability cloud, orbital matrix and collapse, cross-dissolved under a caption track. Each chapter is its own engine and is only alive while on screen.',
    ar: 'فيلم من خمسة فصول على خط زمني واحد: النفق، التفرّد، سحابة الاحتمال، مصفوفة المدارات، ثم الانهيار، بتلاشٍ متقاطع تحت مسار تعليقات. كل فصل يعمل بمحرّكه الخاص ولا يبقى حيًّا إلا وهو على الشاشة.',
  },
  engine: 'composition',
  kind: 'oneshot',
  duration: 20000,
  easing: 'linear',
  colors: ['#04050d', '#7dd3fc', '#f0abfc', '#f8fafc'],
  params: {
    dissolve: { default: 0.04, min: 0.01, max: 0.04, step: 0.005, label: { en: 'Cross-dissolve length', ar: 'طول التلاشي المتقاطع' } },
    caption: { default: 1, min: 0.6, max: 1.6, step: 0.1, label: { en: 'Caption size', ar: 'حجم التعليق' } },
  },
  text: {
    en: { one: 'Enter the tunnel', two: 'A point of infinite density', three: 'Where it might be', four: 'Order in orbit', five: 'Collapse' },
    ar: { one: 'ادخل النفق', two: 'نقطة بكثافة لا نهائية', three: 'حيث يُحتمل أن يكون', four: 'نظامٌ في المدار', five: 'الانهيار' },
  },
  rtl: 'text',
  requirements: { gpu: 'webgl2', cost: 'high' },
  still: 0.5,
  tags: ['film', 'sequence', 'hero', 'opening', 'cinematic'],
  setup: composition({
    layers: (ctx) => [
      ...CHAPTERS.map(({ use, at }, index) => ({
        use,
        at,
        fade: [index === 0 ? 0 : ctx.params.dissolve, index === CHAPTERS.length - 1 ? 0 : ctx.params.dissolve],
        opaque: true,
        cycles: use.kind === 'loop' ? 1 : undefined,
        colors: (css) => [css[0], css[1], css[2]],
      })),
      { use: captions },
    ],
  }),
});
