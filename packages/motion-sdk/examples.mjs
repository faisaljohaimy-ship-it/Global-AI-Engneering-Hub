import {createMotionSystem} from './index.mjs';

/** Supply the reviewed local catalog module; no remote tool is installed. */
export function previewInto(container, reviewedCatalog, id, options = {}) {
  const sdk = createMotionSystem();
  sdk.registerCatalog(reviewedCatalog);
  const instance = sdk.create(id, {container, width: 640, height: 360, ...options});
  return {sdk, instance, cleanup: () => instance.destroy()};
}

/** Deterministic render loop for a separately reviewed offline media pipeline. */
export function frameSequence(instance, {frames = 60} = {}) {
  if (!Number.isInteger(frames) || frames < 2 || frames > 1000) throw new Error('Invalid frame count');
  return Array.from({length: frames}, (_, index) => instance.render(index / (frames - 1)));
}
