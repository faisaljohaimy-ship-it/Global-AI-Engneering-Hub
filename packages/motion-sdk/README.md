# Universal Motion SDK 1.0.0

Additive, dependency-free development tooling. It leaves the existing Motion Lab,
runtime and their evidence unchanged. The new expansion catalog is registered
explicitly; discovery never installs or executes unreviewed remote code.

```js
import {createMotionSystem} from './packages/motion-sdk/index.mjs';
import * as reviewedCatalog from './motion-library/expansion/catalog.mjs';

const motion = createMotionSystem();
motion.registerCatalog(reviewedCatalog);
const clip = motion.create(reviewedCatalog.definitions[0].id, {
  container: document.querySelector('#preview'),
  width: 640, height: 360, rtl: true, reducedMotion: 'auto',
  seed: 1, detail: 12, intensity: 1,
});
clip.play();
clip.pause();
clip.resume();
clip.reverse();
clip.render(0.5);       // deterministic seek, works without a scheduler
clip.export('svg');     // standalone vector snapshot; also JSON and canvas PNG
clip.optimize({profile: 'mobile'});
clip.benchmark({frames: 120});
clip.getCapabilities();
clip.stop();
clip.destroy();
```

The same operations are available through `motion.play(clip)`, `motion.export(clip,
'json')`, and so on. `preview(progress)` samples and draws a chosen frame.
`loadCatalog()` loads the reviewed local expansion module; remote cross-origin
code imports are refused. `definitions()` returns independent metadata copies.

`create` allocates Canvas2D only when given a container/canvas. Without the DOM it
supports deterministic sampling, structured export and benchmarks. Scheduling
requires a real `requestAnimationFrame` host; tests can inject a controlled clock.
Canvas ownership and animation frames are cleaned up on `destroy`; caller-provided
canvas dimensions/style are restored. Dimensions, pixel count, primitive count,
coordinates, colors and exported text are bounded and validated. No HTML is
injected and no remote texture/font/source is fetched.

The catalog sampler owns logical RTL mirroring and the stable reduced-motion
poster. The SDK respects the operating-system preference unless explicitly set to
`reduce` or `full`. Mobile optimization reduces detail and caps device pixel ratio;
it does not label a color/speed variant as a new motion.

For a separately supplied local WAAPI definition, `engine: 'waapi'` and safe
opacity/transform keyframes operate on an explicit `target`. Its timeline can be
seeked/reversed through the same interface; export is structured JSON only.
Expansion Canvas2D recipes are not described as WAAPI, WebGPU or Three.js renders.

`benchmark` reports measured synchronous sampling/draw CPU time. It is not an FPS,
real-device, GPU, Lighthouse or production Web Vitals claim. Encoded-video export,
WebGPU, Three.js, Remotion and worker rendering remain unavailable until their own
reviewed adapter, license and runtime evidence exist. SVG export is a frame, not a
film. The first-party package uses MIT; unrelated hub assets retain their licenses.

Open `motion-studio/index.html` through the local hub server for interactive
discovery, seeking, direction, reduced motion, playback, frame export and benchmarks.
