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

## Purposeful motion policy

The owner's order of 2026-11-28 — adopt purposeful digital motions and forbid random motions — is
one file, `governance/policies/motion-purpose.json`, read by code and tests. It states the rule in
both languages:

> Every motion states, in one sentence per language, what it stands for in a digital service. A
> motion with no stated meaning is not added, and no motion draws from unseeded randomness.
>
> كل حركة تذكر، في جملة واحدة بكل لغة، ما تمثّله في خدمة رقمية. لا تُضاف حركة بلا معنى معلن، ولا ترسم
> أي حركة من عشوائية بلا بذرة.

The file holds the required shape of a meaning (exactly `ar` and `en`, 12–240 characters each,
Arabic script in `ar`), the five classes, the pinned lists, the forbidden source names and the
record of owner decisions. `python3 -m engineering_os.motion_policy` prints the report and exits 1
on a violation. Counts under policy 1.0.0, from that report:

| class | count | what it is |
|---|---|---|
| `purposeful` | 47 | 33 native motions and the 14 scene types of `packages/digital-shows`: each states a valid meaning |
| `legacy-unclassified` | 37 | the 34 native motions of PR #16 and the 3 nextgen camera scenes: no meaning stated |
| `reference-illustrative` | 400 | the Canvas2D reference recipes of `motion-library/expansion`: they illustrate a mechanism and claim no meaning |
| `specification-index` | 156 | the rows of `motion-library/MOTION_CATALOG.json` (127 specification, 29 implemented; each of the 30 components of `components.json` has a row) |
| `withdrawn` | 5 | ids removed as decorative; none has a source on disk |

### What is enforced where

| where | what it refuses or reports |
|---|---|
| `packages/motion-engines/tools/build_registry.mjs` (`scan()`, used by the registry, the browser harness, the sheet and the exporter) | a native motion with no `meaning` unless its id is in `legacy_ids`; an invalid meaning; a withdrawn id; a `legacy_ids` list longer than 34; a missing policy file. Such a motion cannot be registered, proven or exported. |
| `engineering_os/motion_policy.py` (`validate()`, `report()`) | every covered registry: a motion without a meaning that is not pinned, an invalid meaning, a pinned id that now states a meaning or is gone, a withdrawn id with a source or a registry row, a registry row whose `source_sha256` no longer matches its file, a 401st recipe or a 157th catalogue row, a show scene without a meaning, a new camera scene, a forbidden name in a covered source, a legacy id that left the list without a decision record. A record that cannot be read is a violation, never a pass. |
| `tests/test_motion_policy.py` (run by `python3 -m unittest discover -s tests`) | the real tree is clean; each violation above is produced on a temporary copy. |
| `tests/test_native_motions_digital.mjs`, `packages/motion-engines/test/purpose.test.mjs` | registry motions without a meaning are exactly `legacy_ids`; the camera scenes the module defines are exactly the pinned three; the source scan covers every covered source set; the builder refusals are provoked on temporary copies. |
| `packages/motion-engines/orchestrator.mjs` (`recommend()`) | each pick carries `policyClass` and `meaning`, and its first reason is the meaning or "no stated digital meaning (legacy-unclassified)". For `goal: 'operational'` a row whose `meaning` is `null` is left out unless `includeLegacy` is set, and then ranks below the purposeful ones. The builder writes `meaning` on every row; a row with no `meaning` key at all (a record older than the field) is answered as before, labelled. |

Some rules are fixed in `engineering_os/motion_policy.py` so that editing the policy file cannot
relax them: `legacy_ids` must be a subset of the 34 + 3 ids that existed before the rule,
`withdrawn_ids` must keep the five withdrawn ids, the pins cannot rise above 400 and 156, the limits
of a meaning cannot loosen past 12 and 240 characters, and every source set must keep its roots and
still refuse `Math.random()`, `crypto.getRandomValues()`, `crypto.randomUUID()` and a clock used as
a seed. The owner may tighten any of these in the file. Only the Python validator refuses a
duplicate JSON key in the policy; the registry builder reads it with `JSON.parse` and applies its
own fixed limits (12–240 characters, at most 34 legacy ids).

### Randomness

Forbidden in every covered source: `Math.random`, `crypto.getRandomValues`, `crypto.randomUUID`,
`randomBytes`, `randomInt`. Motion definitions (`packages/motion-engines/motions/**`,
`motion-library/expansion/*.mjs`, `packages/digital-shows/kit.mjs`) may also read no clock and set
no timer. Playback code (`packages/motion-engines` core, engines, shaders and adapters,
`packages/motion-sdk`, `motion-library/runtime`) may read a clock to advance the timeline, never
as a seed. **A seeded deterministic generator is allowed**, because the same seed draws the same
frames: `ctx.random(salt)` (mulberry32, `core/util.mjs`), `seeded(seed)` in the show kit and
`noise(i, seed)` in the recipes. The scan is a text screen (lines starting with `//` are skipped);
it does not detect a forbidden name built at run time, and it does not cover test, verify, render
and build tools or the Motion Lab and Motion Studio pages.

### What `legacy-unclassified` means

The 34 native motions of PR #16 (quantum 10, glass 10, atmosphere 10, and one each in typography,
micro, shaders and compositions) and the 3 nextgen camera scenes were built before the rule. Each is
deterministic and the 34 pass every browser check, so they are not random; but nobody has stated
what any of them stands for in a digital service, and five comparable drafts were withdrawn as
decorative. They are therefore not counted, presented or recommended as purposeful anywhere:
`meaning` is `null` in the registry, `counts.with_digital_meaning` stays 33, the report lists them by
id, and the orchestrator labels them. No meaning was written for them to reach 67 of 67: whether a
motion has a real digital meaning is the owner's decision, one motion at a time. Their sources were
not edited, so their browser evidence is unchanged.

### Promoting or withdrawing a legacy motion

With no decision an id stays `legacy-unclassified`. A decision is recorded in `owner_decisions.records`
as `{registry, id, decision, date, note}`; an id that leaves `legacy_ids` without one is a violation.

To **promote** a native motion:

1. The owner states the meaning; add `meaning: { en, ar }` to the motion source. The source hash
   changes, so the motion is `implemented-unverified` until step 2.
2. `node packages/motion-engines/verify/browser.mjs --id <id> --write`, then
   `node packages/motion-engines/tools/build_registry.mjs`.
3. In the policy, remove the id from `legacy_ids` and add the record with `"decision": "promoted"`.
   The validator accepts it only when the registry row is purposeful and `operational`.
4. `tools/native_inventory.mjs` counts every motion with a meaning as added in the batch of
   2026-11-28 (`BASELINE_ENGINE_MOTIONS = 34`), so its arithmetic and
   `docs/evidence/gaie-20-layers/native-motions.json` must be updated in the same change.
   `quantum-light-tunnel` and `atmosphere-core-ignition` are also the shots of
   `docs/evidence/gaie-20-layers/video-sample.json`, whose manifest is bound to their sources.

To **withdraw** a motion: delete its source, rebuild the registry, move the id from `legacy_ids` to
`withdrawn_ids` and add the record with `"decision": "withdrawn"`; step 4 applies as well. A camera
scene has no `meaning` field, so under policy 1.x it can stay legacy or be withdrawn (remove its row
from `nextgen-camera.mjs`, whose receipts are bound to that file); promoting one needs a format
that states the meaning, which is a change to the policy itself.

Then `python3 -m engineering_os.motion_policy` and the tests of step 5 below.

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
   `tools/build_registry.mjs` refuses a motion without a `meaning`, so it could not be proven
   or registered anyway (see "Purposeful motion policy").
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
5. `node --test packages/motion-engines/test/*.test.mjs tests/test_native_motions_digital.mjs` and
   `python3 -m unittest tests.test_motion_policy`.
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
- `docs/evidence/gaie-20-layers/video-sample.json` (cinematic agent) embeds a snapshot of
  `motion_inventory()` taken at render time, so
  `tests/test_video_pipeline.py::test_manifest_is_bound_to_current_sources` fails until the sample
  manifest is regenerated (or its `inventory` field refreshed) on top of this batch; the shots it
  renders (`quantum-light-tunnel`, `atmosphere-core-ignition`) are unchanged.
- `hublink.py` resolves `engine-motion:<id>` from the committed registry, so every new motion can
  be installed selectively once merged to main.
