# Global digital motion library

Catalog entries are specifications until runtime evidence says otherwise. The first
portable implementation is a dependency-free JSON-to-CSS compiler:

```sh
python3 motion-library/compile.py motion-library/specs/fade-in.json
python3 motion-library/compile.py motion-library/specs/fade-in.json --output /tmp/fade-in.css
```

The compiler accepts a deliberately small property set, validates deterministic
timing, and requires a `prefers-reduced-motion` end state. Add effects one small,
tested specification at a time; do not mark unrelated catalog entries implemented.

`components.json` is the executable evidence manifest. It currently maps 26 of the
142 indexed specifications to 21 CSS components, two WAAPI components, one local
WebGL/GLSL component, one deterministic Remotion adapter and one deterministic Three.js
camera adapter. The adapters do not import or claim installation of those optional
packages. Open `motion-lab/` through a local HTTP server to inspect the full catalog;
playback is user-triggered and uses only local assets.

## From specification to browser-verified component

1. Write `specs/<name>.json` with the catalog id. Spring curves come from `springs.py`,
   which samples the spring into keyframes (`python3 motion-library/springs.py --write`).
   Set `"rtl_mirror": true` when the motion travels along the inline axis: the compiler
   then emits mirrored keyframes for `:dir(rtl)` and the runtime mirrors the same way.
2. Add a row to `components.json` with `"runtime_status": "pending-browser"`.
3. `python3 motion-library/component_status.py --write` writes the Motion Lab rule for a
   CSS component that has no hand-written one.
4. `node motion-library/verify/browser.mjs --write` plays every css and waapi component
   in Chromium, from the compiled CSS and through `runtime/hub-motion.mjs`, then drives
   the Motion Lab through its own controls. `evidence/chromium.json` records what the
   engine computed: timing, first and last keyframes, interpolation, easing against the
   engine's own curve, the reduced-motion end state and mirrored travel.
5. Run step 3 again. A row becomes `browser-verified` only while that evidence matches
   the files in the repository; change a specification, the runtime or the lab without
   repeating step 4 and it returns to `pending-browser`. Never edit the status by hand.

`runtime/hub-motion.mjs` plays the same JSON with the Web Animations API, easing each
keyframe interval exactly as CSS does, and adds what a stylesheet cannot: `stagger`,
`typewriterAt` (by grapheme, or by word for joined scripts such as Arabic) and
`counterValueAt`. `verify/rejections.json` holds the cases both it and the compiler must
refuse. Playwright is needed only to produce evidence; no consuming project depends on it.

`render/render.mjs --out DIR` renders `render/scene.html` frame by frame by seeking,
pipes the frames to ffmpeg and reports the cinematic playbook checks it can measure.
The film stays outside the repository; `evidence/sample-render.json` is the record.

Recovered the twelve exact entries of MOTION_CATALOG.csv. The previous Q∞ pack described a 120-variant catalog and a source Remotion sample; the full archive has not been recovered in this pass. This library adds categorized design specifications for UI, cinematic video, typography, data visualization, spatial 3D and interactive effects. No private film, voice, customer assets or third-party code is published. Use reduced-motion alternatives, deterministic frames, RTL-safe text, asset license review and browser/device performance tests. New CSS scroll-trigger and WebGPU features require capability detection and fallbacks. See MOTION_CATALOG.json. External references are implementation starting points, not proof that each effect is documented or implemented there.
