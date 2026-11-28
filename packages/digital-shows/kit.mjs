// GAIE digital show kit: original Canvas2D scenes that each state ONE digital-transformation meaning.
//
// Every scene is a pure function of normalized time t in [0, 1] and its parameters:
// no Math.random, no Date, no timers, no network, no images. Seeded values come from a
// fixed integer generator. The frame at t = 1 is the settled state, and reduced motion
// draws exactly that frame. Labels are parameters (Arabic for an Arabic cut); the kit
// draws no flag, emblem, logo, map or portrait, and "رؤية المملكة 2030" can only ever
// appear as plain typography passed in by the storyboard.
//
// registry.json is generated from this file by tools/build_registry.mjs and carries its
// SHA-256, so the Python pipeline refuses a kit that changed without its registry.
// SPDX-License-Identifier: MIT

export const KIT_VERSION = '1.0.0';
export const REGISTRY_SCHEMA = 'gaie.digital-shows/1';

export const PALETTE = Object.freeze({
  bg0: '#040a14', bg1: '#08162a', panel: '#0c1c31', panelHi: '#12294a', line: '#24405f', dim: '#5c7594',
  text: '#eef4fb', soft: '#bccadb', cyan: '#27d3f5', blue: '#3b8bff', green: '#35d39a', gold: '#e6b450', dark: '#04101c',
});

// Design units are 1/1080 of the frame height times CONTENT_SCALE; the default stage leaves the
// lower third to the caption the compositor draws.
export const CONTENT_SCALE = 1.25;
export const STAGE = Object.freeze({ x0: 0.06, y0: 0.06, x1: 0.94, y1: 0.645 });

export const FONT_FILES = Object.freeze([
  { family: 'IBM Plex Sans Arabic', weight: 400, file: 'IBMPlexSansArabic-400.ttf' },
  { family: 'IBM Plex Sans Arabic', weight: 600, file: 'IBMPlexSansArabic-600.ttf' },
  { family: 'IBM Plex Sans Arabic', weight: 700, file: 'IBMPlexSansArabic-700.ttf' },
  { family: 'Alexandria', weight: 700, file: 'Alexandria-700.ttf' },
  { family: 'Alexandria', weight: 800, file: 'Alexandria-800.ttf' },
  { family: 'IBM Plex Sans', weight: 400, file: 'IBMPlexSans-400.ttf' },
  { family: 'IBM Plex Sans', weight: 600, file: 'IBMPlexSans-600.ttf' },
  { family: 'IBM Plex Mono', weight: 500, file: 'IBMPlexMono-500.ttf' },
]);

export const THEMES = Object.freeze({
  'digital-transformation': {
    title: { ar: 'التحول الرقمي', en: 'Digital transformation' },
    statement: {
      ar: 'كل مشهد يحمل معنى واحدًا مسجّلًا من معاني التحول الرقمي، بما ينسجم مع رؤية المملكة 2030.',
      en: 'Every scene carries one registered digital-transformation meaning, in step with Saudi Vision 2030.',
    },
    palette: PALETTE,
    fonts: { head: 'Alexandria', body: 'IBM Plex Sans Arabic', latin: 'IBM Plex Sans', mono: 'IBM Plex Mono', fallback: 'DejaVu Sans' },
    grade: 'gaie-digital',
    on_screen_language: 'primary',
    excluded: ['flags', 'emblems', 'logos', 'maps', 'portraits'],
  },
});

// ------------------------------------------------------------------ small pure helpers

const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
const seg = (t, a, b) => clamp((t - a) / (b - a));
const lerp = (a, b, u) => a + (b - a) * u;
const eo = (x) => 1 - (1 - x) ** 3;
const eio = (x) => (x < 0.5 ? 4 * x * x * x : 1 - (-2 * x + 2) ** 3 / 2);
const back = (x) => 1 + 2.70158 * (x - 1) ** 3 + 1.70158 * (x - 1) ** 2;
const TAU = Math.PI * 2;
const ARABIC = /[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]/;
const hasArabic = (text) => ARABIC.test(String(text));

/** Seeded integer generator (mulberry32): the only source of variation in the kit. */
export function seeded(seed) {
  let a = (seed >>> 0) || 1;
  return () => {
    a = (a + 0x6D2B79F5) | 0;
    let x = Math.imul(a ^ (a >>> 15), 1 | a);
    x = (x + Math.imul(x ^ (x >>> 7), 61 | x)) ^ x;
    return ((x ^ (x >>> 14)) >>> 0) / 4294967296;
  };
}

/** FNV-1a over code points, chained through `previous`: the audit trail shows real chained digests. */
export function chainDigest(text, previous = 0x811c9dc5) {
  let h = previous >>> 0;
  for (const ch of String(text)) { h ^= ch.codePointAt(0); h = Math.imul(h, 0x01000193) >>> 0; }
  return h >>> 0;
}
const hex8 = (n) => (n >>> 0).toString(16).padStart(8, '0');

function rgba(hex, alpha) {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${alpha})`;
}

const grouped = (n) => String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, ',');

// Parameter schema helpers. `label_in` is the normalized time at which a label is fully
// visible (two numbers: the first and the last label of a list); the pipeline derives the
// reading time of every label from it.
const L = (max, at, required = false) => ({ type: 'label', max_chars: max, required, label_in: at });
const LS = (min, max, chars, from, to) => ({ type: 'labels', min, max, max_chars: chars, required: false, label_in: [from, to] });
const INT = (min, max, fallback) => ({ type: 'int', min, max, default: fallback });
const CODE = (max, at) => ({ type: 'code', max_chars: max, required: false, label_in: at });

export function labelTime(spec, index = 0, count = 1) {
  if (!Array.isArray(spec.label_in)) return spec.label_in;
  return count <= 1 ? spec.label_in[0] : lerp(spec.label_in[0], spec.label_in[1], index / (count - 1));
}
const vis = (t, at, fade = 0.05) => eo(seg(t, at - fade, at));

// ------------------------------------------------------------------ drawing context

function makeContext(g, t, params, env) {
  const W = env.width, H = env.height, u = (H / 1080) * CONTENT_SCALE;
  const st = env.stage || { x0: W * STAGE.x0, y0: H * STAGE.y0, x1: W * STAGE.x1, y1: H * STAGE.y1 };
  const rtl = (env.lang || 'ar') === 'ar';
  const theme = THEMES[env.theme || 'digital-transformation'] || THEMES['digital-transformation'];
  const c = { g, t, p: params, W, H, u, st, rtl, P: theme.palette, F: { ...theme.fonts, ...(env.fonts || {}) }, labels: [],
    glyphs: env.glyphs !== false, seed: env.seed | 0, sw: st.x1 - st.x0, sh: st.y1 - st.y0, d: rtl ? -1 : 1 };
  c.x = (f) => (rtl ? st.x1 - f * c.sw : st.x0 + f * c.sw);   // logical start -> end
  c.y = (f) => st.y0 + f * c.sh;
  return c;
}

function fontStack(c, role) {
  const f = c.F;
  if (role === 'mono') return `"${f.mono}","DejaVu Sans Mono",monospace`;
  if (role === 'head') return `"${f.head}","${f.body}","${f.fallback}",sans-serif`;
  if (role === 'latin') return `"${f.latin}","${f.fallback}",sans-serif`;
  return `"${f.body}","${f.latin}","${f.fallback}",sans-serif`;
}

/** Draw one label, auto-fitted to maxWidth, and record its box for the legibility checks. */
function text(c, value, x, y, o = {}) {
  const g = c.g, str = String(value);
  if (!str) return { width: 0, size: 0 };
  const role = o.font || 'body', weight = o.weight || 600, family = fontStack(c, role);
  let size = (o.size || 30) * c.u;
  let align = o.align || 'center';
  if (align === 'start') align = c.rtl ? 'right' : 'left';
  if (align === 'end') align = c.rtl ? 'left' : 'right';
  g.save();
  g.direction = role === 'mono' ? 'ltr' : (hasArabic(str) ? 'rtl' : 'ltr');
  g.textAlign = align; g.textBaseline = 'middle';
  g.font = `${weight} ${size}px ${family}`;
  let m = g.measureText(str);
  if (o.maxWidth && m.width > o.maxWidth) {
    size = Math.max(1, Math.floor(size * o.maxWidth / m.width));
    g.font = `${weight} ${size}px ${family}`;
    m = g.measureText(str);
  }
  const alpha = clamp(o.alpha ?? 1), color = o.color || c.P.text;
  if (o.track !== false) {
    c.labels.push({ text: str, role: o.role || 'label', size: Math.round(size * 100) / 100, color, alpha: Math.round(alpha * 1000) / 1000,
      x0: x - m.actualBoundingBoxLeft, x1: x + m.actualBoundingBoxRight, y0: y - m.actualBoundingBoxAscent, y1: y + m.actualBoundingBoxDescent });
  }
  if (alpha > 0 && c.glyphs) {
    g.globalAlpha *= alpha;
    if (o.glow) { g.shadowColor = o.glow; g.shadowBlur = 18 * c.u; }
    g.fillStyle = color;
    g.fillText(str, x, y);
  }
  g.restore();
  return { width: m.width, size };
}

function panel(c, x, y, w, h, o = {}) {
  const g = c.g, alpha = clamp(o.alpha ?? 1);
  if (alpha <= 0 || w <= 0 || h <= 0) return;
  g.save();
  g.globalAlpha *= alpha;
  g.beginPath();
  g.roundRect(x, y, w, h, Math.min((o.r ?? 14) * c.u, w / 2, h / 2));
  if (o.fill !== null) {
    if (o.glow) { g.shadowColor = o.glow; g.shadowBlur = (o.blur || 26) * c.u; }
    g.fillStyle = o.fill || c.P.panel; g.fill();
    g.shadowColor = 'transparent'; g.shadowBlur = 0;
  }
  if (o.stroke !== null) {
    if (o.dash) g.setLineDash(o.dash.map((v) => v * c.u));
    g.lineWidth = (o.lw || 2) * c.u; g.strokeStyle = o.stroke || c.P.line; g.stroke();
  }
  g.restore();
}

function disc(c, x, y, r, o = {}) {
  const g = c.g, alpha = clamp(o.alpha ?? 1);
  if (alpha <= 0 || r <= 0) return;
  g.save();
  g.globalAlpha *= alpha;
  g.beginPath(); g.arc(x, y, r, 0, TAU);
  if (o.fill !== null) {
    if (o.glow) { g.shadowColor = o.glow; g.shadowBlur = (o.blur || 22) * c.u; }
    g.fillStyle = o.fill || c.P.panel; g.fill();
    g.shadowColor = 'transparent'; g.shadowBlur = 0;
  }
  if (o.stroke) { g.lineWidth = (o.lw || 3) * c.u; g.strokeStyle = o.stroke; g.stroke(); }
  g.restore();
}

function lengthOf(points) {
  let total = 0;
  for (let i = 1; i < points.length; i += 1) total += Math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1]);
  return total;
}

function pointAt(points, f) {
  const total = lengthOf(points);
  let left = clamp(f) * total;
  for (let i = 1; i < points.length; i += 1) {
    const span = Math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1]);
    if (left <= span || i === points.length - 1) {
      const k = span ? clamp(left / span) : 0;
      return [lerp(points[i - 1][0], points[i][0], k), lerp(points[i - 1][1], points[i][1], k)];
    }
    left -= span;
  }
  return points[points.length - 1];
}

/** Polyline drawn up to `progress` of its length. */
function stroke(c, points, o = {}) {
  const g = c.g, progress = clamp(o.progress ?? 1), alpha = clamp(o.alpha ?? 1);
  if (progress <= 0 || alpha <= 0 || points.length < 2) return;
  const total = lengthOf(points);
  let left = progress * total;
  g.save();
  g.globalAlpha *= alpha;
  g.lineCap = o.cap || 'round'; g.lineJoin = 'round';
  g.lineWidth = (o.lw || 3) * c.u; g.strokeStyle = o.color || c.P.line;
  if (o.dash) { g.setLineDash(o.dash.map((v) => v * c.u)); g.lineDashOffset = (o.dashOffset || 0) * c.u; g.lineCap = 'butt'; }
  if (o.glow) { g.shadowColor = o.glow; g.shadowBlur = (o.blur || 14) * c.u; }
  g.beginPath(); g.moveTo(points[0][0], points[0][1]);
  for (let i = 1; i < points.length && left > 0; i += 1) {
    const span = Math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1]);
    const k = span ? Math.min(1, left / span) : 1;
    g.lineTo(lerp(points[i - 1][0], points[i][0], k), lerp(points[i - 1][1], points[i][1], k));
    left -= span;
  }
  g.stroke();
  g.restore();
}

function check(c, x, y, s, progress, color, lw = 5) {
  stroke(c, [[x - s * 0.9, y + s * 0.05], [x - s * 0.28, y + s * 0.62], [x + s * 0.92, y - s * 0.58]], { progress, color, lw });
}

function cross(c, x, y, s, color, alpha = 1, lw = 4) {
  stroke(c, [[x - s, y - s], [x + s, y + s]], { color, alpha, lw });
  stroke(c, [[x + s, y - s], [x - s, y + s]], { color, alpha, lw });
}

/** A glowing pulse travelling along a path. */
function pulse(c, points, f, color, alpha = 1, r = 7) {
  if (alpha <= 0 || f < 0 || f > 1) return;
  const [x, y] = pointAt(points, f);
  disc(c, x, y, r * c.u, { fill: color, glow: color, blur: 20, alpha });
}

// Line icons, drawn inside a box of half-size s centred on (x, y).
const ICONS = {
  doc(c, x, y, s, color, a) {
    panel(c, x - s * 0.7, y - s, s * 1.4, s * 2, { r: 4, fill: null, stroke: color, lw: 3, alpha: a });
    for (let i = 0; i < 3; i += 1) stroke(c, [[x - s * 0.4, y - s * 0.45 + i * s * 0.45], [x + s * 0.4, y - s * 0.45 + i * s * 0.45]], { color, lw: 3, alpha: a });
  },
  user(c, x, y, s, color, a) {
    disc(c, x, y - s * 0.42, s * 0.42, { fill: null, stroke: color, lw: 3, alpha: a });
    const g = c.g; g.save(); g.globalAlpha *= a; g.lineWidth = 3 * c.u; g.strokeStyle = color; g.lineCap = 'round';
    g.beginPath(); g.arc(x, y + s * 0.95, s * 0.85, Math.PI * 1.15, Math.PI * 1.85); g.stroke(); g.restore();
  },
  lock(c, x, y, s, color, a) {
    panel(c, x - s * 0.75, y - s * 0.1, s * 1.5, s * 1.1, { r: 5, fill: null, stroke: color, lw: 3, alpha: a });
    const g = c.g; g.save(); g.globalAlpha *= a; g.lineWidth = 3 * c.u; g.strokeStyle = color;
    g.beginPath(); g.arc(x, y - s * 0.1, s * 0.48, Math.PI, 0); g.stroke(); g.restore();
    disc(c, x, y + s * 0.42, s * 0.13, { fill: color, alpha: a });
  },
  shield(c, x, y, s, color, a, fill) {
    const g = c.g; g.save(); g.globalAlpha *= a;
    g.beginPath(); g.moveTo(x, y - s); g.lineTo(x + s * 0.85, y - s * 0.62); g.lineTo(x + s * 0.85, y + s * 0.05);
    g.quadraticCurveTo(x + s * 0.8, y + s * 0.72, x, y + s); g.quadraticCurveTo(x - s * 0.8, y + s * 0.72, x - s * 0.85, y + s * 0.05);
    g.lineTo(x - s * 0.85, y - s * 0.62); g.closePath();
    if (fill) { g.fillStyle = fill; g.fill(); }
    g.lineWidth = 3.5 * c.u; g.lineJoin = 'round'; g.strokeStyle = color; g.stroke(); g.restore();
  },
  bell(c, x, y, s, color, a) {
    const g = c.g; g.save(); g.globalAlpha *= a; g.lineWidth = 3 * c.u; g.strokeStyle = color; g.lineJoin = 'round'; g.lineCap = 'round';
    g.beginPath(); g.moveTo(x - s * 0.8, y + s * 0.45); g.quadraticCurveTo(x - s * 0.5, y + s * 0.1, x - s * 0.5, y - s * 0.2);
    g.arc(x, y - s * 0.2, s * 0.5, Math.PI, 0); g.quadraticCurveTo(x + s * 0.5, y + s * 0.1, x + s * 0.8, y + s * 0.45); g.closePath(); g.stroke();
    g.beginPath(); g.arc(x, y + s * 0.62, s * 0.16, 0, Math.PI); g.stroke(); g.restore();
  },
  database(c, x, y, s, color, a) {
    const g = c.g; g.save(); g.globalAlpha *= a; g.lineWidth = 3 * c.u; g.strokeStyle = color;
    for (let i = 0; i < 3; i += 1) { g.beginPath(); g.ellipse(x, y - s * 0.6 + i * s * 0.6, s * 0.8, s * 0.26, 0, i ? 0 : -Math.PI, Math.PI); g.stroke(); }
    g.beginPath(); g.moveTo(x - s * 0.8, y - s * 0.6); g.lineTo(x - s * 0.8, y + s * 0.6); g.moveTo(x + s * 0.8, y - s * 0.6); g.lineTo(x + s * 0.8, y + s * 0.6); g.stroke();
    g.restore();
  },
  tag(c, x, y, s, color, a) {
    const g = c.g; g.save(); g.globalAlpha *= a; g.lineWidth = 3 * c.u; g.strokeStyle = color; g.lineJoin = 'round';
    g.beginPath(); g.moveTo(x - s * 0.85, y - s * 0.55); g.lineTo(x + s * 0.3, y - s * 0.55); g.lineTo(x + s * 0.9, y); g.lineTo(x + s * 0.3, y + s * 0.55);
    g.lineTo(x - s * 0.85, y + s * 0.55); g.closePath(); g.stroke(); g.restore();
    disc(c, x - s * 0.45, y, s * 0.13, { fill: color, alpha: a });
  },
  scan(c, x, y, s, color, a) {
    for (const [sx, sy] of [[-1, -1], [1, -1], [1, 1], [-1, 1]]) {
      stroke(c, [[x + sx * s * 0.85, y + sy * s * 0.35], [x + sx * s * 0.85, y + sy * s * 0.85], [x + sx * s * 0.35, y + sy * s * 0.85]], { color, lw: 3, alpha: a });
    }
    stroke(c, [[x - s * 0.6, y], [x + s * 0.6, y]], { color, lw: 3, alpha: a });
  },
  decision(c, x, y, s, color, a) {
    const g = c.g; g.save(); g.globalAlpha *= a; g.lineWidth = 3 * c.u; g.strokeStyle = color; g.lineJoin = 'round';
    g.beginPath(); g.moveTo(x, y - s * 0.9); g.lineTo(x + s * 0.9, y); g.lineTo(x, y + s * 0.9); g.lineTo(x - s * 0.9, y); g.closePath(); g.stroke(); g.restore();
  },
  api(c, x, y, s, color, a) {
    stroke(c, [[x - s * 0.35, y - s * 0.7], [x - s * 0.95, y], [x - s * 0.35, y + s * 0.7]], { color, lw: 3.5, alpha: a });
    stroke(c, [[x + s * 0.35, y - s * 0.7], [x + s * 0.95, y], [x + s * 0.35, y + s * 0.7]], { color, lw: 3.5, alpha: a });
  },
};

function background(c) {
  const { g, W, H, u, t, P } = c;
  const fill = g.createLinearGradient(0, 0, 0, H);
  fill.addColorStop(0, P.bg1); fill.addColorStop(1, P.bg0);
  g.fillStyle = fill; g.fillRect(0, 0, W, H);
  const cx = W / 2, cy = (c.st.y0 + c.st.y1) / 2;
  const light = g.createRadialGradient(cx, cy, 0, cx, cy, W * 0.6);
  light.addColorStop(0, 'rgba(46,130,245,0.17)'); light.addColorStop(1, 'rgba(46,130,245,0)');
  g.fillStyle = light; g.fillRect(0, 0, W, H);
  const step = 64 * u, shift = t * step * 0.75 * c.d;
  g.save();
  g.strokeStyle = 'rgba(126,172,224,0.06)'; g.lineWidth = Math.max(1, u);
  g.beginPath();
  for (let x = ((shift % step) + step) % step - step; x < W + step; x += step) { g.moveTo(x, 0); g.lineTo(x, H); }
  for (let y = 0; y < H + step; y += step) { g.moveTo(0, y); g.lineTo(W, y); }
  g.stroke();
  const next = seeded(977 + c.seed);
  for (let i = 0; i < 44; i += 1) {
    const px = next(), py = next(), speed = 0.03 + next() * 0.07, size = (1.5 + next() * 2.5) * u, alpha = 0.1 + next() * 0.28;
    const x = (((px + t * speed * c.d) % 1) + 1) % 1 * W;
    g.fillStyle = rgba(i % 6 === 0 ? P.gold : P.cyan, alpha);
    g.fillRect(x, py * H, size, size);
  }
  g.restore();
}

// ------------------------------------------------------------------ scenes

const paperToDigital = {
  id: 'paper-to-digital',
  meaning: {
    ar: 'يتحوّل الإجراء الورقي إلى خدمة رقمية بالحقول نفسها، ويُتحقَّق من كل حقل عند إدخاله.',
    en: 'A paper procedure becomes a digital service with the same fields, each validated as it is entered.',
  },
  params: { paper_label: L(18, 0.12), digital_label: L(18, 0.4), fields: LS(2, 3, 14, 0.5, 0.66), submit_label: L(14, 0.8) },
  defaults: {
    ar: { paper_label: 'نموذج ورقي', digital_label: 'خدمة رقمية', fields: ['الهوية', 'الطلب', 'المرفقات'], submit_label: 'إرسال' },
    en: { paper_label: 'Paper form', digital_label: 'Digital service', fields: ['Identity', 'Request', 'Attachments'], submit_label: 'Submit' },
  },
  state(t, p) {
    const S = paperToDigital.params, n = p.fields.length;
    let valid = 0;
    for (let i = 0; i < n; i += 1) if (t >= labelTime(S.fields, i, n) + 0.12) valid += 1;
    return { fields: n, fields_valid: valid, paper_archived: t >= 0.56, submitted: valid === n && t >= 0.86 };
  },
  draw(c) {
    const { t, p, u, P } = c, S = paperToDigital.params, n = p.fields.length;
    const px = c.x(0.17), py = c.y(0.46), pw = 240 * u, ph = 320 * u;
    const dx = c.x(0.73), dy = c.y(0.46), dw = 520 * u, dh = 410 * u;
    const sheet = (x, y, w, h, alpha, fold) => {
      if (alpha <= 0) return;
      panel(c, x - w / 2, y - h / 2, w, h, { r: 6, fill: '#dfe6ee', stroke: '#f6f9fc', lw: 2, alpha });
      const rows = Math.max(2, Math.round(6 * (h / ph) / (w / pw)));
      for (let i = 0; i < rows; i += 1) {
        const yy = y - h / 2 + (i + 1) * h / (rows + 1), short = i % 3 === 2 ? 0.45 : 0.76;
        stroke(c, [[x - c.d * w * 0.38, yy], [x - c.d * w * 0.38 + c.d * w * short, yy]], { color: '#8494a8', lw: 4 * (w / pw), alpha, cap: 'butt' });
      }
      if (fold > 0) stroke(c, [[x - w / 2, y], [x + w / 2, y]], { color: '#93a2b5', lw: 2, alpha: alpha * fold });
    };
    // Device with the digital form.
    const dv = eo(seg(t, 0.04, 0.2));
    panel(c, dx - dw / 2, dy - dh / 2, dw, dh, { r: 28, fill: P.panel, stroke: P.blue, lw: 3, alpha: dv, glow: rgba(P.blue, 0.35) });
    panel(c, dx - dw / 2 + 18 * u, dy - dh / 2 + 18 * u, dw - 36 * u, 58 * u, { r: 12, fill: P.panelHi, stroke: null, alpha: dv });
    text(c, p.digital_label, dx, dy - dh / 2 + 47 * u, { size: 30, weight: 700, color: P.cyan, alpha: vis(t, S.digital_label.label_in), maxWidth: dw - 80 * u });
    const ix0 = dx - dw / 2 + 30 * u, ix1 = dx + dw / 2 - 30 * u, iw = ix1 - ix0;
    for (let i = 0; i < n; i += 1) {
      const at = labelTime(S.fields, i, n), a = vis(t, at), yy = dy - dh / 2 + 122 * u + i * 76 * u;
      const fill = eo(seg(t, at + 0.02, at + 0.1)), ok = seg(t, at + 0.09, at + 0.14);
      text(c, p.fields[i], c.rtl ? ix1 : ix0, yy, { size: 29, align: 'start', color: P.soft, alpha: a, maxWidth: iw * 0.4 });
      const bx = c.rtl ? ix0 : ix0 + iw * 0.44, bw = iw * 0.56;
      panel(c, bx, yy - 25 * u, bw, 50 * u, { r: 10, fill: P.dark, stroke: ok > 0 ? P.green : P.line, lw: 2, alpha: a });
      const fx = c.rtl ? bx + bw - 14 * u : bx + 14 * u, fw = (bw - 78 * u) * fill;
      panel(c, c.rtl ? fx - fw : fx, yy - 7 * u, fw, 14 * u, { r: 7, fill: rgba(P.cyan, 0.75), stroke: null, alpha: a });
      check(c, c.rtl ? bx + 26 * u : bx + bw - 26 * u, yy, 11 * u, ok, P.green, 4);
    }
    const sb = vis(t, S.submit_label.label_in), ready = seg(t, 0.8, 0.9);
    const bw = 190 * u, bh = 54 * u, by = dy + dh / 2 - 46 * u;
    panel(c, dx - bw / 2, by - bh / 2, bw, bh, { r: 27, fill: P.gold, stroke: null, alpha: sb, glow: rgba(P.gold, 0.25 + 0.3 * ready) });
    text(c, p.submit_label, dx, by, { size: 28, weight: 700, color: P.dark, alpha: sb, maxWidth: bw - 30 * u });
    // The paper, then its folded copy travelling into the device.
    const archived = eio(seg(t, 0.42, 0.56));
    sheet(px, py, pw, ph, eo(seg(t, 0.02, 0.12)) * lerp(1, 0.34, archived), 0);
    const fly = seg(t, 0.18, 0.46);
    const link = [[px + c.d * pw * 0.62, py], [dx - c.d * (dw / 2 + 14 * u), dy]];
    stroke(c, link, { color: P.cyan, lw: 3, dash: [12, 12], dashOffset: -t * 260, alpha: 0.75 * seg(t, 0.14, 0.24), progress: 1 });
    if (fly > 0 && fly < 1) {
      const e = eio(fly), s = lerp(1, 0.3, e), fold = eo(seg(fly, 0.05, 0.55));
      sheet(lerp(px, dx - c.d * dw * 0.3, e), lerp(py, dy, e) - Math.sin(e * Math.PI) * 70 * u, pw * s, ph * s * lerp(1, 0.5, fold), 1 - seg(fly, 0.82, 1), fold);
    }
    text(c, p.paper_label, px, py + ph / 2 + 44 * u, { size: 32, color: P.soft, alpha: vis(t, S.paper_label.label_in), maxWidth: pw * 1.5 });
  },
};

const serviceJourney = {
  id: 'service-journey',
  meaning: {
    ar: 'تُقدَّم الخدمة رحلةً رقمية واحدة يمكن تتبّعها خطوة بخطوة، من الطلب إلى الإشعار.',
    en: 'A service is delivered as one traceable digital journey, step by step, from request to notification.',
  },
  params: { title: L(30, 0.08), steps: LS(3, 5, 14, 0.16, 0.62), done_label: L(16, 0.78) },
  defaults: {
    ar: { title: 'رحلة الخدمة الرقمية', steps: ['طلب', 'تحقّق', 'قرار', 'إشعار'], done_label: 'مكتملة' },
    en: { title: 'Digital service journey', steps: ['Request', 'Verification', 'Decision', 'Notification'], done_label: 'Completed' },
  },
  state(t, p) {
    const S = serviceJourney.params, n = p.steps.length;
    let lit = 0;
    for (let i = 0; i < n; i += 1) if (t >= labelTime(S.steps, i, n)) lit += 1;
    return { steps: n, lit, complete: lit === n && t >= 0.74 };
  },
  draw(c) {
    const { t, p, u, P } = c, S = serviceJourney.params, n = p.steps.length;
    const y = c.y(0.5), xs = p.steps.map((_, i) => c.x(0.1 + 0.8 * i / (n - 1)));
    const times = xs.map((_, i) => labelTime(S.steps, i, n));
    const icons = n === 4 ? ['doc', 'scan', 'decision', 'bell'] : null;
    text(c, p.title, c.x(0.5), c.y(0.09), { size: 36, weight: 700, font: 'head', color: P.soft, alpha: vis(t, S.title.label_in), maxWidth: c.sw * 0.7 });
    const track = xs.map((x) => [x, y]);
    stroke(c, track, { color: P.line, lw: 6, alpha: eo(seg(t, 0.03, 0.14)) });
    let head = 0;
    if (t >= times[n - 1]) head = n - 1;
    else for (let i = 0; i < n - 1; i += 1) if (t >= times[i] && t < times[i + 1]) head = i + eio((t - times[i]) / (times[i + 1] - times[i]));
    if (t >= times[0]) stroke(c, track, { color: P.cyan, lw: 6, progress: head / (n - 1), glow: rgba(P.cyan, 0.7) });
    const done = seg(t, 0.68, 0.76);
    for (let i = 0; i < n; i += 1) {
      const k = eo(seg(t, times[i], times[i] + 0.06)), last = i === n - 1, color = last && done > 0 ? P.green : P.cyan;
      const r = (50 + 5 * Math.sin(Math.PI * seg(t, times[i], times[i] + 0.1))) * u;
      disc(c, xs[i], y, r, { fill: k > 0 ? P.panelHi : P.panel, stroke: k > 0 ? color : P.line, lw: 4, alpha: eo(seg(t, 0.04 + i * 0.02, 0.14 + i * 0.02)), glow: k > 0 ? rgba(color, 0.55 * k) : null });
      if (icons) ICONS[icons[i]](c, xs[i], y, 20 * u, k > 0 ? P.text : P.dim, eo(seg(t, 0.06 + i * 0.02, 0.16 + i * 0.02)));
      else text(c, String(i + 1), xs[i], y, { size: 34, font: 'mono', weight: 500, color: k > 0 ? P.text : P.soft, alpha: eo(seg(t, 0.06, 0.16)), role: 'number' });
      disc(c, xs[i] + 36 * u, y - 36 * u, 17 * u, { fill: last && done > 0 ? P.green : P.cyan, alpha: k });
      check(c, xs[i] + 36 * u, y - 36 * u, 8 * u, k, P.dark, 3.5);
      text(c, p.steps[i], xs[i], y + 100 * u, { size: 34, weight: 700, color: k > 0 ? P.text : P.soft, alpha: vis(t, times[i]), maxWidth: (0.8 * c.sw / (n - 1)) * 0.86 });
    }
    if (t >= times[0] && t < times[n - 1]) pulse(c, track, head / (n - 1), P.text, 1, 8);
    const dl = vis(t, S.done_label.label_in), lx = xs[n - 1];
    panel(c, lx - 110 * u, y - 158 * u, 220 * u, 56 * u, { r: 28, fill: rgba(P.green, 0.16), stroke: P.green, lw: 2, alpha: dl });
    text(c, p.done_label, lx, y - 130 * u, { size: 28, weight: 700, color: P.green, alpha: dl, maxWidth: 190 * u });
    const idle = seg(t, 0.78, 0.84) * (1 - seg(t, 0.94, 1));
    for (let k = 0; k < 3; k += 1) pulse(c, track, (t * 3 + k / 3) % 1, P.cyan, 0.55 * idle, 5);
  },
};

const dataPipeline = {
  id: 'data-pipeline',
  meaning: {
    ar: 'لا تمرّ البيانات إلا عبر مراحل محكومة: تُتحقَّق وتُصنَّف وتُحمى قبل أن تُخزَّن.',
    en: 'Data moves only through governed stages: validated, classified and protected before it is stored.',
  },
  params: { policy_label: L(26, 0.1), stages: LS(3, 4, 12, 0.14, 0.3), quarantine_label: L(16, 0.46), stored_label: L(18, 0.62), records: INT(4, 8, 6) },
  defaults: {
    ar: { policy_label: 'حوكمة البيانات', stages: ['تحقّق', 'تصنيف', 'حماية', 'تخزين'], quarantine_label: 'مرفوض', stored_label: 'سجلات موثوقة', records: 6 },
    en: { policy_label: 'Data governance', stages: ['Validate', 'Classify', 'Protect', 'Store'], quarantine_label: 'Rejected', stored_label: 'Trusted records', records: 6 },
  },
  timing(p) {
    const count = p.records, rejected = 1;   // the second record fails validation
    const enter = (k) => 0.2 + k * (0.42 / (count - 1));
    return { count, rejected, enter, travel: 0.26 };
  },
  state(t, p) {
    const T = dataPipeline.timing(p);
    let stored = 0;
    for (let k = 0; k < T.count; k += 1) if (k !== T.rejected && t >= T.enter(k) + T.travel) stored += 1;
    return { records: T.count, stored, quarantined: t >= T.enter(T.rejected) + T.travel * 0.45 ? 1 : 0, valid_total: T.count - 1 };
  },
  draw(c) {
    const { t, p, u, P } = c, S = dataPipeline.params, n = p.stages.length, T = dataPipeline.timing(p);
    const y = c.y(0.5), fx = p.stages.map((_, i) => 0.16 + 0.68 * i / (n - 1)), xs = fx.map((f) => c.x(f));
    const gw = 176 * u, gh = 168 * u, icons = n === 4 ? ['scan', 'tag', 'lock', 'database'] : ['scan', 'lock', 'database'];
    const rail = [[c.x(0), y], [c.x(1), y]];
    stroke(c, rail, { color: P.line, lw: 8, alpha: eo(seg(t, 0.03, 0.12)) });
    stroke(c, rail, { color: rgba(P.cyan, 0.5), lw: 2, dash: [14, 18], dashOffset: -t * 500, alpha: eo(seg(t, 0.1, 0.2)) });
    // Governance bar over every stage.
    const pa = vis(t, S.policy_label.label_in), py = c.y(0.07);
    const bx0 = Math.min(xs[0], xs[n - 1]) - gw / 2, bx1 = Math.max(xs[0], xs[n - 1]) + gw / 2;
    panel(c, bx0, py - 30 * u, bx1 - bx0, 60 * u, { r: 30, fill: rgba(P.gold, 0.1), stroke: P.gold, lw: 2, alpha: pa });
    text(c, p.policy_label, (bx0 + bx1) / 2, py, { size: 30, weight: 700, color: P.gold, alpha: pa, maxWidth: (bx1 - bx0) * 0.8 });
    for (let i = 0; i < n; i += 1) stroke(c, [[xs[i], py + 30 * u], [xs[i], y - gh / 2]], { color: P.gold, lw: 2, dash: [6, 8], alpha: 0.7 * pa, progress: eo(seg(t, 0.1 + i * 0.03, 0.2 + i * 0.03)) });
    // Records travel behind the gates.
    const qx = xs[0] + c.d * 0 * u, qy = c.y(0.93);
    for (let k = 0; k < T.count; k += 1) {
      const f = seg(t, T.enter(k), T.enter(k) + T.travel);
      if (f <= 0) continue;
      const bad = k === T.rejected;
      let pf = lerp(0, fx[n - 1], f), ry = y, alpha = 1;
      if (bad) {
        const stop = fx[0] / fx[n - 1], drop = eio(seg(f, stop, stop + 0.3));
        pf = lerp(0, fx[n - 1], Math.min(f, stop)); ry = lerp(y, qy - 62 * u, drop); alpha = f < stop ? 1 : lerp(1, 0.9, drop);
        if (f >= stop + 0.3) continue;
      } else if (f >= 1) continue;
      const rx = c.x(pf), masked = !bad && pf >= fx[n - 2], color = bad ? P.gold : P.cyan;
      panel(c, rx - 30 * u, ry - 21 * u, 60 * u, 42 * u, { r: 7, fill: P.panelHi, stroke: color, lw: 2, alpha });
      stroke(c, [[rx - 18 * u, ry - 7 * u], [rx + 18 * u, ry - 7 * u]], { color, lw: 3, alpha });
      if (masked) for (let d = 0; d < 4; d += 1) disc(c, rx - 15 * u + d * 10 * u, ry + 8 * u, 2.6 * u, { fill: P.green, alpha });
      else stroke(c, [[rx - 18 * u, ry + 8 * u], [rx + 8 * u, ry + 8 * u]], { color: rgba(color, 0.7), lw: 3, alpha });
    }
    const st = dataPipeline.state(t, p);
    for (let i = 0; i < n; i += 1) {
      const at = labelTime(S.stages, i, n), a = vis(t, at), last = i === n - 1;
      panel(c, xs[i] - gw / 2, y - gh / 2, gw, gh, { r: 18, fill: P.panel, stroke: last && st.stored ? P.green : P.blue, lw: 3, alpha: a, glow: rgba(P.blue, 0.25) });
      ICONS[icons[Math.min(i, icons.length - 1)]](c, xs[i], y - 30 * u, 24 * u, last ? P.green : P.cyan, a);
      text(c, p.stages[i], xs[i], y + 42 * u, { size: 32, weight: 700, alpha: a, maxWidth: gw - 24 * u });
    }
    const qa = vis(t, S.quarantine_label.label_in);
    panel(c, qx - 120 * u, qy - 32 * u, 240 * u, 64 * u, { r: 12, fill: rgba(P.gold, 0.1), stroke: P.gold, lw: 2, dash: [8, 6], alpha: qa });
    cross(c, qx - c.d * 86 * u, qy, 9 * u, P.gold, qa * st.quarantined);
    text(c, p.quarantine_label, qx + c.d * 14 * u, qy, { size: 28, weight: 700, color: P.gold, alpha: qa, maxWidth: 150 * u });
    const sa = vis(t, S.stored_label.label_in), sx = xs[n - 1], sy = c.y(0.93);
    text(c, `${st.stored}/${st.valid_total}`, sx + c.d * 92 * u, sy, { size: 40, font: 'mono', weight: 500, color: P.green, alpha: sa, role: 'number' });
    text(c, p.stored_label, sx - c.d * 30 * u, sy, { size: 28, color: P.soft, alpha: sa, maxWidth: 190 * u });
  },
};

const integrationMesh = {
  id: 'integration-mesh',
  meaning: {
    ar: 'تتبادل الأنظمة بياناتها عبر واجهات برمجية موثّقة وطبقة تكامل واحدة، لا عبر التسليم اليدوي.',
    en: 'Systems exchange data through documented APIs and one integration layer instead of manual hand-offs.',
  },
  params: { hub_label: L(16, 0.12), systems: LS(4, 6, 14, 0.1, 0.24), contract_label: L(22, 0.8) },
  defaults: {
    ar: { hub_label: 'طبقة التكامل', systems: ['الهوية', 'المدفوعات', 'السجلات', 'الإشعارات'], contract_label: 'واجهات موثّقة' },
    en: { hub_label: 'Integration layer', systems: ['Identity', 'Payments', 'Records', 'Notifications'], contract_label: 'Documented APIs' },
  },
  shake: (i, n) => 0.3 + i * (0.4 / n),
  state(t, p) {
    const n = p.systems.length;
    let connected = 0;
    for (let i = 0; i < n; i += 1) if (t >= integrationMesh.shake(i, n) + 0.14) connected += 1;
    return { systems: n, connected, mesh_ready: connected === n };
  },
  draw(c) {
    const { t, p, u, P } = c, S = integrationMesh.params, n = p.systems.length;
    const hx = c.x(0.5), hy = c.y(0.47), hr = 128 * u, near = Math.ceil(n / 2), sw = 290 * u, sh = 76 * u;
    const st = integrationMesh.state(t, p);
    const ha = vis(t, S.hub_label.label_in);
    for (let i = 0; i < n; i += 1) {
      const side = i < near ? 0 : 1, k = side ? i - near : i, count = side ? n - near : near;
      const sx = c.x(side ? 0.885 : 0.115), sy = c.y(count === 1 ? 0.47 : 0.14 + 0.66 * k / (count - 1));
      const inner = sx + (hx > sx ? 1 : -1) * sw / 2, edge = hx + (sx > hx ? 1 : -1) * hr, mid = (inner + edge) / 2;
      const path = [[inner, sy], [mid, sy], [mid, hy + (sy - hy) * 0.28], [edge, hy + (sy - hy) * 0.28]];
      const a = vis(t, labelTime(S.systems, i, n)), h0 = integrationMesh.shake(i, n);
      const out = seg(t, h0, h0 + 0.07), ret = seg(t, h0 + 0.07, h0 + 0.14), ok = ret >= 1;
      stroke(c, path, { color: P.line, lw: 4, alpha: a });
      if (out > 0) stroke(c, path, { color: ok ? P.cyan : rgba(P.cyan, 0.7), lw: 4, progress: out, glow: ok ? rgba(P.cyan, 0.5) : null });
      if (out > 0 && out < 1) pulse(c, path, out, P.text);
      if (ret > 0 && ret < 1) pulse(c, path, 1 - ret, P.green);
      const idle = seg(t, 0.74, 0.8) * (1 - seg(t, 0.93, 1));
      pulse(c, path, (t * 4 + i * 0.37) % 1, P.cyan, 0.6 * idle, 5);
      panel(c, sx - sw / 2, sy - sh / 2, sw, sh, { r: 16, fill: P.panel, stroke: ok ? P.cyan : P.line, lw: 2.5, alpha: a, glow: ok ? rgba(P.cyan, 0.3) : null });
      text(c, p.systems[i], sx + c.d * 14 * u, sy, { size: 31, weight: 700, alpha: a, maxWidth: sw - 96 * u });
      const cx = sx - c.d * (sw / 2 - 34 * u);
      disc(c, cx, sy, 17 * u, { fill: ok ? P.green : P.dark, stroke: ok ? null : P.line, lw: 2, alpha: a });
      check(c, cx, sy, 8 * u, seg(t, h0 + 0.12, h0 + 0.17), P.dark, 3.5);
    }
    const flash = Math.max(0, ...p.systems.map((_, i) => { const h0 = integrationMesh.shake(i, n); return Math.sin(Math.PI * seg(t, h0 + 0.04, h0 + 0.12)); }));
    const g = c.g;
    g.save(); g.globalAlpha *= ha;
    g.beginPath();
    for (let k = 0; k < 6; k += 1) { const ang = Math.PI / 6 + k * Math.PI / 3; g[k ? 'lineTo' : 'moveTo'](hx + hr * Math.cos(ang), hy + hr * Math.sin(ang)); }
    g.closePath();
    g.shadowColor = rgba(P.blue, 0.5 + 0.4 * flash); g.shadowBlur = (30 + 30 * flash) * u;
    g.fillStyle = P.panelHi; g.fill(); g.shadowBlur = 0; g.shadowColor = 'transparent';
    g.lineWidth = 3.5 * u; g.strokeStyle = st.mesh_ready ? P.green : P.blue; g.stroke(); g.restore();
    ICONS.api(c, hx, hy - 34 * u, 24 * u, P.cyan, ha);
    text(c, p.hub_label, hx, hy + 30 * u, { size: 30, weight: 700, alpha: ha, maxWidth: hr * 1.62 });
    const ca = vis(t, S.contract_label.label_in), cy = c.y(0.935);
    panel(c, hx - 170 * u, cy - 29 * u, 340 * u, 58 * u, { r: 29, fill: rgba(P.green, 0.14), stroke: P.green, lw: 2, alpha: ca });
    text(c, p.contract_label, hx, cy, { size: 28, weight: 700, color: P.green, alpha: ca, maxWidth: 300 * u });
  },
};

const approvalGate = {
  id: 'approval-gate',
  meaning: {
    ar: 'الإجراء الحسّاس ينتظر موافقة بشرية مسمّاة، ولا يعبر البوابة شيء قبلها.',
    en: 'A sensitive action waits for a named human approval; nothing passes the gate before it.',
  },
  params: { request_label: L(16, 0.1), gate_label: L(18, 0.2), approver_label: L(18, 0.26), approved_label: L(16, 0.56), action_label: L(16, 0.14) },
  defaults: {
    ar: { request_label: 'طلب تنفيذ', gate_label: 'بوابة الموافقة', approver_label: 'المسؤول المعتمِد', approved_label: 'تمّت الموافقة', action_label: 'التنفيذ' },
    en: { request_label: 'Change request', gate_label: 'Approval gate', approver_label: 'Named approver', approved_label: 'Approved', action_label: 'Execution' },
  },
  T: { arrive: 0.3, approve: 0.52, open: 0.64, pass: 0.82 },
  state(t) {
    const T = approvalGate.T;
    const approved = t >= T.approve, open = t >= T.open, passed = t >= T.pass;
    return { waiting: t >= T.arrive && !open, approved, gate_open: open, passed, opened_before_approval: open && !approved };
  },
  draw(c) {
    const { t, p, u, P } = c, S = approvalGate.params, T = approvalGate.T;
    const y = c.y(0.62), x0 = c.x(0.08), gx = c.x(0.56), x1 = c.x(0.9), st = approvalGate.state(t);
    stroke(c, [[x0, y], [x1, y]], { color: P.line, lw: 8, alpha: eo(seg(t, 0.03, 0.12)) });
    stroke(c, [[x0, y], [gx - c.d * 46 * u, y]], { color: rgba(P.cyan, 0.8), lw: 4, progress: eo(seg(t, 0.12, T.arrive)) });
    if (st.gate_open) stroke(c, [[gx + c.d * 46 * u, y], [x1, y]], { color: P.green, lw: 4, progress: eio(seg(t, T.open + 0.04, T.pass)), glow: rgba(P.green, 0.5) });
    // Action node.
    const aa = vis(t, S.action_label.label_in);
    disc(c, x1, y, 56 * u, { fill: st.passed ? P.panelHi : P.panel, stroke: st.passed ? P.green : P.line, lw: 4, alpha: aa, glow: st.passed ? rgba(P.green, 0.6) : null });
    check(c, x1, y, 22 * u, seg(t, T.pass, T.pass + 0.07), P.green, 6);
    text(c, p.action_label, x1, y + 104 * u, { size: 32, weight: 700, color: st.passed ? P.green : P.soft, alpha: aa, maxWidth: 240 * u });
    // Gate: two posts and a bar that lifts only after approval.
    const ga = vis(t, S.gate_label.label_in), lift = eio(seg(t, T.open - 0.08, T.open + 0.02));
    const gateColor = st.approved ? P.green : P.gold, top = y - 96 * u;
    panel(c, gx - 46 * u, top, 12 * u, 192 * u, { r: 6, fill: gateColor, stroke: null, alpha: ga });
    panel(c, gx + 34 * u, top, 12 * u, 192 * u, { r: 6, fill: gateColor, stroke: null, alpha: ga });
    panel(c, gx - 34 * u, lerp(y - 12 * u, top - 4 * u, lift), 68 * u, 24 * u, { r: 8, fill: gateColor, stroke: null, alpha: ga, glow: rgba(gateColor, 0.5) });
    text(c, p.gate_label, gx, y + 136 * u, { size: 30, weight: 700, color: gateColor, alpha: ga, maxWidth: 300 * u });
    // Approver panel above the gate.
    const pa = vis(t, S.approver_label.label_in), pw = 380 * u, ph = 150 * u, pyy = c.y(0.16);
    panel(c, gx - pw / 2, pyy - ph / 2, pw, ph, { r: 20, fill: P.panel, stroke: st.approved ? P.green : P.blue, lw: 2.5, alpha: pa, glow: rgba(st.approved ? P.green : P.blue, 0.3) });
    ICONS.user(c, gx + c.d * (pw / 2 - 56 * u), pyy - 4 * u, 30 * u, st.approved ? P.green : P.cyan, pa);
    text(c, p.approver_label, gx - c.d * 34 * u, pyy - 30 * u, { size: 29, weight: 700, alpha: pa, maxWidth: pw - 150 * u });
    const da = vis(t, S.approved_label.label_in), stamp = back(seg(t, T.approve - 0.04, T.approve + 0.04));
    panel(c, gx - c.d * 34 * u - 118 * u, pyy + 6 * u, 236 * u, 50 * u, { r: 25, fill: da > 0 ? rgba(P.green, 0.18) : P.dark, stroke: da > 0 ? P.green : P.line, lw: 2, alpha: pa });
    text(c, p.approved_label, gx - c.d * 34 * u, pyy + 31 * u, { size: 27, weight: 700, color: P.green, alpha: da * clamp(stamp), maxWidth: 200 * u });
    stroke(c, [[gx, pyy + ph / 2], [gx, top - 8 * u]], { color: st.approved ? P.green : P.line, lw: 3, dash: [8, 8], alpha: pa, progress: st.approved ? eo(seg(t, T.approve, T.open - 0.06)) : 1 });
    // The request token: arrives, waits at the gate, passes only after it opens.
    const ra = vis(t, S.request_label.label_in);
    let tx = lerp(x0, gx - c.d * 92 * u, eio(seg(t, 0.12, T.arrive)));
    if (t >= T.arrive && !st.gate_open) tx -= c.d * 5 * u * Math.sin(seg(t, T.arrive, T.open) * Math.PI * 6) ** 2;   // held at the gate
    if (st.gate_open) tx = lerp(gx - c.d * 92 * u, x1, eio(seg(t, T.open + 0.04, T.pass)));
    const hold = t >= T.arrive && !st.approved;
    if (t < T.pass) {
      panel(c, tx - 36 * u, y - 28 * u, 72 * u, 56 * u, { r: 10, fill: P.panelHi, stroke: hold ? P.gold : P.cyan, lw: 3, alpha: ra, glow: rgba(hold ? P.gold : P.cyan, 0.55) });
      ICONS.doc(c, tx, y, 13 * u, P.text, ra);
    }
    text(c, p.request_label, x0 + c.d * 30 * u, y + 104 * u, { size: 32, weight: 700, color: P.soft, alpha: ra, maxWidth: 300 * u });
  },
};

const kpiGauge = {
  id: 'kpi-gauge',
  meaning: {
    ar: 'يُحسب المؤشر من معادلته المعلنة وأرقام مصدره، فيمكن إعادة اشتقاق كل رقم.',
    en: 'An indicator is computed from its published formula and source numbers, so every figure can be re-derived.',
  },
  params: { kpi_label: L(24, 0.08), numerator_label: L(20, 0.16), denominator_label: L(20, 0.22), numerator: INT(0, 999999999, 0),
    denominator: INT(1, 999999999, 1), verified_label: L(24, 0.84) },
  defaults: {
    ar: { kpi_label: 'نسبة الخدمات الرقمية', numerator_label: 'خدمات رقمية', denominator_label: 'إجمالي الخدمات', numerator: 0, denominator: 1, verified_label: 'يُعاد حسابه من المصدر' },
    en: { kpi_label: 'Digital service ratio', numerator_label: 'Digital services', denominator_label: 'All services', numerator: 0, denominator: 1, verified_label: 'Recomputed from source' },
  },
  value: (p) => Math.round(Math.min(p.numerator, p.denominator) / p.denominator * 1000) / 10,
  state(t, p) {
    const value = kpiGauge.value(p), shown = Math.round(value * eio(seg(t, 0.44, 0.76)) * 10) / 10;
    return { value, shown, numerator: p.numerator, denominator: p.denominator, formula: 'numerator / denominator * 100', verified: t >= 0.84 };
  },
  draw(c) {
    const { t, p, u, P, g } = c, S = kpiGauge.params, st = kpiGauge.state(t, p);
    text(c, p.kpi_label, c.x(0.5), c.y(0.07), { size: 38, weight: 700, font: 'head', alpha: vis(t, S.kpi_label.label_in), maxWidth: c.sw * 0.8 });
    // Formula panel on the start side: numerator over denominator, then the visible result.
    const fx = c.x(0.27), fy = c.y(0.49), fw = 560 * u, fh = 292 * u, fa = eo(seg(t, 0.06, 0.16));
    panel(c, fx - fw / 2, fy - fh / 2, fw, fh, { r: 22, fill: P.panel, stroke: P.line, lw: 2, alpha: fa });
    const count = eio(seg(t, 0.2, 0.42)), labelX = fx - c.d * (fw / 2 - 30 * u), numX = fx + c.d * (fw / 2 - 120 * u);
    const row = (label, value, y, at) => {
      text(c, label, labelX, y, { size: 30, align: 'start', color: P.soft, alpha: vis(t, at), maxWidth: fw * 0.52 });
      text(c, grouped(value * count), numX, y, { size: 42, font: 'mono', weight: 500, color: P.cyan, alpha: vis(t, at), role: 'number', maxWidth: 200 * u });
    };
    row(p.numerator_label, p.numerator, fy - 92 * u, S.numerator_label.label_in);
    stroke(c, [[fx - fw / 2 + 30 * u, fy - 46 * u], [fx + fw / 2 - 30 * u, fy - 46 * u]], { color: P.soft, lw: 3, alpha: fa, progress: eo(seg(t, 0.14, 0.24)) });
    row(p.denominator_label, p.denominator, fy, S.denominator_label.label_in);
    text(c, `\u00D7 100 = ${st.shown.toFixed(1)}%`, fx, fy + 92 * u, { size: 44, font: 'mono', weight: 500, color: P.gold, alpha: eo(seg(t, 0.4, 0.48)), role: 'number', maxWidth: fw - 60 * u });
    // Gauge on the end side.
    const gx = c.x(0.77), gy = c.y(0.54), r = 158 * u, a0 = Math.PI * 0.75, sweep = Math.PI * 1.5, ga = eo(seg(t, 0.1, 0.22));
    const arc = (from, to, color, lw, glow) => {
      g.save(); g.globalAlpha *= ga; g.lineCap = 'round'; g.lineWidth = lw * u; g.strokeStyle = color;
      if (glow) { g.shadowColor = glow; g.shadowBlur = 24 * u; }
      g.beginPath(); g.arc(gx, gy, r, from, to); g.stroke(); g.restore();
    };
    arc(a0, a0 + sweep, P.line, 22);
    if (st.shown > 0) arc(a0, a0 + sweep * clamp(st.shown / 100), st.verified ? P.green : P.cyan, 22, rgba(st.verified ? P.green : P.cyan, 0.6));
    for (let k = 0; k <= 10; k += 1) {
      const ang = a0 + sweep * k / 10;
      stroke(c, [[gx + Math.cos(ang) * (r + 20 * u), gy + Math.sin(ang) * (r + 20 * u)], [gx + Math.cos(ang) * (r + 30 * u), gy + Math.sin(ang) * (r + 30 * u)]], { color: P.dim, lw: 3, alpha: ga });
    }
    text(c, `${st.shown.toFixed(1)}%`, gx, gy, { size: 74, font: 'latin', weight: 600, color: P.text, alpha: ga, role: 'number', maxWidth: r * 1.5 });
    const va = vis(t, S.verified_label.label_in), vy = c.y(0.93), vw = 460 * u;
    panel(c, fx - vw / 2, vy - 28 * u, vw, 56 * u, { r: 28, fill: rgba(P.green, 0.14), stroke: P.green, lw: 2, alpha: va });
    check(c, fx + c.d * -(vw / 2 - 36 * u), vy, 10 * u, seg(t, 0.8, 0.86), P.green, 4.5);
    text(c, p.verified_label, fx + c.d * 14 * u, vy, { size: 28, weight: 700, color: P.green, alpha: va, maxWidth: vw - 100 * u });
  },
};

const auditTrail = {
  id: 'audit-trail',
  meaning: {
    ar: 'كل إجراء يترك إيصالًا موقّعًا ومتسلسلًا يمكن تدقيقه لاحقًا.',
    en: 'Every action leaves a signed, chained receipt that can be audited later.',
  },
  params: { title: L(26, 0.08), entries: LS(3, 4, 22, 0.16, 0.56), seal_label: L(24, 0.8) },
  defaults: {
    ar: { title: 'سجل التدقيق', entries: ['استلام الطلب', 'التحقق من الهوية', 'اعتماد القرار', 'إشعار المستفيد'], seal_label: 'سلسلة إيصالات مختومة' },
    en: { title: 'Audit trail', entries: ['Request received', 'Identity verified', 'Decision approved', 'Beneficiary notified'], seal_label: 'Sealed receipt chain' },
  },
  chain(p) {
    let previous = 0x811c9dc5;
    return p.entries.map((entry) => { previous = chainDigest(entry, previous); return hex8(previous); });
  },
  state(t, p) {
    const S = auditTrail.params, n = p.entries.length;
    let stamped = 0;
    for (let i = 0; i < n; i += 1) if (t >= labelTime(S.entries, i, n) + 0.08) stamped += 1;
    return { entries: n, stamped, sealed: stamped === n && t >= 0.8, chain: auditTrail.chain(p) };
  },
  draw(c) {
    const { t, p, u, P } = c, S = auditTrail.params, n = p.entries.length, chain = auditTrail.chain(p);
    text(c, p.title, c.x(0.5), c.y(0.06), { size: 36, weight: 700, font: 'head', color: P.soft, alpha: vis(t, S.title.label_in), maxWidth: c.sw * 0.6 });
    const rw = c.sw * 0.86, rh = Math.min(84 * u, (c.sh * 0.68) / n - 14 * u), x0 = c.x(0.5) - rw / 2, top = c.y(0.15);
    const gap = (c.sh * 0.68 - rh * n) / Math.max(1, n - 1);
    const startX = c.rtl ? x0 + rw : x0, hx = c.x(0.5) + c.d * rw * 0.2, sx = c.rtl ? x0 + 52 * u : x0 + rw - 52 * u;
    for (let i = 0; i < n; i += 1) {
      const at = labelTime(S.entries, i, n), a = vis(t, at), yy = top + i * (rh + gap) + rh / 2;
      const st = back(seg(t, at + 0.03, at + 0.1)), stamped = t >= at + 0.08;
      if (i > 0) stroke(c, [[hx, yy - rh / 2 - gap], [hx, yy - rh / 2]], { color: P.cyan, lw: 3, alpha: 0.9, progress: eo(seg(t, at - 0.04, at + 0.02)), glow: rgba(P.cyan, 0.5) });
      panel(c, x0, yy - rh / 2, rw, rh, { r: 16, fill: P.panel, stroke: stamped ? rgba(P.green, 0.8) : P.line, lw: 2, alpha: a, glow: stamped ? rgba(P.green, 0.18) : null });
      text(c, String(i + 1).padStart(2, '0'), startX + c.d * 46 * u, yy, { size: 30, font: 'mono', weight: 500, color: P.dim, alpha: a, track: false });
      text(c, p.entries[i], startX + c.d * 96 * u, yy, { size: 31, weight: 700, align: 'start', alpha: a, maxWidth: rw * 0.5 });
      panel(c, hx - 108 * u, yy - 24 * u, 216 * u, 48 * u, { r: 10, fill: P.dark, stroke: P.cyan, lw: 2, alpha: a * seg(t, at, at + 0.04) });
      text(c, chain[i], hx, yy + 1 * u, { size: 28, font: 'mono', weight: 500, color: P.cyan, alpha: a * seg(t, at, at + 0.04), role: 'number' });
      disc(c, sx, yy, 26 * u * clamp(st, 0, 1.25), { fill: rgba(P.green, 0.16), stroke: P.green, lw: 3, alpha: seg(t, at + 0.03, at + 0.06) });
      check(c, sx, yy, 11 * u, seg(t, at + 0.06, at + 0.11), P.green, 4.5);
    }
    const sa = vis(t, S.seal_label.label_in), sy = c.y(0.935);
    panel(c, c.x(0.5) - 250 * u, sy - 30 * u, 500 * u, 60 * u, { r: 30, fill: rgba(P.gold, 0.12), stroke: P.gold, lw: 2, alpha: sa });
    ICONS.lock(c, c.x(0.5) + c.d * 204 * u, sy, 15 * u, P.gold, sa);
    text(c, p.seal_label, c.x(0.5) - c.d * 16 * u, sy, { size: 28, weight: 700, color: P.gold, alpha: sa, maxWidth: 380 * u });
  },
};

const zeroTrustShield = {
  id: 'zero-trust-shield',
  meaning: {
    ar: 'الوصول مرفوض افتراضيًا، ولا يبلغ المورد إلا مسار واحد متحقَّق منه ومطابق للسياسة.',
    en: 'Access is denied by default; only one verified, policy-checked path reaches the resource.',
  },
  params: { deny_label: L(20, 0.36), checks: LS(2, 3, 12, 0.48, 0.66), allow_label: L(20, 0.76), resource_label: L(16, 0.12) },
  defaults: {
    ar: { deny_label: 'مرفوض افتراضيًا', checks: ['الهوية', 'الجهاز', 'الصلاحية'], allow_label: 'مسار واحد مصرّح', resource_label: 'المورد المحمي' },
    en: { deny_label: 'Denied by default', checks: ['Identity', 'Device', 'Permission'], allow_label: 'One allowed path', resource_label: 'Protected resource' },
  },
  REQUESTS: 5, ALLOWED: 2,
  state(t, p) {
    const S = zeroTrustShield.params, n = p.checks.length;
    let passed = 0;
    for (let i = 0; i < n; i += 1) if (t >= labelTime(S.checks, i, n) + 0.04) passed += 1;
    const denied = t >= 0.36 ? zeroTrustShield.REQUESTS - 1 : 0;
    return { requests: zeroTrustShield.REQUESTS, denied, checks: n, checks_passed: passed, allowed: passed === n && t >= 0.74 ? 1 : 0 };
  },
  draw(c) {
    const { t, p, u, P } = c, S = zeroTrustShield.params, n = p.checks.length, R = zeroTrustShield.REQUESTS, A = zeroTrustShield.ALLOWED;
    const st = zeroTrustShield.state(t, p), wallX = c.x(0.23), srcX = c.x(0.03), resX = c.x(0.895), midY = c.y(0.5);
    const ys = Array.from({ length: R }, (_, i) => c.y(0.1 + 0.8 * i / (R - 1)));
    stroke(c, [[wallX, c.y(0.02)], [wallX, c.y(0.98)]], { color: P.gold, lw: 3, dash: [10, 10], alpha: 0.85 * eo(seg(t, 0.1, 0.22)) });
    for (let i = 0; i < R; i += 1) {
      const a = eo(seg(t, 0.04 + i * 0.015, 0.14 + i * 0.015)), go = eo(seg(t, 0.16 + i * 0.03, 0.3 + i * 0.03));
      disc(c, srcX, ys[i], 20 * u, { fill: P.panelHi, stroke: i === A ? P.cyan : P.dim, lw: 3, alpha: a });
      if (i === A) continue;
      stroke(c, [[srcX + c.d * 26 * u, ys[i]], [wallX - c.d * 22 * u, ys[i]]], { color: P.dim, lw: 3, progress: go, alpha: lerp(1, 0.55, seg(t, 0.36, 0.5)) });
      cross(c, wallX, ys[i], 11 * u, P.gold, seg(t, 0.3 + i * 0.03, 0.34 + i * 0.03), 4.5);
    }
    text(c, p.deny_label, c.x(0.44), c.y(0.2), { size: 30, weight: 700, color: P.gold, alpha: vis(t, S.deny_label.label_in), align: 'center', maxWidth: c.sw * 0.3 });
    // The single verified path through the checks.
    const cw = 216 * u, chh = 68 * u, cfs = p.checks.map((_, i) => 0.33 + 0.36 * (n === 1 ? 0.5 : i / (n - 1)));
    const cxs = cfs.map((f) => c.x(f)), path = [[srcX + c.d * 26 * u, midY], [resX - c.d * 96 * u, midY]];
    const reach = (i) => labelTime(S.checks, i, n);
    let head = eo(seg(t, 0.2, 0.34)) * (Math.abs(wallX - path[0][0]) / Math.abs(path[1][0] - path[0][0]));
    const fAt = (x) => Math.abs(x - path[0][0]) / Math.abs(path[1][0] - path[0][0]);
    for (let i = 0; i < n; i += 1) if (t >= reach(i) - 0.08) head = lerp(i ? fAt(cxs[i - 1]) : fAt(wallX), fAt(cxs[i]), eio(seg(t, reach(i) - 0.08, reach(i))));
    if (st.checks_passed === n) head = lerp(fAt(cxs[n - 1]), 1, eio(seg(t, reach(n - 1) + 0.04, 0.76)));
    stroke(c, path, { color: P.line, lw: 4, alpha: eo(seg(t, 0.12, 0.2)) * 0.6 });
    stroke(c, path, { color: st.allowed ? P.green : P.cyan, lw: 5, progress: head, glow: rgba(st.allowed ? P.green : P.cyan, 0.6) });
    if (head > 0 && head < 1) pulse(c, path, head, P.text);
    for (let i = 0; i < n; i += 1) {
      const at = reach(i), a = vis(t, at), ok = t >= at + 0.04;
      panel(c, cxs[i] - cw / 2, midY - chh / 2, cw, chh, { r: 34, fill: P.panel, stroke: ok ? P.green : P.cyan, lw: 2.5, alpha: a, glow: ok ? rgba(P.green, 0.35) : null });
      text(c, p.checks[i], cxs[i] + c.d * 20 * u, midY, { size: 29, weight: 700, alpha: a, maxWidth: cw - 84 * u });
      const kx = cxs[i] - c.d * (cw / 2 - 34 * u);
      disc(c, kx, midY, 16 * u, { fill: ok ? P.green : P.dark, stroke: ok ? null : P.line, lw: 2, alpha: a });
      check(c, kx, midY, 7.5 * u, seg(t, at + 0.02, at + 0.07), P.dark, 3.5);
    }
    text(c, p.allow_label, c.x(0.51), c.y(0.8), { size: 30, weight: 700, color: P.green, alpha: vis(t, S.allow_label.label_in), maxWidth: c.sw * 0.4 });
    const ra = vis(t, S.resource_label.label_in), open = eo(seg(t, 0.74, 0.84));
    disc(c, resX, midY, 96 * u, { fill: rgba(st.allowed ? P.green : P.blue, 0.08 + 0.08 * open), stroke: null, alpha: ra, glow: rgba(st.allowed ? P.green : P.blue, 0.5) });
    ICONS.shield(c, resX, midY, 74 * u, st.allowed ? P.green : P.blue, ra, P.panelHi);
    ICONS.lock(c, resX, midY + 2 * u, 24 * u, st.allowed ? P.green : P.cyan, ra);
    text(c, p.resource_label, resX, midY + 132 * u, { size: 30, weight: 700, color: P.soft, alpha: ra, maxWidth: 2 * Math.abs(c.x(1) - resX) });
  },
};

const commandToSpec = {
  id: 'command-to-spec',
  meaning: {
    ar: 'أمرٌ واحد يتحوّل إلى مواصفة قابلة للمراجعة: كيانات وميزات ومعايير قبول.',
    en: 'One command is expanded into a reviewable specification: entities, features and acceptance criteria.',
  },
  params: { command: CODE(30, 0.3), root_label: L(16, 0.38), branches: LS(3, 3, 16, 0.46, 0.6), leaves_a: LS(1, 3, 14, 0.52, 0.58),
    leaves_b: LS(1, 3, 14, 0.6, 0.66), leaves_c: LS(1, 3, 14, 0.68, 0.74) },
  defaults: {
    ar: { command: 'gaie build "service"', root_label: 'المواصفة', branches: ['الكيانات', 'الميزات', 'معايير القبول'],
      leaves_a: ['مستفيد', 'طلب', 'قرار'], leaves_b: ['تقديم', 'تتبّع', 'إشعار'], leaves_c: ['اختبار', 'أمان', 'أداء'] },
    en: { command: 'gaie build "service"', root_label: 'Specification', branches: ['Entities', 'Features', 'Acceptance criteria'],
      leaves_a: ['Beneficiary', 'Request', 'Decision'], leaves_b: ['Submit', 'Track', 'Notify'], leaves_c: ['Tests', 'Security', 'Performance'] },
  },
  state(t, p) {
    const S = commandToSpec.params, typed = Math.round(p.command.length * seg(t, 0.06, 0.28));
    let branches = 0, leaves = 0;
    for (let i = 0; i < 3; i += 1) if (t >= labelTime(S.branches, i, 3)) branches += 1;
    ['leaves_a', 'leaves_b', 'leaves_c'].forEach((key) => p[key].forEach((_, j) => { if (t >= labelTime(S[key], j, p[key].length)) leaves += 1; }));
    return { typed, command_length: p.command.length, root: t >= S.root_label.label_in, branches, leaves,
      leaves_total: p.leaves_a.length + p.leaves_b.length + p.leaves_c.length };
  },
  draw(c) {
    const { t, p, u, P, g } = c, S = commandToSpec.params, st = commandToSpec.state(t, p);
    // Terminal on the start side; its content is code and always left to right.
    const tw = c.sw * 0.34, th = 250 * u, tcx = c.x(0.17), tcy = c.y(0.5), tx0 = tcx - tw / 2, ty0 = tcy - th / 2, ta = eo(seg(t, 0.02, 0.1));
    panel(c, tx0, ty0, tw, th, { r: 18, fill: P.dark, stroke: P.line, lw: 2, alpha: ta, glow: rgba(P.blue, 0.25) });
    panel(c, tx0, ty0, tw, 46 * u, { r: 18, fill: P.panelHi, stroke: null, alpha: ta });
    for (let k = 0; k < 3; k += 1) disc(c, tx0 + (28 + k * 26) * u, ty0 + 23 * u, 7 * u, { fill: [P.dim, P.gold, P.green][k], alpha: ta });
    const shown = p.command.slice(0, st.typed), line = `$ ${shown}`;
    const full = text(c, `$ ${p.command}`, tx0 + 26 * u, ty0 + 104 * u, { size: 30, font: 'mono', weight: 500, align: 'left', alpha: 0, maxWidth: tw - 52 * u, track: false });
    g.save();
    g.font = `500 ${full.size}px ${fontStack(c, 'mono')}`; g.textAlign = 'left'; g.textBaseline = 'middle'; g.direction = 'ltr';
    const typedWidth = g.measureText(line).width;
    if (c.glyphs) { g.globalAlpha *= ta; g.fillStyle = P.text; g.fillText(line, tx0 + 26 * u, ty0 + 104 * u); }
    g.restore();
    if (st.typed === p.command.length) text(c, `$ ${p.command}`, tx0 + 26 * u, ty0 + 104 * u, { size: 30, font: 'mono', weight: 500, align: 'left', alpha: ta, maxWidth: tw - 52 * u, role: 'code' });
    if (t < 0.34 && Math.floor(t * 50) % 2 === 0) panel(c, tx0 + 28 * u + typedWidth, ty0 + 88 * u, 14 * u, 32 * u, { r: 2, fill: P.cyan, stroke: null, alpha: ta });
    const out = eo(seg(t, 0.3, 0.36));
    check(c, tx0 + 38 * u, ty0 + 170 * u, 11 * u, out, P.green, 4.5);
    stroke(c, [[tx0 + 64 * u, ty0 + 170 * u], [tx0 + lerp(64, 240, out) * u, ty0 + 170 * u]], { color: rgba(P.green, 0.7), lw: 5, alpha: out });
    // Tree: root -> three branches -> leaves.
    const curve = (x0, y0, x1, y1, progress, color, alpha = 1) => {
      if (progress <= 0) return;
      const pts = [];
      for (let k = 0; k <= 24; k += 1) {
        const s = k / 24, mx = (x0 + x1) / 2, a = (1 - s) ** 3, b = 3 * (1 - s) ** 2 * s, d = 3 * (1 - s) * s * s, e = s ** 3;
        pts.push([a * x0 + b * mx + d * mx + e * x1, a * y0 + b * y0 + d * y1 + e * y1]);
      }
      stroke(c, pts, { color, lw: 3, progress, alpha });
    };
    const rx = c.x(0.47), ry = c.y(0.5), rw = 220 * u, rh = 76 * u, ra = vis(t, S.root_label.label_in);
    curve(tcx + c.d * tw / 2, tcy, rx - c.d * rw / 2, ry, eo(seg(t, 0.3, 0.38)), P.cyan);
    panel(c, rx - rw / 2, ry - rh / 2, rw, rh, { r: 18, fill: P.panelHi, stroke: P.cyan, lw: 3, alpha: ra, glow: rgba(P.cyan, 0.4) });
    text(c, p.root_label, rx, ry, { size: 32, weight: 700, alpha: ra, maxWidth: rw - 30 * u });
    const bx = c.x(0.7), bw = 270 * u, bh = 68 * u, lx = c.x(0.92), lw = 210 * u, lh = 44 * u;
    const colors = [P.cyan, P.blue, P.gold], keys = ['leaves_a', 'leaves_b', 'leaves_c'];
    for (let i = 0; i < 3; i += 1) {
      const at = labelTime(S.branches, i, 3), a = vis(t, at), by = c.y(0.17 + 0.33 * i);
      curve(rx + c.d * rw / 2, ry, bx - c.d * bw / 2, by, eo(seg(t, at - 0.07, at)), colors[i]);
      panel(c, bx - bw / 2, by - bh / 2, bw, bh, { r: 16, fill: P.panel, stroke: colors[i], lw: 2.5, alpha: a });
      text(c, p.branches[i], bx, by, { size: 30, weight: 700, alpha: a, maxWidth: bw - 28 * u });
      const leaves = p[keys[i]], m = leaves.length;
      for (let j = 0; j < m; j += 1) {
        const lt = labelTime(S[keys[i]], j, m), la = vis(t, lt, 0.04), ly = by + (j - (m - 1) / 2) * (lh + 8 * u);
        curve(bx + c.d * bw / 2, by, lx - c.d * lw / 2, ly, eo(seg(t, lt - 0.05, lt)), rgba(colors[i], 0.8));
        panel(c, lx - lw / 2, ly - lh / 2, lw, lh, { r: 24, fill: P.dark, stroke: rgba(colors[i], 0.8), lw: 2, alpha: la });
        text(c, leaves[j], lx, ly, { size: 27, color: P.text, alpha: la, maxWidth: lw - 28 * u });
      }
    }
  },
};

const layerStack = {
  id: 'layer-stack',
  meaning: {
    ar: 'عشرون طبقة هندسية، لكل طبقة عمل واحد، ولا تُعتمد طبقة قبل التحقق منها.',
    en: 'Twenty engineering layers each do one job, and no layer counts before it is verified.',
  },
  params: { count: INT(4, 24, 20), groups: LS(2, 4, 14, 0.16, 0.56), counter_label: L(22, 0.2) },
  defaults: {
    ar: { count: 20, groups: ['فهم', 'بناء', 'تحقّق', 'تشغيل'], counter_label: 'طبقة متحقَّق منها' },
    en: { count: 20, groups: ['Understand', 'Build', 'Verify', 'Operate'], counter_label: 'verified layers' },
  },
  lit: (i, n) => 0.14 + 0.6 * i / (n - 1),
  state(t, p) {
    let lit = 0;
    for (let i = 0; i < p.count; i += 1) if (t >= layerStack.lit(i, p.count) + 0.03) lit += 1;
    return { count: p.count, lit, verified: lit, complete: lit === p.count && t >= 0.8 };
  },
  draw(c) {
    const { t, p, u, P } = c, S = layerStack.params, n = p.count, st = layerStack.state(t, p);
    const gap = 5 * u, h = Math.min(30 * u, (c.sh - gap * (n - 1)) / n), total = n * h + (n - 1) * gap;
    const cx = c.x(0.43), w = c.sw * 0.34, bottom = c.y(0.5) + total / 2, m = p.groups.length;
    for (let i = 0; i < n; i += 1) {
      const y = bottom - (i + 1) * h - i * gap, at = layerStack.lit(i, n), k = eo(seg(t, at, at + 0.04));
      const group = Math.min(m - 1, Math.floor(i * m / n)), color = st.complete ? P.green : [P.cyan, P.blue, P.cyan, P.blue][group % 4];
      panel(c, cx - w / 2, y, w, h, { r: 6, fill: P.panel, stroke: P.line, lw: 1.5, alpha: eo(seg(t, 0.02 + i * 0.004, 0.1 + i * 0.004)) });
      if (k > 0) {
        const lw = w * k;
        panel(c, c.rtl ? cx + w / 2 - lw : cx - w / 2, y, lw, h, { r: 6, fill: rgba(color, 0.78), stroke: null, glow: rgba(color, 0.4), blur: 12 });
        check(c, cx - c.d * (w / 2 - 22 * u), y + h / 2, Math.min(8 * u, h * 0.3), seg(t, at + 0.02, at + 0.05), P.dark, 3);
      }
    }
    // Group brackets on the start side.
    for (let j = 0; j < m; j += 1) {
      const first = Math.ceil(j * n / m), last = Math.ceil((j + 1) * n / m) - 1, a = vis(t, labelTime(S.groups, j, m));
      const y0 = bottom - (last + 1) * h - last * gap, y1 = bottom - first * (h + gap), bx = cx + c.d * (-w / 2 - 22 * u);
      stroke(c, [[bx + c.d * 10 * u, y0 + 3 * u], [bx, y0 + 3 * u], [bx, y1 - 3 * u], [bx + c.d * 10 * u, y1 - 3 * u]], { color: P.gold, lw: 3, alpha: a });
      text(c, p.groups[j], bx - c.d * 18 * u, (y0 + y1) / 2, { size: 31, weight: 700, align: 'end', color: P.soft, alpha: a, maxWidth: c.sw * 0.19 });
    }
    const kx = c.x(0.82), ky = c.y(0.42), ka = eo(seg(t, 0.08, 0.18)), color = st.complete ? P.green : P.text;
    text(c, `${st.lit}/${n}`, kx, ky, { size: 124, font: 'latin', weight: 600, color, alpha: ka, role: 'number', maxWidth: c.sw * 0.3, glow: st.complete ? rgba(P.green, 0.5) : null });
    text(c, p.counter_label, kx, ky + 104 * u, { size: 32, weight: 700, color: P.soft, alpha: vis(t, S.counter_label.label_in), maxWidth: c.sw * 0.3 });
    const done = seg(t, 0.8, 0.88);
    disc(c, kx, ky + 190 * u, 30 * u, { fill: rgba(P.green, 0.16), stroke: P.green, lw: 3, alpha: done });
    check(c, kx, ky + 190 * u, 13 * u, done, P.green, 5);
  },
};

const testMatrix = {
  id: 'test-matrix',
  meaning: {
    ar: 'لا يُقبل النظام إلا حين ينجح كل اختبار في المصفوفة، وما يفشل يُصلَح ثم يُعاد اختباره.',
    en: 'The system is accepted only when every test in the matrix passes; a failure is fixed and re-tested.',
  },
  params: { rows: LS(3, 5, 16, 0.1, 0.2), columns: INT(4, 9, 6), summary_label: L(20, 0.24) },
  defaults: {
    ar: { rows: ['وظائف', 'أمان', 'أداء', 'وصول'], columns: 6, summary_label: 'اختبارًا ناجحًا' },
    en: { rows: ['Functions', 'Security', 'Performance', 'Access'], columns: 6, summary_label: 'tests passing' },
  },
  cell(p, row, col) {
    const R = p.rows.length, C = p.columns, order = (col + row * 0.7) / (C - 1 + (R - 1) * 0.7), start = 0.16 + 0.46 * order;
    const flaky = row === 1 && col === Math.floor(C / 2);
    return { start, pass: flaky ? 0.82 : start + 0.07, fail_from: flaky ? start + 0.07 : null, retry_from: flaky ? 0.74 : null, flaky };
  },
  state(t, p) {
    const R = p.rows.length, C = p.columns;
    let passed = 0, failed = 0;
    for (let r = 0; r < R; r += 1) for (let k = 0; k < C; k += 1) {
      const cell = testMatrix.cell(p, r, k);
      if (t >= cell.pass) passed += 1; else if (cell.flaky && t >= cell.fail_from && t < cell.retry_from) failed += 1;
    }
    return { total: R * C, passed, failed, all_green: passed === R * C };
  },
  draw(c) {
    const { t, p, u, P } = c, S = testMatrix.params, R = p.rows.length, C = p.columns, st = testMatrix.state(t, p);
    const gx0 = 0.27, gx1 = 0.7, size = Math.min((c.sw * (gx1 - gx0)) / C - 12 * u, (c.sh * 0.84) / R - 12 * u, 96 * u);
    const stepX = (c.sw * (gx1 - gx0)) / C, stepY = Math.min((c.sh * 0.84) / R, size + 22 * u), top = c.y(0.5) - (stepY * R) / 2;
    for (let r = 0; r < R; r += 1) {
      const y = top + stepY * (r + 0.5);
      text(c, p.rows[r], c.x(0.23), y, { size: 32, weight: 700, align: 'end', color: P.soft, alpha: vis(t, labelTime(S.rows, r, R)), maxWidth: c.sw * 0.2 });
      for (let k = 0; k < C; k += 1) {
        const cell = testMatrix.cell(p, r, k), x = c.x(gx0) + c.d * stepX * (k + 0.5), a = eo(seg(t, 0.06, 0.16));
        const passed = t >= cell.pass, failing = cell.flaky && t >= cell.fail_from && t < cell.retry_from;
        const running = !passed && !failing && t >= (cell.flaky && t >= cell.retry_from ? cell.retry_from : cell.start);
        const color = passed ? P.green : failing ? P.gold : running ? P.cyan : P.line;
        const grow = passed ? back(seg(t, cell.pass, cell.pass + 0.05)) : 1;
        panel(c, x - (size * grow) / 2, y - (size * grow) / 2, size * grow, size * grow, { r: 14, fill: passed ? rgba(P.green, 0.82) : failing ? rgba(P.gold, 0.2) : running ? rgba(P.cyan, 0.2) : P.panel,
          stroke: color, lw: 2.5, alpha: a, glow: passed || failing || running ? rgba(color, 0.4) : null, blur: 14 });
        if (passed) check(c, x, y, size * 0.2, seg(t, cell.pass, cell.pass + 0.04), P.dark, 4.5);
        if (failing) cross(c, x, y, size * 0.16, P.gold, 1, 4.5);
        if (running) disc(c, x, y, size * 0.12 * (1 + 0.4 * Math.sin(t * 90)), { fill: P.cyan });
      }
    }
    const kx = c.x(0.86), ky = c.y(0.4), ka = eo(seg(t, 0.1, 0.2)), color = st.all_green ? P.green : P.text;
    text(c, `${st.passed}/${st.total}`, kx, ky, { size: 104, font: 'latin', weight: 600, color, alpha: ka, role: 'number', maxWidth: c.sw * 0.24, glow: st.all_green ? rgba(P.green, 0.5) : null });
    text(c, p.summary_label, kx, ky + 94 * u, { size: 32, weight: 700, color: P.soft, alpha: vis(t, S.summary_label.label_in), maxWidth: c.sw * 0.24 });
    const bw = c.sw * 0.2, by = ky + 150 * u;
    panel(c, kx - bw / 2, by, bw, 14 * u, { r: 7, fill: P.panel, stroke: P.line, lw: 1.5, alpha: ka });
    const fw = bw * st.passed / st.total;
    panel(c, c.rtl ? kx + bw / 2 - fw : kx - bw / 2, by, fw, 14 * u, { r: 7, fill: st.all_green ? P.green : P.cyan, stroke: null, alpha: ka });
  },
};

const checkpointResume = {
  id: 'checkpoint-resume',
  meaning: {
    ar: 'يُختم العمل عند نقاط حفظ، فإذا انقطع التشغيل استُؤنف من آخر ختم لا من البداية.',
    en: 'Work is sealed at checkpoints, so an interrupted run resumes from the last seal instead of starting over.',
  },
  params: { steps: INT(4, 8, 6), checkpoint_at: INT(1, 6, 3), checkpoint_label: L(20, 0.4), interrupt_label: L(14, 0.56), resume_label: L(22, 0.68), done_label: L(14, 0.9) },
  defaults: {
    ar: { steps: 6, checkpoint_at: 3, checkpoint_label: 'نقطة حفظ مختومة', interrupt_label: 'انقطاع', resume_label: 'استئناف من الختم', done_label: 'اكتمل' },
    en: { steps: 6, checkpoint_at: 3, checkpoint_label: 'Sealed checkpoint', interrupt_label: 'Interruption', resume_label: 'Resume from the seal', done_label: 'Complete' },
  },
  /** Progress in steps (float) as a function of t; it never falls below the sealed checkpoint. */
  progress(t, p) {
    const n = p.steps, k = Math.min(p.checkpoint_at, n - 1);
    if (t < 0.34) return k * eio(seg(t, 0.08, 0.34));
    if (t < 0.5) return k + 0.55 * eio(seg(t, 0.4, 0.5));
    if (t < 0.62) return k + 0.55 * (1 - eio(seg(t, 0.52, 0.6)));
    return lerp(k, n, eio(seg(t, 0.66, 0.88)));
  },
  state(t, p) {
    const n = p.steps, k = Math.min(p.checkpoint_at, n - 1), progress = checkpointResume.progress(t, p);
    return { steps: n, checkpoint_at: k, progress: Math.round(progress * 1000) / 1000, sealed: t >= 0.38, interrupted: t >= 0.5 && t < 0.64,
      resumed_from: t >= 0.64 ? k : null, restarted_from_zero: t >= 0.38 && progress < k - 1e-9, complete: t >= 0.88 };
  },
  draw(c) {
    const { t, p, u, P } = c, S = checkpointResume.params, n = p.steps, st = checkpointResume.state(t, p), k = st.checkpoint_at;
    const y = c.y(0.6), xs = Array.from({ length: n + 1 }, (_, i) => c.x(0.06 + 0.88 * i / n)), track = xs.map((x) => [x, y]);
    stroke(c, track, { color: P.line, lw: 8, alpha: eo(seg(t, 0.03, 0.12)) });
    const lost = st.interrupted, color = st.complete ? P.green : P.cyan;
    stroke(c, track, { color, lw: 8, progress: st.progress / n, glow: rgba(color, 0.6) });
    if (t >= 0.38) stroke(c, track.slice(0, k + 1), { color: P.green, lw: 8, glow: rgba(P.green, 0.4) });   // sealed work stays
    for (let i = 0; i <= n; i += 1) {
      const reached = st.progress >= i - 1e-6, sealed = t >= 0.38 && i <= k;
      disc(c, xs[i], y, (i === k ? 26 : 18) * u, { fill: reached ? (sealed || st.complete ? P.green : P.cyan) : P.panel, stroke: reached ? null : P.line, lw: 3, alpha: eo(seg(t, 0.04 + i * 0.01, 0.12 + i * 0.01)) });
      if (reached && (sealed || st.complete)) check(c, xs[i], y, 8 * u, 1, P.dark, 3.5);
    }
    if (st.progress > 0 && st.progress < n && !lost) pulse(c, track, st.progress / n, P.text, 1, 8);
    // Sealed capsule above the checkpoint node.
    const ca = vis(t, S.checkpoint_label.label_in), cx = xs[k], cy = c.y(0.2), cw = 400 * u, chh = 96 * u, drop = back(seg(t, 0.33, 0.4));
    const px = clamp(cx, c.st.x0 + cw / 2, c.st.x1 - cw / 2);
    stroke(c, [[cx, cy + chh / 2], [cx, y - 30 * u]], { color: P.green, lw: 3, dash: [8, 8], alpha: ca });
    panel(c, px - cw / 2, cy - chh / 2 - (1 - clamp(drop)) * 30 * u, cw, chh, { r: 22, fill: P.panelHi, stroke: P.green, lw: 3, alpha: seg(t, 0.33, 0.37), glow: rgba(P.green, 0.4) });
    ICONS.lock(c, px + c.d * (cw / 2 - 48 * u), cy, 20 * u, P.green, ca);
    text(c, p.checkpoint_label, px - c.d * 28 * u, cy, { size: 30, weight: 700, alpha: ca, maxWidth: cw - 130 * u });
    // Interruption beyond the seal, then resume from it.
    const ix = lerp(xs[k], xs[Math.min(n, k + 1)], 0.62), ia = vis(t, S.interrupt_label.label_in, 0.04) * (1 - seg(t, 0.84, 0.9));
    cross(c, ix, y, 16 * u, P.gold, ia, 5.5);
    text(c, p.interrupt_label, ix, y - 66 * u, { size: 29, weight: 700, color: P.gold, alpha: ia, maxWidth: 220 * u });
    const ra = vis(t, S.resume_label.label_in), rx = clamp(lerp(xs[k], xs[n], 0.5), c.st.x0 + 220 * u, c.st.x1 - 220 * u), ry = y + 84 * u;
    text(c, p.resume_label, rx, ry, { size: 31, weight: 700, color: P.cyan, alpha: ra, maxWidth: 420 * u });
    const da = vis(t, S.done_label.label_in);
    text(c, p.done_label, xs[n], y - 70 * u, { size: 31, weight: 700, color: P.green, alpha: da, align: 'end', maxWidth: 240 * u });
  },
};

const titleCard = {
  id: 'title-card',
  meaning: {
    ar: 'يحدّد الإطار الذي يخدمه العمل الرقمي بكلمات صريحة مطبوعة، دون شعارات أو رموز.',
    en: 'States in plain typography the goal the digital work serves, with no emblem or logo.',
  },
  params: { kicker: L(40, 0.12), heading: L(30, 0.32, true), chips: LS(0, 4, 16, 0.5, 0.7) },
  defaults: { ar: { kicker: '', heading: '', chips: [] }, en: { kicker: '', heading: '', chips: [] } },
  state(t, p) {
    const S = titleCard.params, n = p.chips.length;
    let chips = 0;
    for (let i = 0; i < n; i += 1) if (t >= labelTime(S.chips, i, n)) chips += 1;
    return { heading_visible: t >= S.heading.label_in, chips, chips_total: n };
  },
  draw(c) {
    const { t, p, u, P, g } = c, S = titleCard.params, n = p.chips.length, cx = c.x(0.5), hy = c.y(n ? 0.45 : 0.52);
    // Converging data lines behind the heading.
    const next = seeded(4242 + c.seed);
    for (let i = 0; i < 14; i += 1) {
      const yy = c.y(0.06 + 0.88 * next()), len = (0.12 + next() * 0.2) * c.sw, from = i % 2 ? c.st.x0 : c.st.x1, dir = i % 2 ? 1 : -1;
      const k = eo(seg(t, 0.02 + next() * 0.2, 0.3 + next() * 0.3)), slide = t * 40 * u * dir;
      stroke(c, [[from + slide, yy], [from + slide + dir * len * k, yy]], { color: i % 5 === 0 ? P.gold : P.cyan, lw: 2, alpha: 0.28 });
      disc(c, from + slide + dir * len * k, yy, 3.5 * u, { fill: i % 5 === 0 ? P.gold : P.cyan, alpha: 0.6 * k });
    }
    text(c, p.kicker, cx, c.y(n ? 0.16 : 0.2), { size: 34, weight: 600, color: P.cyan, alpha: vis(t, S.kicker.label_in), maxWidth: c.sw * 0.8 });
    // Heading revealed by a wipe from the reading start (never letter by letter).
    const wipe = eio(seg(t, S.heading.label_in - 0.2, S.heading.label_in)), hw = c.sw * 0.92;
    g.save();
    g.beginPath();
    if (c.rtl) g.rect(cx + hw / 2 - hw * wipe, c.st.y0, hw * wipe, c.sh); else g.rect(cx - hw / 2, c.st.y0, hw * wipe, c.sh);
    g.clip();
    const head = text(c, p.heading, cx, hy, { size: 120, weight: 800, font: 'head', color: P.text, maxWidth: hw, alpha: wipe >= 1 ? 1 : 0.999, glow: rgba(P.blue, 0.55) });
    g.restore();
    const rule = eo(seg(t, S.heading.label_in - 0.04, S.heading.label_in + 0.1)), rw = Math.min(hw, head.width) * 0.6 * rule;
    panel(c, cx - rw / 2, hy + head.size * 0.72, rw, 6 * u, { r: 3, fill: P.gold, stroke: null, glow: rgba(P.gold, 0.6) });
    if (n) {
      const cw = Math.min(360 * u, (c.sw * 0.9) / n - 20 * u), step = cw + 24 * u, cy = c.y(0.84);
      for (let i = 0; i < n; i += 1) {
        const a = vis(t, labelTime(S.chips, i, n)), x = cx + c.d * (i - (n - 1) / 2) * step;
        panel(c, x - cw / 2, cy - 36 * u, cw, 72 * u, { r: 36, fill: rgba(P.cyan, 0.08), stroke: P.cyan, lw: 2, alpha: a });
        text(c, p.chips[i], x, cy, { size: 32, weight: 700, alpha: a, maxWidth: cw - 40 * u });
      }
    }
  },
};

const callToAction = {
  id: 'call-to-action',
  meaning: {
    ar: 'يُختم العرض بخطوة واحدة واضحة يستطيع المشاهد أن يبدأ بها.',
    en: 'The show closes with one clear next step the viewer can take.',
  },
  params: { heading: L(30, 0.14, true), points: LS(0, 3, 22, 0.3, 0.52), action_label: L(22, 0.68, true), footer: L(34, 0.8) },
  defaults: { ar: { heading: '', points: [], action_label: '', footer: '' }, en: { heading: '', points: [], action_label: '', footer: '' } },
  state(t, p) {
    const S = callToAction.params, n = p.points.length;
    let points = 0;
    for (let i = 0; i < n; i += 1) if (t >= labelTime(S.points, i, n)) points += 1;
    return { points, points_total: n, action_ready: t >= S.action_label.label_in };
  },
  draw(c) {
    const { t, p, u, P } = c, S = callToAction.params, n = p.points.length, cx = c.x(0.5), cy = c.y(0.5);
    const w = c.sw * 0.72, h = c.sh * 0.98, a = eo(seg(t, 0.02, 0.14)), rise = (1 - a) * 26 * u;
    panel(c, cx - w / 2, cy - h / 2 + rise, w, h, { r: 30, fill: P.panel, stroke: P.blue, lw: 2.5, alpha: a, glow: rgba(P.blue, 0.4), blur: 40 });
    panel(c, cx - w / 2, cy - h / 2 + rise, w, 8 * u, { r: 4, fill: P.cyan, stroke: null, alpha: a });
    text(c, p.heading, cx, cy - h * 0.34, { size: 56, weight: 800, font: 'head', alpha: vis(t, S.heading.label_in), maxWidth: w - 100 * u });
    const colW = w / Math.max(1, n);
    for (let i = 0; i < n; i += 1) {
      const pa = vis(t, labelTime(S.points, i, n)), x = cx + c.d * (i - (n - 1) / 2) * colW, y = cy - h * 0.05;
      disc(c, x, y - 34 * u, 20 * u, { fill: rgba(P.green, 0.16), stroke: P.green, lw: 2.5, alpha: pa });
      check(c, x, y - 34 * u, 9 * u, seg(t, labelTime(S.points, i, n) - 0.03, labelTime(S.points, i, n) + 0.03), P.green, 4);
      text(c, p.points[i], x, y + 22 * u, { size: 31, weight: 600, color: P.soft, alpha: pa, maxWidth: colW - 44 * u });
    }
    const ba = vis(t, S.action_label.label_in), bw = Math.min(w * 0.56, 560 * u), bh = 84 * u, by = cy + h * 0.24;
    const breathe = 0.5 + 0.5 * Math.sin(seg(t, 0.7, 1) * Math.PI * 3 - Math.PI / 2);
    panel(c, cx - bw / 2, by - bh / 2, bw, bh, { r: 42, fill: P.gold, stroke: null, alpha: ba, glow: rgba(P.gold, 0.3 + 0.35 * breathe), blur: 34 });
    text(c, p.action_label, cx, by, { size: 38, weight: 700, color: P.dark, alpha: ba, maxWidth: bw - 60 * u });
    text(c, p.footer, cx, cy + h * 0.42, { size: 28, weight: 600, color: P.soft, alpha: vis(t, S.footer.label_in), maxWidth: w - 100 * u });
  },
};

const SCENE_LIST = [paperToDigital, serviceJourney, dataPipeline, integrationMesh, approvalGate, kpiGauge, auditTrail,
  zeroTrustShield, commandToSpec, layerStack, testMatrix, checkpointResume, titleCard, callToAction];

export const SCENES = Object.freeze(Object.fromEntries(SCENE_LIST.map((scene) => [scene.id, scene])));
export const SCENE_IDS = Object.freeze(SCENE_LIST.map((scene) => scene.id));

// ------------------------------------------------------------------ public API

/** Defaults of the language merged with the given parameters; unknown or mistyped parameters throw. */
export function resolveParams(id, params = {}, lang = 'ar') {
  const scene = SCENES[id];
  if (!scene) throw new Error(`unknown show scene ${id}`);
  const out = { ...(scene.defaults[lang] || scene.defaults.ar) };
  for (const [key, value] of Object.entries(params || {})) {
    const spec = scene.params[key];
    if (!spec) throw new Error(`${id}: unknown parameter ${key}`);
    if (spec.type === 'labels' && !(Array.isArray(value) && value.every((item) => typeof item === 'string'))) throw new Error(`${id}.${key}: list of labels`);
    if ((spec.type === 'label' || spec.type === 'code') && typeof value !== 'string') throw new Error(`${id}.${key}: label`);
    if (spec.type === 'int' && !Number.isInteger(value)) throw new Error(`${id}.${key}: integer`);
    out[key] = spec.type === 'labels' ? [...value] : value;
  }
  for (const [key, spec] of Object.entries(scene.params)) {
    if (spec.type === 'labels' && (out[key].length < spec.min || out[key].length > spec.max)) throw new Error(`${id}.${key}: ${spec.min}-${spec.max} labels`);
    if (spec.type === 'int' && (out[key] < spec.min || out[key] > spec.max)) throw new Error(`${id}.${key}: ${spec.min}-${spec.max}`);
    if (spec.required && !out[key]) throw new Error(`${id}.${key}: required`);
  }
  return out;
}

/** The meaning-level state of a scene at time t (what is lit, open, approved, counted). */
export function sceneState(id, t, params = {}, lang = 'ar') {
  return SCENES[id].state(clamp(Number(t) || 0), resolveParams(id, params, lang));
}

/**
 * Draw scene `id` at normalized time t on a 2D context.
 * env: { width, height, lang: 'ar' | 'en', stage?: { x0, y0, x1, y1 }, reducedMotion?, glyphs?, seed?, theme?, fonts? }
 * Returns { id, t, state, labels } where labels are the measured boxes of every drawn label.
 */
export function drawShowScene(g, id, t, params, env) {
  const scene = SCENES[id];
  if (!scene) throw new Error(`unknown show scene ${id}`);
  const lang = env.lang || 'ar';
  const resolved = resolveParams(id, params, lang);
  const time = env.reducedMotion ? 1 : clamp(Number(t) || 0);
  const c = makeContext(g, time, resolved, { ...env, lang });
  g.save();
  g.setTransform(1, 0, 0, 1, 0, 0);
  g.globalAlpha = 1; g.globalCompositeOperation = 'source-over'; g.filter = 'none';
  g.shadowColor = 'transparent'; g.shadowBlur = 0; g.setLineDash([]);
  background(c);
  scene.draw(c);
  g.restore();
  return { id, t: time, state: scene.state(time, resolved), labels: c.labels };
}

/** The registry document written to registry.json (ids, parameter schemas, meanings, themes). */
export function buildRegistry() {
  return {
    schema: REGISTRY_SCHEMA,
    kit_version: KIT_VERSION,
    kit: 'packages/digital-shows/kit.mjs',
    fonts: { directory: 'packages/digital-shows/fonts', notice: 'NOTICE-FONTS-V2.txt', license: 'SIL Open Font License 1.1', files: FONT_FILES.map((font) => ({ ...font })) },
    themes: Object.fromEntries(Object.entries(THEMES).map(([id, theme]) => [id, JSON.parse(JSON.stringify(theme))])),
    scenes: SCENE_LIST.map((scene) => ({ id: scene.id, meaning: { ...scene.meaning }, params: JSON.parse(JSON.stringify(scene.params)),
      defaults: JSON.parse(JSON.stringify(scene.defaults)) })),
  };
}
