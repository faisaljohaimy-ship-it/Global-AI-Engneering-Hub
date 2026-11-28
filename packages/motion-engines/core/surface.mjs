// The drawing surface a motion gets: one sized root element inside the caller's
// container, with helpers to add canvases or nodes and to clean all of it up again.
import { Unsupported } from './define.mjs';
import { fnv1a } from './util.mjs';

export function createSurface(container, { width, height, pixelRatio, dir, background }) {
  const doc = container.ownerDocument;
  const root = doc.createElement('div');
  root.className = 'hub-motion-surface';
  root.dir = dir;
  root.style.cssText = `position:relative;overflow:hidden;width:${width}px;height:${height}px;background:${background};`;
  container.append(root);
  const canvases = [];
  const releases = new Set();
  let nodes = 0;

  const makeCanvas = (parent) => {
    const canvas = doc.createElement('canvas');
    canvas.width = Math.max(1, Math.round(width * pixelRatio));
    canvas.height = Math.max(1, Math.round(height * pixelRatio));
    canvas.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;display:block;';
    parent.append(canvas);
    return canvas;
  };

  // The drawing helpers, bound to one parent node: the surface itself or one of its layers.
  const face = (parent) => {
    const own = new Set();
    const keep = (entry, release) => {
      if (entry) canvases.push(entry);
      const undo = () => {
        release?.();
        if (entry) {
          canvases.splice(canvases.indexOf(entry), 1);
          entry.canvas.remove();
        }
      };
      own.add(undo);
      releases.add(undo);
    };
    return {
      root: parent,
      width,
      height,
      pixelRatio,
      /** A 2D canvas scaled so that drawing code works in CSS pixels. */
      canvas2d({ alpha = false } = {}) {
        const canvas = makeCanvas(parent);
        const g = canvas.getContext('2d', { alpha });
        if (!g) throw new Unsupported('canvas2d');
        keep({ canvas, kind: '2d', context: g });
        return { canvas, g };
      },
      webgl(attributes = {}) {
        const canvas = makeCanvas(parent);
        const gl = canvas.getContext('webgl2', {
          alpha: false, antialias: false, depth: false, stencil: false, premultipliedAlpha: false,
          preserveDrawingBuffer: false, powerPreference: 'high-performance', ...attributes,
        });
        if (!gl) {
          canvas.remove();
          throw new Unsupported('webgl2');
        }
        keep({ canvas, kind: 'webgl2', context: gl }, () => gl.getExtension('WEBGL_lose_context')?.loseContext());
        return { canvas, gl };
      },
      /**
       * A WebGPU device and a way to put frames on screen. Normally frames go straight to
       * the canvas. With `readback` they are drawn into a texture and copied to a 2D canvas
       * a moment later: slower, but it works where the browser cannot show a WebGPU canvas
       * (some headless and virtual machines), and it is what makes WGSL testable there.
       * Returns { canvas, device, format, frame(encode), settled(), lost, present }.
       */
      async webgpu({ readback = false } = {}) {
        const view = doc.defaultView;
        const gpu = view.navigator.gpu;
        let device = null;
        try {
          const adapter = gpu ? await gpu.requestAdapter() : null;
          device = adapter ? await adapter.requestDevice() : null;
        } catch {
          device = null;
        }
        if (!device) throw new Unsupported('webgpu');
        const canvas = makeCanvas(parent);
        let released = false;
        // Resolves only when the device is lost by something other than our own cleanup.
        const lost = device.lost.then((info) => (released ? new Promise(() => {}) : info));
        const release = () => {
          released = true;
          device.destroy();
        };
        if (!readback) {
          const context = canvas.getContext('webgpu');
          if (!context) {
            canvas.remove();
            release();
            throw new Unsupported('webgpu');
          }
          const format = gpu.getPreferredCanvasFormat();
          context.configure({ device, format, alphaMode: 'opaque' });
          keep({ canvas, kind: 'webgpu', context }, release);
          return {
            canvas, device, format, lost, present: 'canvas',
            /** Draw one frame: encode(encoder, view) adds the passes that render into `view`. */
            frame(encode) {
              if (released) return;
              const encoder = device.createCommandEncoder();
              encode(encoder, context.getCurrentTexture().createView());
              device.queue.submit([encoder.finish()]);
            },
            settled: () => Promise.resolve(),
          };
        }
        const g = canvas.getContext('2d');
        const [wide, high] = [canvas.width, canvas.height];
        const texture = device.createTexture({ size: [wide, high], format: 'rgba8unorm', usage: view.GPUTextureUsage.RENDER_ATTACHMENT | view.GPUTextureUsage.COPY_SRC });
        const stride = Math.ceil((wide * 4) / 256) * 256;
        const staging = device.createBuffer({ size: stride * high, usage: view.GPUBufferUsage.COPY_DST | view.GPUBufferUsage.MAP_READ });
        const image = g.createImageData(wide, high);
        let busy = false;
        let queued = null;
        const waiting = [];
        // One frame is in flight at a time. A frame asked for meanwhile replaces any other
        // waiting frame, so the newest request always wins and nothing piles up.
        const frame = (encode) => {
          if (released) return;
          if (busy) {
            queued = encode;
            return;
          }
          busy = true;
          const encoder = device.createCommandEncoder();
          encode(encoder, texture.createView());
          encoder.copyTextureToBuffer({ texture }, { buffer: staging, bytesPerRow: stride }, [wide, high]);
          device.queue.submit([encoder.finish()]);
          staging.mapAsync(view.GPUMapMode.READ).then(() => {
            const bytes = new Uint8Array(staging.getMappedRange());
            for (let y = 0; y < high; y += 1) image.data.set(bytes.subarray(y * stride, y * stride + wide * 4), y * wide * 4);
            staging.unmap();
            g.putImageData(image, 0, 0);
          }).catch(() => {
            // The device went away mid-frame; `lost` reports it.
          }).finally(() => {
            busy = false;
            if (queued && !released) {
              const next = queued;
              queued = null;
              frame(next);
            } else waiting.splice(0).forEach((resolve) => resolve());
          });
        };
        keep({ canvas, kind: '2d', context: g }, release);
        return {
          canvas, device, format: 'rgba8unorm', lost, present: 'readback', frame,
          /** Resolves when every requested frame has reached the canvas. */
          settled: () => (busy ? new Promise((resolve) => waiting.push(resolve)) : Promise.resolve()),
        };
      },
      /** A DOM or SVG node inside the surface. */
      element(tag = 'div', namespace) {
        nodes += 1;
        const node = namespace ? doc.createElementNS(namespace, tag) : doc.createElement(tag);
        parent.append(node);
        return node;
      },
      /**
       * A full-size layer stacked over what was added before it, with the same drawing
       * helpers plus clear(). `blend` is a CSS mix-blend-mode: 'screen' lets a dark-backed
       * GPU layer add its light to the layers below.
       */
      layer({ blend = 'normal' } = {}) {
        nodes += 1;
        const node = doc.createElement('div');
        node.style.cssText = `position:absolute;inset:0;mix-blend-mode:${blend};`;
        parent.append(node);
        return face(node);
      },
      onDispose(cleanup) {
        keep(null, cleanup);
      },
      /** Release everything created through this face (canvases, GPU contexts, nodes) and empty it. */
      clear() {
        for (const undo of [...own].reverse()) {
          try {
            undo();
          } catch {
            // One failing cleanup must not keep the others alive.
          }
          releases.delete(undo);
        }
        own.clear();
        parent.replaceChildren();
      },
    };
  };

  return {
    ...face(root),
    /** Number of pixels drawn per frame; falls with the quality tier. */
    get pixels() {
      return canvases.reduce((sum, layer) => sum + layer.canvas.width * layer.canvas.height, 0)
        || Math.round(width * height * pixelRatio * pixelRatio);
    },
    /** The canvas, when the whole picture is exactly one canvas; otherwise null. */
    get canvas() {
      return canvases.length === 1 && nodes === 0 ? canvases[0].canvas : null;
    },
    /** RGBA bytes of the only canvas, read in the same task as the draw. Null for layered or DOM pictures. */
    read() {
      if (canvases.length !== 1 || nodes > 0) return null;
      const { canvas, kind, context } = canvases[0];
      if (kind === '2d') return { width: canvas.width, height: canvas.height, data: context.getImageData(0, 0, canvas.width, canvas.height).data };
      if (kind === 'webgl2') {
        // Rows come back bottom-up; flip them so that every engine reports the same orientation.
        const raw = new Uint8Array(canvas.width * canvas.height * 4);
        context.readPixels(0, 0, canvas.width, canvas.height, context.RGBA, context.UNSIGNED_BYTE, raw);
        const data = new Uint8ClampedArray(raw.length);
        const row = canvas.width * 4;
        for (let y = 0; y < canvas.height; y += 1) data.set(raw.subarray(y * row, (y + 1) * row), (canvas.height - 1 - y) * row);
        return { width: canvas.width, height: canvas.height, data };
      }
      // A WebGPU canvas cannot be read synchronously: such pictures are read from a screenshot.
      return null;
    },
    /** Make sure queued GPU work has run, so that a timing is the real cost of the frame. */
    flush() {
      for (const layer of canvases) if (layer.kind === 'webgl2') layer.context.finish();
    },
    dispose() {
      for (const undo of [...releases].reverse()) {
        try {
          undo();
        } catch {
          // A failing cleanup must not keep the rest of the surface alive.
        }
      }
      releases.clear();
      root.remove();
    },
  };
}

/**
 * Facts about a frame: a hash, how many colours it has, how much of it differs from its
 * most common colour, and where that differing content sits horizontally (0 left, 1 right).
 */
export function analyze({ width, height, data }) {
  const counts = new Map();
  for (let index = 0; index < data.length; index += 4) {
    const key = ((data[index] >> 3) << 10) | ((data[index + 1] >> 3) << 5) | (data[index + 2] >> 3);
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  let mode = 0;
  let most = 0;
  for (const [key, count] of counts) {
    if (count > most) {
      most = count;
      mode = key;
    }
  }
  const base = [((mode >> 10) & 31) << 3, ((mode >> 5) & 31) << 3, (mode & 31) << 3];
  let weight = 0;
  let moment = 0;
  let luma = 0;
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const index = (y * width + x) * 4;
      const difference = Math.abs(data[index] - base[0]) + Math.abs(data[index + 1] - base[1]) + Math.abs(data[index + 2] - base[2]);
      luma += data[index] * 0.2126 + data[index + 1] * 0.7152 + data[index + 2] * 0.0722;
      if (difference > 24) {
        weight += difference;
        moment += difference * (x + 0.5);
      }
    }
  }
  const pixels = width * height;
  return {
    hash: fnv1a(data),
    width,
    height,
    distinct: counts.size,
    spread: 1 - most / pixels,
    centroidX: weight ? moment / weight / width : 0.5,
    meanLuma: luma / pixels / 255,
  };
}

/** Fraction of pixels that differ visibly between two frames of the same size. */
export function changedFraction(a, b) {
  if (a.length !== b.length) return 1;
  let changed = 0;
  for (let index = 0; index < a.length; index += 4) {
    if (Math.abs(a[index] - b[index]) > 8 || Math.abs(a[index + 1] - b[index + 1]) > 8 || Math.abs(a[index + 2] - b[index + 2]) > 8) changed += 1;
  }
  return changed / (a.length / 4);
}
