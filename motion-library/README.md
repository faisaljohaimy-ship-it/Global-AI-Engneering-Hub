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

## From specification to verified component

1. Write `specs/<catalog-id>.json`. Spring curves come from `springs.py`, which samples
   the spring into keyframes; run `python3 motion-library/springs.py --write`.
2. `python3 motion-library/compile.py specs/<catalog-id>.json` must succeed.
3. `node motion-library/verify/browser.mjs --write` plays every specification in
   Chromium, from the compiled CSS and through `runtime/hub-motion.mjs`, and writes
   `evidence/chromium.json` with what the engine computed: timing, first and last
   keyframes, interpolation, easing against the engine's own curve, the reduced-motion
   end state, and mirrored travel under `dir="rtl"`.
4. `python3 motion-library/catalog_status.py --write` marks an entry implemented only
   while that evidence matches the files in the repository. Change a specification or
   the runtime without repeating step 3 and the entry returns to `specification`.

`runtime/hub-motion.mjs` plays the same JSON with the Web Animations API and adds what
a stylesheet cannot: `stagger`, `typewriterAt` (by grapheme, or by word for joined
scripts such as Arabic) and `counterValueAt`. Inline-relative motions multiply their
travel by `--hub-inline-sign` from `runtime/hub-motion-base.css`, so one specification
serves both directions. Playwright is needed only to produce evidence; nothing in a
consuming project depends on it.

`render/render.mjs --out DIR` renders `render/scene.html` frame by frame by seeking,
pipes the frames to ffmpeg and reports the cinematic playbook checks it can measure.
The film stays outside the repository; `evidence/sample-render.json` is the record.

Recovered the twelve exact entries of MOTION_CATALOG.csv. The previous Q∞ pack described a 120-variant catalog and a source Remotion sample; the full archive has not been recovered in this pass. This library adds categorized design specifications for UI, cinematic video, typography, data visualization, spatial 3D and interactive effects. No private film, voice, customer assets or third-party code is published. Use reduced-motion alternatives, deterministic frames, RTL-safe text, asset license review and browser/device performance tests. New CSS scroll-trigger and WebGPU features require capability detection and fallbacks. See MOTION_CATALOG.json. External references are implementation starting points, not proof that each effect is documented or implemented there.
