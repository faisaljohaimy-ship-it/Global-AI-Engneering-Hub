// WebGPU engine helpers: WGSL compute and render pipelines behind the same contract as
// every other engine. A motion built on them must give `fallback` in its definition
// (usually the WebGL2 version of the same formula), because WebGPU is not everywhere.

/** WGSL every shader receives. Colours are the palette: color0 is the background. */
export const FRAME = `
struct Frame {
  resolution: vec2f,   // drawing buffer size in pixels
  time: f32,           // seconds since the start
  progress: f32,       // eased 0..1 (loop: position in the loop)
  raw: f32,            // linear 0..1
  intro: f32,          // eased 0..1 over the first 600 ms
  dir: f32,            // 1 left-to-right, -1 right-to-left
  quality: f32,        // 1 low, 2 medium, 3 high
  count: f32,          // particle count at this quality
  color0: vec4f,
  color1: vec4f,
  color2: vec4f,
  color3: vec4f,
  color4: vec4f,
  params: array<vec4f, 2>,   // the motion's own values, in the order it returns them
};
fn hash11(n: f32) -> f32 { var p = fract(n * 0.1031); p = p * (p + 33.33); p = p * (p + p); return fract(p); }
fn hash31(n: f32) -> vec3f {
  var q = fract(vec3f(n) * vec3f(0.1031, 0.1030, 0.0973));
  q = q + dot(q, q.yzx + 33.33);
  return fract((q.xxy + q.yzz) * q.zyx);
}
`;
const FLOATS = 40;

function writeFrame(target, ctx, state, canvas, count, extra) {
  target.fill(0);
  target.set([canvas.width, canvas.height, state.t, state.progress, state.raw, state.intro, ctx.dir, ctx.quality.level, count], 0);
  for (let index = 0; index < 5; index += 1) {
    const colour = ctx.colors[index] ?? ctx.colors[ctx.colors.length - 1];
    target.set([colour[0], colour[1], colour[2], 1], 12 + index * 4);
  }
  if (extra) target.set(extra.slice(0, 8), 32);
}

/**
 * Particles whose positions are computed on the GPU by a WGSL compute shader, then drawn
 * as soft sprites. `simulate` is WGSL defining
 *   fn simulate(id: u32, f: Frame) -> Particle
 * where Particle { position: vec2f (clip space, y up), size: f32 (pixels), color: vec4f }.
 * It must depend only on the id and the frame values, so that any frame can be drawn on demand.
 * `values(ctx, state)` returns up to eight numbers, read in WGSL as f.params[0].x ... f.params[1].w.
 */
export function computeParticles({ count, simulate, values }) {
  const compute = `${FRAME}
struct Particle { position: vec2f, size: f32, color: vec4f };
@group(0) @binding(0) var<uniform> frame: Frame;
@group(0) @binding(1) var<storage, read_write> particles: array<Particle>;
${simulate}
@compute @workgroup_size(64)
fn main(@builtin(global_invocation_id) cell: vec3u) {
  if (cell.x >= u32(frame.count)) { return; }
  particles[cell.x] = simulate(cell.x, frame);
}`;
  const draw = `${FRAME}
struct Particle { position: vec2f, size: f32, color: vec4f };
@group(0) @binding(0) var<uniform> frame: Frame;
@group(0) @binding(1) var<storage, read> particles: array<Particle>;
struct Sprite { @builtin(position) position: vec4f, @location(0) corner: vec2f, @location(1) color: vec4f };
@vertex
fn vertex(@builtin(vertex_index) index: u32, @builtin(instance_index) instance: u32) -> Sprite {
  var corners = array<vec2f, 6>(vec2f(-1.0, -1.0), vec2f(1.0, -1.0), vec2f(-1.0, 1.0), vec2f(-1.0, 1.0), vec2f(1.0, -1.0), vec2f(1.0, 1.0));
  let particle = particles[instance];
  let corner = corners[index];
  var sprite: Sprite;
  sprite.position = vec4f(particle.position + corner * particle.size / frame.resolution, 0.0, 1.0);
  sprite.corner = corner;
  sprite.color = particle.color;
  return sprite;
}
@fragment
fn fragment(sprite: Sprite) -> @location(0) vec4f {
  let falloff = smoothstep(1.0, 0.0, length(sprite.corner));
  return vec4f(sprite.color.rgb, sprite.color.a * falloff);
}`;
  return async function setup(ctx) {
    const gpu = await ctx.surface.webgpu({ readback: ctx.gpu === 'readback' });
    const { canvas, device, format } = gpu;
    const total = ctx.count(count, 64);
    const uniforms = device.createBuffer({ size: FLOATS * 4, usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST });
    const storage = device.createBuffer({ size: total * 32, usage: GPUBufferUsage.STORAGE });
    const computeModule = device.createShaderModule({ code: compute });
    const drawModule = device.createShaderModule({ code: draw });
    for (const module of [computeModule, drawModule]) {
      const report = await module.getCompilationInfo();
      const errors = report.messages.filter((message) => message.type === 'error');
      if (errors.length) throw new Error(`WGSL did not compile: ${errors.map((message) => `${message.lineNum}: ${message.message}`).join('; ')}`);
    }
    const computePipeline = await device.createComputePipelineAsync({ layout: 'auto', compute: { module: computeModule, entryPoint: 'main' } });
    const drawPipeline = await device.createRenderPipelineAsync({
      layout: 'auto',
      vertex: { module: drawModule, entryPoint: 'vertex' },
      fragment: {
        module: drawModule, entryPoint: 'fragment',
        targets: [{ format, blend: { color: { srcFactor: 'src-alpha', dstFactor: 'one' }, alpha: { srcFactor: 'one', dstFactor: 'one' } } }],
      },
      primitive: { topology: 'triangle-list' },
    });
    const bind = (pipeline) => device.createBindGroup({
      layout: pipeline.getBindGroupLayout(0),
      entries: [{ binding: 0, resource: { buffer: uniforms } }, { binding: 1, resource: { buffer: storage } }],
    });
    const computeGroup = bind(computePipeline);
    const drawGroup = bind(drawPipeline);
    const data = new Float32Array(FLOATS);
    const [r, g, b] = ctx.colors[0];
    return {
      render(state) {
        const extra = values ? values(ctx, state) : null;
        gpu.frame((encoder, view) => {
          writeFrame(data, ctx, state, canvas, total, extra);
          device.queue.writeBuffer(uniforms, 0, data);
          const simulation = encoder.beginComputePass();
          simulation.setPipeline(computePipeline);
          simulation.setBindGroup(0, computeGroup);
          simulation.dispatchWorkgroups(Math.ceil(total / 64));
          simulation.end();
          const pass = encoder.beginRenderPass({ colorAttachments: [{ view, clearValue: { r, g, b, a: 1 }, loadOp: 'clear', storeOp: 'store' }] });
          pass.setPipeline(drawPipeline);
          pass.setBindGroup(0, drawGroup);
          pass.draw(6, total);
          pass.end();
        });
      },
      settled: gpu.settled,
      lost: gpu.lost,
      info: () => ({ gpu: 'webgpu', present: gpu.present, particles: total, compute: true }),
    };
  };
}

/**
 * A motion that is one WGSL fragment shader over the whole frame. `shade` is WGSL defining
 *   fn shade(pixel: vec2f, f: Frame) -> vec3f      // pixel: x right, y up, in drawing-buffer pixels
 */
export function wgslFragment({ shade, values }) {
  const code = `${FRAME}
@group(0) @binding(0) var<uniform> frame: Frame;
${shade}
@vertex
fn vertex(@builtin(vertex_index) index: u32) -> @builtin(position) vec4f {
  let p = vec2f(f32((index << 1u) & 2u), f32(index & 2u));
  return vec4f(p * 2.0 - 1.0, 0.0, 1.0);
}
@fragment
fn fragment(@builtin(position) at: vec4f) -> @location(0) vec4f {
  return vec4f(shade(vec2f(at.x, frame.resolution.y - at.y), frame), 1.0);
}`;
  return async function setup(ctx) {
    const gpu = await ctx.surface.webgpu({ readback: ctx.gpu === 'readback' });
    const { canvas, device, format } = gpu;
    const module = device.createShaderModule({ code });
    const errors = (await module.getCompilationInfo()).messages.filter((message) => message.type === 'error');
    if (errors.length) throw new Error(`WGSL did not compile: ${errors.map((message) => `${message.lineNum}: ${message.message}`).join('; ')}`);
    const pipeline = await device.createRenderPipelineAsync({
      layout: 'auto',
      vertex: { module, entryPoint: 'vertex' },
      fragment: { module, entryPoint: 'fragment', targets: [{ format }] },
      primitive: { topology: 'triangle-list' },
    });
    const uniforms = device.createBuffer({ size: FLOATS * 4, usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST });
    const group = device.createBindGroup({ layout: pipeline.getBindGroupLayout(0), entries: [{ binding: 0, resource: { buffer: uniforms } }] });
    const data = new Float32Array(FLOATS);
    return {
      render(state) {
        const extra = values ? values(ctx, state) : null;
        gpu.frame((encoder, view) => {
          writeFrame(data, ctx, state, canvas, 0, extra);
          device.queue.writeBuffer(uniforms, 0, data);
          const pass = encoder.beginRenderPass({ colorAttachments: [{ view, clearValue: { r: 0, g: 0, b: 0, a: 1 }, loadOp: 'clear', storeOp: 'store' }] });
          pass.setPipeline(pipeline);
          pass.setBindGroup(0, group);
          pass.draw(3);
          pass.end();
        });
      },
      settled: gpu.settled,
      lost: gpu.lost,
      info: () => ({ gpu: 'webgpu', present: gpu.present, shader: 'wgsl-fragment' }),
    };
  };
}
