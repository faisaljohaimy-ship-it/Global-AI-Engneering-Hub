# Writing a motion

A motion is one file, `packages/motion-engines/motions/<module>/<slug>.mjs`, whose default export is
`defineMotion({...})` with the id `<module>-<slug>`. It has no dependencies outside
`packages/motion-engines/core`, `packages/motion-engines/engines` and `packages/motion-engines/shaders` (a composition may also
import other motion files). Nothing is downloaded, and no image, font, sound or video
file is used: everything on screen is computed.

The one rule everything else follows from:

> **A motion is a pure function of its inputs.** `render(state)` must draw exactly the same
> pixels for the same `state`, parameters, colours, direction and input, whatever was
> drawn before and however often it is called.

So: no `Math.random()`, `Date.now()`, `performance.now()`, timers, `requestAnimationFrame`,
event listeners, CSS transitions or CSS animations, and nothing accumulated from one frame
to the next (no trails left on a canvas, no positions integrated frame by frame). Random
numbers come from `ctx.random(salt)`; time comes from `state`. A simulation is written in
closed form, or re-run from its start inside `render` for a bounded number of steps.

## The definition

```js
import { defineMotion } from '../../core/define.mjs';

export default defineMotion({
  id: 'camera-dolly-in',            // '<module>-<slug>', the same as the file path
  number: 11,                       // the number in tools/brief.json
  module: 'camera',
  name: { en: 'Cinematic Dolly In', ar: 'اقتراب الكاميرا السينمائي' },   // en exactly as in tools/brief.json
  summary: { en: 'One or two sentences saying what is seen.', ar: 'الوصف نفسه بالعربية.' },
  meaning: {                        // required for every motion added after 2026-11-28 (owner direction)
    en: 'One sentence saying what it stands for in a digital service.',
    ar: 'جملةٌ واحدة تقول ما يمثّله في خدمةٍ رقمية.',
  },
  engine: 'canvas2d',               // canvas2d | webgl2-glsl | webgl2-points | dom | svg | webgpu-wgsl | composition
  kind: 'oneshot',                  // 'oneshot' runs once from 0 to 1; 'loop' runs for ever
  duration: 2400,                   // ms: the length of a oneshot, or of one cycle of a loop
  easing: 'ease-in-out',            // linear, ease, ease-in, ease-out, ease-in-out, ease-out-cubic, ease-in-out-cubic, ease-out-back
  colors: ['#05070f', '#93c5fd', '#fbbf24'],   // 3 to 5 hex colours; the first is the background
  params: {                         // at least two; each one must visibly change the picture
    depth: { default: 1, min: 0.4, max: 2, step: 0.1, label: { en: 'Depth', ar: 'العمق' } },
    layers: { default: 5, min: 3, max: 8, step: 1, label: { en: 'Layers', ar: 'عدد الطبقات' } },
  },
  camera: {                         // optional, same shape as params: for motions with a camera
    fov: { default: 50, min: 30, max: 80, step: 1, label: { en: 'Field of view', ar: 'مجال الرؤية' } },
  },
  text: {                           // optional: the strings shown, in both languages, same keys
    en: { title: 'Launch' }, ar: { title: 'انطلاق' },
  },
  interactive: {                    // optional: only for motions that read ctx.input
    sample: { x: 0.8, y: 0.3, down: true },     // an input that visibly changes the still frame
    note: { en: 'Pointer x, y in 0..1 of the frame; down while pressed.', ar: 'موضع المؤشر x و y من 0 إلى 1 داخل الإطار، وdown أثناء الضغط.' },
  },
  rtl: 'neutral',                   // 'neutral' | 'mirror' | 'text' (see Direction)
  requirements: { gpu: 'none', cost: 'low' },   // gpu: none | webgl2 | webgpu; cost: low | medium | high
  still: 0.6,                       // the progress shown, once, under reduced motion: pick the most complete frame
  tags: ['camera', 'reveal', 'hero'],           // what it is for: used by the orchestrator to choose motions
  setup: canvas2d({ ... }),         // from an engine helper, or your own (ctx) => ({ render(state), dispose?(), info?() })
});
```

`defineMotion` rejects anything that does not fit. `meaning` is checked by
`tools/build_registry.mjs` (exactly `en` and `ar`, one sentence each, Arabic script in `ar`) and
copied into `registry.json`: a motion must say what it means digitally (a data pipeline, an
identity check, an approval gate, a cloud migration ...). A purely decorative motion is not added.
No official logos, emblems, flags or maps. Write the Arabic as a native speaker
would say it, not word for word; technical product names may stay in Latin letters.

## What `setup(ctx)` receives

| | |
|---|---|
| `ctx.width`, `ctx.height` | Size in CSS pixels. **Lay everything out from these.** The harness uses 320x180 and 180x320; the gallery and real pages use anything. Never hard-code a position or a size in pixels. |
| `ctx.pixelRatio` | Device pixels per CSS pixel (already applied to canvases). |
| `ctx.params`, `ctx.camera` | The numeric settings, clamped to their ranges. Round the ones that are counts. |
| `ctx.colors` | The palette as `[r, g, b]` triples in 0..1. `ctx.css` is the same palette as hex strings. Use every colour you declare; draw nothing in a colour that is not derived from the palette (`rgba()`, `mixColour()` from `core/util.mjs`). |
| `ctx.text` | The strings for the current language (defaults from `text`, replaced by the caller's). |
| `ctx.dir`, `ctx.rtl`, `ctx.locale` | `1` or `-1`; `true` under right-to-left; `'en'` or `'ar'` (or what the caller gave). |
| `ctx.random(salt)` | A seeded generator `() => 0..1`. Call it in `setup`/`init`, once per salt, and keep the numbers. |
| `ctx.count(full, floor)` | A count scaled to the quality tier: `ctx.count(4000)` is 4000, 2000 or 1000. Use it for every particle, node, line or step count that costs time. |
| `ctx.quality` | `{ tier, level (3, 2, 1), scale }` for anything else that should get cheaper. |
| `ctx.ease(x)` | The chosen easing as a function, for staging the parts of a motion (`ctx.ease(clamp((p - 0.2) / 0.5))`). |
| `ctx.input` | `{ live, x, y, down, ... }`. While `live` is false the motion plays its own scripted demonstration. |
| `ctx.transparent` | True when the motion is a layer of a composition: do not paint a background. The helpers handle it. |
| `ctx.surface` | Where to draw. The helpers below call it for you. |

## What `render(state)` receives

| | |
|---|---|
| `state.progress` | oneshot: the **eased** position, 0..1. loop: position in the current cycle, 0..1. |
| `state.raw` | The linear position, 0..1. |
| `state.t` | The motion's clock in seconds. It runs at the speed the duration control sets, so use it freely for anything that keeps moving. |
| `state.intro` | Eased 0..1 over the first 600 ms. **A loop must use it** (fade or grow in), or the easing control does nothing. |
| `state.time`, `state.duration`, `state.dt`, `state.rate` | Milliseconds since the start, the duration in ms, seconds since the last frame (0 when seeking: do not rely on it), and the speed factor. |

A oneshot must be driven by `state.progress` and reach a complete, resting picture at 1.
A loop must be driven by `state.t` or `state.raw` and look alive at every moment.

## Engines

**Canvas 2D** – `canvas2d({ init(ctx), draw(g, state, ctx, data) })` from `engines/canvas2d.mjs`.
`g` is scaled so that one unit is one CSS pixel; the frame is already cleared. `init`
returns whatever `draw` needs (seeded positions, precomputed paths). For 3D on a canvas use
`camera()`, `rotateX/Y/Z`, `farToNear()` from `engines/math3d.mjs` (see
`motions/quantum/orbital-matrix.mjs`). Reset nothing yourself except what you change
outside `save()`/`restore()`; avoid `shadowBlur` and `filter` over large areas (slow).

**GLSL fragment shader** – `fragment({ fragment, uniforms(ctx, state) })` from
`engines/webgl.mjs`: GLSL ES 3.00 without the header; declare your own uniforms, write
`outColor`. You get `u_resolution, u_time, u_progress, u_raw, u_intro, u_dir, u_quality,
u_color0..4`. Building blocks (`hash, noise, fbm, noise3, fbm3, voronoi, rotate, centred,
frame, sdf, palette, fresnel, ray, finish`) are in `shaders/chunks.mjs`. Scale loop counts with `u_quality` (for example ray-march
`16 + 16 * u_quality` steps, never more than 64) and keep the shader small: it also has to
run on software rendering. See `motions/quantum/light-tunnel.mjs`.

**GPU particles** – `points({ count, vertex, fragment, uniforms, blend })`: every point
finds its own place from `gl_VertexID` and the uniforms, so there is no per-frame CPU
work. At most about 20000 points at high quality. See `motions/quantum/energy-collapse.mjs`.

**DOM and SVG** – `dom({ css, build(root, ctx), apply(refs, state, ctx) })` from
`engines/dom.mjs`; `svg(document, tag, attributes)` creates SVG nodes. `build` creates the
nodes once; `apply` sets styles and attributes for one moment. In `css`, write `:scope`
for the motion's root. No `transition`, `animation`, `will-change`, `translateZ`,
`perspective` or 3D transforms: the browser then caches layers and frames stop being
reproducible (use Canvas 2D with `math3d` for depth). No `url()`, no external fonts.
Sizes in `%`, `em` or computed from `ctx.width`/`ctx.height`. See
`motions/quantum/energy-pulse.mjs` (SVG) and `motions/micro/magnetic-button.mjs` (DOM).

**WGSL / WebGPU** – `computeParticles({ count, simulate, values })` and
`wgslFragment({ shade, values })` from `engines/webgpu.mjs`. A WGSL motion must also give
`fallback:` (the same picture with `points()` or `fragment()`), because WebGPU is not
available everywhere. See `motions/shaders/wgsl-compute-particles.mjs`.

**Composition** – `composition({ layers })` from `engines/composition.mjs`: layers drawn by
different engines on one timeline, each with a window (`at`), fades, a blend mode and its
own parameters. A layer is a helper call (`canvas2d({...})`, `fragment({...})`, `dom({...})`)
or another motion's definition. The first layer is opaque; put GPU layers that sit above
it on `blend: 'screen'`. At most two WebGL layers may be on screen at the same moment.
See `motions/compositions/quantum-master-sequence.mjs`.

A module may keep helpers of its own in `motions/<module>/lib/*.mjs` (only files directly
inside `motions/<module>/` are motions). `core/util.mjs` has `clamp, lerp, smoothstep,
stage, pingPong, TAU, rgba, mixColour, noise1`; `core/spring.mjs` has `spring, wobble`.

Physics and other simulations stay pure by being computed up front: run the simulation in
`init` with a fixed step for the whole timeline (a few hundred steps), keep the states, and
let `draw` interpolate between them for the moment asked.

## Direction (`rtl`)

- `'neutral'`: the picture has no reading direction. It must be **byte-identical** under
  left-to-right and right-to-left, so do not use `ctx.dir`, `u_dir` or `frameUv()`.
- `'mirror'`: the motion travels along the reading direction (a wipe, a slide, a flow from
  start to end) and is mirrored under right-to-left. Multiply x offsets by `ctx.dir`, or
  use `frameUv()` in a shader. The harness checks that the picture's centre of mass flips,
  so the frame at 35% must be visibly lopsided.
- `'text'`: the motion shows words. Under right-to-left it is created with locale `ar` and
  must show the Arabic strings, laid out right to left. Declare the strings in `text`.

Arabic letters join, so never animate Arabic letter by letter: move whole words
(`units()` in `core/text.mjs`) or reveal the line with a moving mask. Set
`g.direction = 'rtl'` on a canvas, use `font()` from `core/text.mjs` for the font stack,
and use logical CSS (`inset-inline-start`, `text-align: start`) in DOM motions. Numbers
are formatted with `Intl.NumberFormat(ctx.locale)`.

## Interaction

A motion that reacts to the pointer (or to sound, or to a value) declares `interactive`
and reads `ctx.input` in `render`:

```js
const pointer = ctx.input.live ? ctx.input : script(state.raw, ctx.dir);   // { x, y, down }
```

`script` is the motion's own demonstration: a pointer path, a press, a toggle, written as a
function of time. With live input the response is immediate (no smoothing state). Audio
motions read `ctx.input.levels` (an array of 0..1) and synthesise a spectrum from
`state.t` when not live. Draw the scripted cursor only when `!ctx.input.live`.

Micro-interactions on controls also export the response itself, so that it can be attached
to a real element (`adapters/behaviour.mjs`):

```js
/** `input`: { x, y } from the element's centre in half-sizes, down, hover, focus, since (ms since the last change). */
export function respond(input, params) {
  return { transform: '...', boxShadow: '...' };   // CSS declarations only: transform, opacity, filter, boxShadow, borderRadius, letterSpacing, and --custom properties
}
```

`spring()` in `core/spring.mjs` gives a closed-form spring for `since`.

## What the harness checks

`node packages/motion-engines/verify/browser.mjs --module <module>` (or `--id <id>`) creates every
motion in a real browser at 320x180 and fails it unless all of this holds:

| check | meaning |
|---|---|
| `draws` | The still frame has at least 6 distinct colours and at least 1% of its pixels differ from the most common colour. |
| `changesOverTime` | Frames at 10%, 35%, 60% and 85% are different pictures. |
| `sameFrameForSameMoment` | Rendering 35% again, and in a second instance, gives identical pixels. |
| `coloursChangeTheFrame` | Another palette changes the picture. |
| `everyParameterChangesTheFrame` | Each parameter and camera setting, at its minimum or maximum, changes the picture at 60%, 35% or 85%. |
| `everyTextChangesTheFrame` | Each declared string, when replaced, changes the picture. |
| `durationSetsTheSpeed`, `durationChangesTheFrame` | Half speed reaches half as far, and the same instant then looks different. |
| `easingChangesTheFrame` | `linear` and `ease-in` differ (oneshot at 30%; loop at 200 ms, through `intro`). |
| `transportWorks`, `oneShotFinishes` | play, pause, resume, reverse and stop behave; a oneshot ends and schedules nothing more. |
| `reducedMotionIsOneStillFrame` | Under reduced motion exactly one frame is drawn and nothing is scheduled. |
| `directionNeutral` / `mirrorsUnderRtl` / `rendersArabicRightToLeft` | See Direction. |
| `inputChangesTheFrame`, `releasingInputRestoresTheFrame` | Interactive motions react to `interactive.sample` and return to the scripted frame. |
| `drawsInPortrait` | It also fills a 180x320 frame. |
| `lowerQualityStillDraws` | The low tier draws fewer pixels and still shows a picture. |
| `exportsFrames`, `destroyReleasesEverything`, `releasesMemory`, `noPageErrors` | Frames export; destroy removes every node and GPU context; nothing leaks; no console errors. |
| `uniqueFrames` | No two motions draw the same frames. |

A motion that fails any check is not operational and is not counted.

## Looking at it

The harness proves that a motion works. Only looking at it shows whether it is good:

```
node packages/motion-engines/verify/sheet.mjs --module <module> --out /path/outside/the/repo/sheet.png [--direction rtl]
```

renders three moments of every motion in the module side by side. Open the PNG and judge
it as a designer would: is the subject of the name recognisable, is the frame composed
(centred or deliberately placed, nothing clipped, not a small thing lost in a large empty
field), do the colours read well, is the Arabic correct and joined, does the 85% frame look
finished. Fix what is weak and look again.

## Performance

Aim for under 4 ms a frame at 320x180 on software rendering (the harness prints nothing
about speed, but every frame it asks for is rendered, so a slow motion makes the run slow
and can time out). Do setup work in `setup`/`init`, not in `render`. In `render`, avoid
allocating large arrays every frame, building long strings, or touching layout
(`offsetWidth`, `getBoundingClientRect`) more than once.
