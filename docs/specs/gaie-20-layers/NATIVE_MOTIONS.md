# L08 — Native engine motions

Native motions are the **original, engine-native** motions of `packages/motion-engines`: each one
is a single file that draws on a real engine (WebGL2 GLSL, WebGL2 GPU points, WebGPU WGSL with a
WebGL2 fallback, Canvas 2D, DOM, SVG, multi-engine compositions) behind one instance API
(`create`, `play`, `pause`, `resume`, `reverse`, `stop`, `render`, `export`, `destroy`). They are a
separate namespace from the 400 Canvas2D reference recipes of `motion-library/expansion`, and the
two are never added together (`engineering_os/cinematic.motion_inventory()` checks that).

The target is the owner's brief of 200 named motions (`packages/motion-engines/tools/brief.json`).

## Inventory

All numbers come from `docs/evidence/gaie-20-layers/native-motions.json`, which
`packages/motion-engines/tools/native_inventory.mjs` writes from the registry, the browser evidence
and the brief (nothing is typed by hand; `--check` fails when it is stale).

| | count |
|---|---|
| Native engine motions before this batch (PR #16) | 34 |
| Nextgen camera scenes (PR #25, `motion-library/expansion/nextgen-camera.mjs`) | 3 |
| **Baseline** | **37** |
| Added and verified in this batch | **33** |
| **Native total** | **70** |
| Remaining to the 200-name target | **130** |

The 33 new motions by engine: Canvas 2D 17, WebGL2 GLSL 8, WebGL2 GPU points 5, SVG 2, DOM 1.
By module: camera 5, dashboard 4, particles 4, neural 3, physics 3, transitions 3, networks 2,
twin 2, story 2, micro 2, shaders 2, hologram 1.

None of the new ids is one of the three nextgen camera scenes (`camera-infinite-flythrough`,
`camera-drone-approach`, `camera-macro-to-micro`), so nothing is counted twice; the test
`tests/test_native_motions_digital.mjs` enforces it.

## Owner direction: every motion means something digital

On 2026-11-28 the owner asked that motions not be random but tell a digital-transformation story.
Every motion added from this batch on therefore carries a `meaning` field — one English and one
Arabic sentence saying what it stands for in a digital service:

```js
meaning: {
  en: 'Paper to digital: a paper application is scanned into a digital form, completed and approved in one flow.',
  ar: 'من الورق إلى الرقمي: يُمسح طلبٌ ورقي ليصبح نموذجًا رقميًّا يُستكمل ويُعتمد في مسارٍ واحد.',
},
```

`tools/build_registry.mjs` validates it (`validMeaning`: exactly `en` and `ar`, 12–240 characters,
Arabic script in `ar`) and copies it into `registry.json` (`null` for the 34 earlier motions;
`counts.with_digital_meaning`). No motion uses an official logo, emblem, flag or map: identity
cards, portals, phones and city grids are generic drawings.

Five motions drafted and verified in this batch were **withdrawn before counting** because their
meaning was only decorative: `lighting-lens-flare`, `lighting-studio-spotlight`,
`lighting-volumetric-beams`, `shaders-raymarched-geometry`, `shaders-sdf-morph` (two physics drafts,
cloth and rigid collision, were dropped unsubmitted for the same reason). Four kept motions were
redrawn to make their meaning visible: the orbiting bodies became communication satellites with
downlinks, the parallax landscape a smart city with connected street lights, the curtain reveal now
unveils an app screen, and the disintegrating shape is a record card.

## Catalogue of the batch

| # | id | engine | kind | direction | digital meaning |
|---|---|---|---|---|---|
| 11 | `camera-dolly-in` | canvas2d | oneshot | neutral | A walk down a corridor of separate service screens into one unified digital portal. |
| 12 | `camera-dolly-out` | webgl2-glsl | oneshot | neutral | Zooming out from one core platform to show the ring of connected digital services that depend on it. |
| 15 | `camera-focus-pull` | webgl2-glsl | oneshot | neutral | Attention shifts from the alerts on a user's device to the digital service hub, then to the city's connected infrastructure behind it. |
| 16 | `camera-parallax-tracking` | canvas2d | loop | mirror | Tracking past a smart city: layered districts behind, connected street lights reporting their status in the foreground. |
| 20 | `camera-spatial-roll` | webgl2-glsl | oneshot | neutral | A flight along a network backbone lined with edge nodes, turning to inspect the infrastructure from every angle. |
| 22 | `hologram-scanline-reveal` | canvas2d | oneshot | neutral | Identity verification: a digital ID is scanned field by field and confirmed before access is granted. |
| 47 | `neural-task-orchestration` | canvas2d | loop | neutral | Human approval gate: AI agents do the work, but nothing is released until a person approves it. |
| 48 | `neural-inference-pipeline` | canvas2d | loop | neutral | AI inference: input data goes into a trained model, passes through its layers and comes out as one decision. |
| 50 | `neural-embedding-space` | webgl2-points | oneshot | neutral | An AI model groups incoming requests or documents by meaning, so similar cases cluster together for routing. |
| 57 | `twin-sensor-propagation` | webgl2-glsl | loop | neutral | An IoT smart-city grid: street sensors report their readings, and each report travels the street network to the central gateway. |
| 60 | `twin-risk-heatmap` | webgl2-glsl | loop | neutral | Real-time risk monitoring of a facility's digital twin: hotspots rise and the room under the worst one is flagged. |
| 61 | `particles-gpu-swarm` | webgl2-points | loop | neutral | Three streams of requests follow a load-balanced route through the network, stretching and bunching with the traffic. |
| 66 | `particles-vortex` | webgl2-points | loop | neutral | An ingestion funnel: a wide intake of raw events is drawn into one fast, narrow processing stream. |
| 67 | `particles-disintegration` | webgl2-points | oneshot | neutral | Secure disposal of a retired data record: it is shredded beyond recovery once its retention period ends. |
| 69 | `particles-path-convergence` | webgl2-points | oneshot | neutral | Data from many separate sources converges into one unified platform. |
| 96 | `micro-toggle-transformation` | dom | loop | text | Turning on two-step verification: a digital account setting switches its security protection on and off. |
| 100 | `micro-success-feedback` | svg | oneshot | neutral | Audit trail: a completed digital transaction issues a receipt with a reference code and an approval stamp. |
| 101 | `dashboard-kpi-flow` | canvas2d | loop | text | The KPI counters of a digital service update in real time, each with its recent trend. |
| 106 | `dashboard-sankey-flow` | canvas2d | loop | mirror | A data pipeline (ETL): records flow from source systems through processing stages into outcomes, in proportion to their volume. |
| 108 | `dashboard-time-series-reveal` | canvas2d | oneshot | mirror | A live operations metric is plotted against a comparison period and read point by point as the data arrives. |
| 109 | `dashboard-signal-pulse` | svg | loop | neutral | Real-time monitoring: a live service signal is watched continuously, and an incident raises an alert until the service recovers. |
| 113 | `transitions-mask-reveal` | canvas2d | oneshot | neutral | Moving from the operations dashboard to a citizen-facing service page in one continuous step. |
| 118 | `transitions-curtain-reveal` | canvas2d | oneshot | neutral | Launch day: a new digital service is unveiled and its app screen appears from behind the curtains. |
| 119 | `transitions-fragment-transition` | canvas2d | oneshot | neutral | Breaking out of a legacy screen: the old interface shatters and the new digital interface is waiting underneath. |
| 125 | `physics-gravitational-orbit` | canvas2d | loop | neutral | Satellite connectivity: communication satellites circle the Earth on elliptical orbits, fastest where they pass closest. |
| 127 | `physics-spring-motion` | canvas2d | oneshot | neutral | Tuning interface motion for a digital product: spring presets are compared side by side before they enter the design system. |
| 130 | `physics-metaball-fusion` | webgl2-glsl | loop | neutral | Duplicate records from separate systems merge into one master record when they match, and part again when they do not. |
| 136 | `shaders-chromatic-aberration` | webgl2-glsl | oneshot | neutral | System cut-over: the legacy interface switches to the new digital platform in one controlled glitch. |
| 140 | `shaders-material-dissolve` | webgl2-glsl | oneshot | neutral | Legacy modernisation: the old metal layer burns away to reveal the live digital circuitry beneath it. |
| 162 | `networks-data-transmission` | canvas2d | loop | neutral | An API handshake: the client is authenticated by the gateway before its data is routed across the service mesh and acknowledged. |
| 169 | `networks-distributed-system` | canvas2d | loop | neutral | Zero trust: no call between services is trusted by default; each one is verified at the service it reaches, and an unverified call is refused. |
| 184 | `story-system-evolution` | canvas2d | oneshot | neutral | Cloud migration: workloads move from on-premise servers to the cloud, and the old racks are retired. |
| 189 | `story-transformation-journey` | canvas2d | oneshot | neutral | Paper to digital: a paper application is scanned into a digital form, completed and approved in one flow. |

Interactive: `transitions-curtain-reveal` (pointer x opens the curtains) and
`dashboard-sankey-flow` (the band under the pointer is highlighted); both return exactly to the
scripted frame when the input is released. `micro-toggle-transformation` also exports
`respond(input, params)` so the knob response can be attached to a real switch
(`adapters/behaviour.mjs`).

## How each motion is proven

`node packages/motion-engines/verify/browser.mjs --id <id>` creates the motion in headless Chromium
(Playwright) at 320x180 and fails it unless every check of `packages/motion-engines/CONTRACT.md`
holds: it draws (≥ 6 colours, ≥ 1 % of pixels off the background), frames at 10/35/60/85 % differ,
the same moment gives byte-identical pixels in the same and in a second instance (determinism:
seeded `ctx.random`, time only from `state`, physics run in closed form or simulated once up front),
palette, every parameter, every text string, duration and easing visibly change the frame, the
transport works, **reduced motion draws exactly one still frame and schedules nothing**, direction
is neutral / mirrored / Arabic right-to-left as declared, a 180x320 portrait frame is filled, the
low quality tier draws fewer pixels and still a picture, frames export, `destroy` removes every node
and GPU context, the heap does not grow per instance, and there are no page errors. A full run
also fails any two motions that draw the same frames.

The batch was proven by a full run over all 67 engine motions (`--write`), which rewrote
`packages/motion-engines/evidence/chromium.json`; each row is bound to the motion's source SHA-256
and the SDK core SHA-256, and the registry marks a motion `operational` only while both match.
`docs/evidence/gaie-20-layers/native-motions.json` records, per new motion, its source hash, its
frame signature (the FNV-1a hashes of four frames), the number of checks passed and the average
frame time. Re-running the harness reproduces the same signatures; `tests/test_native_motions_browser.mjs`
re-renders one motion per engine and compares.

Honest limits: rendering is **SwiftShader** (Chromium's CPU implementation of WebGL2/WebGPU); no
hardware GPU ran these motions and none is claimed. Frame times are measured on that software
renderer at 320x180 and only say the motions are cheap, not how they run on a phone. Firefox and
WebKit were not run (`compatibility.browsers` says `not-run`).

## Adding the remaining 130

1. Pick an id from `remaining_brief_ids` in `docs/evidence/gaie-20-layers/native-motions.json`
   (never one of the three nextgen camera ids) and decide its digital meaning first: if it cannot be
   said in one sentence about a digital service, do not build it.
2. Write `packages/motion-engines/motions/<module>/<slug>.mjs` following `CONTRACT.md`: `number` and
   `name.en` exactly as in the brief, Arabic `name`, `summary` and `meaning`, at least two
   parameters that each change the picture, `still` for reduced motion, `ctx.count()` for anything
   that costs time. Only `core/`, `engines/` and `shaders/` may be imported; no third-party code.
3. `node packages/motion-engines/verify/browser.mjs --id <id>` until it passes, then look at it:
   `node packages/motion-engines/verify/sheet.mjs --id <id> --out /tmp/sheet.png` (and
   `--direction rtl` for text or mirrored motions).
4. `node packages/motion-engines/verify/browser.mjs --id <id> --write`, then
   `node packages/motion-engines/tools/build_registry.mjs` and
   `node packages/motion-engines/tools/native_inventory.mjs`.
5. `node --test packages/motion-engines/test/*.test.mjs tests/test_native_motions_digital.mjs`.
   Before merging a batch, run the harness once over everything (no `--id`, with `--write`) so
   that frame uniqueness is checked across all motions.

Remaining by module (from the evidence file): quantum 0, camera 2 (crane reveal, orbital sweep),
hologram 9, glass 0, neural 7, twin 8, particles 6, lighting 10, typography 9, micro 7,
dashboard 6, transitions 7, physics 7, shaders 7, icons 10, product 10, networks 8,
atmosphere 0, story 8, compositions 9.

## Integration notes

- `engineering_os/cinematic.motion_inventory()` reads the registry directly, so its
  `native_engine_motions.count` becomes 67 and `native_total` 70 with no code change.
  `tests/test_cinematic_intelligence.py::test_motion_inventory_keeps_native_and_reference_counts_apart`
  (owned by the cinematic agent) still hard-codes the PR #16 numbers (34 / 37, `by_engine`, GPU 26 /
  CPU 8) and must be updated with this batch: count 67, by_engine
  `{'canvas2d': 22, 'composition': 1, 'dom': 2, 'svg': 3, 'webgl2-glsl': 31, 'webgl2-points': 7, 'webgpu-wgsl': 1}`,
  GPU-API 39, CPU 28, native_total 70.
- `hublink.py` resolves `engine-motion:<id>` from the committed registry, so every new motion can
  be installed selectively once merged to main.
