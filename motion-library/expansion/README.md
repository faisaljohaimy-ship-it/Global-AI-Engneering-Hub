# Additive portable motion expansion 1.0.0

This is **new authored source**, not a claim to have recovered a missing original
400-motion archive. The previous motion catalog and runtime are preserved.

There are 200 separately authored base visual mechanisms: ten in each of the
twenty owner-requested categories. `families.mjs` and `systems.mjs` contain their
named executable geometry/field algorithms. There are also 200 advanced scene
compositions. Each pairs two different source mechanisms and one explicit
geometric coupling: focus handoff, counter-orbit, depth cascade, cross-axis
passage, signal transfer, radial triptych, folded dialogue, temporal braid,
editorial panels or convergent proof. The source pair and coupling are part of
the component's identity. They are not duration or color variations.

Every ID has Arabic/English names, source mapping, configuration, mobile and
directional behavior, a stable reduced-motion poster, an executable integration
example and a Motion Studio preview deep link. `definitions.json` is generated
from executable source with `node motion-library/expansion/generate.mjs`; use
`--check` to reject stale metadata.

## Actual engine and limits

All these new scenes use deterministic CPU mathematics and **Canvas2D**. Spatial,
camera, lighting, shader and quantum names describe illustrative visual mechanisms.
They do not claim a live digital twin, physical solver, quantum computation,
training/inference session, WebGPU implementation, installed Three.js/Remotion,
or a multi-engine GPU render. Projected wire geometry is a portable 2D reference
for a spatial icon. Optional engine integrations remain separate capabilities.
The category named multi-engine compositions contains portable reference
compositions; it does not prove simultaneous execution of optional engines.

The sampler limits detail on mobile/advanced scenes, primitive count to 256 and
points per path to 160. It returns geometry in logical LTR coordinates or mirrors
all geometry for RTL without reversing text. Intensity controls geometric extent.
Seed provides a tiny deterministic composition offset, not model randomness.
Reduced-motion mode always returns the same representative pose at progress .65.

## Integrate selectively

```js
import * as catalog from './motion-library/expansion/catalog.mjs';
import {motion} from './packages/motion-sdk/index.mjs';
motion.registerCatalog(catalog);
const player = motion.create('os-quantum-b01', {container: document.querySelector('#stage')});
player.play();
// player.destroy() when unmounting.
```

For a renderer-independent integration, call
`sampleMotion(id, progress, {width, height, rtl, reducedMotion})`. It returns only
the documented circle, line, polyline, rect and text primitives. It performs no
DOM manipulation, network access, provider authentication or installation.
`examples.mjs` exports an executable example for every ID.

## Verification and evidence

`node --test tests/test_motion_expansion.mjs` checks all 400 source graphs,
style-stripped sampled geometry uniqueness, determinism, animated change,
mobile/desktop bounds, every RTL reflection, every static poster, input rejection
and integration examples. It is **not** browser rendering evidence.

Actual browser pixels and per-ID sampling/draw benchmarks are produced separately
by `tests/test_motion_studio_browser.mjs`, after integration with the Universal
Motion SDK. A receipt belongs to the source digests and browser version it tested.
Metadata deliberately says `pending-browser-evidence`: the implementation count
must not silently become a browser/GPU/real-device/FPS claim. Read current receipts
to determine verified count. Measured CPU sampling/draw time is not 60/120 FPS,
Lighthouse, INP, real mobile hardware or production telemetry.

New expansion files only are MIT licensed under `LICENSE`. No private assets,
external source, audio or media were copied into this expansion.
