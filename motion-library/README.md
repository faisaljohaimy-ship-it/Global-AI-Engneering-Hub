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

`components.json` is the executable evidence manifest. It currently maps 30 of the
142 indexed entries to six CSS components, eighteen WAAPI components, three shared
WAAPI behaviours, one local WebGL/GLSL component, one deterministic Remotion adapter
and one deterministic Three.js camera adapter. The adapters do not import or claim
installation of those optional packages. Open `motion-lab/` through a local HTTP
server to inspect the full catalog and run all 30 implemented controls; playback is
user-triggered and uses only local assets.

## From specification to browser-verified component

1. Write a validated JSON specification. Generated spring curves come from
   `springs.py` and must be deterministic.
2. Compile it with `compile.py`; reduced-motion and property grammars are mandatory.
3. `npm ci --prefix motion-library/verify --ignore-scripts`, then
   `node motion-library/verify/browser.mjs --write`, plays compiled CSS and the shared
   WAAPI runtime in Chromium and records computed timing, interpolation, RTL and
   reduced-motion evidence in `evidence/chromium.json`.
4. `catalog_status.py --write` marks catalog entries implemented only while the
   evidence digests still match. Never edit those claims by hand.

`runtime/hub-motion.mjs` supplies the browser-tested generic runtime, stagger,
grapheme/word-safe typewriter and counter interpolation. `render/render.mjs --out DIR`
seeks frames deterministically and pipes them to the locally available FFmpeg; no film
or private media is stored in this repository.

Recovered the twelve exact entries of MOTION_CATALOG.csv. The previous Q∞ pack described a 120-variant catalog and a source Remotion sample; the full archive has not been recovered in this pass. This library adds categorized design specifications for UI, cinematic video, typography, data visualization, spatial 3D and interactive effects. No private film, voice, customer assets or third-party code is published. Use reduced-motion alternatives, deterministic frames, RTL-safe text, asset license review and browser/device performance tests. New CSS scroll-trigger and WebGPU features require capability detection and fallbacks. See MOTION_CATALOG.json. External references are implementation starting points, not proof that each effect is documented or implemented there.
