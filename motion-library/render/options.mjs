import { existsSync, realpathSync, statSync } from 'node:fs';
import { dirname, isAbsolute, relative, resolve, sep } from 'node:path';

export const RENDER_LIMITS = Object.freeze({
  fps: Object.freeze({ min: 1, max: 60 }),
  width: Object.freeze({ min: 320, max: 3840 }),
  height: Object.freeze({ min: 180, max: 2160 }),
  maxPixels: 3840 * 2160,
  maxDurationMs: 30_000,
  maxFrames: 1_800,
});

const containedBy = (base, candidate) => {
  const path = relative(base, candidate);
  return path === '' || (!isAbsolute(path) && path !== '..' && !path.startsWith(`..${sep}`));
};

const boundedInteger = (name, raw, { min, max }) => {
  const value = typeof raw === 'number' ? raw : Number(raw);
  if (!Number.isSafeInteger(value) || value < min || value > max) {
    throw new Error(`${name} must be an integer from ${min} to ${max}`);
  }
  return value;
};

export function assertOutputOutsideRepository(out, repository) {
  const target = resolve(out);
  const root = resolve(repository);
  if (target === resolve(target, sep)) throw new Error('Output cannot be the filesystem root');
  if (containedBy(root, target)) throw new Error('Output must be outside the repository');
  return target;
}

export function assertCreatableOutputOutsideRepository(out, repository) {
  const target = assertOutputOutsideRepository(out, repository);
  let ancestor = target;
  while (!existsSync(ancestor)) {
    const parent = dirname(ancestor);
    if (parent === ancestor) break;
    ancestor = parent;
  }
  assertOutputOutsideRepository(realpathSync(ancestor), realpathSync(repository));
  return target;
}

export function validateRenderOptions(raw, { library, repository }) {
  if (!raw.out || typeof raw.out !== 'string') {
    throw new Error('Missing --out directory');
  }
  const out = assertCreatableOutputOutsideRepository(raw.out, repository);
  const fps = boundedInteger('fps', raw.fps ?? 30, RENDER_LIMITS.fps);
  const width = boundedInteger('width', raw.width ?? 1280, RENDER_LIMITS.width);
  const height = boundedInteger('height', raw.height ?? 720, RENDER_LIMITS.height);
  if (width * height > RENDER_LIMITS.maxPixels) throw new Error('Requested frame exceeds the pixel budget');
  if (width * 9 !== height * 16) throw new Error('Width and height must use a 16:9 aspect ratio');

  const renderRoot = resolve(library, 'render');
  const scene = raw.scene ?? 'render/scene.html';
  if (typeof scene !== 'string' || scene.includes('\0')) throw new Error('Invalid scene path');
  const sceneFile = resolve(library, scene);
  if (!containedBy(renderRoot, sceneFile) || !sceneFile.endsWith('.html')) {
    throw new Error('Scene must be a local HTML file under motion-library/render');
  }
  if (!statSync(sceneFile).isFile()) throw new Error('Scene does not exist or is not a file');
  const verifiedScene = realpathSync(sceneFile);
  if (!containedBy(realpathSync(renderRoot), verifiedScene)) {
    throw new Error('Scene must resolve inside motion-library/render');
  }

  return {
    out,
    fps,
    width,
    height,
    scenePath: relative(realpathSync(library), verifiedScene).split(sep).join('/'),
  };
}

export function boundedFrameCount(durationMs, fps) {
  if (!Number.isFinite(durationMs) || durationMs <= 0 || durationMs > RENDER_LIMITS.maxDurationMs) {
    throw new Error(`Scene duration must be greater than 0 and at most ${RENDER_LIMITS.maxDurationMs}ms`);
  }
  const frames = Math.round((durationMs / 1000) * fps);
  if (!Number.isSafeInteger(frames) || frames < 1 || frames > RENDER_LIMITS.maxFrames) {
    throw new Error(`Scene must render between 1 and ${RENDER_LIMITS.maxFrames} frames`);
  }
  return frames;
}
