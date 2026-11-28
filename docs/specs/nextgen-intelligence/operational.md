# Operational acceptance for PR #25

Resume at `9789272a817a794868775e939634e939498ca858`. Preserve prior source,
contracts and evidence. Independent Codex worktrees use the existing private
lease store. Clause-level verification is reported with its actual scope.

| Deliverable | Acceptance |
|---|---|
| Twenty layers | Twenty stable layer IDs with named, executable local contracts. Every suite runs and passes without skips. Source digests are returned for each layer. |
| Reasoning | Compute and verify a capacity-bounded dependency schedule plus fresh plan-bound review and verification. |
| Memory | Persist and search project records and Python symbols. Reject cross-project references and replay a checksummed checkpoint. Apply file indexing atomically. |
| Factory | Generate application code, schema and an API contract from bounded structured requirements. Validate HTTP behavior and persistence against the generated system before publishing an isolated output. |
| Healing | Reproduce faulty settings with real SQLite behavior, verify fixed behavior and replay exact restored bytes. |
| Cinematic | Register only authored brief identities. Render samples at desktop and mobile viewports on Chromium, Firefox and WebKit. Require a complete current-source-bound receipt per engine. |
| Economics | Measure real local runtime and reconcile supplied team usage with verified denominators. Preserve unknown billing, token counts and subscription data. |
| Performance | Preserve existing drawing quality and CPU thresholds. Run the unchanged Studio browser gate on the same reviewed runtime and compare time and rendered pixels. |
| Claude Code | Expose bounded local operations through project MCP. Exercise each surfaced operation through JSON-RPC and track native Claude host evidence separately. |
| Approval | Preserve existing mandatory workflows and run verification on the PR head. Publish deliberate limits and unresolved criteria for approval. |

The 163 missing original identities are tracked independently from the 400
reference recipes. An illustration is eligible only when it implements the named
behavior at its stated scope. Hardware-dependent effects need genuine engine
support and proof. The deterministic offline generation and repair contracts cover
specific supported application and configuration classes. External model access
requires a separately reviewed runtime and authorization.

## Original motion runtime

The original brief contains 200 identities. PR #16 holds the historical source
for 34. This branch has the preceding three plus all 163 remaining identities.
The reference catalogue of 400 scenes keeps its separate identifiers and proof.
The original manifest binds the Canvas2D IDs to their authored modules. A Node
acceptance test checks that every original outside PR #16 appears exactly once
across the Canvas2D and WebGL2 libraries.

| Renderer | Identities | Chromium | Firefox | WebKit |
|---|---:|---:|---:|---:|
| Canvas2D | 154 | 308 cases, max p95 2.6 ms | 308 cases, max p95 7 ms | 308 cases, max p95 8 ms |
| WebGL2 | 12 | 24 cases, max p95 2.2 ms | 24 cases, max p95 7 ms | 24 cases, max p95 3 ms |

Each case tests rendered pixel changes, exact deterministic replay, reduced
motion, RTL, cleanup, export and a 25 ms draw budget. The browser environments
are local laboratory profiles. The twelve WebGL2 identities include nine
shader programs, a 2,048 point vertex shader, a GPU interface transformation
and a composition with a real Canvas2D texture feeding WebGL2. The WebGL2
profile caps the source framebuffer at 416 pixels on its longest edge. Tests
use displayed viewport dimensions of 390×844 and 1280×720. Chromium used
SwiftShader and headed Firefox used llvmpipe on an isolated Xvfb display.
Renderer strings do not establish hardware acceleration. Real devices,
uncapped GPU performance and presentation FPS still need their own tests.

Use the existing SDK to render the Canvas2D catalogue and the local WebGL2
module for the shader catalogue.

```js
import {createMotionSystem} from './packages/motion-sdk/index.mjs';
import * as originals from './motion-library/expansion/nextgen-catalog.mjs';
import {createMotion} from './motion-library/expansion/nextgen-motion-webgl.mjs';

const system = createMotionSystem();
system.registerCatalog(originals);
const classic = system.create('camera-orbital-sweep', {container: preview});
const shader = createMotion(canvas, 'shaders-sdf-morph');
classic.render(0.5);
shader.render(0.5);
```

Destroy each instance when its view unmounts. Pointer reactions use the SDK
interaction coordinates. Some scenes show generated data and illustrative
systems. Variable typography uses procedural vector strokes. The view
transition samples composed layout states. The audio visualization has a
bounded PCM sampler and uses a synthetic input by default. Connected data,
OpenType assets, native View Transition APIs and device audio permissions
remain consuming project decisions.

`cinematic` checks the exact six browser receipt files against their pinned
digests and current source. The 24-hour window applies to recorded runtime
claims. The browser matrix in GitHub Actions emits fresh evidence for each run.
The unmerged 34 identities retain their own evidence and review requirements.

## Studio performance and host compatibility

The shared SDK now validates a draw once, uses the same validated primitive
colors, avoids unchanged CSS writes, and reserves copies for public snapshots.
The original Motion Studio test covered 400 recipes in two viewports. Its
source-binding checks, 16.667 ms drawing budget and sampling quality remain in
force. On the matched Chromium lab runs, all 2,400 pixel hashes, primitive
counts and changed pixel counts agreed. Desktop worst recipe
p95 moved from 27.2 ms to 7.4 ms. Mobile worst moved from 5.8 ms to 13.8 ms and
passed the same budget. Chromium, Firefox and WebKit each completed the unchanged
400-recipe suite on the optimized SDK. The first local WebKit run exceeded a
desktop budget and the subsequent run used three-core affinity. Local results
depend on the host and rendering load. The recorded Lighthouse and axe audit
passed both viewport profiles.

The native smoke run used the pinned official Claude Code 2.1.332 package in an
isolated configuration without model credentials. The host discovered the
repository MCP configuration and showed its normal approval prompt. An explicit
disposable local registration connected. The wire trace recorded `initialize`,
`notifications/initialized` and `tools/list`. The stdio integration tests called
the actual local tools, including factory generation, SQLite repair and replay,
runtime measurement and architecture. A model-driven tool call in a signed-in
Claude session still requires the user's ordinary host approval and access.

The verified factory profile generates typed CRUD, SQLite, OpenAPI and a runnable
HTTP service over a private Unix socket. Tests cover three restarts and refuse
existing destinations. The verified healing profile reproduces SQLite ingestion
failures, chooses fixed settings and replays exact rollback bytes. Reasoning
handles deterministic schedule comparison, fresh evidence and independent review
receipts. Memory applies indexing atomically and rejects changing file snapshots.
Economics measures actual local operation time, with token billing and provider
allowance absent without their own receipts. Arbitrary application types, live
inference, embedding generation and scoped production deployment remain outside
these local profiles.
