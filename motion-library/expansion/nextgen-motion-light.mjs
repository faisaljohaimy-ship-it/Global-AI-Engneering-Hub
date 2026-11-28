// SPDX-License-Identifier: MIT
// Original cinematic lighting and product illustrations for the Universal Motion SDK.

const TAU = 2 * Math.PI;
const INK = '#08111f';
const PANEL = '#162b43';
const DIM = '#38516a';
const WHITE = '#f1f5f9';
const CYAN = '#67e8f9';
const BLUE = '#60a5fa';
const VIOLET = '#a78bfa';
const GOLD = '#fbbf77';
const MINT = '#6ee7b7';

const clamp = (value) => Math.max(0, Math.min(1, value));
const mix = (start, end, amount) => start + (end - start) * amount;
const ease = (amount) => {
  const bounded = clamp(amount);
  return bounded * bounded * (3 - 2 * bounded);
};
const phase = (time, start, duration) => ease((time - start) / duration);
const wave = (angle) => .5 + .5 * Math.sin(angle);
const range = (count) => Array.from({length: count}, (_, index) => index);
const polar = (angle, radius, x = 0, y = 0) => [
  x + radius * Math.cos(angle), y + radius * Math.sin(angle),
];
const bounded = (value, minimum, maximum) => Number.isFinite(value) && value >= minimum && value <= maximum;

function stage(width, height, rtl) {
  const scale = Math.min(width, height) * .93;
  const mirror = rtl ? -1 : 1;
  const x = (value) => width / 2 + mirror * (value - .025) * scale;
  const y = (value) => height / 2 + value * scale;
  const primitives = [];
  const strokeWidth = (value) => Math.max(.6, value * scale);
  return {
    primitives,
    line(from, to, stroke = DIM, opacity = 1, weight = .003) {
      primitives.push({type: 'line', x1: x(from[0]), y1: y(from[1]), x2: x(to[0]), y2: y(to[1]),
        stroke, opacity: clamp(opacity), lineWidth: strokeWidth(weight)});
    },
    path(points, stroke, opacity = 1, {fill, closed = false, weight = .003} = {}) {
      primitives.push({type: 'polyline', points: points.map(([px, py]) => ({x: x(px), y: y(py)})),
        stroke, fill, closed, opacity: clamp(opacity), lineWidth: strokeWidth(weight)});
    },
    dot(px, py, radius, fill, opacity = 1, stroke) {
      primitives.push({type: 'circle', x: x(px), y: y(py), r: radius * scale, fill, stroke,
        opacity: clamp(opacity), lineWidth: strokeWidth(.002)});
    },
    rect(px, py, w, h, fill, {opacity = 1, stroke, rotation = 0, radius = .012} = {}) {
      primitives.push({type: 'rect', x: x(px) - w * scale / 2, y: y(py) - h * scale / 2,
        width: w * scale, height: h * scale, fill, stroke, rotation: mirror * rotation,
        radius: Math.min(radius, w / 2, h / 2) * scale, opacity: clamp(opacity), lineWidth: strokeWidth(.002)});
    },
    label(px, py, english, arabic, opacity = 1, size = .032, fill = WHITE) {
      primitives.push({type: 'text', x: x(px), y: y(py), text: rtl ? arabic : english, fill,
        opacity: clamp(opacity), align: 'center', size: Math.max(1, size * scale)});
    },
  };
}

function polygon(graph, points, fill, opacity, stroke) {
  graph.path(points, stroke, opacity, {fill, closed: true});
}

function halo(graph, x, y, radius, color, glow) {
  for (const step of [1, .81, .62, .42, .25]) {
    graph.dot(x, y, radius * step, color, glow * (.2 - .13 * step));
  }
}

function grid(graph, horizon = .31) {
  graph.line([-.43, horizon], [.43, horizon], DIM, .75);
  for (const index of range(11)) {
    const x = -.42 + index * .084;
    graph.line([x * .49, horizon - .09], [x, horizon + .1], DIM, .48);
  }
}

function device(graph, x = 0, y = 0, size = 1, opacity = 1) {
  graph.rect(x, y, .35 * size, .48 * size, PANEL, {stroke: DIM, opacity});
  graph.rect(x, y - .012 * size, .31 * size, .405 * size, INK, {stroke: DIM, opacity});
  graph.dot(x, y + .211 * size, .012 * size, DIM, opacity);
}

function panel(graph, x, y, width, height, color, level, opacity = 1, rotation = 0) {
  const position = (dx, dy) => [x + dx * Math.cos(rotation) - dy * Math.sin(rotation),
    y + dx * Math.sin(rotation) + dy * Math.cos(rotation)];
  graph.rect(x, y, width, height, PANEL, {stroke: color, opacity, rotation});
  graph.rect(...position(-width * .19, -height * .21), width * .4, height * .075, color, {opacity, rotation});
  graph.rect(...position(width * (-.4 + .39 * level), height * .13),
    width * .78 * level, height * .09, color, {opacity: .7 * opacity, rotation});
}

function volumetricBeams(graph, time) {
  grid(graph);
  const apex = [mix(-.29, .08, time), -.34];
  for (const index of range(4)) {
    const target = -.32 + index * .19 + .037 * Math.sin(time * 5 + index);
    const tint = index % 2 ? BLUE : CYAN;
    polygon(graph, [apex, [target - .1, .29], [target + .105, .29]], tint, .13);
    polygon(graph, [apex, [target - .043, .29], [target + .044, .29]], tint, .16);
    for (const mote of range(6)) {
      const depth = ((mote * .137 + time * .32 + index * .09) % .8) + .15;
      graph.dot(mix(apex[0], target, depth) + Math.sin(mote * 13 + time * 4) * .034 * depth,
        mix(apex[1], .29, depth), .005, CYAN, .25 + .6 * Math.sin(Math.PI * depth));
    }
  }
  graph.dot(...apex, .028, WHITE);
}

function bloomReveal(graph, time) {
  const x = -.105;
  const released = phase(time, .08, .78);
  halo(graph, x, 0, .08 + released * .26, VIOLET, mix(.25, 1, released));
  halo(graph, x, 0, .045 + released * .19, CYAN, .85 * released);
  for (const [index, tint] of [VIOLET, CYAN, WHITE].entries()) {
    const radius = .072 + .037 * index;
    const points = range(6).map((n) => polar(n * TAU / 6 + time * .64, radius, x, 0));
    polygon(graph, points, tint, mix(.48, .09, index / 2), WHITE);
  }
  for (const index of range(12)) {
    const angle = index * TAU / 12 + .41;
    const from = polar(angle, .146 + released * .017, x, 0);
    const to = polar(angle, .153 + released * (.05 + (index % 3) * .031), x, 0);
    graph.line(from, to, CYAN, released, .005);
  }
}

function studioSpotlight(graph, time) {
  grid(graph);
  const x = mix(-.33, .29, time);
  const lamp = [x * .46, -.35];
  const pool = range(24).map((n) => {
    const angle = n * TAU / 24;
    return [x + .165 * Math.cos(angle), .285 + .049 * Math.sin(angle)];
  });
  polygon(graph, [lamp, [x - .168, .285], [x + .168, .285]], GOLD, .18);
  polygon(graph, pool, GOLD, .39, GOLD);
  for (const [index, height] of [.16, .235, .132].entries()) {
    const objectX = -.25 + index * .225;
    const lit = Math.max(.16, 1 - Math.abs(objectX - x) * 4.3);
    graph.rect(objectX, .274 - height / 2, .12, height, PANEL, {stroke: DIM});
    graph.rect(objectX, .273 - height / 2, .116, height, GOLD, {opacity: .69 * lit});
  }
  graph.rect(...lamp, .092, .054, PANEL, {stroke: GOLD, rotation: x});
}

function lensFlare(graph, time) {
  const source = [mix(-.31, .23, time), mix(-.22, -.04, time)];
  halo(graph, ...source, .14, GOLD, .95);
  graph.dot(...source, .031, WHITE);
  graph.line([source[0] - .12, source[1]], [source[0] + .15, source[1]], GOLD, .85);
  for (const [index, tint] of [BLUE, VIOLET, GOLD, CYAN, MINT].entries()) {
    const x = source[0] * (1 - (index + 1) * .38);
    const y = source[1] * (1 - (index + 1) * .38);
    const radius = .027 + index * .012;
    const points = range(6).map((n) => polar(n * TAU / 6 + .3, radius, x, y));
    polygon(graph, points, tint, .36 - index * .035, tint);
  }
}

function atmosphericScattering(graph, time) {
  const sun = [mix(-.22, .19, time), mix(.08, -.23, time)];
  const sunHeight = clamp((.14 - sun[1]) * 2.6);
  for (const index of range(16)) {
    const y = -.34 + index * .041;
    const horizonWeight = Math.exp(-5 * Math.abs(y - .165));
    graph.rect(0, y, .83, .047, index > 8 ? GOLD : BLUE, {
      opacity: .07 + horizonWeight * (.32 - sunHeight * .15), radius: 0,
    });
  }
  halo(graph, ...sun, .19, GOLD, .9);
  graph.dot(...sun, .037, GOLD);
  const ridge = range(15).map((n) => [-.42 + .06 * n, .24 - .032 * wave(n * 1.33)]);
  polygon(graph, [...ridge, [.42, .37], [-.42, .37]], PANEL, 1, DIM);
  for (const index of range(7)) {
    const spread = index * .11 - .32;
    graph.line([sun[0], sun[1] + .024], [spread, .208], GOLD,
      (.1 + .08 * (1 - Math.abs(spread))) * (1 - sunHeight * .35));
  }
}

function shadowSweep(graph, time) {
  grid(graph, .3);
  const light = [mix(-.36, .35, time), -.33];
  for (const [index, height] of [.15, .205, .112].entries()) {
    const x = -.225 + index * .2;
    const dx = (x - light[0]) * height * 1.09;
    const foot = .205 + index * .018;
    polygon(graph, [[x - .056, foot], [x + .056, foot],
      [x + .056 + dx, foot + height * .59], [x - .056 + dx, foot + height * .59]], BLUE, .37);
    graph.rect(x, foot - height / 2, .112, height, PANEL, {stroke: DIM});
    const illuminatedSide = x > light[0] ? x - .055 : x + .055;
    graph.line([illuminatedSide, foot], [illuminatedSide, foot - height], GOLD, .83, .005);
  }
  halo(graph, ...light, .091, GOLD, .7);
  graph.dot(...light, .022, GOLD);
}

function reflectionTransition(graph, time) {
  const horizon = .07;
  const shift = mix(-.135, .12, time);
  const speed = 1 - phase(time, .03, .88);
  const peaks = [[-.33, .04], [-.13, -.25], [.01, -.08], [.149, -.218], [.34, .04]];
  const moved = peaks.map(([x, y]) => [x + shift * .43, y]);
  polygon(graph, [...moved, [.31, .057], [-.3, .057]], PANEL, 1, CYAN);
  graph.line([-.42, horizon], [.42, horizon], BLUE, .91);
  for (const index of range(12)) {
    const amount = (index + 1) / 13;
    const y = horizon + amount * .325;
    const distortion = speed * .077 * Math.sin(index * 1.67 + time * 8);
    const x = shift + distortion;
    const width = .145 + .18 * wave(index * 2.37);
    graph.line([x - width / 2, y], [x + width / 2, y], index % 3 === 0 ? CYAN : BLUE,
      mix(.62, .09, amount), .009);
  }
  graph.path(moved.map(([x, y], index) => [x + speed * .045 * Math.sin(index + time * 8),
    horizon + (horizon - y) * .72]), VIOLET, 1 - speed * .57);
}

function lightPainting(graph, time) {
  const trace = (step) => {
    const angle = step * TAU * 1.35 - .35;
    return [.35 * Math.cos(angle) + .073 * Math.cos(2 * angle),
      .21 * Math.sin(2 * angle) - .045 * Math.sin(angle)];
  };
  const portion = .1 + .9 * time;
  for (const [index, tone] of [BLUE, VIOLET, CYAN].entries()) {
    const points = range(64).map((n) => trace(n * portion / 63));
    graph.path(points, tone, .21 + index * .17, {weight: .018 - index * .006});
  }
  const end = trace(portion);
  halo(graph, ...end, .068, CYAN, .9);
  graph.dot(...end, .013, WHITE);
}

function emissiveActivation(graph, time) {
  const hubs = [[-.32, .13], [-.16, .13], [-.16, -.095], [.014, -.095],
    [.014, .095], [.18, .095], [.18, -.175], [.353, -.175]];
  graph.path(hubs, DIM, .86, {weight: .007});
  const head = time * (hubs.length - 1);
  for (const [index, cell] of hubs.entries()) {
    const activated = ease(head - index + .5);
    if (index > 0) graph.line(hubs[index - 1], cell, MINT, activated, .007);
    graph.rect(...cell, .086, .086, PANEL, {stroke: MINT, radius: .006});
    halo(graph, ...cell, .076, MINT, activated * .9);
    graph.rect(...cell, .059, .059, MINT, {opacity: activated * .79, radius: .004});
  }
  const index = Math.min(hubs.length - 2, Math.floor(head));
  const from = hubs[index], to = hubs[index + 1];
  graph.dot(mix(from[0], to[0], head - index), mix(from[1], to[1], head - index), .012, WHITE);
}

function exposureTransition(graph, time) {
  const exposure = 2 ** mix(-3, 2.8, time);
  const light = (luminance) => clamp((1 - Math.exp(-luminance * exposure)) ** .65);
  const shade = (value) => [value * .74, value * .91, value]
    .map((channel) => Math.round(channel * 255).toString(16).padStart(2, '0')).join('');
  const tones = [.025, .07, .16, .31, .54, .82, 1.5, 3];
  for (const [index, tone] of tones.entries()) {
    const x = -.349 + .1 * index;
    const output = light(tone);
    const height = .063 + .17 * output;
    graph.rect(x, .21 - height / 2, .076, height, '#' + shade(output));
    graph.rect(x, -.14, .076, .096, '#' + shade(output), {stroke: DIM});
  }
  graph.line([-.393, .225], [.397, .225], DIM);
  graph.label(0, -.266, 'EXPOSURE RESPONSE', 'استجابة التعريض', .9);
}

function productMaterialization(graph, time) {
  const rows = 7, columns = 5;
  graph.rect(0, 0, .355, .488, INK, {stroke: DIM, opacity: .5});
  for (const index of range(rows * columns)) {
    const x = ((index % columns) - 2) * .058;
    const y = (Math.floor(index / columns) - 3) * .057;
    const delay = ((index * 13) % 19) / 42;
    const start = polar(index * 2.39996, .33 + .02 * Math.sin(index));
    const arrived = phase(time, delay, .53);
    graph.rect(mix(start[0], x, arrived), mix(start[1], y, arrived), .043, .041,
      index % 8 === 0 ? CYAN : index % 3 === 0 ? BLUE : PANEL,
      {stroke: arrived > .62 ? DIM : CYAN, rotation: (1 - arrived) * index * .28});
  }
  graph.dot(0, .213, .012, CYAN, phase(time, .72, .24));
}

function executiveRotation(graph, time) {
  const angle = mix(-.72, 1.03, time);
  const corners = [[-.15, -.23, -.065], [.15, -.23, -.065], [.15, .23, -.065], [-.15, .23, -.065],
    [-.15, -.23, .065], [.15, -.23, .065], [.15, .23, .065], [-.15, .23, .065]];
  const rotated = corners.map(([x, y, z]) => [
    x * Math.cos(angle) + z * Math.sin(angle), y, z * Math.cos(angle) - x * Math.sin(angle),
  ]);
  const faceVertices = [[0, 1, 2, 3], [4, 5, 6, 7], [0, 1, 5, 4], [3, 2, 6, 7], [0, 3, 7, 4], [1, 2, 6, 5]];
  const faces = faceVertices.map((vertices, index) => {
    const coords = vertices.map((n) => rotated[n]);
    const depth = coords.reduce((sum, point) => sum + point[2], 0) / coords.length;
    return {points: coords.map(([x, y, z]) => [x / (1 + z), y / (1 + z) + z * .2]),
      depth, color: [PANEL, DIM, BLUE, DIM, '#223e59', '#335879'][index]};
  }).sort((a, b) => b.depth - a.depth);
  grid(graph, .298);
  for (const face of faces) polygon(graph, face.points, face.color, 1, CYAN);
}

function componentReveal(graph, time) {
  device(graph, -.075, 0, .95);
  const coveredY = mix(-.179, .171, time);
  for (const [index, x] of [-.17, -.105, -.03, .036].entries()) {
    for (const row of range(5)) {
      const y = -.153 + row * .071;
      const visible = phase(time, (y + .16) * 2.4, .16);
      graph.rect(x, y, .043, .042, index % 2 ? MINT : BLUE,
        {opacity: .13 + .83 * visible, radius: .004});
      graph.line([x, y - .017], [x + .034, y], CYAN, visible);
    }
  }
  graph.line([-.227, coveredY], [.073, coveredY], CYAN, .95, .009);
  graph.path([[.064, coveredY], [.18, -.014], [.332, -.014]], CYAN);
  graph.label(.257, -.057, 'SECTION', 'مقطع', 1, .034);
}

function featureSpotlight(graph, time) {
  const locations = [[-.137, -.13], [.123, -.038], [-.113, .124]];
  device(graph, -.01, 0, 1.18);
  const step = Math.min(1, Math.floor(time * 2));
  const amount = phase(time, step / 2, .5);
  const point = [mix(locations[step][0], locations[step + 1][0], amount),
    mix(locations[step][1], locations[step + 1][1], amount)];
  for (const [index, [x, y]] of locations.entries()) {
    const focus = 1 - clamp(Math.hypot(x - point[0], y - point[1]) * 6);
    graph.rect(x, y, .108, .071, [BLUE, VIOLET, MINT][index], {opacity: .22 + focus * .68});
  }
  graph.dot(...point, .056, 'none', .97, WHITE);
  graph.path([point, [.212, point[1]], [.286, -.06]], GOLD);
  graph.rect(.29, -.082, .105, .043, PANEL, {stroke: GOLD});
}

function interfaceFlythrough(graph, time) {
  const depthOrder = range(6).map((index) => ({
    index, depth: (index + .7 - time * 3.7 + 7) % 6,
  })).sort((a, b) => b.depth - a.depth);
  for (const {index, depth} of depthOrder) {
    const size = .22 / (.44 + depth * .31);
    const x = Math.sin(index * 1.6) * .17 * size + .18 * (time - .5);
    const y = (index % 2 - .45) * .125 * size;
    const opacity = Math.min(1, (depth + .2) * 1.5);
    panel(graph, x, y, size * 1.46, size * .92, index % 2 ? CYAN : BLUE,
      .35 + index * .09, opacity, -.08 + index * .025);
  }
}

function multiScreenAssembly(graph, time) {
  const screenTargets = [[-.285, -.043], [.005, .008], [.295, -.043]];
  graph.line([-.45, .19], [.445, .19], DIM, .7);
  for (const [index, [x, y]] of screenTargets.entries()) {
    const amount = phase(time, index * .113, .68);
    const height = .155 + index % 2 * .071;
    const centerX = x * mix(1.41, 1, amount);
    const centerY = y + mix(index % 2 ? .29 : -.31, 0, amount);
    const width = .29 * mix(.58, 1, amount);
    panel(graph, centerX, centerY, width, height, [BLUE, CYAN, VIOLET][index],
      .25 + .64 * amount, .97, (1 - amount) * (index - 1) * .83);
    graph.line([centerX, centerY + height / 2], [centerX, .19], DIM, amount);
  }
}

function systemDemonstration(graph, time) {
  const endpoints = [[-.347, -.128], [-.13, .086], [.106, -.088], [.325, .139]];
  const stageColors = [BLUE, CYAN, VIOLET, MINT];
  graph.path(endpoints, DIM, .9, {weight: .009});
  const position = time * 3;
  const hop = Math.min(2, Math.floor(position));
  const amount = position - hop;
  for (const [index, [x, y]] of endpoints.entries()) {
    const active = phase(position, index - .45, .6);
    panel(graph, x, y, .153, .101, stageColors[index], .23 + .68 * active);
    if (index > 0) graph.line(endpoints[index - 1], [x, y], stageColors[index], active, .005);
  }
  const x = mix(endpoints[hop][0], endpoints[hop + 1][0], amount);
  const y = mix(endpoints[hop][1], endpoints[hop + 1][1], amount);
  graph.dot(x, y, .022, WHITE, 1, MINT);
  graph.label(0, -.285, 'SYSTEM FLOW', 'مسار النظام', .75);
}

function timelineTransformation(graph, time) {
  graph.line([-.408, .21], [.407, .21], DIM, .9, .006);
  const positions = [-.299, -.105, .09, .295];
  for (const [index, x] of positions.entries()) {
    const transformed = phase(time, index * .17, .45);
    const y = mix(.182, -.06 - .06 * (index % 2), transformed);
    const tone = [BLUE, CYAN, VIOLET, MINT][index];
    graph.line([x, .21], [x, y], tone, .35 + .65 * transformed);
    graph.dot(x, .21, .012, tone, .72);
    graph.rect(x, y, mix(.029, .177, transformed), mix(.029, .231, transformed),
      PANEL, {stroke: tone, radius: .009});
    if (transformed > .18) {
      graph.label(x, y - .054 * transformed, '0' + (index + 1), '٠' + ['١', '٢', '٣', '٤'][index],
        transformed, .042, tone);
      graph.line([x - .055 * transformed, y + .036], [x + .055 * transformed, y + .036], tone, transformed);
    }
  }
  graph.dot(mix(-.4, .4, time), .21, .019, WHITE);
}

function featureExplosion(graph, time, interaction) {
  const expansion = phase(time, .055, .67);
  const angle = interaction.x * .32 + time * .45;
  graph.rect(0, 0, .145, .145, PANEL, {stroke: WHITE, rotation: .12});
  for (const [index, tint] of [CYAN, BLUE, VIOLET, GOLD, MINT, CYAN].entries()) {
    const ring = .097 + expansion * (.183 + (index % 2) * .049);
    const [x, y] = polar(index * TAU / 6 + angle, ring);
    const displacement = y + interaction.y * expansion * .047;
    graph.line([0, 0], [x, displacement], tint, .25 + expansion * .6);
    graph.rect(x, displacement, .095 + expansion * .041, .078, PANEL,
      {stroke: tint, rotation: (1 - expansion) * .37 * index});
    graph.dot(x, displacement, .012, tint);
  }
}

function brandReveal(graph, time) {
  const mark = [[-.19, .13], [-.15, -.107], [.019, -.225], [.189, -.102],
    [.226, .139], [.035, .043], [-.19, .13]];
  const traced = Math.max(.05, time) * (mark.length - 1);
  let tip = mark[0];
  for (let index = 0; index < Math.ceil(traced); index++) {
    const start = mark[index];
    const next = mark[index + 1];
    const amount = clamp(traced - index);
    tip = [mix(start[0], next[0], amount), mix(start[1], next[1], amount)];
    graph.line(start, tip, index < 3 ? CYAN : VIOLET, .93, .014);
  }
  graph.dot(...tip, .021, CYAN, .52 * (1 - time));
  const aperture = mix(.01, .406, phase(time, .22, .76));
  graph.line([-aperture, .233], [aperture, .233], DIM, .95);
  graph.label(.015, .317, 'STUDIO', 'استوديو', .14 + .86 * phase(time, .54, .39), .081);
}

const specs = [
  ['lighting-volumetric-beams', 'Volumetric Light Beams', 'حزم ضوئية حجمية', 'Moving nested light cones illuminate traveling dust at depth.', volumetricBeams],
  ['lighting-bloom-reveal', 'Dynamic Bloom Reveal', 'كشف التوهج الديناميكي', 'Radial halos and spokes spread from a luminous crystal core.', bloomReveal],
  ['lighting-studio-spotlight', 'Moving Studio Spotlight', 'إضاءة استوديو متحركة', 'A spotlight moves its footprint and changes subject illumination by distance.', studioSpotlight],
  ['lighting-lens-flare', 'Cinematic Lens Flare', 'وهج عدسة سينمائي', 'Aperture ghosts move in opposition along the source-to-center optical axis.', lensFlare],
  ['lighting-atmospheric-scattering', 'Atmospheric Light Scattering', 'تشتت الضوء الجوي', 'Altitude-driven light bands shape a horizon haze in a stylized landscape.', atmosphericScattering],
  ['lighting-shadow-sweep', 'Dynamic Shadow Sweep', 'مسح الظلال الديناميكي', 'Cast shadow vertices shift with the position of a moving point light.', shadowSweep],
  ['lighting-reflection-transition', 'Real-time Reflection Transition', 'انتقال الانعكاس الآني', 'A mirrored outline and ripple samples settle beneath a water line.', reflectionTransition],
  ['lighting-light-painting', 'Light Painting Animation', 'رسم بالضوء', 'An illuminated emitter traces an increasingly long parametric ribbon.', lightPainting],
  ['lighting-emissive-activation', 'Emissive Material Activation', 'تنشيط مادة باعثة للضوء', 'A signal advances along a conductor and activates its material cells in order.', emissiveActivation],
  ['lighting-exposure-transition', 'Cinematic Exposure Transition', 'انتقال التعريض السينمائي', 'A tone-mapped exposure ramp converts scene luminance to swatches and response bars.', exposureTransition],
  ['product-materialization', 'Luxury Product Materialization', 'تجسيد منتج فاخر', 'Distributed shell pieces converge into a staggered device tessellation.', productMaterialization],
  ['product-executive-rotation', 'Executive Product Rotation', 'دوران المنتج الاستعراضي', 'Perspective vertices rotate around a vertical axis with depth-sorted faces.', executiveRotation],
  ['product-component-reveal', 'Technical Component Reveal', 'كشف المكونات التقنية', 'A scanning section line activates successive rows of a hidden circuit.', componentReveal],
  ['product-feature-spotlight', 'Feature-by-Feature Spotlight', 'تسليط الضوء على المزايا', 'A focus ring hands attention between individual device features.', featureSpotlight],
  ['product-interface-flythrough', 'Cinematic Interface Flythrough', 'عبور سينمائي للواجهة', 'Interface planes pass a moving camera with perspective scale and depth ordering.', interfaceFlythrough],
  ['product-multi-screen-assembly', 'Multi-screen Product Assembly', 'تجميع شاشات المنتج', 'Offset screens rotate and slide into a shared presentation layout.', multiScreenAssembly],
  ['product-system-demonstration', 'Immersive System Demonstration', 'عرض النظام التفاعلي', 'A data packet crosses a system diagram and activates processing stages.', systemDemonstration],
  ['product-timeline-transformation', 'Product Timeline Transformation', 'تحول الجدول الزمني للمنتج', 'Chronological markers expand into milestone cards as the cursor advances.', timelineTransformation],
  ['product-feature-explosion', 'Interactive Feature Explosion', 'تفريع تفاعلي للمزايا', 'Linked feature panels fan radially and respond to pointer coordinates.', featureExplosion],
  ['product-brand-reveal', 'Cinematic Final Brand Reveal', 'كشف ختامي للعلامة', 'A geometric brand mark is traced before the closing wordmark and rule appear.', brandReveal],
];

const samplers = new Map(specs.map(([id, , , , render]) => [id, render]));
export const definitions = Object.freeze(specs.map(([id, name_en, name_ar, mechanism]) => Object.freeze({
  id, name_en, name_ar, mechanism, engine: 'canvas2d', duration_ms: 3200,
  source: {module: 'motion-library/expansion/nextgen-motion-light.mjs'},
  license: 'MIT', license_file: 'motion-library/expansion/LICENSE',
  implementation_status: 'implemented-source', runtime_status: 'requires-current-source-bound-proof',
  reduced_motion: {mode: 'static-poster', progress: .55},
  mobile: {requires_real_device_verification: true},
  semantics: 'Illustrative CPU-rendered scene using Canvas2D vector primitives.',
})));

export function sampleMotion(value, progress, options = {}) {
  const id = typeof value === 'string' ? value : value?.id;
  const sampler = samplers.get(id);
  if (!sampler || !bounded(progress, -1e7, 1e7)) throw new RangeError('Unknown motion or invalid progress');
  const {width = 640, height = 360, intensity = 1, rtl = false, reducedMotion = false,
    interaction = {x: 0, y: 0}} = options;
  if (!bounded(width, 120, 4096) || !bounded(height, 90, 4096) || !bounded(intensity, 0, 1)
      || typeof rtl !== 'boolean' || typeof reducedMotion !== 'boolean'
      || !bounded(interaction?.x, -1, 1) || !bounded(interaction?.y, -1, 1)) {
    throw new RangeError('Invalid motion options');
  }
  const time = reducedMotion ? .55 : clamp(progress);
  const graph = stage(width, height, rtl);
  sampler(graph, .5 + (time - .5) * intensity, reducedMotion ? {x: 0, y: 0} : interaction);
  return {width, height, background: INK, primitives: graph.primitives,
    meta: {id, progress: time, engine: 'canvas2d', reducedMotion}};
}
