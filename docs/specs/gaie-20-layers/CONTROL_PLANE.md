# GAIE OS — Engineering Control Plane (layer L04)

Status: implemented on `gaie/w1-control-plane`. Contracts: [CONTRACTS.md](CONTRACTS.md) §2, §4, §5.
Code: `governance/engines.json`, `engineering_os/control_plane.py`, `engineering_os/adapters.py`,
`hub.py engines | engine-health | invoke`, tests in `tests/test_control_plane.py`.

The control plane is one registry and one governed way in for every engine. It owns no
engineering logic: every action is a thin adapter over the module that already
implements it. It makes no model, provider, network or deployment call. Deterministic
logic only; there is no AI-model reasoning anywhere on this path.

## 1. Engine map

17 engines, 15 owning layers. Layers L01–L12 follow `ARCHITECTURE.md`; L13–L20 follow
`docs/specs/nextgen-intelligence/plan.md` (the `master-build → L16` assignment matches
`tests/test_contracts.py`). L05, L07, L10, L15 and L20 own no engine yet. This mapping must be
reconciled with `governance/layers.json` when that file lands (w1-layers).

| Engine | Layer | Module(s) | Actions → side effect |
|---|---|---|---|
| `security-governor` | L01 | `engineering_os/governor.py` (w1-governor), `contracts.validate_grant` | `check` none, `validate-grant` none |
| `context-intelligence` | L02 | `tools/headroom_context.py` (status/retrieve/optimize), `skills/ultra-context-optimization/scripts/hr.py` (view) | `status` none, `view` none, `retrieve` none, `optimize` state-write |
| `master-router` | L03 | `engineering_os/gaie_router.py` | `route` none, `projects` none |
| `agent-swarm` | L03 | `swarm/scheduler.py` (`plan`, `simulate`; path-loaded, read-only) | `plan` none, `simulate` none |
| `adaptive-scheduler` | L03 | `swarm/phase3/adaptive.py` (`next_wave`; path-loaded, read-only) | `next-wave` none |
| `capability-registry` | L04 | `engineering_os/control.py` (`capabilities`, `integrations`, `architecture`), `hub.registry`/`hub.recommend` | `list` none, `search` none, `recommend` none, `integrations` none, `architecture` none |
| `master-upgrade` | L06 | `engineering_os/factory.py` + route `upgrade`/`accelerate`/`repair`, `skills/gaie-upgrade`, `prompts/MASTER_UPGRADE.md` | `spec` none, `plan` none, `evaluate` none |
| `motion-sdk` | L08 | `hub.motion_catalog`/`hub.motion_components`, `control.motions` | `catalog` none, `components` none, `runtime` none |
| `quality-assurance` | L09 | `governor.sandbox_run` + `unittest`; `contracts.validate_engines`/`validate_layers` | `run-tests` workspace-write, `contracts` none |
| `master-release` | L11 | `scripts/verify_release.py` (`approved_runs`, `approved_jobs`), `sdk/engineering_sdk.release`, `skills/gaie-release` | `spec` none, `provenance` none, `eligibility` none |
| `master-audit` | L12 | `engineering_os/gaie_inventory.py`, `control.health`, `hub.audit`, `skills/gaie-audit` | `spec` none, `inventory` none, `health` none, `hub-audit` none |
| `reasoning` | L13 | `engineering_os/reasoning.py` | `plan` none, `review` none, `root-causes` none |
| `memory` | L14 | `engineering_os/memory.py` (`MemoryStore`, via `adapters.memory_store`) | `put` state-write, `search` none, `graph` none, `index` state-write, `checkpoint` state-write, `restore` state-write, `verify` state-write |
| `master-build` | L16 | `engineering_os/factory.py` + route `build`, `skills/gaie-build`, `prompts/MASTER_BUILD.md` | `spec` none, `plan` none, `evaluate` none |
| `self-healing` | L17 | `engineering_os/healing.py` | `analyze` none, `verify-repair` workspace-write |
| `master-cinematic` | L18 | `engineering_os/cinematic.py` + route `cinematic`, `skills/gaie-cinematic` | `spec` none, `audit` none |
| `economics` | L19 | `engineering_os/economics.py` (+ `model_router.select_model` via `recommend_model`), control-plane ledger | `summarize` none, `recommend-model` none, `ledger` none |

Side-effect classes are honest: an action is `none` only when it writes nothing (a read of
an absent memory store returns empty instead of creating it); `verify-repair` and
`run-tests` write disposable files, so they are `workspace-write`; `optimize` writes the
private context store and starts the pinned SDK worker behind its no-IP boundary. No
registered action pushes, publishes or deploys, so nothing is `repo-write` or above and no
action needs an approval token in this revision. A test enforces that `none` ⇔ no `write:*`
permission. Engine ids are stable; the real build/upgrade generators of wave 2 become new
actions of `master-build` / `master-upgrade`, not new engines.

Payload fields that name a filesystem location (`adapters.PATH_FIELDS`, also shown by
`describe(id)["path_fields"]`) are passed to the governor as `paths=` so it can check them
against the grant after `realpath`: `route.workspace`, `evaluate.artifact_root`,
`inventory.target`, audit `health.project`, `eligibility.root`, memory `search/index.source_root`,
`checkpoint.destination`, `restore.checkpoint`, `verify.source_root/receipt_path`, `optimize.input`.

## 2. Duplicates found and how they are unified

| Found | Decision |
|---|---|
| Two memories: `memory.MemoryStore` (locked, checksummed JSON in a private state dir; used by `intelligence.dispatch`) and `gaie_memory.Memory` (hash-chained JSONL under `$GAIE_HOME/memory/<project>`; used by the gaie skills) | The control plane uses `MemoryStore` **only** through `adapters.memory_store()` / `record_checkpoint()`. w1-memory is unifying the two; when it lands, those two functions are the single switch point. |
| Two routers: `gaie_router` (owner command → engine, skill, workstreams, gates; L03) and `model_router` (model selection under policy, evidence, budget; L02) | Different concerns, deliberately **not** merged. `gaie_router` is `master-router`; `model_router` is reached only through `economics.recommend-model` (the existing `economics.recommend_model` facade), with an empty environment so host credentials are never consulted. |
| Two dispatchers: `intelligence.dispatch` (16 ungoverned local operations) and `control_plane.invoke` | `intelligence.dispatch` is unchanged (its tests keep passing) and stays as a facade; each engine lists the operations it supersedes in `supersedes` (`intelligence.dispatch:reasoning-plan`, …). New callers use `invoke`. Routing dispatch through the control plane is a later, owner-reviewed change (it would add a grant requirement). |
| Hub audit in two places of the brief (master-audit and quality-assurance) | One owner: `master-audit.hub-audit`. `quality-assurance` adds what is not duplicated: the sandboxed unittest runner and the registry contract check. |
| `control.motions` named for both master-cinematic and motion-sdk | One owner: `motion-sdk.runtime`. `master-cinematic.audit` is the cinematic inventory (`cinematic.audit_inventory`), which already binds its own browser receipts. |
| Headroom: `tools/headroom_context.py` and `skills/ultra-context-optimization/scripts/hr.py` | Already one integration (hr.py is the front end of the tool). `context-intelligence` wraps the tool for status/retrieve/optimize and hr's pure `plain_view`/`must_keep` for `view`; one store under the private state dir. |
| Four schedulers: `swarm/scheduler.plan` (who does which task in which wave), `swarm/phase3/adaptive.next_wave` (how many agents next), `reasoning.plan` (rank alternatives, dependency waves of plan nodes), `orchestration.TaskStore` (leases) | Different questions; each registered once (`agent-swarm`, `adaptive-scheduler`, `reasoning`). The swarm files are owned by the swarm session and are only path-loaded read-only (no `sys.modules` entry, `sys.path` restored); `own`/`submit`/`checkpoint` and the swarm setup scripts are not exposed. |
| Two economics modules: `engineering_os/economics.py` and `swarm/phase3/economics.py` (+ `swarm/phase3/ledger.py`) | `economics` wraps the engineering_os module; the swarm modules are experiment tooling owned by the swarm session and are not registered. |
| Build and upgrade share `factory.plan_factory` / `evaluate_factory` | Two engines with stable ids because their routes, prompts and skills differ; the shared factory code is one implementation. |
| Two canonical-JSON helpers: `contracts.canonical` (`allow_nan` default) and `orchestration.canonical` (`allow_nan=False`, bytes) | The control plane validates with the strict helper, then hashes with `contracts.sha256`; digests are identical for finite data. Recommendation for the contracts owner: set `allow_nan=False` in `contracts.canonical`. |
| Two layer projections: `control.LAYERS` (12) and `contracts.LAYER_IDS` (20) | Out of scope here (w1-layers). `capability-registry.architecture` keeps reporting the existing 12-layer projection unchanged. |

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

- The governor is implemented in parallel (w1-governor). Until it is merged, the tests use a
  test double of the agreed API inside the test file only; the real-governor tests skip with
  a message. `sandbox_run` argument semantics (`allowed_paths`, `env_allow`) are assumed from
  the agreed signature.
- The layer assignment is provisional until `governance/layers.json` exists.
- No gated action exists yet; gating is tested by a test-only registry copy (patched
  `ENGINES_PATH`). The CLI cannot pass an approval token.
- Checkpoint provenance records the invoking host (`ctx.host`, default `claude-code`); it is a
  caller declaration, not authentication.
- Receipts bind source bytes and results; they do not authenticate an evaluator, and
  `master-*` `spec` results are plans, not execution evidence.
