// SPDX-License-Identifier: MIT
// Original synthetic systems visualizations for the Universal Motion SDK.
const CYAN = '#67e8f9';
const VIOLET = '#a78bfa';
const AMBER = '#fcd34d';
const GREEN = '#6ee7b7';
const TEXT = '#dbeafe';
const MUTED = '#334b6b';
const PANEL = '#142845';
const BG = '#08111f';
const TAU = Math.PI * 2;
const SOURCE = 'motion-library/expansion/nextgen-motion-systems.mjs';
const clamp = (n) => Math.max(0, Math.min(1, n));
const mix = (a, b, t) => a + (b - a) * t;
const lerp = ([x, y], [u, v], t) => [mix(x, u, t), mix(y, v, t)];
const smooth = (x) => clamp(x) ** 2 * (3 - 2 * clamp(x));
const wheel = (x, y, rx, ry, angle) => [x + rx * Math.cos(angle), y + ry * Math.sin(angle)];
const range = (n) => Array.from({length: n}, (_, i) => i);
const chain = (points) => points.slice(1).map((_, i) => [i, i + 1]);

function painter(width, height, rtl, primitives) {
  const unit = Math.min(width, height) / 380;
  const x = (u) => (rtl ? 1 - u : u) * width;
  const y = (v) => v * height;
  const point = ([u, v]) => ({x: x(u), y: y(v)});
  return {
    dot([u, v], radius, fill = CYAN, opacity = 1) {
      primitives.push({type: 'circle', x: x(u), y: y(v), r: unit * radius, fill, opacity});
    },
    ring([u, v], radius, stroke = CYAN, opacity = 1) {
      primitives.push({type: 'circle', x: x(u), y: y(v), r: unit * radius, stroke, lineWidth: 1.6 * unit, opacity});
    },
    line([u, v], [a, b], stroke = MUTED, opacity = 1, weight = 1.5) {
      primitives.push({type: 'line', x1: x(u), y1: y(v), x2: x(a), y2: y(b), stroke, opacity, lineWidth: weight * unit});
    },
    path(points, stroke = MUTED, opacity = 1, closed = false) {
      primitives.push({type: 'polyline', points: points.map(point), stroke, opacity, closed, lineWidth: 1.5 * unit});
    },
    box([u, v], w, h, fill = PANEL, stroke = MUTED, opacity = 1) {
      primitives.push({type: 'rect', x: x(u) - w * width / 2, y: y(v) - h * height / 2,
        width: w * width, height: h * height, radius: 4 * unit, fill, stroke, opacity});
    },
    label([u, v], text, fill = TEXT, size = 12) {
      primitives.push({type: 'text', x: x(u), y: y(v), text, fill, size: Math.max(1, size * unit),
        align: 'center'});
    },
  };
}

function graph(p, nodes, edges) {
  for (const [a, b] of edges) p.line(nodes[a], nodes[b]);
}

function signal(p, points, phase, color = CYAN, radius = 4) {
  const value = clamp(phase) * (points.length - 1);
  const segment = Math.min(points.length - 2, Math.floor(value));
  p.dot(lerp(points[segment], points[segment + 1], value - segment), radius, color);
}

function synapse(p, t) {
  const soma = [.68, .51];
  const terminals = [[.2,.24], [.16,.42], [.25,.66], [.35,.77]];
  let potential = 0;
  for (const [i, start] of terminals.entries()) {
    const relay = [start[0] + .23, mix(start[1], soma[1], .45)];
    const phase = clamp(t * 1.35 - i * .12);
    p.path([start, relay, soma], MUTED);
    p.dot(start, 5, VIOLET);
    p.ring(relay, 7, VIOLET, .75);
    signal(p, [start, relay, soma], phase, CYAN);
    potential += smooth((phase - .48) * 1.95);
  }
  p.ring(soma, 25 + potential * 9, CYAN, .65);
  p.dot(soma, 9 + potential * 2, potential >= 2 ? GREEN : CYAN);
  const output = [.87, .57];
  p.line(soma, output, potential >= 2 ? GREEN : MUTED);
  p.dot(lerp(soma, output, clamp((potential - 2) / 2)), 4, AMBER);
}

function propagation(p, t) {
  const layers = [[[.12,.43]], [[.31,.28],[.31,.66]], [[.55,.2],[.55,.49],[.55,.75]], [[.83,.37],[.83,.63]]];
  for (let level = 0; level < layers.length - 1; level++) {
    for (const [i, a] of layers[level].entries()) {
      for (const [j, b] of layers[level + 1].entries()) {
        if ((i + j + level) % 3 === 2) continue;
        p.line(a, b, MUTED, .75);
        const progress = t * 3.5 - level - i * .12 - j * .13;
        if (progress >= 0 && progress <= 1) p.dot(lerp(a, b, progress), 5, CYAN);
        else if (progress > 1) p.line(a, b, VIOLET, .7);
      }
    }
  }
  for (const [i, layer] of layers.entries()) {
    for (const node of layer) p.dot(node, 7 + 3 * Math.sin(Math.PI * clamp(t * 4 - i)), CYAN, .8);
  }
}

function thoughtFlow(p, t) {
  const start = [.13,.56], end = [.87,.5];
  const scores = [];
  for (let path = 0; path < 4; path++) {
    const score = (.4 + .6 * Math.sin((t * 1.2 + .13 + path * .14) * Math.PI) ** 2);
    scores.push(score);
    const route = range(18).map((i) => {
      const u = i / 17;
      return [mix(start[0], end[0], u), mix(start[1], end[1], u) + Math.sin(Math.PI * u) * (.15 * path - .26)];
    });
    p.path(route, path === 1 ? CYAN : VIOLET, score);
    signal(p, route, (t * .84 + path * .17) % 1, path === 1 ? AMBER : VIOLET, 4 + score * 3);
    p.box([.36 + path * .1, .83], .072, .023 + score * .055, PANEL, VIOLET, score);
  }
  p.dot(start, 9, GREEN);
  p.ring(end, 10 + 5 * scores[1], GREEN);
}

function messages(p, t) {
  const nodes = [[.17,.3],[.54,.18],[.81,.48],[.43,.75]];
  const links = [[0,1],[1,2],[2,3],[3,0],[1,3]];
  graph(p, nodes, links);
  for (const [i, [a, b]] of links.entries()) {
    const phase = (t * 1.2 + i * .17) % 1;
    const progress = phase < .5 ? phase * 2 : (1 - phase) * 2;
    const color = phase < .5 ? CYAN : AMBER;
    p.box(lerp(nodes[a], nodes[b], progress), .027, .027, color, color);
  }
  for (const [i, point] of nodes.entries()) {
    p.box(point, .145, .095, PANEL, i === 0 ? GREEN : VIOLET);
    p.label(point, ['PLAN','BUILD','TEST','REVIEW'][i], TEXT, 11);
  }
}

function networkGrowth(p, t) {
  const nodes = [[.26,.55],[.49,.46],[.6,.63],[.42,.25],[.7,.34],[.8,.57],[.56,.78],[.22,.32]];
  const parents = [0,0,1,1,3,4,2,0];
  p.dot(nodes[0], 9, GREEN);
  p.ring(nodes[0], 13 + 8 * t, GREEN, .65);
  for (let i = 1; i < nodes.length; i++) {
    const begin = nodes[parents[i]];
    const visible = smooth((t * 1.4 + .13 - i * .115) * 2);
    if (!visible) continue;
    const tip = lerp(begin, nodes[i], visible);
    p.line(begin, tip, CYAN, .6 + visible * .4);
    p.dot(tip, 3 + visible * 6, VIOLET);
    if (visible === 1) p.ring(tip, 15 + 5 * Math.sin(t * TAU + i), CYAN, .38);
  }
}

function decisionTree(p, t) {
  const nodes = [[.46,.18],[.25,.43],[.69,.43],[.14,.75],[.36,.75],[.57,.75],[.82,.75]];
  const edges = [[0,1],[0,2],[1,3],[1,4],[2,5],[2,6]];
  const score = .11 + .78 * t;
  const middle = score >= .5 ? 2 : 1;
  const leaf = middle * 2 + (Math.cos(t * TAU) > 0 ? 1 : 2);
  graph(p, nodes, edges);
  p.line(nodes[0], nodes[middle], CYAN, .9, 3);
  p.line(nodes[middle], nodes[leaf], GREEN, .9, 3);
  signal(p, [nodes[0], nodes[middle], nodes[leaf]], t, AMBER, 6);
  for (const [i, node] of nodes.entries()) {
    p.box(node, .095, .078, PANEL, i === leaf ? GREEN : MUTED);
    p.label(node, ['RULE','LOW','HIGH','A','B','C','D'][i], TEXT, 10);
  }
  p.box([.15 + .33 * score, .89], .22 * score, .025, CYAN, CYAN);
}

function orchestration(p, t) {
  const tasks = [[0,.23],[.24,.31],[.24,.44],[.45,.66],[.69,.96]];
  const prerequisites = [[],[0],[0],[1,2],[3]];
  const x = (v) => .23 + v * .62;
  const y = (i) => .23 + .133 * i;
  for (let i = 0; i < tasks.length; i++) {
    const [start, end] = tasks[i];
    const current = Math.max(start, Math.min(t, end));
    const completed = Math.max(0, current - start);
    const ready = prerequisites[i].every(parent => t >= tasks[parent][1]);
    p.label([.125,y(i)], ['INTAKE','DESIGN','AUDIT','TEST','REVIEW'][i], TEXT, 10);
    p.box([x((start + end) / 2), y(i)], (end - start) * .62, .06, PANEL, ready ? VIOLET : MUTED);
    if (completed > 0) p.box([x(start + completed / 2), y(i)], completed * .62, .045, t >= end ? GREEN : CYAN);
  }
  p.line([x(t),.146],[x(t),.83],AMBER,.85,2);
  p.dot([x(t),.15],5,AMBER);
}

function inference(p, t) {
  const stage = [[.15,.55],[.38,.55],[.61,.55],[.84,.55]];
  graph(p, stage, chain(stage));
  for (const [i, pos] of stage.entries()) {
    p.box(pos, .15, .22, PANEL, i === Math.min(3, Math.floor(t * 4)) ? CYAN : MUTED);
    p.label([pos[0],.73], ['TOKENS','VECTOR','MIX','RESULT'][i], TEXT, 10);
    for (let token = 0; token < 4 - i; token++) {
      const phase = Math.sin(Math.PI * clamp(t * 4 - i));
      p.box([pos[0],.485 + .043 * token], .04 + .016 * (token + i) + .022 * phase,
            .022, i === 3 ? GREEN : VIOLET, MUTED);
    }
  }
  signal(p, stage, t, AMBER, 5);
}

function attention(p, t) {
  const active = Math.min(3, Math.floor(t * 4));
  const keys = [[.7,.1,-.4],[-.2,.8,.2],[-.6,-.2,.9],[.3,-.7,.2]];
  for (let row = 0; row < 4; row++) {
    const query = [.65 + .3*t, Math.sin(row * .9 + t*3), Math.cos(t*4 - row)];
    const exp = keys.map(key => Math.exp(key.reduce((product, value, i) => product + value * query[i], 0)));
    const total = exp.reduce((a, b) => a + b, 0);
    const weights = exp.map((v) => v / total);
    for (const [col, weight] of weights.entries()) {
      const u = .24 + col * .133, v = .29 + row * .115;
      const color = row === active ? CYAN : VIOLET;
      p.box([u,v], .112, .094, PANEL, MUTED);
      p.box([u,v], .1 * weight ** .38, .08 * weight ** .38, color, color, .5 + weight * .5);
    }
    p.box([.82,.29 + row * .115], .027 + .145 * Math.max(...weights), .043, row === active ? GREEN : MUTED);
  }
  p.label([.47,.17], 'ILLUSTRATIVE ATTENTION', TEXT, 12);
}

const vectors = [[-.72,-.25,.18],[-.47,.15,.45],[-.44,-.37,-.1],[-.29,.4,-.43],
  [.34,-.35,.56],[.46,.29,-.31],[.71,-.17,-.43],[.56,.2,.37],[.04,.61,.47]];

function project([x, y, z], angle, {cx = .5, cy = .51, sx = .39, sy = .31, tilt = .24} = {}) {
  const u = x * Math.cos(angle) - z * Math.sin(angle);
  const depth = x * Math.sin(angle) + z * Math.cos(angle);
  const perspective = 1 / (1.4 + depth * .35);
  return [cx + u * perspective * sx, cy - (y + tilt * depth) * perspective * sy, depth];
}

function embeddings(p, t) {
  const query = [mix(-.5,.48,t), .1 * Math.sin(t * TAU), mix(.35,-.2,t)];
  const angle = -.33 + t * 1.3;
  const center = project(query, angle);
  const nodes = vectors.map((vector, i) => ({
    point: project(vector, angle), i, distance: Math.hypot(...vector.map((v, j) => v - query[j])),
  }));
  const nearest = [...nodes].sort((a,b) => a.distance - b.distance).slice(0,3);
  for (const a of nearest) p.line(center, a.point, GREEN, .85, 2);
  for (const {point,i} of nodes.sort((a,b) => b.point[2]-a.point[2])) {
    p.dot(point, 6.5 - point[2] * 2.7, i < 4 ? CYAN : VIOLET);
  }
  p.ring(center, 16, AMBER);
  p.dot(center, 5, AMBER);
  p.label([.5,.8], 'NEAREST THREE', TEXT, 11);
}

function spatialNetwork(p, t) {
  const nodes = range(8).map((i) => [i & 1 ? .65 : -.65, i & 2 ? .65 : -.65, i & 4 ? .65 : -.65]);
  const projected = nodes.map((node) => project(node, t * 2.2 + .23, {cx:.47,sx:.44,sy:.35}));
  for (let i = 0; i < nodes.length; i++) {
    for (const mask of [1,2,4]) {
      const neighbor = i ^ mask;
      if (neighbor > i) p.line(projected[i], projected[neighbor], projected[i][2] > 0 ? MUTED : VIOLET, .8, 2);
    }
  }
  for (const point of [...projected].sort((a,b) => b[2] - a[2])) p.dot(point, 8 - point[2] * 3, CYAN);
  p.dot(project([.9, .4, -.35], t * 2.2 + .23, {cx:.47,sx:.44,sy:.35}), 6, AMBER);
}

function transmission(p, t) {
  const switches = [[.14,.36],[.34,.36],[.54,.59],[.79,.59],[.88,.39]];
  graph(p, switches, chain(switches));
  for (let n = 0; n < 6; n++) signal(p, switches, (t * 1.15 + n / 6) % 1, n % 2 ? CYAN : VIOLET, 5);
  for (const [i, node] of switches.entries()) p.box(node,.071,.071,PANEL,i === 2 ? AMBER : CYAN);
  const queue = Math.round(2 + 2 * Math.sin((t + .08) * TAU));
  for (let i=0;i<4;i++) p.box([.43 + i * .064,.77],.045,.052,i < queue ? AMBER : PANEL,MUTED);
  p.label([.523,.85], 'BUFFER', TEXT, 11);
}

function reconfiguration(p, t) {
  const duration = smooth((t - .22) * 1.8);
  const origin = range(7).map((i) => wheel(.47,.51,.32,.3,i * TAU/7+.2));
  const destination = [[.47,.51],[.73,.27],[.81,.55],[.66,.78],[.35,.76],[.18,.54],[.25,.22]];
  const nodes = origin.map((point,i) => lerp(point,destination[i],duration));
  for (const [i, point] of nodes.entries()) {
    if (duration < 1) p.line(point,nodes[(i+1)%7],VIOLET,1-duration,2);
    if (i > 0) p.line(nodes[0],lerp(nodes[0],point,duration),CYAN,.2+.8*duration,2);
    p.dot(point,6 + (i === 0 ? duration * 6 : 0),i === 0 ? AMBER : CYAN);
  }
  p.ring(nodes[0],18+7*Math.sin(t*Math.PI),AMBER,.5);
}

const continents = [
  [[.13,.32],[.22,.27],[.31,.32],[.27,.39],[.22,.42],[.27,.5],[.19,.45],[.13,.32]],
  [[.28,.5],[.37,.55],[.37,.64],[.31,.75],[.27,.61],[.28,.5]],
  [[.43,.38],[.47,.3],[.55,.25],[.63,.31],[.72,.27],[.88,.33],[.83,.43],[.73,.48],[.62,.44],[.54,.52],[.43,.38]],
  [[.46,.46],[.56,.48],[.57,.61],[.5,.73],[.45,.56],[.46,.46]],
  [[.72,.63],[.78,.58],[.86,.65],[.87,.72],[.75,.72],[.72,.63]],
];

function geographic(p, t) {
  for (const shape of continents) p.path(shape, VIOLET, .55, true);
  const points = [[.206,.37],[.51,.32],[.769,.375],[.789,.66]];
  const links = [[0,1],[0,2],[1,3]];
  for (const [i,[a,b]] of links.entries()) {
    const arc = range(22).map((k) => {
      const phase = k / 21;
      const base = lerp(points[a],points[b],phase);
      return [base[0],base[1] - (.11 + i * .014) * Math.sin(Math.PI * phase)];
    });
    p.path(arc,CYAN,.65);
    signal(p,arc,(t+.21*i)%1,AMBER,5);
  }
  for (const node of points) { p.ring(node,11,CYAN,.66); p.dot(node,5,GREEN); }
}

function relationships(p, t) {
  const groups = [[[.23,.31],[.23,.49],[.23,.67]],[[.73,.22],[.73,.4],[.73,.58],[.73,.76]]];
  const links = [[0,0,.9],[0,2,.4],[1,1,.7],[1,3,.45],[2,1,.28],[2,3,.86]];
  for (const [index,[left,right,weight]] of links.entries()) {
    const a = groups[0][left], b = groups[1][right];
    const strength = .25 + .75 * Math.cos((t + .13 * index) * Math.PI) ** 2;
    const points = range(21).map(k => {
      const u = k / 20;
      return [mix(a[0],b[0],u),mix(a[1],b[1],smooth(u))];
    });
    p.path(points, weight > .5 ? CYAN : VIOLET, strength);
    p.dot(points[8+index],4+6*strength*weight,weight > .5 ? CYAN : VIOLET,strength);
  }
  for (const [i,group] of groups.entries()) {
    for (const node of group) p.box(node,.12,.055,PANEL,i ? CYAN : VIOLET);
  }
}

function constellation(p, t) {
  const groups = [[.3,.31],[.7,.37],[.55,.71]];
  const spread = smooth(t);
  const leads = groups.map((point) => lerp(point,[.51,.48],spread * .42));
  graph(p,leads,[[0,1],[1,2],[2,0]]);
  for (const [i,center] of leads.entries()) {
    p.ring(center,23+12*spread,i===1?VIOLET:CYAN,.45);
    for (let j=0;j<5;j++) {
      const peer = wheel(center[0],center[1],.115,.09,t * (i+1) + j*TAU/5);
      p.line(center,peer,MUTED);
      p.dot(peer,4.5,i===1?VIOLET:CYAN);
    }
    p.dot(center,9,GREEN);
  }
  signal(p,[...leads,leads[0]],t,AMBER,5);
}

function dependency(p, t) {
  const nodes = [[.15,.34],[.38,.25],[.38,.56],[.62,.39],[.84,.42],[.64,.73]];
  const edges = [[0,1],[0,2],[1,3],[2,3],[2,5],[3,4],[5,4]];
  const begins = [0,.16,.16,.42,.72,.42];
  graph(p,nodes,edges);
  for (const [a,b] of edges) {
    const active = smooth((t-begins[b]) * 4);
    if (active) p.line(nodes[a],lerp(nodes[a],nodes[b],active),CYAN,.8,2);
  }
  for (const [i,node] of nodes.entries()) {
    const done = t >= begins[i]+.2;
    p.box(node,.132,.083,PANEL,done?GREEN:t>=begins[i]?CYAN:MUTED);
    p.label(node,['BASE','CORE','DATA','API','PAGE','CACHE'][i],TEXT,10);
  }
  p.box([.17 + .33*t,.89],.1+.48*t,.028,CYAN,CYAN);
}

function hierarchy(p, t) {
  const center = [.43,.24];
  p.dot(center,11,GREEN);
  for (let branch=0;branch<3;branch++) {
    const hub = [.19 + branch*.29,.48];
    const open = smooth((t+.1-branch*.08)*1.33);
    const tip = lerp(center,hub,open);
    p.line(center,tip,VIOLET,.85,2);
    p.dot(tip,7+open*2,CYAN);
    for (let leaf=0;leaf<3;leaf++) {
      const start = [.19 + branch*.29 + (leaf-1)*.078,.79];
      const growth = smooth((t - .14 - leaf*.085 - branch*.07) * 1.7);
      if (growth <= 0) continue;
      const endpoint = lerp(tip,start,growth);
      p.line(tip,endpoint,MUTED);
      p.dot(endpoint,4+growth*3,AMBER);
    }
  }
  p.ring(center,17+9*t,GREEN,.65);
}

function distributed(p, t) {
  const coordinator=[.2,.48], peers=[[.68,.22],[.79,.47],[.64,.74]];
  const acks = [];
  for (const [i,peer] of peers.entries()) {
    const duration = 1.2 - i*.21;
    const round = clamp(.08 + t * duration);
    p.line(coordinator,peer,MUTED);
    p.box(peer,.13,.095,PANEL,round >= .58 ? GREEN : VIOLET);
    p.label(peer,`R${i+1}`,TEXT,11);
    const ack = round >= .58;
    if (round >= .8) acks.push(i);
    p.dot(lerp(coordinator,peer,ack ? 1-clamp((round-.58)/.22) : round/.58),5,ack?GREEN:CYAN);
  }
  p.ring(coordinator,21+10*t,acks.length>=2?GREEN:AMBER,.9);
  p.dot(coordinator,8,CYAN);
  p.label([.245,.78],`ACK ${acks.length}/3`,TEXT,13);
}

const gridSize = 6;
const unavailable = new Set([7,8,9,15,21]);
const grid = range(gridSize * gridSize).map(i => [.15+(i%gridSize)*.133, .22+Math.floor(i/gridSize)*.114]);

function route(start, target) {
  const visited = new Map([[start,null]]);
  const queue = [start];
  for (let head = 0; head < queue.length && !visited.has(target); head++) {
    const id = queue[head], x = id%gridSize, y = Math.floor(id/gridSize);
    const neighbors = [[x+1,y],[x,y+1],[x-1,y],[x,y-1]]
      .filter(([u,v]) => u>=0&&u<gridSize&&v>=0&&v<gridSize)
      .map(([u,v]) => v*gridSize+u);
    for (const next of neighbors) {
      if (unavailable.has(next)||visited.has(next)) continue;
      visited.set(next,id);
      queue.push(next);
    }
  }
  const path = [];
  for (let node=target;node!=null;node=visited.get(node)) path.push(node);
  return path.reverse();
}

const routingPath = route(0,29);
function routing(p, t) {
  for (const [i,node] of grid.entries()) {
    if (unavailable.has(i)) {
      p.box(node,.062,.058,PANEL,AMBER,.75);
      continue;
    }
    if (i%gridSize < gridSize-1 && !unavailable.has(i+1)) p.line(node,grid[i+1],MUTED,.65);
    if (i+gridSize < grid.length && !unavailable.has(i+gridSize)) p.line(node,grid[i+gridSize],MUTED,.65);
    p.dot(node,3,VIOLET);
  }
  const points = routingPath.map(i=>grid[i]);
  p.path(points,CYAN,.7);
  signal(p,points,t,GREEN,8);
  p.ring(points[0],13,AMBER);
  p.ring(points.at(-1),15+6*t,GREEN);
}

const originals = [
  ['neural-synapse-activation','Neural Synapse Activation','تنشيط المشابك العصبية','Multiple presynaptic pulses accumulate until an illustrative threshold fires.',synapse],
  ['neural-signal-propagation','Neural Signal Propagation','انتشار الإشارة العصبية','A wave traverses scheduled hops through a layered directed graph.',propagation],
  ['neural-thought-flow','AI Thought Flow Visualization','تصوير تدفق الأفكار','Parallel candidate paths carry changing synthetic scores and converge on an output.',thoughtFlow],
  ['neural-multi-agent-communication','Multi-Agent Communication','اتصالات الوكلاء المتعددين','Independent message tokens move between request and reply directions.',messages],
  ['neural-network-growth','Neural Network Growth','نمو الشبكة العصبية','Child connections sprout from established branch points in dependency order.',networkGrowth],
  ['neural-decision-tree','AI Decision Tree Animation','حركة شجرة القرار','A changing scalar selects and traverses a branch and leaf.',decisionTree],
  ['neural-task-orchestration','Agent Task Orchestration','تنسيق مهام الوكلاء','A playback cursor reveals overlapping task schedules and completion bars.',orchestration],
  ['neural-inference-pipeline','AI Inference Pipeline','خط أنابيب الاستدلال','Illustrative tokens transform across four explicitly marked stages.',inference],
  ['neural-attention-matrix','Attention Matrix Visualization','تصوير مصفوفة الانتباه','An active row and softmax weights change over synthetic dot-product scores.',attention],
  ['neural-embedding-space','Embedding Space Exploration','استكشاف فضاء التضمين','The nearest vectors to a moving query are recomputed before projection.',embeddings],
  ['networks-node-network-3d','Three-dimensional Node Network','شبكة عقد ثلاثية الأبعاد','Perspective projects explicit cube connectivity with depth-sorted nodes.',spatialNetwork],
  ['networks-data-transmission','Data Transmission Through Nodes','إرسال البيانات عبر العقد','A packet train moves hop by hop past a changing buffer indicator.',transmission],
  ['networks-reconfiguration','Dynamic Network Reconfiguration','إعادة تشكيل الشبكة ديناميكيًا','Old ring links fade as a hub forms and new spoke endpoints connect.',reconfiguration],
  ['networks-geographic-connection','Geographic Network Connection','ربط الشبكات جغرافيًا','Packets trace curved links between locations on a schematic world map.',geographic],
  ['networks-relationship-mapping','Spatial Relationship Mapping','رسم العلاقات المكانية','Weighted relations move between two partitions along monotonic curves.',relationships],
  ['networks-agent-constellation','Agent Collaboration Constellation','كوكبة تعاون الوكلاء','Rotating clusters converge through leads connected by a collaboration cycle.',constellation],
  ['networks-dependency-animation','Infrastructure Dependency Animation','حركة تبعيات البنية التحتية','Activation follows prerequisite order through an infrastructure graph.',dependency],
  ['networks-hierarchical-expansion','Hierarchical Network Expansion','تمدد الشبكة الهرمية','Branches unfold into independent child groups and expose new leaves.',hierarchy],
  ['networks-distributed-system','Distributed System Visualization','تصوير النظام الموزع','Replica responses converge and display a two-of-three acknowledgement threshold.',distributed],
  ['networks-signal-routing','Network Signal Routing','توجيه الإشارات في الشبكة','Breadth-first routing avoids blocked grid tiles and moves a packet along the chosen path.',routing],
];

const renderers = new Map(originals.map(([id, , , , render]) => [id, render]));
export const definitions = Object.freeze(originals.map(([id,name_en,name_ar,mechanism]) => Object.freeze({
  id, name_en, name_ar, mechanism, engine:'canvas2d', duration_ms:3600,
  license:'MIT', license_file:'motion-library/expansion/LICENSE',
  implementation_status:'implemented-source', runtime_status:'requires-current-source-bound-proof',
  source:Object.freeze({module:SOURCE}),
  reduced_motion:Object.freeze({mode:'static-poster',progress:.55}),
  mobile:Object.freeze({requires_real_device_verification:true}),
  semantics:'Fixed illustrative data and geometry. This visualization has no live model or network connection.',
})));

const within = (value, lower, upper) => typeof value === 'number' && Number.isFinite(value)
  && value >= lower && value <= upper;

export function sampleMotion(value, progress, options = {}) {
  const id = typeof value === 'string' ? value : value?.id;
  const render = renderers.get(id);
  if (!render || !within(progress,-1e7,1e7)) throw new RangeError('Unknown system motion or invalid progress');
  const {width=640,height=360,intensity=1,rtl=false,reducedMotion=false} = options;
  if (!within(width,120,4096) || !within(height,90,4096) || !within(intensity,0,1)
      || typeof rtl !== 'boolean' || typeof reducedMotion !== 'boolean') {
    throw new RangeError('Invalid system motion options');
  }
  const time = reducedMotion ? .55 : clamp(progress);
  const primitives = [];
  render(painter(width,height,rtl,primitives), mix(.5,time,intensity));
  return {width,height,background:BG,primitives,meta:{id,progress:time,engine:'canvas2d',reducedMotion}};
}
