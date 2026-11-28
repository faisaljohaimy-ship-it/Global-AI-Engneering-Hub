// SPDX-License-Identifier: MIT
// Original time-seekable Canvas2D scenes for the owner’s transition and story brief.
const cyan = '#67e8f9';
const violet = '#a78bfa';
const green = '#6ee7b7';
const orange = '#fdba74';
const soft = '#94a3b8';
const panel = '#172b44';
const dark = '#102039';
const colors = [cyan, violet, green, orange];
const clamp = (value) => Math.min(1, Math.max(0, value));
const smooth = (value) => {
  const p = clamp(value);
  return p * p * (3 - 2 * p);
};
const mix = (a, b, t) => a + (b - a) * t;
const segment = (t, start, end) => clamp((t - start) / (end - start));
const stages = [0.19, 0.39, 0.59, 0.79];

function geometry(width, height, rtl) {
  const primitives = [];
  const scale = Math.min(width, height);
  const x = (value) => width * (rtl ? 1 - value : value);
  const y = (value) => height * value;
  const point = ([px, py]) => ({x: x(px), y: y(py)});
  return {
    primitives,
    rect(px, py, w, h, fill = panel, stroke = 'none', opacity = 1, rotation = 0) {
      const position = point([rtl ? px + w : px, py]);
      primitives.push({type: 'rect', ...position, width: width * w, height: height * h, fill,
        stroke, opacity, rotation: rotation * (rtl ? -1 : 1), lineWidth: 2});
    },
    line(a, b, stroke = cyan, opacity = 1, lineWidth = 2) {
      const start = point(a), end = point(b);
      primitives.push({type: 'line', x1: start.x, y1: start.y, x2: end.x, y2: end.y,
        stroke, opacity, lineWidth});
    },
    circle(px, py, r, fill = cyan, stroke = 'none', opacity = 1) {
      primitives.push({type: 'circle', ...point([px, py]), r: scale * r, fill, stroke, opacity, lineWidth: 2});
    },
    polygon(points, fill = 'none', stroke = cyan, opacity = 1, closed = true) {
      primitives.push({type: 'polyline', points: points.map(point), fill, stroke, opacity, closed, lineWidth: 2});
    },
    text(value, px, py, fill = '#e2e8f0', opacity = 1) {
      primitives.push({type: 'text', ...point([px, py]), text: value, align: 'center',
        size: Math.max(9, Math.min(20, scale * .033)), fill, opacity});
    },
  };
}

function page(g, x, y, w, h, accent, opacity = 1) {
  g.rect(x, y, w, h, dark, accent, opacity);
  g.rect(x + w * .09, y + h * .15, w * .46, h * .11, accent, 'none', opacity);
  for (let i = 0; i < 3; i++) {
    g.rect(x + w * .09, y + h * (.39 + .15 * i), w * (.73 - .13 * i), h * .056, panel, 'none', opacity);
  }
}

function spatialNavigation(g, t) {
  const p = smooth(t);
  page(g, .16 - .57 * p, .27 + .06 * p, .63 - .09 * p, .46 - .12 * p, violet, 1 - .4 * p);
  page(g, .83 - .67 * p, .33 - .06 * p, .54 + .09 * p, .34 + .12 * p, cyan);
  g.line([.17, .83], [.82, .83], panel);
  g.circle(.21 + .57 * p, .83, .015, cyan);
}

function liquidScreen(g, t) {
  page(g, .13, .23, .71, .53, violet);
  const boundary = Array.from({length: 25}, (_, index) => {
    const y = .18 + .64 * index / 24;
    const ripple = Math.sin(index / 24 * Math.PI * 4 - 6 * t) * .06 * Math.sin(Math.PI * t);
    return [.09 + .79 * t + ripple, y];
  });
  g.polygon([[.08, .18], ...boundary, [.08, .82]], dark, cyan);
  const tip = boundary[9];
  g.circle(tip[0] - .02, tip[1] + .014, .017, green);
}

function maskReveal(g, t) {
  const amount = .13 + .86 * smooth(t);
  g.rect(.14, .24, .69, .48, dark, violet);
  // Reveal the contents within a bounded trapezoid, row by row.
  for (let i = 0; i < 7; i++) {
    const y = .29 + .055 * i;
    const width = (.57 - .028 * i) * amount;
    g.rect(.18 + .015 * i, y, width, .026, i === 0 ? cyan : panel);
  }
  g.polygon([[.18, .25], [.18 + .6 * amount, .25], [.28 + .4 * amount, .69], [.28, .69]], 'none', cyan);
}

function panelAssembly(g, t) {
  const parts = [[.17, .26, -.35, -.38], [.49, .26, .44, -.34], [.17, .53, -.37, .38], [.49, .53, .42, .39]];
  parts.forEach(([x, y, ox, oy], i) => {
    const p = smooth(segment(t, .13 * i, .81 + .05 * i));
    page(g, x + ox * (1 - p), y + oy * (1 - p), .29, .22, colors[i]);
  });
  g.line([.17, .81], [.17 + .60 * t, .81], soft);
}

function sharedElement(g, t) {
  const p = smooth(t);
  page(g, .13, .25, .29, .46, violet, 1 - .38 * p);
  page(g, .47, .21, .37, .53, green, .45 + .55 * p);
  const cx = mix(.27, .64, p), cy = .46 - .20 * Math.sin(Math.PI * p);
  g.line([.27, .46], [cx, cy], orange, .7);
  g.rect(cx - mix(.055, .13, p), cy - mix(.04, .11, p),
    mix(.11, .26, p), mix(.08, .22, p), cyan, '#e2e8f0', .9, .2 * Math.sin(Math.PI * p));
}

function perspectivePortal(g, t) {
  const vanish = .6 - .17 * t;
  for (let i = 6; i >= 0; i--) {
    const z = .32 + ((i / 7 + 1 - .9 * t) % 1) * 2.8;
    const size = .13 / z;
    const lift = .1 / z;
    g.polygon([[vanish - size, .48 - lift], [vanish + size, .48 - lift],
      [vanish + size * 1.32, .48 + lift], [vanish - size * 1.32, .48 + lift]],
    'none', colors[i % colors.length], .85);
  }
  g.circle(vanish, .48, .012, orange);
}

function depthReplacement(g, t) {
  const near = smooth(t), shift = .10 * Math.sin(Math.PI * t);
  page(g, .20 - shift, .22, .51 + .22 * near, .53 + .18 * near, violet, 1 - near * .72);
  const far = .29 + .28 * near;
  page(g, .47 - .22 * near, .32 - .1 * near, far, .32 + .21 * near, green, .32 + near * .68);
  g.line([.18, .82], [.2 + near * .57, .82], orange, .8, 3);
}

function curtainReveal(g, t, interaction) {
  const point = .47 + .12 * interaction.x;
  const half = .3 * smooth(t);
  page(g, .16, .22, .66, .54, cyan);
  const leftEdge = Math.max(.13, point - half), rightEdge = Math.min(.86, point + half);
  for (let i = 0; i < 12; i++) {
    const x = .13 + i * (leftEdge - .13) / 12;
    const rx = rightEdge + i * (.86 - rightEdge) / 12;
    const shade = i % 2 ? dark : panel;
    g.rect(x, .18, (leftEdge - .13) / 12, .62, shade);
    g.rect(rx, .18, (.86 - rightEdge) / 12, .62, shade);
  }
  g.line([leftEdge, .18], [leftEdge, .8], orange);
  g.line([rightEdge, .18], [rightEdge, .8], violet);
}

function fragmentTransition(g, t) {
  const split = Math.sin(Math.PI * t);
  const p = smooth(t);
  for (let i = 0; i < 18; i++) {
    const col = i % 6, row = Math.floor(i / 6);
    const cx = .23 + col * .084 + .20 * p + (col - 2.5) * .06 * split;
    const cy = .33 + row * .105 - .08 * p + (row - 1) * .17 * split;
    const span = .039 * (1 - .43 * split);
    g.polygon([[cx, cy - span], [cx - span, cy + span], [cx + span, cy + span]],
      colors[(col + row) % colors.length], 'none', .72 + .28 * p);
  }
}

function viewTransition(g, t) {
  // Snapshot interpolation for a Canvas view. It does not use a browser SPA API.
  const p = smooth(t);
  page(g, .14, .20, .70, .56, soft);
  for (let i = 0; i < 4; i++) {
    const col = i % 2, row = Math.floor(i / 2);
    const x = mix(.21 + .115 * i, .24 + col * .28, p);
    const y = mix(.49 + (i % 2) * .03, .32 + row * .19, p);
    g.rect(x, y, mix(.09, .22, p), mix(.08, .13, p), colors[i], 'none', .87);
  }
}

function architectureTimeline(g, t) {
  g.line([.16, .59], [.84, .59], panel, 1, 4);
  g.line([.16, .59], [.16 + .68 * t, .59], cyan, 1, 4);
  stages.forEach((x, i) => {
    const grown = smooth(segment(t, i * .18, .28 + i * .18));
    const top = .56 - .22 * grown;
    g.line([x, .59], [x, top], colors[i], .5 + .5 * grown);
    g.circle(x, top, .024, colors[i]);
    g.text(['Client', 'API', 'Data', 'Audit'][i], x, top - .072, '#e2e8f0', .3 + .7 * grown);
  });
}

function capabilityReveal(g, t) {
  for (let i = 0; i < 4; i++) {
    const p = smooth(segment(t, i * .13, .49 + i * .13));
    const x = .17 + .31 * (i % 2), y = .23 + .26 * Math.floor(i / 2) + .09 * (1 - p);
    g.rect(x, y, .29, .22, dark, colors[i], .25 + .75 * p);
    g.polygon([[x + .04, y + .05], [x + .074, y + .09], [x + .04, y + .13]],
      colors[i], 'none', .35 + .65 * p);
    g.text(['Plan', 'Build', 'Test', 'Ship'][i], x + .18, y + .11, '#e2e8f0', .35 + .65 * p);
  }
}

function workflowTransformation(g, t) {
  const p = smooth(t);
  const locations = stages.map((x, i) => [mix(.30 + i * .12, x, p), mix(.29 + i * .12, .48 + .12 * (i % 2), p)]);
  locations.slice(1).forEach((end, i) => {
    const start = locations[i];
    g.line(start, end, soft, 1, 3);
    const q = (t * 3 + i / 4) % 1;
    g.circle(mix(start[0], end[0], q), mix(start[1], end[1], q), .014, orange);
  });
  locations.forEach(([x, y], i) => {
    g.circle(x, y, .029, dark, colors[i]);
    g.text(['Input', 'Plan', 'Check', 'Output'][i], x, y - .09);
  });
}

function systemEvolution(g, t) {
  const p = smooth(t);
  g.rect(.13, .27, .31, .41, dark, violet, 1 - .52 * p);
  g.text('Before', .27, .32);
  g.rect(.5, .20, .35, .60, dark, green);
  g.text('After', .68, .25);
  for (let i = 0; i < 3; i++) {
    const shift = smooth(segment(t, i * .15, .68 + i * .13));
    const oldY = .40 + i * .068, newY = .35 + i * .15;
    const cx = mix(.23, .58, shift), cy = mix(oldY, newY, shift);
    g.rect(cx, cy, .13 + .08 * shift, .045 + .037 * shift, colors[i]);
  }
}

function executiveKPI(g, t) {
  g.line([.16, .70], [.82, .70], soft);
  const values = [24, 43, 58, 82];
  values.forEach((value, i) => {
    const height = .48 * value / 100 * smooth(segment(t, i * .12, .64 + .11 * i));
    const x = .20 + i * .15;
    g.rect(x, .70 - height, .105, height, colors[i]);
    g.text(String(Math.round(height * 100 / .48)), x + .052, .65 - height);
  });
}

function milestoneJourney(g, t, interaction) {
  const points = [[.14, .62], [.36, .42], [.57, .60], [.81, .35]];
  g.polygon(points, 'none', soft, 1, false);
  const distance = Math.max(0, Math.min(2.999999, t * 3 + .38 * interaction.x));
  const start = Math.floor(distance);
  const fraction = distance - start;
  points.forEach(([x, y], i) => {
    g.circle(x, y, .026, i <= start ? green : dark, colors[i]);
    g.text(String(i + 1), x, y - .07);
  });
  g.circle(mix(points[start][0], points[start + 1][0], fraction),
    mix(points[start][1], points[start + 1][1], fraction), .042, 'none', orange);
}

function achievementSequence(g, t) {
  for (let i = 0; i < 4; i++) {
    const cx = stages[i], cy = .47 - .045 * (i % 2);
    const p = smooth(segment(t, .17 * i, .47 + .17 * i));
    const points = Array.from({length: 7}, (_, vertex) => {
      const angle = Math.PI * vertex / 3 + .52;
      return [cx + (.035 + .037 * p) * Math.cos(angle), cy + (.072 + .037 * p) * Math.sin(angle)];
    });
    g.polygon(points, dark, colors[i], .48 + .52 * p);
    g.line([cx - .027, cy + .01], [cx - .007, cy + .040], green, p, 3);
    g.line([cx - .007, cy + .04], [cx + .033, cy - .043], green, p, 3);
  }
  g.line([.19, .66], [.19 + .60 * t, .66], orange, 1, 3);
}

function roadmapAnimation(g, t) {
  for (let i = 0; i < 3; i++) {
    const y = .26 + .20 * i;
    g.line([.13, y + .11], [.84, y + .11], panel);
    for (let j = 0; j < 3; j++) {
      const start = .16 + .12 * j + i * .045;
      const reveal = clamp((t - .12 * (i + j)) * 1.8);
      const length = (.22 + .015 * (2 - j)) * reveal;
      g.rect(start, y + .033 * j, length, .028, colors[(i + j) % 4]);
    }
  }
  g.line([.13 + .69 * t, .22], [.13 + .69 * t, .79], soft, 1, 3);
}

function digitalJourney(g, t) {
  for (let i = 0; i < 7; i++) {
    const p = smooth(segment(t, i * .065, .55 + i * .065));
    const old = [.23 + i % 2 * .13, .26 + i * .063];
    const next = [.66 + .11 * Math.cos(i * Math.PI / 3), .50 + .18 * Math.sin(i * Math.PI / 3)];
    const x = mix(old[0], next[0], p), y = mix(old[1], next[1], p);
    g.line(old, [x, y], colors[i % 4], 1 - .59 * p);
    g.circle(x, y, .012 + .018 * p, cyan);
    g.line([x, y], [.66, .50], violet, .46 * p);
  }
  g.circle(.66, .5, .05, dark, green);
}

function evidencePresentation(g, t) {
  const current = Math.min(2, Math.floor(t * 3));
  for (let i = 2; i >= 0; i--) {
    const selected = i === current;
    const dx = selected ? .07 * smooth((t * 3) % 1) : .18 + .07 * i;
    const x = .16 + dx, y = .21 + i * .08;
    page(g, x, y, .39, .30, colors[i], selected ? 1 : .48);
    if (selected) {
      g.rect(x + .042, y + .059, .23, .054, dark);
      g.text(['Source', 'Tests', 'Receipt'][i], x + .17, y + .083, green);
    }
  }
}

const scenes = [
  ['transitions-spatial-navigation', 'Seamless Spatial Navigation', 'تنقل مكاني متصل', 'Opposing page translation with a depth shift and a directional progress marker.', spatialNavigation],
  ['transitions-liquid-screen', 'Liquid Screen Transition', 'انتقال الشاشة السائل', 'A traveling wave edge distorts across a bounded filled screen.', liquidScreen],
  ['transitions-mask-reveal', 'Cinematic Mask Reveal', 'كشف بقناع سينمائي', 'Trapezoid aperture exposes progressively longer contents on each row.', maskReveal],
  ['transitions-panel-assembly', 'Multi-panel Page Assembly', 'تجميع صفحة متعددة اللوحات', 'Four panels converge from different corners at staggered times.', panelAssembly],
  ['transitions-shared-element', 'Shared Element Transformation', 'تحول عنصر مشترك', 'An identifiable card travels between layouts and interpolates its bounds.', sharedElement],
  ['transitions-perspective-portal', 'Perspective Portal Transition', 'انتقال عبر بوابة منظورية', 'Portal planes advance past a moving vanishing point under perspective.', perspectivePortal],
  ['transitions-depth-replacement', 'Depth-based Page Replacement', 'استبدال الصفحة حسب العمق', 'Depth scaling and paired fades replace overlapping page layers.', depthReplacement],
  ['transitions-curtain-reveal', 'Interactive Curtain Reveal', 'كشف ستارة تفاعلي', 'Alternating pleats compress around a pointer-adjustable aperture.', curtainReveal],
  ['transitions-fragment-transition', 'Geometric Fragment Transition', 'انتقال بشظايا هندسية', 'A grid of triangular fragments separates and reassembles at a new position.', fragmentTransition],
  ['transitions-view-transition', 'Dynamic View Transition', 'انتقال عرض ديناميكي', 'Canvas snapshot elements retain identity while moving from rows to a grid.', viewTransition],
  ['story-architecture-timeline', 'Cinematic Architecture Timeline', 'خط زمني سينمائي للمعمارية', 'Timeline segments lead into stacked architecture nodes and labels.', architectureTimeline],
  ['story-capability-reveal', 'Engineering Capability Reveal', 'كشف القدرات الهندسية', 'Engineering stages slide into a staggered card grid.', capabilityReveal],
  ['story-workflow-transformation', 'AI Workflow Transformation', 'تحول سير عمل الذكاء الاصطناعي', 'Four workflow nodes reorganize while signals traverse explicit links.', workflowTransformation],
  ['story-system-evolution', 'Before-and-After System Evolution', 'تطور النظام قبل وبعد', 'Components migrate one by one between old and new system envelopes.', systemEvolution],
  ['story-kpi-storytelling', 'Executive KPI Storytelling', 'سرد مؤشرات الأداء التنفيذية', 'Synthetic bars and their numeric labels grow in sequence.', executiveKPI],
  ['story-milestone-journey', 'Interactive Milestone Journey', 'رحلة إنجازات تفاعلية', 'A pointer-adjustable marker moves along a segmented milestone trail.', milestoneJourney],
  ['story-achievement-sequence', 'Technical Achievement Sequence', 'تسلسل الإنجازات التقنية', 'Hexagonal achievement seals gain drawn checkmarks in sequence.', achievementSequence],
  ['story-roadmap-animation', 'Strategic Roadmap Animation', 'تحريك خريطة الطريق الاستراتيجية', 'Three work tracks grow bars relative to a common animated playhead.', roadmapAnimation],
  ['story-transformation-journey', 'Digital Transformation Journey', 'رحلة التحول الرقمي', 'Separate legacy nodes converge into an interconnected hub topology.', digitalJourney],
  ['story-evidence-presentation', 'Cinematic Evidence Presentation', 'عرض الأدلة السينمائي', 'Source, test and receipt cards move through a visible evidence stack.', evidencePresentation],
];

export const definitions = Object.freeze(scenes.map(([id, name_en, name_ar, mechanism]) => Object.freeze({
  id, name_en, name_ar, mechanism, engine: 'canvas2d', duration_ms: 3600,
  license: 'MIT', license_file: 'motion-library/expansion/LICENSE',
  implementation_status: 'implemented-source',
  runtime_status: 'requires-current-source-bound-proof',
  source: {module: 'motion-library/expansion/nextgen-motion-scenes.mjs'},
  reduced_motion: {mode: 'static-poster', progress: .55},
  mobile: {requires_real_device_verification: true},
  semantics: 'Canvas2D engineering illustration with synthetic data.',
})));
const sample = new Map(scenes.map(([id, , , , render]) => [id, render]));
const bounded = (value, min, max) => Number.isFinite(value) && value >= min && value <= max;

export function sampleMotion(value, progress, options = {}) {
  const id = typeof value === 'string' ? value : value?.id;
  const render = sample.get(id);
  const {width = 640, height = 360, intensity = 1, rtl = false, reducedMotion = false,
    interaction = {x: 0, y: 0}} = options;
  if (!render || !bounded(progress, -1e7, 1e7)) throw new RangeError('Unknown scene or invalid progress');
  if (!bounded(width, 120, 4096) || !bounded(height, 90, 4096) || !bounded(intensity, 0, 1)
    || typeof rtl !== 'boolean' || typeof reducedMotion !== 'boolean'
    || !bounded(interaction?.x, -1, 1) || !bounded(interaction?.y, -1, 1)) {
    throw new RangeError('Invalid scene options');
  }
  const p = reducedMotion ? .55 : clamp(progress);
  const t = .5 + (p - .5) * intensity;
  const drawing = geometry(width, height, rtl);
  render(drawing, t, reducedMotion ? {x: 0, y: 0} : interaction);
  return {width, height, background: '#08111f', primitives: drawing.primitives,
    meta: {id, progress: p, engine: 'canvas2d', reducedMotion}};
}
