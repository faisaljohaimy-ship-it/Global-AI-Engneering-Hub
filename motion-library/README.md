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

`components.json` is the executable evidence manifest. It currently maps 11 of the
142 indexed specifications to six CSS components, two WAAPI components, one local
WebGL/GLSL component, one deterministic Remotion adapter and one deterministic Three.js
camera adapter. The adapters do not import or claim installation of those optional
packages. Open `motion-lab/` through a local HTTP server to inspect the full catalog;
playback is user-triggered and uses only local assets.

Recovered the twelve exact entries of MOTION_CATALOG.csv. The previous Q∞ pack described a 120-variant catalog and a source Remotion sample; the full archive has not been recovered in this pass. This library adds categorized design specifications for UI, cinematic video, typography, data visualization, spatial 3D and interactive effects. No private film, voice, customer assets or third-party code is published. Use reduced-motion alternatives, deterministic frames, RTL-safe text, asset license review and browser/device performance tests. New CSS scroll-trigger and WebGPU features require capability detection and fallbacks. See MOTION_CATALOG.json. External references are implementation starting points, not proof that each effect is documented or implemented there.
