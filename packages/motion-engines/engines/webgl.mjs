// WebGL2 engine helpers. No geometry buffers are needed: a full-screen triangle and
// point clouds are both derived from gl_VertexID, so a motion is only its shader.
import { Unsupported } from '../core/define.mjs';

const TRIANGLE = `#version 300 es
void main() {
  vec2 p = vec2(float((gl_VertexID << 1) & 2), float(gl_VertexID & 2));
  gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}`;

/** Uniforms every shader receives. Colours are the motion's palette: u_color0 is the background. */
export const UNIFORMS = `
uniform vec2 u_resolution;   // drawing buffer size in pixels
uniform float u_time;        // seconds since the start
uniform float u_progress;    // eased 0..1 (loop: position in the loop)
uniform float u_raw;         // linear 0..1
uniform float u_intro;       // eased 0..1 over the first 600 ms
uniform float u_dir;         // 1 for left-to-right, -1 for right-to-left
uniform int u_quality;       // 1 low, 2 medium, 3 high
uniform vec3 u_color0;
uniform vec3 u_color1;
uniform vec3 u_color2;
uniform vec3 u_color3;
uniform vec3 u_color4;
`;

function compile(gl, type, source) {
  const shader = gl.createShader(type);
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    const log = gl.getShaderInfoLog(shader);
    gl.deleteShader(shader);
    throw new Error(`Shader did not compile: ${log}`);
  }
  return shader;
}

export function program(gl, vertex, fragment) {
  const handle = gl.createProgram();
  gl.attachShader(handle, compile(gl, gl.VERTEX_SHADER, vertex));
  gl.attachShader(handle, compile(gl, gl.FRAGMENT_SHADER, fragment));
  gl.linkProgram(handle);
  if (!gl.getProgramParameter(handle, gl.LINK_STATUS)) throw new Error(`Program did not link: ${gl.getProgramInfoLog(handle)}`);
  const locations = new Map();
  const locate = (name) => {
    if (!locations.has(name)) locations.set(name, gl.getUniformLocation(handle, name));
    return locations.get(name);
  };
  return {
    handle,
    /** Set uniforms from a plain object: numbers, or arrays of 2, 3 or 4 numbers. */
    set(values) {
      for (const [name, value] of Object.entries(values)) {
        const location = locate(name);
        if (location === null) continue;
        if (typeof value === 'number') gl.uniform1f(location, value);
        else if (value.length === 2) gl.uniform2fv(location, value);
        else if (value.length === 3) gl.uniform3fv(location, value);
        else gl.uniform4fv(location, value);
      }
    },
    setInt(name, value) {
      const location = locate(name);
      if (location !== null) gl.uniform1i(location, value);
    },
  };
}

function standard(shader, ctx, state, canvas) {
  shader.set({
    u_resolution: [canvas.width, canvas.height], u_time: state.t, u_progress: state.progress, u_raw: state.raw,
    u_intro: state.intro, u_dir: ctx.dir,
  });
  shader.setInt('u_quality', ctx.quality.level);
  // A palette shorter than five colours repeats its last colour, so u_color3 and u_color4 are never black by accident.
  for (let index = 0; index < 5; index += 1) shader.set({ [`u_color${index}`]: ctx.colors[index] ?? ctx.colors[ctx.colors.length - 1] });
}

/**
 * A motion that is one fragment shader over the whole frame.
 * `fragment` is GLSL ES 3.00 without the header: declare extra uniforms, then
 * `void main()` writing `outColor`. `uniforms(ctx, state)` returns the extra values.
 */
export function fragment({ fragment: body, uniforms }) {
  const source = `#version 300 es\nprecision highp float;\n${UNIFORMS}\nout vec4 outColor;\n${body}`;
  function setup(ctx) {
    const { canvas, gl } = ctx.surface.webgl();
    const shader = program(gl, TRIANGLE, source);
    return {
      render(state) {
        gl.viewport(0, 0, canvas.width, canvas.height);
        gl.useProgram(shader.handle);
        standard(shader, ctx, state, canvas);
        if (uniforms) shader.set(uniforms(ctx, state));
        gl.drawArrays(gl.TRIANGLES, 0, 3);
      },
      info: () => ({ shader: 'fragment' }),
    };
  }
  // The shader itself, for adapters that run it inside another renderer.
  setup.shader = Object.freeze({ kind: 'fragment', source, uniforms });
  return setup;
}

/** The standard uniform values for one frame, as a plain object (for adapters). */
export function standardUniforms(ctx, state, size) {
  const values = {
    u_resolution: size, u_time: state.t, u_progress: state.progress, u_raw: state.raw,
    u_intro: state.intro, u_dir: ctx.dir, u_quality: ctx.quality.level,
  };
  for (let index = 0; index < 5; index += 1) values[`u_color${index}`] = ctx.colors[index] ?? ctx.colors[ctx.colors.length - 1];
  return values;
}

/**
 * A GPU particle motion. Each point computes its own position from gl_VertexID and time
 * in the vertex shader, so there is no per-frame CPU work and no state between frames.
 * `vertex` must set gl_Position and gl_PointSize and may write `v_color`; `fragment`
 * shades one point sprite using gl_PointCoord. `count` is the particle count at high quality.
 */
export function points({ count, vertex, fragment: body, uniforms, blend = 'additive' }) {
  const head = `#version 300 es\nprecision highp float;\n${UNIFORMS}\nuniform float u_count;\n`;
  const vertexSource = `${head}out vec4 v_color;\n${vertex}`;
  const fragmentSource = `${head}in vec4 v_color;\nout vec4 outColor;\n${body}`;
  return function setup(ctx) {
    const { canvas, gl } = ctx.surface.webgl();
    const shader = program(gl, vertexSource, fragmentSource);
    const total = ctx.count(count, 16);
    return {
      render(state) {
        gl.viewport(0, 0, canvas.width, canvas.height);
        gl.clearColor(ctx.colors[0][0], ctx.colors[0][1], ctx.colors[0][2], 1);
        gl.clear(gl.COLOR_BUFFER_BIT);
        gl.enable(gl.BLEND);
        if (blend === 'additive') gl.blendFunc(gl.SRC_ALPHA, gl.ONE);
        else gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
        gl.useProgram(shader.handle);
        standard(shader, ctx, state, canvas);
        shader.set({ u_count: total });
        if (uniforms) shader.set(uniforms(ctx, state));
        gl.drawArrays(gl.POINTS, 0, total);
        gl.disable(gl.BLEND);
      },
      info: () => ({ particles: total }),
    };
  };
}

export { Unsupported };
