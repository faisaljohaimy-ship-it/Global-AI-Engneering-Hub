// Original portable scene mathematics. No browser, GPU, network or dependency required.
export const TAU = Math.PI * 2;
export const clamp = (n, a = 0, b = 1) => Math.max(a, Math.min(b, n));
export const mix = (a, b, t) => a + (b - a) * t;
export const ease = t => t * t * (3 - 2 * t);
export const pulse = (t, center = .5, width = .2) => Math.exp(-1 * ((t - center) / width) ** 2);
export const wave = (t, phase = 0) => Math.sin(TAU * (t + phase));
export const fract = value => value - Math.floor(value);
export const noise = (i, seed = 1) => fract(Math.sin(i * 127.1 + seed * 311.7) * 43758.5453);
export const range = (n, fn) => Array.from({length: n}, (_, i) => fn(i, n));
export const color = (i = 0, alpha = 1) => `rgba(${[[96, 224, 244],[161, 139, 250],[247, 195, 112],[106, 224, 170]][Math.abs(i) % 4].join(',')},${clamp(alpha)})`;
export const point = (x, y) => ({x, y});
export const circle = (x, y, r = .015, fill = color(), extra = {}) => ({type: 'circle', x, y, r, fill, ...extra});
export const line = (x1, y1, x2, y2, stroke = color(), lineWidth = .003, extra = {}) => ({type: 'line', x1, y1, x2, y2, stroke, lineWidth, ...extra});
export const rect = (x, y, width, height, fill = color(), extra = {}) => ({type: 'rect', x, y, width, height, fill, ...extra});
export const polyline = (points, stroke = color(), lineWidth = .003, extra = {}) => ({type: 'polyline', points, stroke, lineWidth, ...extra});
export const label = (x, y, text, size = .032, extra = {}) => ({type: 'text', x, y, text, size, fill: color(0), align: 'center', ...extra});
export const curve = (fn, n = 56) => range(n, (i, count) => fn(i / (count - 1)));
export const ring = (x, y, r, start = 0, sweep = TAU, extra = {}) => polyline(curve(q => point(x + r * Math.cos(start + q * sweep), y + r * Math.sin(start + q * sweep))), color(), .003, extra);
export const polygon = (x, y, r, sides = 6, rotation = 0, extra = {}) => polyline(range(sides, i => point(x + r * Math.cos(rotation + TAU * i / sides), y + r * Math.sin(rotation + TAU * i / sides))), color(), .003, {closed: true, ...extra});
export const grid = (cols = 7, rows = 5, fn = (x, y) => point(x, y)) => range(cols * rows, i => fn(.14 + .72 * (i % cols) / (cols - 1), .18 + .64 * Math.floor(i / cols) / (rows - 1), i));
export const pathSegments = points => points.slice(1).map((p, i) => line(points[i].x, points[i].y, p.x, p.y));
export const mesh = (vertices, edges, t, options = {}) => {
  const yaw = t * TAU + (options.interaction?.x || 0) * .45, pitch = .4 + (options.interaction?.y || 0) * .35;
  const cy = Math.cos(yaw), sy = Math.sin(yaw), cp = Math.cos(pitch), sp = Math.sin(pitch);
  const p = vertices.map(([x, y, z]) => {
    const ax = x * cy - z * sy, az = x * sy + z * cy, ay = y * cp - az * sp, bz = y * sp + az * cp;
    const scale = .24 / (1 + bz * .18);
    return point(.5 + ax * scale, .5 + ay * scale);
  });
  return [...edges.map(([a, b]) => line(p[a].x, p[a].y, p[b].x, p[b].y, color(1), .003)), ...p.map(v => circle(v.x, v.y, .009))];
};
export const cube = [[-1,-1,-1],[1,-1,-1],[1,1,-1],[-1,1,-1],[-1,-1,1],[1,-1,1],[1,1,1],[-1,1,1]];
export const cubeEdges = [[0,1],[1,2],[2,3],[3,0],[4,5],[5,6],[6,7],[7,4],[0,4],[1,5],[2,6],[3,7]];
export function transform(primitives, {scale = 1, dx = 0, dy = 0, angle = 0, opacity = 1} = {}) {
  const position = (x, y) => {
    const ax = (x - .5) * scale, ay = (y - .5) * scale;
    return point(.5 + ax * Math.cos(angle) - ay * Math.sin(angle) + dx, .5 + ax * Math.sin(angle) + ay * Math.cos(angle) + dy);
  };
  return primitives.map(p => {
    const item = {...p, opacity: clamp((p.opacity ?? 1) * opacity)};
    if (p.type === 'line') {const a = position(p.x1,p.y1), b = position(p.x2,p.y2); Object.assign(item,{x1:a.x,y1:a.y,x2:b.x,y2:b.y});}
    else if (p.type === 'polyline') item.points = p.points.map(v => position(v.x,v.y));
    else Object.assign(item, position(p.x,p.y));
    if (p.r !== undefined) item.r = p.r * scale;
    if (p.width !== undefined) item.width = p.width * scale;
    if (p.height !== undefined) item.height = p.height * scale;
    if (p.size !== undefined) item.size = p.size * scale;
    if (p.lineWidth !== undefined) item.lineWidth = p.lineWidth * scale;
    if (p.type === 'rect') item.rotation = (p.rotation || 0) + angle;
    return item;
  });
}
