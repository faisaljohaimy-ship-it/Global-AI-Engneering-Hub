// Drive a motion from somebody else's timeline. Animation libraries animate numbers on
// objects; this gives them an object whose `progress` (0..1) and `time` (ms) seek the motion.
//
//   const target = progressTarget(instance);
//   gsap.to(target, { progress: 1, duration: 2, ease: 'power2.inOut' });          // GSAP
//   animate(0, 1, { duration: 2, onUpdate: (value) => { target.progress = value; } });   // Motion
//   sheetObject.onValuesChange(({ progress }) => { target.progress = progress; });       // Theatre.js
//
// The motion is paused first: the outside timeline is now the only clock.
export function progressTarget(instance) {
  instance.pause();
  let progress = instance.progress;
  return {
    get progress() {
      return progress;
    },
    set progress(value) {
      progress = Math.min(1, Math.max(0, Number(value) || 0));
      instance.render({ progress });
    },
    get time() {
      return instance.time;
    },
    set time(ms) {
      instance.render({ time: Math.max(0, Number(ms) || 0) });
      progress = instance.progress;
    },
    instance,
  };
}

/**
 * The motion's canvas as an image source for another renderer: a texture in Three.js,
 * Babylon.js or PixiJS, or a frame for a video encoder. Null when the motion is not a
 * single canvas (DOM, SVG and layered motions).
 *   const texture = new THREE.CanvasTexture(canvasSource(instance));
 *   // after every instance.render(...):  texture.needsUpdate = true;
 */
export function canvasSource(instance) {
  return instance.canvas;
}
