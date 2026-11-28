# GAIE OS — Engineering Control Plane (layer L04)

Status: implemented (wave 1 on `gaie/w1-control-plane`; the wave-2 engines and actions were
registered by the control-plane integration lane). Contracts: [CONTRACTS.md](CONTRACTS.md) §2, §4, §5.
Code: `governance/engines.json`, `engineering_os/control_plane.py`, `engineering_os/adapters.py`,
`hub.py engines | engine-health | invoke`, tests in `tests/test_control_plane.py` and
`tests/test_engine_registry_w2.py`.

The control plane is one registry and one governed way in for every engine. It owns no
engineering logic: every action is a thin adapter over the module that already
implements it. It makes no model, provider, network or deployment call. Deterministic
logic only; there is no AI-model reasoning anywhere on this path.

## 1. Engine map

22 engines with 118 actions, on 16 owning layers; the table equals `python3 hub.py engines`.
L05, L07, L10 and L20 own no engine. Each engine's layer is the one `governance/layers.json`
gives its module; the wave-2 engines are `orchestrator` (L03), `security-audit` (L09),
`requirements` (L15) and `cinematic-production` (L18). The L20 assurance engine and a release
engine are written by other lanes and are registered later (section 6).

| Engine | Layer | Module(s) | Actions → side effect |
|---|---|---|---|
| `security-governor` | L01 | `engineering_os/governor.py`, `contracts.validate_grant` | `check` none, `validate-grant` none |
| `context-intelligence` | L02 | `tools/headroom_context.py` (status/retrieve/optimize), `skills/ultra-context-optimization/scripts/hr.py` (view) | `status` none, `view` none, `retrieve` none, `optimize` state-write |
| `master-router` | L03 | `engineering_os/gaie_router.py` | `route` none, `projects` none |
| `agent-swarm` | L03 | `swarm/scheduler.py` (`plan`, `simulate`; path-loaded, read-only) | `plan` none, `simulate` none |
| `adaptive-scheduler` | L03 | `swarm/phase3/adaptive.py` (`next_wave`; path-loaded, read-only) | `next-wave` none |
| `orchestrator` | L03 | `engineering_os/orchestrator.py` (`engine`: plan, schedule, review_assignment, worktree_plan, scenario_h) | `plan` none, `schedule` none, `review-assignment` none, `worktree-plan` none, `scenario-h` none |
| `capability-registry` | L04 | `engineering_os/control.py` (`capabilities`, `integrations`, `architecture`), `hub.registry`/`hub.recommend` | `list` none, `search` none, `recommend` none, `integrations` none, `architecture` none |
| `layers` | L04 | `engineering_os/layers.py` (`status`, `verify`), `governance/layers.json`, `governance/agent-roles.json` | `status` none, `verify` state-write |
| `master-upgrade` | L06 | `engineering_os/factory.py` + route `upgrade`/`accelerate`/`repair`, `skills/gaie-upgrade`, `prompts/MASTER_UPGRADE.md`; `engineering_os/upgrade_engine.py` (`audit`, `upgrade`) | `spec` none, `plan` none, `evaluate` none, `audit` none, `upgrade` workspace-write |
| `motion-sdk` | L08 | `hub.motion_catalog`/`hub.motion_components`, `control.motions` | `catalog` none, `components` none, `runtime` none |
| `quality-assurance` | L09 | `governor.sandbox_run` + `unittest`; `contracts.validate_engines`/`validate_layers` | `run-tests` workspace-write, `contracts` none |
| `security-audit` | L09 | `engineering_os/security_audit.py` (`run`, `audit_anchor`, `verify_audit_anchor`) | `scan` none, `audit` workspace-write, `anchor` none, `verify-anchor` none |
| `master-release` | L11 | `scripts/verify_release.py` (`approved_runs`, `approved_jobs`), `sdk/engineering_sdk.release`, `skills/gaie-release` | `spec` none, `provenance` none, `eligibility` none |
| `master-audit` | L12 | `engineering_os/gaie_inventory.py`, `control.health`, `hub.audit`, `skills/gaie-audit` | `spec` none, `inventory` none, `health` none, `hub-audit` none |
| `reasoning` | L13 | `engineering_os/reasoning.py` (`plan`, `review_decision`, `root_causes`; the rest through `reasoning.engine`) | `plan` none, `review` none, `root-causes` none, `strategy` none, `decompose` none, `plan-goal` none, `constraints` none, `dependencies` none, `rca` none, `counterfactual` none, `uncertainty` none, `perspectives` none, `validate-decision` none, `trade-off` none, `route-model` none |
| `memory` | L14 | `engineering_os/memory.py` (`MemoryStore`, via `adapters.memory_store`; one store, reads never create it) | `put` state-write, `search` none, `graph` none, `index` state-write, `checkpoint` state-write, `restore` state-write, `verify` state-write, `retrieve` none, `neighbours` none, `path` none, `adr-get` none, `why` none, `solutions` none, `failure-recall` none, `next-steps` none, `brief` none, `where` none, `evidence-status` none, `adr-add` state-write, `adr-status` state-write, `failure-record` state-write, `task-progress` state-write |
| `requirements` | L15 | `engineering_os/requirements.py` (`engine`: parse, refine, validate_spec, diff_specs, acceptance_checks, domain_packs) | `parse` none, `refine` none, `validate` none, `diff` none, `acceptance` none, `packs` none |
| `master-build` | L16 | `engineering_os/factory.py` + route `build`, `skills/gaie-build`, `prompts/MASTER_BUILD.md`; `engineering_os/build_engine.py` (`plan`, `build`, `evaluate`, `request_repository`; `publish` not registered) | `spec` none, `plan` none, `evaluate` none, `plan-app` none, `build` workspace-write, `evaluate-app` none, `request-repository` workspace-write |
| `self-healing` | L17 | `engineering_os/healing.py` (`analyze`, `verify_repair`, `heal`), `engineering_os/detectors.py` (`run_all`, static only) | `analyze` none, `verify-repair` workspace-write, `detect` none, `heal` workspace-write |
| `master-cinematic` | L18 | `engineering_os/cinematic.py` + route `cinematic`, `skills/gaie-cinematic` | `spec` none, `audit` none |
| `cinematic-production` | L18 | `engineering_os/video_pipeline.py` (imported, not edited: `inventory`, `validate_storyboard`, `direct`, subtitles, `browser_probe`, `render`, `qa_media`) | `inventory` none, `validate` none, `direct` none, `subtitles` none, `probe` workspace-write, `render` workspace-write, `qa` workspace-write |
| `economics` | L19 | `engineering_os/economics.py` (+ `model_router.select_model` via `recommend_model`; the rest through `economics.engine`), control-plane ledger | `summarize` none, `recommend-model` none, `ledger` none, `assess` none, `recommend-concurrency` none, `estimate-scope` none, `estimate-infrastructure` none, `estimate-maintenance` none, `estimate-rework` none, `context-footprint` none, `measured-baseline` none |

Side-effect classes are honest: an action is `none` only when it writes nothing (a read of
an absent memory store returns empty instead of creating it); `verify-repair` and
`run-tests` write disposable files, so they are `workspace-write`; `optimize` writes the
private context store and starts the pinned SDK worker behind its no-IP boundary. An
action that executes code or host tools in child processes (`exec:sandbox`: `build`,
`upgrade`, `heal`, `security-audit.audit`, `cinematic-production.probe/render/qa`) is
`workspace-write` even when it only writes temporary files, because the router's permission
floor puts `exec:sandbox` there and the read-only rule of `invoke` refuses anything but read
permissions on a `none` action. These children run under Python-level guards
(`detectors.Sandbox`, fixed drivers), not an OS sandbox: governing them adds authorization,
audit and accounting, not isolation. No registered action pushes, publishes or deploys, so
nothing is `repo-write` or above and no action needs an approval token in this revision.
Tests enforce that `none` ⇔ no `write:*` permission and that every action is at most
`workspace-write`. Engine ids are stable; the real build/upgrade/heal generators of wave 2
are actions of `master-build`, `master-upgrade` and `self-healing`, not new engines.

Gated steps stay unregistered: `build_engine.publish` (external-write push to an
owner-created remote) and the router's gated steps `master-build:create-repository`,
`master-release:preview` and `master-release:promote` have no control-plane action.
`master-build.request-repository` only writes the owner's request file. One name per gated
step across `gaie-routes.json` and `build_engine` is a router-policy change
(`create-repository` → `publish`), requested from the router owner, not made here.

Payload fields that name a filesystem location (`adapters.PATH_FIELDS`, also shown by
`describe(id)["path_fields"]`) are passed to the governor as `paths=` so it can check them
against the grant after `realpath`: `route.workspace`, `evaluate.artifact_root`,
`inventory.target`, audit `health.project`, `eligibility.root`, memory `search/index.source_root`,
`checkpoint.destination`, `restore.checkpoint`, `verify.source_root/receipt_path`, `optimize.input`.
The wave-2 location fields (`adapters.CANONICAL_PATH_FIELDS`) must in addition be canonical
before the governor is asked (absolute, normalized, no `..`, no symbolic link in any existing
component; refused as a malformed request otherwise): `worktree-plan.repo/base_dir`,
`render.out_dir/voiceover_dir/music_file`, `qa.path`, `build.out_dir/workspace`,
`evaluate-app.app_dir`, `request-repository.app_dir`, master-upgrade `audit/upgrade.target/workdir`,
`detect.target`, `heal.target/workdir`, and the optional `source_root` of the memory reads.
`quality-assurance.run-tests` and `security-audit.audit` always read the hub checkout, so their
grant must cover it. The governed `build` takes an explicit `workspace` (no fallback to
`$GAIE_HOME`), and `render` an explicit `out_dir` (no fallback to the private state directory).

## 2. Duplicates found and how they are unified

| Found | Decision |
|---|---|
| Two memories: `memory.MemoryStore` (locked, checksummed JSON in a private state dir; used by `intelligence.dispatch`) and `gaie_memory.Memory` (hash-chained JSONL under `$GAIE_HOME/memory/<project>`; used by the gaie skills) | Unified: `MemoryStore` is the engine and `gaie_memory` is a facade over it ([MEMORY.md](MEMORY.md)). The control plane opens it **only** through `adapters.memory_store(ctx, read_only=...)`, the single switch point; all 22 `memory.ENGINE_RECORD` actions use that one store (reads read-only, never creating it). There is no implicit task checkpoint: a checkpoint is the explicit `memory.checkpoint` action under its own state-write grant. |
| Three motion inventories: `motion-sdk.catalog` (the motion catalog and its components), `master-cinematic.audit` (cinematic briefs) and `video_pipeline.inventory` (native engine motions from `packages/motion-engines/registry.json`) | Different questions, each reachable once: the native inventory is `cinematic-production.inventory` (registry-derived `native_total`), kept apart from the Canvas2D reference recipes it counts separately. |
| Ungoverned module CLIs: `python3 -m engineering_os.<orchestrator, requirements, security_audit, video_pipeline, build_engine, upgrade_engine>` | Kept as facades (listed in `supersedes` for the four wave-2 engines); they run without a grant, audit row or ledger row. Governed callers use `invoke`; `hub.py` has no build or upgrade command. |
| Two routers: `gaie_router` (owner command → engine, skill, workstreams, gates; L03) and `model_router` (model selection under policy, evidence, budget; L02) | Different concerns, deliberately **not** merged. `gaie_router` is `master-router`; `model_router` is reached only through `economics.recommend-model` (the existing `economics.recommend_model` facade), with an empty environment so host credentials are never consulted. |
| Two dispatchers: `intelligence.dispatch` (16 ungoverned local operations) and `control_plane.invoke` | `intelligence.dispatch` is unchanged (its tests keep passing) and stays as a facade; each engine lists the operations it supersedes in `supersedes` (`intelligence.dispatch:reasoning-plan`, …). New callers use `invoke`. Routing dispatch through the control plane is a later, owner-reviewed change (it would add a grant requirement). |
| Hub audit in two places of the brief (master-audit and quality-assurance) | One owner: `master-audit.hub-audit`. `quality-assurance` adds what is not duplicated: the sandboxed unittest runner and the registry contract check. |
| `control.motions` named for both master-cinematic and motion-sdk | One owner: `motion-sdk.runtime`. `master-cinematic.audit` is the cinematic inventory (`cinematic.audit_inventory`), which already binds its own browser receipts. |
| Headroom: `tools/headroom_context.py` and `skills/ultra-context-optimization/scripts/hr.py` | Already one integration (hr.py is the front end of the tool). `context-intelligence` wraps the tool for status/retrieve/optimize and hr's pure `plain_view`/`must_keep` for `view`; one store under the private state dir. |
| Four schedulers: `swarm/scheduler.plan` (who does which task in which wave), `swarm/phase3/adaptive.next_wave` (how many agents next), `reasoning.plan` (rank alternatives, dependency waves of plan nodes), `orchestration.TaskStore` (leases) | Different questions; each registered once (`agent-swarm`, `adaptive-scheduler`, `reasoning`). The swarm files are owned by the swarm session and are only path-loaded read-only (no `sys.modules` entry, `sys.path` restored); `own`/`submit`/`checkpoint` and the swarm setup scripts are not exposed. |
| Two economics modules: `engineering_os/economics.py` and `swarm/phase3/economics.py` (+ `swarm/phase3/ledger.py`) | `economics` wraps the engineering_os module; the swarm modules are experiment tooling owned by the swarm session and are not registered. |
| Build and upgrade share `factory.plan_factory` / `evaluate_factory` | Two engines with stable ids because their routes, prompts and skills differ; the shared factory code is one implementation. |
| Two canonical-JSON helpers: `contracts.canonical` (`allow_nan` default) and `orchestration.canonical` (`allow_nan=False`, bytes) | The control plane validates with the strict helper, then hashes with `contracts.sha256`; digests are identical for finite data. Recommendation for the contracts owner: set `allow_nan=False` in `contracts.canonical`. |
| Two layer projections: `control.LAYERS` (12) and `contracts.LAYER_IDS` (20) | `governance/layers.json` is the twenty-layer registry (engine `layers`); `capability-registry.architecture` keeps reporting the existing 12-layer projection unchanged. |

## 3. Invocation flow

```
caller ── invoke(engine, action, payload, *, grant, ctx) ──────────────────────────────────
  │ 1 ctx: only state_dir (absolute, outside Git, no symlink), task_id, project, host, now,
  │        approval_token, environ                                  ── else ControlPlaneError
  │ 2 governor installed?                                            ── else refuse (fail closed)
  │ 3 payload: object, finite strict JSON, ≤ 1 MiB → request_sha256
  │ 4 engine/action in governance/engines.json (validated contract)  ── else reject + audit
  │ 5 paths = adapters.request_paths(payload)                        ── malformed → reject + audit
  ▼
governor.check(grant, engine, action, action_spec, paths, approval_token=ctx, now=ctx)
  │   GovernorDenied ─► audit "deny" ─► re-raise          (nothing ran: no ledger, no memory)
  │   other fault / no explicit allow / other grant_id ─► audit ─► ControlPlaneError
  ▼ explicit allow
governor.audit("allow")                                    ── audit fails → nothing runs
  ▼
adapters.<engine>(action, deep-copied payload, {state_dir, environ, root})  ── existing module
  │   raises ─► audit "error" + ledger row status=failed ─► EngineFailure
  ▼ result (object, strict JSON ≤ 16 MiB)
receipt {request_sha256, result_sha256, grant_id, side_effect, duration_ms, at,
         source_sha256 = sha256({file: sha256(bytes)} over adapters.py + engine sources)}
  ▼ contracts.validate_receipt
adapters.append_usage → <state_dir>/economics/ledger.jsonl (0600, flock, O_APPEND)
  ▼
{"ok": true, "engine", "action", "result", "receipt"}
```

Payloads are data. Authorization comes only from `grant` and `ctx["approval_token"]`; a
payload field named `approval_token`, `grant` or `ctx`, or instruction text anywhere in a
payload, is passed to the engine as plain data and changes nothing (tested). Audit rows
carry digests and reasons, never payloads.

A task ID adds correlation to operational accounting. To persist a memory entry
or checkpoint, invoke the explicit memory action using a separate state-write
grant. The static `master-audit` actions issue no child processes.
`quality-assurance.run-tests` requires the measured filesystem and network
isolation tier and uses a private disposable write root with the validated hub
source mounted read-only. See [MASTER security acceptance](MASTER_SECURITY_ACCEPTANCE.md).

Ledger row (`kind: control-plane-invocation`): engine, action, status, task_id, project,
grant_id, side_effect, duration_ms, request/result/source digests, `execution:
deterministic-local`, `model_calls: 0`, `provider_calls: 0`, `input_tokens: 0`,
`output_tokens: 0`, `charged_usd: "0"` — tokens and charges are separate fields and
subscription quota is not recorded. `economics.ledger` reads these rows back.

## 4. Discovery, health and CLI

- `engines()`, `layers()`, `describe(id)` (record + bound sources + path fields),
  `health(id|None)`: probes are read-only (they never create state; a broken probe is
  reported, not raised). Without `engineering_os/governor.py`, `security-governor` and
  `quality-assurance` report not ok and every `invoke` is refused.
- `python3 hub.py engines [--json]` — table of id, layer, actions, side effects.
- `python3 hub.py engine-health [ID]` — exit 1 when not ok or unknown.
- `python3 hub.py invoke ENGINE ACTION --payload JSON --grant FILE --state DIR [--task ID] [--host claude-code|codex]`
  — exit 0 with the result, 3 when the governor denies, 1 on a malformed or failed request.

Example grant (deny by default; one engine, one action, no writes):

```json
{"grant_id": "g-audit-1", "role": "quality-assurance-engineer",
 "engines": {"master-audit": ["inventory"]}, "paths": ["/work/checkout"],
 "max_side_effect": "none", "expires_at": "2026-12-31T00:00:00Z", "approvals": []}
```

## 5. Limitations

- `tests/test_control_plane.py` exercises the control plane against a test double of the
  governor API as well as the real `engineering_os/governor.py`;
  `tests/test_engine_registry_w2.py` uses the real governor only.
- The registry and `governance/layers.json` are separate files: registering an engine does not
  add its interfaces or tests to a layer (that is the layers owner's append; section 6).
- No gated action exists yet; gating is tested by a test-only registry copy (patched
  `ENGINES_PATH`). The CLI cannot pass an approval token.
- Checkpoint provenance records the invoking host (`ctx.host`, default `claude-code`); it is a
  caller declaration, not authentication.
- Receipts bind source bytes and results; they do not authenticate an evaluator, and
  `master-*` `spec` results are plans, not execution evidence.
- `cinematic-production.probe/render/qa` need ffmpeg, ffprobe, node and headless Chromium;
  its health stays ok without them (validation and planning work) and names what is missing.
- `security-audit.anchor` reads the control plane's own audit log, which already holds the
  allow row of that invocation; keep the anchor outside the state directory.

## 6. Adding an engine

A new engine (for example the L20 assurance engine or a release engine) is one record and
one adapter, in one commit:

1. Module: `engine(action, payload, ctx)` and `health()` in its own file (the module owner).
2. `engineering_os/adapters.py`: `def <id>(action, payload, ctx)` that raises `AdapterError`
   for an unknown action (`_unknown`), checks exact payload fields (`_fields`) and passes
   locations through `_location`/`_directory`; `def <id>_health()` through `_healthy`, side
   effect free. Add `SOURCES["<id>"]` (the files whose bytes define its behaviour) and, for
   every location field, `CANONICAL_PATH_FIELDS[(<id>, <action>)]`.
3. `governance/engines.json`: the record (`id`, `layer`, `title` en/ar, `entrypoint`
   `engineering_os.adapters:<id>`, `health`, `actions` with an honest side effect and the
   permissions it needs, `supersedes`). `none` needs read-only permissions; `exec:sandbox`
   or a payload-named write is `workspace-write`; nothing above `workspace-write` without
   the owner's approval (tests enforce both).
4. Tests: the engine id and layer in `EXPECTED` of `tests/test_control_plane.py`; an invoke
   case per action, unknown-action and bad-payload cases and the escaping/symlink cases of
   its location fields (the tables in `tests/test_engine_registry_w2.py` are data-driven:
   add the engine to `NEW_ENGINES` or the actions to `NEW_ACTIONS`).
5. Pins: `docs/evidence/gaie-20-layers/scenario-h.json` binds a plan digest over
   `governance/engines.json` and `governance/agent-roles.json`; refresh only its
   `simulated_20_agent_schedule` block with `orchestrator.scenario_h_evidence` in the same commit.
6. Requests: the layer's interfaces and tests (`governance/layers.json`, `LAYERS.md`), role
   grants (`governance/agent-roles.json`) and route templates (`gaie-routes.json`) belong to
   their owners.
