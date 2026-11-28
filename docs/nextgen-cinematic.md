# Cinematic intelligence — first verified increment

This lane adds three original perspective-camera scenes through the existing
Universal Motion SDK. It does not copy or merge PR #16. The API remains
`createMotionSystem().registerCatalog(catalog)`, then `create/play/pause/resume/
reverse/stop/render/export/optimize/benchmark/destroy`. A single instance can serve
an interface preview or deterministic offline frame sampling. Encoded films use
the separately reviewed existing renderer; no new renderer is introduced.

```js
import {createMotionSystem} from './packages/motion-sdk/index.mjs';
import * as camera from './motion-library/expansion/nextgen-camera.mjs';
const sdk = createMotionSystem();
sdk.registerCatalog(camera);
const clip = sdk.create('camera-drone-approach', {
  container: document.querySelector('#preview'), width: 390, height: 844,
  reducedMotion: 'auto', rtl: true,
});
clip.play(); // Destroy the instance when its owning view unmounts.
```

The new scenes are `camera-infinite-flythrough`, `camera-drone-approach` and
`camera-macro-to-micro`. They project fixed 3D geometry using a moving camera,
near-plane clipping and viewport clipping into existing Canvas2D primitives.
Flythrough translates through portal planes, drone approach changes camera height
and depth over a city grid, and macro-to-micro crosses nested scales with
world-space perspective. They are not speed/color variants or aliases for main's
symbolic reference recipes. They are illustrative wireframes, with no live sensor,
physical simulation, GPU shader, digital-twin synchronization or inference claim.
The existing scoped MIT license covers the new expansion module and its tests.

## Actual inventory and PR #16 review

The independently inspected read-only PR head is
`f9b88f3928def5c804a1353a17a5dffca071406c`.
`docs/evidence/nextgen-cinematic-inventory.json` preserves the owner's 200 requested
identities and hashes each of the 34 implementation files found in that head.
Those 34 are on the unmerged PR branch, not installed or reverified by this change.
The three new implementations fill previously absent requested identities. Of the
200 names, 163 have no implementation in either inspected source. Main's 400
separately named Canvas2D reference recipes are excluded from these counts.
No alias-based double counting is performed.

Review findings remain material:

- PR16 has 34 loader entries and 34 source files matching the requested names;
  its recorded 34 passing rows are historical Chromium evidence only.
- `packages/motion-engines/` is outside the existing scoped MIT license. Nothing
  here approves its commercial adoption, copies its implementation, or changes
  the owner's licensing decision.
- PR16 registry preview targets use `motion-studio/engines.html`; this page is
  absent in main. No working Studio preview is inferred from that metadata.
- Main CI does not execute PR16's unmerged package harness. PR16 must reconcile
  its merge conflict, CI, licensing and fresh browser evidence before adoption.
- WebGPU compute/readback is not proof of canvas presentation; no presentation
  claim is imported from its old receipt. Neither PR16 nor this lane proves
  real-device frame rate or Firefox/WebKit compatibility.

## Evidence and limits

The committed `docs/evidence/nextgen-camera-chromium.json` is a reproducible local
receipt from actual Chromium 156.0.8078.79 on Linux, controlled by the existing
reviewed Playwright 1.65.1 lock. Six cases cover three IDs at 390×844 and 1280×720,
with 18 sampled pixel frames, deterministic replay, frame changes, reduced-motion
stability, RTL mirroring, PNG/SVG export, pause/stop and cleanup. Each case samples
45 synchronous draws against a 25ms CPU budget. The first run's maximum p95 was
4.7ms. This is headless lab evidence, not measured display FPS, a real phone test,
or a production SLO. A visual contact sheet was inspected outside Git.

`engineering_os.cinematic.audit_inventory(request=None, *, now=None)` and
`catalog_report()` check the inspected inventory, current source hashes, receipt
freshness (at most 24h), unique browser/viewport matrices, pixel hashes, required
behavior and CPU budgets. Missing, stale, future, malformed, changed or failed
proof withdraws runtime eligibility. The default requires Chromium, Firefox and
WebKit, so its current all-browser operational count is **zero**. A request scoped
to Chromium reports the three actually tested local scenes while the receipt is
fresh. Historical PR16 implementations are never promoted by this report.
Receipts are reviewer-controlled local evidence, not authenticated attestation.

```python
from engineering_os.cinematic import audit_inventory
report = audit_inventory({
    'schema_version': 1, 'required_browsers': ['chromium'],
    'max_age_seconds': 86400, 'max_p95_ms': 25,
})
```

Three.js, WebGPU, WebGL, GSAP, Motion, Remotion, Blender, Rive, Lottie, React Three
Fiber, shader engines and GPU particle systems remain **not activated by this
change**. Their discovery records and prior adapters retain their own separate
review and evidence requirements. No paid service or new dependency is added.

## Reproduce

```sh
python3 -m unittest discover -s tests -p test_cinematic_intelligence.py -v
node --test tests/test_nextgen_camera.mjs
npm ci --ignore-scripts --no-audit --no-fund --cache /tmp/gaie-npm-cache --prefix motion-library/chromium-stack
MOTION_CHROMIUM_EXECUTABLE=/usr/bin/chromium NEXTGEN_CAMERA_RECEIPT=/tmp/nextgen-camera-chromium.json node tests/test_nextgen_camera_browser.mjs
```

The browser harness accepts `MOTION_BROWSER=firefox|webkit` with those reviewed
runtimes installed and `MOTION_PLAYWRIGHT_PACKAGE` pointing to the exact reviewed
package. It does not skip failed or unavailable browsers. Browser tests need a
local HTTP listener; restricted shells must grant that capability. No required
hub check is waived by this lane's focused checks.

The next increment should validate Firefox/WebKit and actual device behavior,
then implement a bounded next group from the 163 absent identities. Full films,
interactive products and connected digital twins still need their own acceptance
criteria, licensed assets, composition, application integration and project proof.
