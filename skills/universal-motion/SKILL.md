---
name: universal-motion
description: Use the reviewed local Universal Motion SDK and 400 Canvas2D reference scenes with deterministic sampling, RTL, reduced motion and offline imports.
---

Read the project's AGENTS.md, CLAUDE.md and .engineering/capabilities.json first.
Use this skill when a project needs the Universal Motion SDK, a Canvas2D scene,
an accessible motion preview or deterministic SVG/JSON frame export.

During a reviewed dependency update, run the existing hub CLI from its trusted
checkout with a full merged commit SHA:

```sh
python3 hub.py register /absolute/project --revision FULL_REVIEWED_MERGED_SHA --capability pack:motion-sdk
```

Inspect that dry run for conflicts before adding `--apply`; preserve existing
capabilities and project-owned files. Run `hub.py verify /absolute/project --strict`
from the reviewed hub checkout after registration. The pack installs this skill in
both .agents/skills and .claude/skills and copies sources, examples, definitions
and licenses beneath .engineering/vendor/os-motion. No host configuration is
replaced. Discovery files alone do not prove invocation by Codex or Claude Code.

At runtime use the project's local files. No hub checkout, GitHub request, npm
installation, API key, model subscription or provider connection is required:

```js
import {createMotionSystem} from './.engineering/vendor/os-motion/packages/motion-sdk/index.mjs';

const motion = createMotionSystem();
await motion.loadCatalog(); // resolves the reviewed vendored catalog locally
const clip = motion.create('os-quantum-b01', {
  width: 320, height: 180, rtl: true, reducedMotion: 'reduce', detail: 6,
});
const scene = clip.render(0.5); // deterministic scene sampling without a DOM
const svg = clip.export('svg'); // a vector frame, not an encoded film
clip.destroy();
```

For a browser preview, pass an explicit project-owned `container` or `canvas` and
use `reducedMotion: 'auto'`. Call play/pause/resume/reverse/stop/destroy on the clip,
or through the motion facade; destroy the clip when unmounting. Use `preview`,
`render`, `optimize`, `benchmark` and `getCapabilities` only within the documented
finite dimensions, detail and frame budgets. Retain reduced-motion posters and
test RTL/LTR, mobile layout and cleanup in the consuming project's real UI.

The expansion has 200 base mechanisms and 200 composed Canvas2D reference scenes.
It does not run WebGPU, Three.js, Remotion, a physical simulation or model inference.
The pack does not install Motion Studio, its preview page, browser binaries or
browser evidence. Definition metadata retains paths into the original hub; those
references are provenance, not installed product routes or current product tests.
Use the vendored examples.mjs modules for local samples. Benchmarks measure local
synchronous sampling/draw CPU time; they do not certify FPS or production Web Vitals.

Keep both vendored MIT LICENSE files with copied source. Their scope covers these
original SDK/expansion files only. Review optional engines, external assets and
commercial licenses separately; do not enable services or incur additional costs.
If pack:engineering-sdk is already installed, run its offline integrity verifier
before invocation. Record actual product usage, browser tests and current source
hashes separately from installation; upstream provenance is checked during review,
and production execution remains independent of hub availability.
