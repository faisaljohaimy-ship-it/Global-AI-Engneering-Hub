// SPDX-License-Identifier: MIT
// Original generated-data engineering scenes. All trajectories are repeatable.
const SOURCE = 'motion-library/expansion/nextgen-motion-physics.mjs';
const BACKGROUND = '#08111f';
const CYAN = '#67e8f9';
const PURPLE = '#a78bfa';
const INK = '#e2e8f0';
const AMBER = '#fbbf24';
const MUTED = '#314762';
const GREEN = '#6ee7b7';
const TAU = 2 * Math.PI;
const clamp = (value) => Math.max(0, Math.min(1, value));
const mix = (a, b, t) => a + (b - a) * t;
const lerp = (a, b, t) => [mix(a[0], b[0], t), mix(a[1], b[1], t)];
function smooth(value) {
  const t = clamp(value);
  return t * t * (3 - 2 * t);
}
const dots = (count, point) => Array.from({length: count}, (_, i) => point(i));
const polygon = (x, y, radius, count, phase = 0) => dots(count, i => {
  const angle = phase + TAU * i / count;
  return [x + radius * Math.cos(angle), y + radius * Math.sin(angle)];
});

function drawing(width, height, rtl) {
  const size = Math.min(width, height);
  const strokeWidth = Math.max(1.15, size * .004);
  const primitives = [];
  const point = ([x, y]) => ({x: width * .5 + (rtl ? -1 : 1) * size * (x - .5),
    y: height * .5 + size * (y - .5)});
  return {
    primitives,
    line(a, b, stroke = CYAN, opacity = 1) {
      if (opacity <= 0) return;
      const from = point(a);
      const to = point(b);
      primitives.push({type: 'line', x1: from.x, y1: from.y, x2: to.x, y2: to.y,
        stroke, opacity, lineWidth: strokeWidth});
    },
    path(points, {stroke = CYAN, fill, closed = false, opacity = 1} = {}) {
      if (opacity <= 0 || points.length < 2) return;
      primitives.push({type: 'polyline', points: points.map(point), closed, stroke, fill,
        opacity, lineWidth: strokeWidth});
    },
    dot(position, radius, {fill = CYAN, stroke, opacity = 1} = {}) {
      if (opacity <= 0) return;
      primitives.push({type: 'circle', ...point(position), r: radius * size, fill, stroke, opacity,
        lineWidth: strokeWidth});
    },
  };
}

const iso = (x, y, z) => [.47 + x * .29 - z * .17, .67 + x * .115 + z * .12 - y * .34];
function box(draw, center, dimensions, stroke = CYAN, opacity = 1) {
  const [x, y, z] = center;
  const [w, h, d] = dimensions;
  const foot = [[x, z], [x + w, z], [x + w, z + d], [x, z + d]];
  for (let i = 0; i < 4; i++) {
    const [a, b] = foot[i];
    const [c, e] = foot[(i + 1) % 4];
    draw.line(iso(a, y, b), iso(c, y, e), stroke, opacity);
    draw.line(iso(a, y + h, b), iso(c, y + h, e), stroke, opacity);
    draw.line(iso(a, y, b), iso(a, y + h, b), stroke, opacity);
  }
}

function construction(draw, t) {
  box(draw, [-.93, -.14, -.35], [1.48, .1, .85], MUTED);
  for (let floor = 0; floor < 5; floor++) {
    const growth = smooth(t * 5.1 + .3 - floor);
    const y = floor * .23;
    const width = 1.08 - floor * .07;
    box(draw, [-.68, y, -.27], [width, .16 * growth, .6], floor % 2 ? PURPLE : CYAN, growth);
    draw.dot(iso(-.68, y + .16 * growth, -.27), .018, {fill: AMBER, opacity: growth});
  }
}

function synchronize(draw, t) {
  const source = [.24, .36];
  const target = [.73, .66];
  draw.path(polygon(...source, .14, 6, .17), {closed: true, stroke: PURPLE});
  draw.path(polygon(...target, .145, 6, .17), {closed: true, stroke: GREEN});
  const route = [source, [.48, .36], [.48, .66], target];
  draw.path(route, {stroke: MUTED});
  for (let i = 0; i < 4; i++) {
    const phase = clamp(1.3 * t - i * .14);
    const segment = Math.min(2, Math.floor(phase * 3));
    draw.dot(lerp(route[segment], route[segment + 1], phase * 3 - segment), .017, {fill: AMBER});
    const current = smooth((phase - .64) * 3);
    draw.line([.64, .61 + i * .034], [.64 + current * (.11 + i * .014), .61 + i * .034], GREEN);
    draw.line([.16, .31 + i * .033], [.29 + i * .011, .31 + i * .033], PURPLE, .85);
  }
}

function explodedAssembly(draw, t) {
  const spread = .43 * smooth(t);
  const pieces = [
    {at: [-.65, -.1, -.23], size: [1.02, .16, .63], shift: [-.7, .1, 0], color: MUTED},
    {at: [-.54, .12, -.15], size: [.43, .39, .42], shift: [-.53, .48, .3], color: CYAN},
    {at: [-.05, .12, -.15], size: [.37, .31, .42], shift: [.62, .28, -.28], color: PURPLE},
    {at: [-.67, .56, -.27], size: [1.06, .1, .66], shift: [.0, 1.18, 0], color: AMBER},
  ];
  for (const {at, size, shift, color} of pieces) {
    const moved = at.map((coordinate, i) => coordinate + spread * shift[i]);
    draw.line(iso(...at), iso(...moved), MUTED, .8);
    box(draw, moved, size, color);
  }
}

function isolateLayer(draw, t) {
  const scan = t * 3.4;
  for (let layer = 0; layer < 4; layer++) {
    const proximity = Math.max(.16, 1 - Math.abs(layer - scan) * .78);
    const y = .035 + layer * .28;
    const z = -.37 + .1 * layer;
    box(draw, [-.75, y, z], [1.18 - layer * .1, .055, .77], CYAN, proximity);
    for (let i = 1; i <= 4; i++) {
      draw.line(iso(-.75 + i * .15, y + .055, z), iso(-.75 + i * .15, y + .055, z + .77), PURPLE, proximity);
    }
  }
  draw.line([.8, .15], [.8, .79], MUTED);
  draw.dot([.8, .75 - t * .56], .021, {fill: AMBER});
}

function blueprint(draw, t) {
  const face = [[-.77, -.37], [.49, -.37], [.49, .49], [-.77, .49]];
  const plan = (x, z) => [.49 + x * .37, .54 + z * .47];
  const fold = (x, y, z) => lerp(plan(x, z), iso(x, y, z), smooth(t));
  for (let i = 0; i < face.length; i++) {
    const [x, z] = face[i];
    const [a, b] = face[(i + 1) % face.length];
    draw.line(fold(x, 0, z), fold(a, 0, b), MUTED);
    draw.line(fold(x, .74, z), fold(a, .74, b), CYAN);
    draw.line(fold(x, 0, z), fold(x, .74, z), PURPLE);
  }
  draw.line(fold(-.5, .74, -.24), fold(.32, .74, .36), AMBER);
  draw.line(fold(-.5, .74, .36), fold(.32, .74, -.24), AMBER);
}

function flythrough(draw, t) {
  // Perspective passage between three offset sensor banks.
  const camera = t * 8.6;
  const project = (x, y, z) => [.45 + x * .61 / z, .48 + y * .61 / z];
  for (let bank = 12; bank >= 1; bank--) {
    const depth = bank * 1.35 - camera;
    if (depth < 1.8) continue;
    const offset = .22 * Math.sin(bank * .9);
    const top = project(-.94 + offset, -.66, depth);
    const left = project(-.94 + offset, .68, depth);
    const bottom = project(1.05 + offset, .68, depth);
    const right = project(1.05 + offset, -.66, depth);
    draw.path([top, left, bottom, right], {closed: true, stroke: CYAN, opacity: .76});
    for (let sensor = 0; sensor < 3; sensor++) {
      draw.dot(project(.85 + offset, -.42 + sensor * .36, depth), .049 / depth, {fill: AMBER});
    }
  }
  draw.line([.19, .83], [.7, .83], MUTED);
  draw.dot([.19 + t * .51, .83], .012, {fill: AMBER});
}

function sensorPropagation(draw, t) {
  const nodes = [[.18, .55], [.35, .33], [.43, .62], [.53, .25], [.7, .44], [.62, .72], [.82, .64]];
  const skin = [[0, 1], [0, 2], [1, 3], [1, 4], [2, 5], [4, 6], [5, 6]];
  const distances = [0, 1, 1, 2, 2, 2, 3];
  const sweep = 3.25 * t;
  for (const [a, b] of skin) {
    draw.line(nodes[a], nodes[b], MUTED);
    if (sweep >= distances[a] - .15 && sweep <= distances[b] + .3) {
      draw.dot(lerp(nodes[a], nodes[b], clamp(sweep - distances[a])), .022, {fill: AMBER});
    }
  }
  for (let i = 0; i < nodes.length; i++) {
    const on = sweep >= distances[i];
    draw.dot(nodes[i], .035, {fill: on ? GREEN : MUTED});
    if (on) draw.dot(nodes[i], .034 + .035 * Math.exp(-2.5 * (sweep - distances[i])),
      {stroke: CYAN, fill: 'transparent', opacity: .55});
  }
}

const elevation = (x, z) => .13 + .45 * Math.exp(-3 * ((x - .2) ** 2 + (z + .18) ** 2))
  + .08 * Math.sin(8 * x + 2 * z) * Math.cos(4 * z);
function reconstructTerrain(draw, t) {
  const count = 10;
  const z = i => i / count * 1.42 - .76;
  const x = i => i / count * 1.51 - .85;
  const station = t * 11.2;
  for (let row = 0; row <= count; row++) {
    const visibility = smooth(station - row + .4);
    const p = index => iso(x(index), elevation(x(index), z(row)), z(row));
    draw.path(dots(count + 1, p), {stroke: row % 2 ? CYAN : PURPLE, opacity: visibility});
    if (row > 0) for (let col = 0; col <= count; col++) {
      draw.line(p(col), iso(x(col), elevation(x(col), z(row - 1)), z(row - 1)),
        MUTED, .85 * visibility);
    }
  }
  const front = z(Math.min(count, station));
  draw.path(dots(count + 1, i => iso(x(i), elevation(x(i), front) + .045, front)), {stroke: AMBER});
}

function assetCondition(draw, t) {
  const timeline = [.12, .26, .39, .57, .62, .88, .81, .72];
  box(draw, [-.86, .09, -.4], [.62, .85, .47], PURPLE);
  const at = p => [.45 + p * .38, .68 - timeline[Math.min(7, Math.floor(p * 8))] * .43];
  draw.line([.45, .72], [.85, .72], MUTED);
  draw.line([.45, .28], [.45, .72], MUTED);
  draw.line([.45, .38], [.85, .38], AMBER, .66);
  const head = t * 7;
  for (let i = 0; i < 7; i++) {
    const amount = clamp(head - i);
    const a = at(i / 8);
    const b = at((i + 1) / 8);
    draw.line(a, lerp(a, b, amount), b[1] < .38 ? AMBER : GREEN, amount);
  }
  const index = Math.min(6, Math.floor(head));
  const value = lerp(at(index / 8), at((index + 1) / 8), head - index);
  draw.dot(value, .02, {fill: INK});
  draw.dot(iso(-.49, .59, -.4), .023 + .022 * (1 - value[1]),
    {fill: value[1] < .38 ? AMBER : GREEN});
}

const HEAT = ['#243b58', '#2d566e', '#277481', '#39a095', '#85b871', '#e1a952', '#ee814d', '#ef625c'];
function riskHeatmap(draw, t) {
  const center = [mix(.29, .68, t), .44 + .14 * Math.sin(t * 4)];
  for (let row = 0; row < 8; row++) for (let col = 0; col < 11; col++) {
    const x = .125 + col * .061;
    const y = .22 + row * .06;
    const distance = (x - center[0]) ** 2 + (y - center[1]) ** 2;
    const risk = .76 * Math.exp(-25 * distance) + .22 * Math.exp(-38 * ((x - .3) ** 2 + (y - .68) ** 2));
    draw.path([[x, y], [x + .054, y], [x + .054, y + .053], [x, y + .053]], {
      closed: true, fill: HEAT[Math.min(7, Math.floor(risk * 10))], stroke: 'transparent',
    });
  }
  draw.dot(center, .028, {fill: 'transparent', stroke: INK});
  draw.line([.13, .75], [.77, .75], MUTED);
  draw.dot([.13 + t * .64, .75], .014, {fill: AMBER});
}

function clothFrames() {
  // Small position-based lattice with pins and three distance passes per step.
  const cols = 9;
  const rows = 7;
  const rest = .074;
  const positions = dots(rows * cols, i => [.15 + i % cols * rest, .215 + Math.floor(i / cols) * rest]);
  const previous = positions.map(point => [...point]);
  const links = [];
  positions.forEach((_, i) => {
    if (i % cols < cols - 1) links.push([i, i + 1]);
    if (i < cols * (rows - 1)) links.push([i, i + cols]);
  });
  const frames = [];
  for (let step = 0; step <= 60; step++) {
    for (let i = cols; i < positions.length; i++) {
      const [x, y] = positions[i];
      const row = Math.floor(i / cols);
      positions[i] = [x + .96 * (x - previous[i][0]) + .00043 * Math.sin(step * .31 + row * .68),
        y + .96 * (y - previous[i][1]) + .00031];
      previous[i] = [x, y];
    }
    for (let pass = 0; pass < 3; pass++) for (const [a, b] of links) {
      const dx = positions[b][0] - positions[a][0];
      const dy = positions[b][1] - positions[a][1];
      const distance = Math.hypot(dx, dy) || rest;
      const correction = (distance - rest) / distance;
      const free = a >= cols;
      const delta = free ? correction * .5 : correction;
      if (free) {
        positions[a][0] += dx * delta;
        positions[a][1] += dy * delta;
      }
      positions[b][0] -= dx * delta;
      positions[b][1] -= dy * delta;
    }
    frames.push(positions.map(point => [...point]));
  }
  return {frames, links, cols};
}

const cloth = clothFrames();
function drawCloth(draw, t) {
  const sample = t * (cloth.frames.length - 1);
  const i = Math.min(cloth.frames.length - 2, Math.floor(sample));
  const point = index => lerp(cloth.frames[i][index], cloth.frames[i + 1][index], sample - i);
  for (const [a, b] of cloth.links) draw.line(point(a), point(b), b - a === 1 ? CYAN : PURPLE);
  for (let pin = 0; pin < cloth.cols; pin++) draw.dot(point(pin), .012, {fill: AMBER});
}

function softBody(draw, t) {
  const center = [.41 + .1 * t, .41 + .26 * Math.sin(Math.PI * t) ** 2];
  const deformation = .26 * Math.exp(-2.8 * t) * Math.sin(16 * t + .4);
  const perimeter = polygon(...center, .16, 36, t * .5).map(([x, y]) =>
    [center[0] + (x - center[0]) * (1 + deformation),
      Math.min(.83, center[1] + (y - center[1]) / (1 + deformation))]);
  draw.path(perimeter, {closed: true, stroke: PURPLE, fill: '#222b52'});
  for (let i = 0; i < perimeter.length; i += 6) draw.line(center, perimeter[i], CYAN, .45);
  draw.line([.15, .84], [.84, .84], MUTED);
  draw.dot(center, .02, {fill: AMBER});
}

function rigidCollision(draw, t) {
  const radiusA = .085;
  const radiusB = .098;
  const approachA = .43;
  const approachB = -.26;
  const massA = radiusA ** 2;
  const massB = radiusB ** 2;
  const restitution = .78;
  const contact = (.68 - .2 - radiusA - radiusB) / (approachA - approachB);
  const impulse = (1 + restitution) * (approachA - approachB) / (1 / massA + 1 / massB);
  const moving = Math.min(t, contact);
  const bounced = Math.max(0, t - contact);
  const a = [.2 + approachA * moving + (approachA - impulse / massA) * bounced, .53];
  const b = [.68 + approachB * moving + (approachB + impulse / massB) * bounced, .53];
  draw.line([.1, .64], [.87, .64], MUTED);
  draw.dot(a, radiusA, {fill: '#243b58', stroke: CYAN});
  draw.dot(b, radiusB, {fill: '#332954', stroke: PURPLE});
  const spin = t * 8;
  draw.line(a, [a[0] + .074 * Math.cos(spin), a[1] + .074 * Math.sin(spin)], CYAN);
  draw.line(b, [b[0] + .085 * Math.cos(-spin), b[1] + .085 * Math.sin(-spin)], PURPLE);
  draw.dot([.2 + approachA * contact + radiusA, .53], .012 + .07 * Math.exp(-35 * Math.abs(t - contact)),
    {fill: 'transparent', stroke: AMBER});
}

function fluidSurface(draw, t) {
  const sample = x => {
    const wave = (offset, speed, period) => Math.sin((x - offset - speed * t) * period * TAU)
      * Math.exp(-18 * (x - offset - speed * t) ** 2);
    return .52 + .084 * wave(.18, .51, 3.2) + .052 * wave(.8, -.39, 4.4);
  };
  const top = dots(50, i => {
    const x = .13 + .72 * i / 49;
    return [x, sample(x)];
  });
  draw.path([...top, [.85, .79], [.13, .79]], {fill: '#133649', closed: true, stroke: CYAN});
  draw.path(top.map(([x, y]) => [x, .16 + y * .82]), {stroke: PURPLE, opacity: .72});
  const trace = .19 + .49 * t;
  draw.dot([trace, sample(trace)], .014, {fill: AMBER});
}

function anomaly(mean, eccentricity) {
  let value = mean;
  for (let i = 0; i < 7; i++) value -= (value - eccentricity * Math.sin(value) - mean)
    / (1 - eccentricity * Math.cos(value));
  return value;
}
function gravityOrbit(draw, t) {
  const focus = [.45, .55];
  const e = .51;
  const at = theta => [focus[0] + .275 * (Math.cos(theta) - e), focus[1] + .245 * Math.sin(theta)];
  draw.path(dots(64, i => at(TAU * i / 64)), {closed: true, stroke: MUTED});
  const angle = anomaly(t * TAU + .27, e);
  const position = at(angle);
  draw.path(dots(20, i => at(angle - .63 * (1 - i / 19))), {stroke: CYAN});
  draw.line(focus, position, MUTED);
  draw.dot(focus, .041, {fill: AMBER});
  draw.dot(position, .022, {fill: PURPLE});
}

function geometryGrowth(draw, t) {
  function branch(from, angle, length, level, start) {
    const fraction = smooth((t - start) * (3.8 + .45 * level));
    if (!fraction) return;
    const end = [from[0] + Math.cos(angle) * length * fraction, from[1] + Math.sin(angle) * length * fraction];
    draw.line(from, end, level % 2 ? PURPLE : CYAN);
    if (level === 4) draw.dot(end, .012, {fill: AMBER, opacity: fraction});
    else {
      branch(end, angle - .61, length * .69, level + 1, start + .15);
      branch(end, angle + .52, length * .72, level + 1, start + .18);
    }
  }
  draw.line([.18, .83], [.71, .83], MUTED);
  draw.dot([.39, .81], .025, {fill: GREEN});
  branch([.39, .81], -1.2, .24, 0, 0);
}

function springMotion(draw, t) {
  const response = x => Math.exp(-3.2 * x) * Math.cos(21 * x);
  const anchor = [.15, .48];
  const position = [.58 - .19 * response(t), .48];
  const zigzag = [anchor, ...dots(20, i => {
    const p = (i + 1) / 21;
    return [mix(anchor[0], position[0], p), .48 + (i % 2 ? -.033 : .033)];
  }), position];
  draw.path(zigzag, {stroke: CYAN});
  draw.dot(anchor, .023, {fill: AMBER});
  draw.dot(position, .058, {fill: '#352858', stroke: PURPLE});
  draw.path(dots(48, i => {
    const time = i / 47;
    return [.19 + time * .63, .75 - response(time) * .082];
  }), {stroke: MUTED});
  draw.dot([.19 + t * .63, .75 - response(t) * .082], .017, {fill: GREEN});
}

function halfPlane(vertices, a, b) {
  // Squared distance difference is affine, so each polygon edge crosses at most once.
  const side = p => 2 * (p[0] * (b[0] - a[0]) + p[1] * (b[1] - a[1]))
    + a[0] ** 2 + a[1] ** 2 - b[0] ** 2 - b[1] ** 2;
  const result = [];
  for (let i = 0; i < vertices.length; i++) {
    const first = vertices[i];
    const next = vertices[(i + 1) % vertices.length];
    const d1 = side(first);
    const d2 = side(next);
    if (d1 <= 0) result.push(first);
    if ((d1 < 0 && d2 > 0) || (d1 > 0 && d2 < 0)) result.push(lerp(first, next, d1 / (d1 - d2)));
  }
  return result;
}
function voronoiStructure(draw, t) {
  const sites = [[.2, .34], [.38, .28], [.66, .29], [.26, .62], [.5, .49], [.74, .59], [.58, .73], [.33, .73]]
    .map(([x, y], i) => [x + .046 * Math.sin(t * 7 + i * 1.4), y + .055 * Math.cos(t * 6 + i)]);
  for (let i = 0; i < sites.length; i++) {
    let region = [[.13, .19], [.84, .19], [.84, .83], [.13, .83]];
    for (let j = 0; j < sites.length && region.length; j++) {
      if (i !== j) region = halfPlane(region, sites[i], sites[j]);
    }
    draw.path(region, {closed: true, stroke: i % 2 ? PURPLE : CYAN, fill: i % 2 ? '#212440' : '#102b39'});
    draw.dot(sites[i], .014, {fill: AMBER});
  }
}

function terrainFrames() {
  const frames = [];
  const side = 10;
  let surface = dots(side * side, i => elevation(i % side / side * 1.58 - .73,
    Math.floor(i / side) / side * 1.58 - .78));
  for (let step = 0; step <= 32; step++) {
    frames.push(surface);
    surface = surface.map((height, i) => {
      const col = i % side;
      const row = Math.floor(i / side);
      const adjacent = [
        col > 0 ? surface[i - 1] : height,
        col < side - 1 ? surface[i + 1] : height,
        row > 0 ? surface[i - side] : height,
        row < side - 1 ? surface[i + side] : height,
      ];
      return height + .205 * adjacent.reduce((delta, value) => delta + value - height, 0);
    });
  }
  return {side, frames};
}
const terrain = terrainFrames();
function terrainEvolution(draw, t) {
  const sample = t * (terrain.frames.length - 1);
  const stage = Math.min(terrain.frames.length - 2, Math.floor(sample));
  const point = (x, z) => {
    const index = z * terrain.side + x;
    const y = 1.6 * mix(terrain.frames[stage][index], terrain.frames[stage + 1][index], sample - stage);
    return iso(x * .17 - .85, y, z * .17 - .71);
  };
  for (let i = 0; i < terrain.side; i++) {
    draw.path(dots(terrain.side, j => point(j, i)), {stroke: i % 2 ? GREEN : CYAN});
    draw.path(dots(terrain.side, j => point(i, j)), {stroke: PURPLE, opacity: .56});
  }
}

function metaballFusion(draw, t) {
  const fieldA = [mix(.26, .48, t), .48];
  const fieldB = [mix(.75, .52, t), .56 - .08 * t];
  const strength = (x, y, center, radius) => radius * radius / (.002 + (x - center[0]) ** 2 + (y - center[1]) ** 2);
  const field = ([x, y]) => strength(x, y, fieldA, .123) + strength(x, y, fieldB, .097) - 1;
  const size = 24;
  const points = dots(size * size, index => [.11 + .78 * (index % size) / (size - 1),
    .18 + .64 * Math.floor(index / size) / (size - 1)]);
  const values = points.map(field);
  for (let row = 0; row < size - 1; row++) for (let col = 0; col < size - 1; col++) {
    const i = row * size + col;
    const corners = [i, i + 1, i + size + 1, i + size];
    const crossings = [];
    for (let side = 0; side < corners.length; side++) {
      const x = corners[side];
      const y = corners[(side + 1) % corners.length];
      if ((values[x] >= 0) !== (values[y] >= 0)) {
        crossings.push(lerp(points[x], points[y], values[x] / (values[x] - values[y])));
      }
    }
    if (crossings.length === 2) draw.line(crossings[0], crossings[1], CYAN);
    else if (crossings.length === 4) {
      const center = lerp(points[i], points[i + size + 1], .5);
      if ((field(center) >= 0) === (values[i] >= 0)) {
        draw.line(crossings[0], crossings[1], CYAN);
        draw.line(crossings[2], crossings[3], CYAN);
      } else {
        draw.line(crossings[0], crossings[3], CYAN);
        draw.line(crossings[1], crossings[2], CYAN);
      }
    }
  }
  draw.dot(fieldA, .026, {fill: PURPLE});
  draw.dot(fieldB, .017, {fill: AMBER});
}

const specs = [
  ['twin-construction', 'Twin Construction', 'بناء التوأم الرقمي', 'Stage the shell and floors from an isometric base.', construction],
  ['twin-asset-synchronization', 'Asset Synchronization', 'مزامنة الأصل', 'Move version packets to a replica and fill the received rows.', synchronize],
  ['twin-exploded-assembly', 'Exploded Assembly', 'تفكيك التجميع', 'Separate four volumes along individual assembly axes.', explodedAssembly],
  ['twin-layer-isolation', 'Layer Isolation', 'عزل الطبقات', 'Sweep a layer selector with opacity on adjacent strata.', isolateLayer],
  ['twin-blueprint-transformation', 'Blueprint Transformation', 'تحويل المخطط', 'Fold a two-dimensional plan into an isometric volume.', blueprint],
  ['twin-system-flythrough', 'System Flythrough', 'جولة داخل النظام', 'Advance a perspective eye through a sequence of sensor banks.', flythrough],
  ['twin-sensor-propagation', 'Sensor Propagation', 'انتشار إشارات الحساسات', 'Traverse a fixed graph by hop distance and persist visited nodes.', sensorPropagation],
  ['twin-terrain-reconstruction', 'Terrain Reconstruction', 'إعادة بناء التضاريس', 'Reveal cross-sections and join neighboring scans into a mesh.', reconstructTerrain],
  ['twin-asset-condition', 'Asset Condition', 'حالة الأصل', 'Advance a condition series through its alert threshold and mark the asset.', assetCondition],
  ['twin-risk-heatmap', 'Risk Heatmap', 'خريطة مخاطر حرارية', 'Interpolate two generated risk fields into a colored spatial matrix.', riskHeatmap],
  ['physics-cloth-simulation', 'Cloth Simulation', 'محاكاة القماش', 'Apply damped Verlet integration and distance constraints to a pinned wind lattice.', drawCloth],
  ['physics-soft-body', 'Soft Body', 'جسم مرن', 'Compress an elastic perimeter under area-preserving scale and damped response.', softBody],
  ['physics-rigid-collision', 'Rigid Collision', 'تصادم صلب', 'Track a pair of rigid disks through a piecewise inelastic impact.', rigidCollision],
  ['physics-fluid-surface', 'Fluid Surface', 'سطح السائل', 'Superpose two traveling wave packets in a bounded surface cross-section.', fluidSurface],
  ['physics-gravitational-orbit', 'Gravitational Orbit', 'مدار الجاذبية', 'Solve Kepler’s equation to sample a body orbiting an off-center focus.', gravityOrbit],
  ['physics-geometry-growth', 'Geometry Growth', 'نمو هندسي', 'Extend a recursive branch graph with a level-dependent growth delay.', geometryGrowth],
  ['physics-spring-motion', 'Spring Motion', 'حركة النابض', 'Sample a damped spring response, including its position-time trace.', springMotion],
  ['physics-voronoi-structure', 'Voronoi Structure', 'بنية فورونوي', 'Clip polygons by moving pairwise bisectors to reconstruct Voronoi regions.', voronoiStructure],
  ['physics-terrain-evolution', 'Terrain Evolution', 'تطور التضاريس', 'Advance a height grid by neighboring-state diffusion and draw the evolving surface.', terrainEvolution],
  ['physics-metaball-fusion', 'Metaball Fusion', 'اندماج الحقول الكروية', 'Extract isocontours of overlapping scalar fields using marching squares.', metaballFusion],
];
const samplers = new Map(specs.map(([id, ...rest]) => [id, rest.at(-1)]));
export const definitions = Object.freeze(specs.map(([id, name_en, name_ar, mechanism]) => {
  const category = id.split('-')[0];
  return Object.freeze({
    id, name_en, name_ar, mechanism, category, engine: 'canvas2d', duration_ms: 3200,
    license: 'MIT', license_file: 'motion-library/expansion/LICENSE',
    implementation_status: 'implemented-source', runtime_status: 'requires-current-source-bound-proof',
    source: Object.freeze({module: SOURCE}), reduced_motion: Object.freeze({mode: 'static-poster', progress: .55}),
    semantics: category === 'twin' ? 'Generated-data digital twin visualization.' : 'Bounded illustrative physics model.',
  });
}));

export function sampleMotion(input, progress, options = {}) {
  const id = typeof input === 'string' ? input : input?.id;
  const sampler = samplers.get(id);
  if (!sampler || !Number.isFinite(progress)) throw new RangeError('Unknown motion or invalid progress');
  const {width = 640, height = 360, intensity = 1, rtl = false, reducedMotion = false} = options;
  if (!Number.isFinite(width) || width < 120 || width > 4096 || !Number.isFinite(height) || height < 90
      || height > 4096 || !Number.isFinite(intensity) || intensity < 0 || intensity > 1
      || typeof rtl !== 'boolean' || typeof reducedMotion !== 'boolean') throw new RangeError('Invalid motion options');
  const t = reducedMotion ? .55 : mix(.5, clamp(progress), intensity);
  const draw = drawing(width, height, rtl);
  sampler(draw, t);
  return {width, height, background: BACKGROUND, primitives: draw.primitives,
    meta: {id, progress: t, engine: 'canvas2d', reducedMotion}};
}
