# GAIE OS — the twenty layers

Status: specification of `governance/layers.json` (records follow `CONTRACTS.md` §1) and
`governance/agent-roles.json` (§6). The per-layer sections below are kept in step with the
registry: `tests/test_layers.py` fails when an interface, test or name in the registry is
missing here. Code: `engineering_os/layers.py`. CLI: `python3 hub.py layers`.

## Verification and evidence

A layer is never complete because a name, a file or this document exists. Its status
comes only from a receipt:

1. `load_layers` validates the twenty records under `contracts.validate_layers`, then checks
   the repository: every listed test file and skill exists, every interface module is a file
   in this tree, every agent is one of the owner's twenty roles, and every interface is named
   (with its module) in at least one of the layer's Python tests — a static lower bound on
   "the tests exercise the interface", not a coverage measurement.
2. `verify(layer_ids=None, state_dir=...)` resolves the interfaces in a fresh interpreter and
   runs each listed test in its own subprocess: Python files with `unittest` (imported the
   way `python3 -m unittest discover -s tests` imports them), `.mjs` files with
   `node --test`. Without node the `.mjs` tests are recorded as `skipped` and the layer is
   `INCOMPLETE`, never `VERIFIED`. A test file runs once per call even when several layers
   list it. Python counts travel through a result file (nothing a test prints is parsed);
   node counts come from the TAP summary of `node --test` together with its exit status.
3. The receipt (`<state>/<Lxx>.json`, mode 0600, in a private directory outside Git;
   default `$GAIE_HOME/layers`, i.e. `~/.gaie/layers`) binds the SHA-256 of the layer record,
   of its test files and interface modules (with their packages), of every in-tree `.py`
   file the interface probe and the tests loaded (the modules left in `sys.modules` plus every
   location given to `importlib.util.spec_from_file_location`; the environment and the test
   process are otherwise untouched), and of the relative import closure of each `.mjs` test.
   It carries a `contract_receipt` valid under `contracts.validate_receipt`
   and a `receipt_sha256` over its own body.
4. `status` / `receipt_status` report the receipt's status (`VERIFIED`, `FAILED`,
   `INCOMPLETE`) only while the receipt is intact, internally consistent, for the same layer
   record, and every bound source still hashes the same; otherwise `UNVERIFIED` with the
   reason (`no receipt`, `stale receipt: N source file(s) changed`, `layer record changed`,
   digest mismatch, …). Editing a source withdraws `VERIFIED`; restoring the bytes restores it.

What a receipt does not prove: who ran it (digests detect corruption and staleness, they do
not authenticate), behaviour outside the listed tests, files read by grandchild processes
(for example `python3 hub.py …` started by a test), or data files the tests read (only code
is bound). Tests run as ordinary subprocesses, not in the `swarm/phase3/cage.py` sandbox.
No model is called; nothing is simulated; nothing remote is touched.

Commands:

```
python3 hub.py layers [--layer Lxx[,Lyy]] [--state DIR] [--json]   # status table, read-only
python3 hub.py layers --verify [--layer Lxx] [--state DIR] [--json] # run tests, write receipts
python3 hub.py architecture                                         # twenty-layer projection
```

`--verify` exits 0 only when every selected layer is `VERIFIED` (1 otherwise); an unknown
layer id, a missing test file or a state directory inside Git exits 2 before any test runs.

## Additive rule

`governance/layers.json` changes only additively: append interfaces and tests to a record,
never repoint or drop an existing one without the owner's review. Any change to a record
changes its `record_sha256`, so every earlier receipt of that layer becomes `UNVERIFIED`
until it is verified again.

The wave-2 modules were appended this way on 2026-11-28 (nothing was repointed or dropped):
`governor` (L01 decisions and audit, L09 sandbox), `security_audit` and `workspace_policy`
(L09), `orchestrator` (L03), `project_registry` (L10), the extra `reasoning` callables (L13),
the unified `memory` tests (L14), `engineering_os/requirements.py` (L15), `build_engine` and
`upgrade_engine` (L16), `healing.heal` and `detectors` (L17), `video_pipeline` (L18) and the
measured `economics` callables (L19), each with its test files. L15's earlier interfaces
(`engineering_os.gaie_router`, `engineering_os.intelligence:read_request`,
`engineering_os.factory:validate_stage`) stay listed. `build_engine.publish` and
`build_engine.request_repository` are not listed: publishing is an approval-gated
`external-write` step and this release deploys nothing.

- **L20** still has no dedicated module in this tree. It points at the evidence and provenance
  validators that exist (`contracts:validate_receipt`, `control:runtime_review`,
  `reasoning:review_decision`, `scripts.verify_release:approved_runs`), at this layer verifier
  and at the scenario checks. `engineering_os/assurance.py` (producer/reviewer separation from
  receipts) is being written in another lane; it is listed below as not yet bound.
- The permissions `exec:sandbox` on L16, L17 and L18 declare that those layers run code
  (generated applications, target test suites, ffmpeg and a browser); they do not claim an OS
  sandbox. The measured isolation of those child processes is tracked as SEC-07, and that of
  `layers.verify` itself as SEC-12, in `ENTERPRISE_SECURITY.md`.
- The **Evidence boundary** line of each layer below is `layers.EVIDENCE_BOUNDARY`, which
  `ARCHITECTURE.md` repeats verbatim; its L15, L16, L17 and L20 wording predates wave 2 and is
  changed together with `ARCHITECTURE.md`, not here alone.

## Acceptance scenarios A–I

`contracts.SCENARIOS` names nine end-to-end acceptance scenarios (`contracts.SCENARIO_TITLES`):
A master build, B master upgrade, C video pipeline, D memory resume, E security governor,
F self-healing, G release engine, H adaptive orchestration, I permanent Claude Code install.

A layer claims a scenario only through a binding in its `scenarios` list, for example
`{"id": "B", "test": "tests/test_upgrade_engine.py", "case": "ScenarioB"}`. `test` must be one
of the layer's own Python tests, so `layers.verify` runs it whenever it verifies the layer;
`case` is a test class or `Class.test_method` in that file. `contracts.validate_layer` refuses
unknown letters, foreign or `.mjs` tests, malformed case names and duplicates;
`tests/test_layer_scenarios.py` parses the file and refuses a binding whose case does not exist.
A bare letter is still valid under the contract (participation, never proof); this registry
uses bindings only.

`contracts.scenario_report(records, layer_status)` reports each scenario: `UNBOUND` when no
layer binds it, whatever the layers' status; otherwise the weakest status of the layers that
bind it (`FAILED` < `UNVERIFIED` < `INCOMPLETE` < `VERIFIED`). From the receipts on disk:

```
python3 -c "import json; from engineering_os import contracts as c, layers as l; s = {r['id']: r['status'] for r in l.status()}; print(json.dumps({k: v['status'] for k, v in c.scenario_report(l.load_layers(), s).items()}))"
```

What a bound scenario on a `VERIFIED` layer does not prove: a receipt counts test cases per
file, not per class, so a bound case that is skipped on a host leaves the layer `VERIFIED`
while the scenario's own case did not run. A is skipped without Playwright and Chromium, C
without node, ffmpeg and Playwright, and E's `SandboxTests` depend on the sandbox tier the
host provides (they were skipped in GitHub CI, where the tier was plain). The last column
records the per-case run on this host.

### Scenario bindings

| Scenario | Title | Layer | Test file | Case | Run alone on this host, 2026-11-28 |
|---|---|---|---|---|---|
| A | master build | L16 | `tests/test_build_engine_e2e.py` | `ScenarioATests` | 4 ran, 0 skipped (104 s) |
| B | master upgrade | L16 | `tests/test_upgrade_engine.py` | `ScenarioB` | 16 ran, 0 skipped |
| C | video pipeline | L18 | `tests/test_video_pipeline.py` | `ScenarioCTests` | 3 ran, 0 skipped |
| D | memory resume | L14 | `tests/test_memory_unified.py` | `ScenarioDTests` | 1 ran, 0 skipped |
| E | security governor | L01 | `tests/test_governor.py` | `CheckTests` | 18 ran, 0 skipped |
| E | security governor | L01 | `tests/test_governor.py` | `PayloadTests` | 4 ran, 0 skipped |
| E | security governor | L01 | `tests/test_governor.py` | `AuditTests` | 8 ran, 0 skipped |
| E | security governor | L09 | `tests/test_governor.py` | `StrictSandboxTests` | 6 ran, 0 skipped |
| E | security governor | L09 | `tests/test_governor.py` | `SandboxTests` | 14 ran, 0 skipped |
| F | self-healing | L17 | `tests/test_self_healing_loop.py` | `ScenarioF` | 10 ran, 0 skipped |
| H | adaptive orchestration | L03 | `tests/test_orchestrator.py` | `ScenarioHTests` | 5 ran, 1 skipped (`test_live_metrics_file_when_present`: the metrics file outside the repository is absent) |

Last column: `python3 -m unittest -v tests.<module>.<Case>` for each row, one at a time, on
base `e3f4c8d` with this registry change (Python 3.13.18, node v22.23.5, ffmpeg 6.1.1,
Playwright Chromium present). It is a record of that run, not a receipt; the receipts of
`python3 hub.py layers --verify` are the authority for the layers.

### Not yet bound

These are deliberately absent from the registry: their code or test is being written in
another lane of this integration and is not in this tree. `tests/test_layer_scenarios.py`
fails when a scenario is unbound without a row here, when a row's scenario is bound, and
when the assurance module is listed by a layer while its row remains (or is missing from L20
once the row is removed). Binding one is the addition in the last column, mirrored in the
layer's section below, plus deleting this row and the file's row in the next section.

| Item | State | Lane | Addition when bound (`governance/layers.json`) |
|---|---|---|---|
| Scenario G release engine | not yet bound | scenario-g | L11 `tests` += `"tests/test_release_engine.py"`; L11 `scenarios` += `{"id": "G", "test": "tests/test_release_engine.py", "case": "ScenarioG"}`; L11 `interfaces` += the `engineering_os.release_engine` callables that test names (for example `engineering_os.release_engine:evaluate`) |
| Scenario I permanent Claude Code install | not yet bound | install | L16 `tests` += `"tests/test_gaie_install_scenario_i.py"`; L16 `scenarios` += `{"id": "I", "test": "tests/test_gaie_install_scenario_i.py", "case": "ScenarioI"}` (the bootstrap interfaces `scripts.gaie_bootstrap:install` and `:verify` are already on L16) |
| L20 assurance module | not yet bound | assurance | L20 `interfaces` += the `engineering_os.assurance` callables that `tests/test_assurance.py` names (for example `engineering_os.assurance:assign`, `:verify`, `:gate`); L20 `tests` += `"tests/test_assurance.py"` |

## Test files outside the registry

Every `tests/test_*.py` and `tests/test_*.mjs` file is either listed by a layer or named here
with its reason; `tests/test_layer_scenarios.py` fails on a file that is neither. An `unbound`
row names files in this tree that no layer runs (a glob row covers only the files no layer
lists). An `announced` row names a file another lane of this integration is adding; it may be
absent here and is bound, or moved to `unbound` with a reason, in the next registry pass.

| Test file | Kind | Reason |
|---|---|---|
| `tests/test_p3_*.py` | unbound | Frozen phase-3 swarm suite pinned by `swarm/phase3/FREEZE.json`; timing-sensitive on a loaded host. CI runs it in `python3 -m unittest discover -s tests`. `tests/test_p3_cage.py`, `tests/test_p3_team.py` (L09) and `tests/test_p3_context_budget.py` (L19) are bound. |
| `tests/test_chromium_stack_runtime.mjs` | unbound | Browser proof: needs Playwright Chromium from `motion-library/chromium-stack`; run by `.github/workflows/operating-system.yml`. |
| `tests/test_motion_lab_browser.mjs` | unbound | Browser proof: needs Playwright from `motion-library/verify`; run by `.github/workflows/verify.yml`. |
| `tests/test_motion_studio_browser.mjs` | unbound | Browser proof: needs Playwright; run by `operating-system.yml` and `motion-cross-browser.yml`. |
| `tests/test_native_motions_browser.mjs` | unbound | Browser proof: needs Playwright with Chromium; without it every case is skipped, which would leave L08 INCOMPLETE on a plain host. |
| `tests/test_nextgen_camera_browser.mjs` | unbound | Browser proof: needs Playwright from `motion-library/chromium-stack`; run by `.github/workflows/nextgen-intelligence.yml`. |
| `tests/test_digital_show_scenes.mjs` | unbound | Browser proof in headless Chromium; reserved for the earlier session, listed here and not edited. |
| `tests/test_quality_audit.mjs` | unbound | Imports the `lighthouse` package that `operating-system.yml` installs; on a host without it the import fails, so a layer would FAIL for a missing tool. |
| `tests/test_quality_audit_browser.mjs` | unbound | Needs Lighthouse and Chrome (`QUALITY_AUDIT_CHROME`); run by `operating-system.yml`. |
| `tests/test_motion_performance.mjs` | unbound | Asserts a wall-clock budget (under 1 s); run by `verify.yml`. On a shared loaded host it could fail for timing, not for a defect. |
| `tests/test_ported_motions_browser.mjs` | unbound | Browser proof of the ported motions: needs Playwright with Chromium; it writes `docs/evidence/ported-motions-chromium.json` (with `--write`), whose binding `tests/test_ported_motions.py` (L08) checks. |
| `tests/test_release_engine.py` | announced | Scenario G, lane scenario-g; bind to L11 (see Not yet bound). |
| `tests/test_gaie_install_scenario_i.py` | announced | Scenario I, lane install; bind to L16 (see Not yet bound). |
| `tests/test_assurance.py` | announced | L20 assurance module, lane assurance; bind to L20 (see Not yet bound). |
| `tests/test_isolation_enforcement.py` | unbound | SEC-07 and SEC-12 enforcement (lane sec-isolation). It measures `read_caller_home` against the caller's own HOME and compares the live matrix with `isolation.json`; a layer run gives every test an empty private HOME, so 6 cases read `not-available` there (measured). CI runs it in discover and in the isolation job. |
| `tests/test_motion_policy.py` | announced | Purposeful motion policy, lane motion-policy; its request asks for L08 with `engineering_os.motion_policy:validate` and `:report`. |
| `tests/test_ported_motions.mjs` | unbound | Ported-motion module checks in node; `tests/test_ported_motions.py` (L08) runs it itself and skips the check only where node is missing, so binding it again would run it twice. |
| `tests/test_engine_registry_w2.py` | announced | Wave-2 engine registration, lane reg-engines; candidate L04. |
| `tests/test_agent_team.py` | announced | Twenty-agent team policy, lane agents-20; candidate L03. |
| `tests/test_master_docs.py` | announced | MASTER documents manifest, lane master-docs; candidate L01. |
| `tests/test_activation_receipt.py` | announced | Activation receipt, lane activation; candidate L12. |
| `tests/test_ci_coverage.py` | announced | Workflow coverage of `.mjs` tests, lane ci; candidate L09. |
| `tests/test_status_docs.py` | announced | Status documents and final-report matrix, lane status-docs; candidate L20. |

## Roles and default grants

`governance/agent-roles.json` lists the owner's twenty roles (teams A–H). `validate_roles`
rejects unknown, missing, duplicate or reordered roles and privilege escalation in the
default grant templates: a template never exceeds `repo-write`, never carries `network`,
`external-write` or `production`; a reviewer stays at `state-write`; write classes need
scoped paths (`workspace-write` under `workspace/`, `repo-write` only within the role's
owned paths) and read classes may have none. When `governance/engines.json` exists (it does),
every granted action must be registered there, its side-effect class must not exceed the
template's, and the template's ceiling must be exactly what its granted actions need.
Role layers and layer agents must agree both ways. `instantiate_grant` turns a template
into a grant valid under `contracts.validate_grant`. Owned path patterns use `fnmatch`
(`*` also crosses `/`); they describe ownership for coordination, they are not an OS guard.

| Role | Team | Layers | Default grant (engines → actions) | Max side effect |
|---|---|---|---|---|
| `chief-engineering-architect` | A | L01, L04 | layers: status; capability-registry: architecture; reasoning: plan, review | `none` |
| `twenty-layer-architecture-engineer` | A | L01, L04, L20 | layers: status, verify; capability-registry: architecture | `state-write` |
| `control-plane-integration-engineer` | A | L04, L05 | layers: status; capability-registry: list, integrations, architecture; master-audit: health | `none` |
| `engineering-reasoning-engineer` | B | L13, L15 | reasoning: plan, review, root-causes; master-router: route | `none` |
| `persistent-memory-engineer` | B | L14 | memory: search, graph, put, checkpoint, restore | `state-write` |
| `knowledge-intelligence-integration-engineer` | B | L07, L12 | memory: search, graph; context-intelligence: view, retrieve; capability-registry: search, recommend | `none` |
| `master-build-engine-engineer` | C | L06, L16 | master-build: spec, plan, evaluate; master-router: route | `none` |
| `master-upgrade-engine-engineer` | C | L06, L16 | master-upgrade: spec, plan, evaluate; master-audit: inventory | `none` |
| `nl-router-project-registry-engineer` | C | L10, L15, L16 | master-router: route, projects | `none` |
| `adaptive-agent-orchestration-engineer` | D | L03 | agent-swarm: plan, simulate; adaptive-scheduler: next-wave | `none` |
| `context-token-economics-engineer` | D | L02, L19 | economics: summarize, recommend-model, ledger; context-intelligence: status, view | `none` |
| `cinematic-production-engineer` | E | L08, L18 | master-cinematic: spec, audit; motion-sdk: catalog | `none` |
| `motion-sdk-animation-engineer` | E | L08 | motion-sdk: catalog, components, runtime | `none` |
| `gpu-3d-digital-twin-engineer` | E | L08, L18 | motion-sdk: runtime; master-cinematic: audit | `none` |
| `agent-isolation-security-engineer` | F | L03, L09 | security-governor: check, validate-grant | `none` |
| `enterprise-security-privacy-engineer` | F | L01, L09 | security-governor: validate-grant; quality-assurance: contracts | `none` |
| `testing-self-healing-engineer` | G | L09, L17 | self-healing: analyze, verify-repair; quality-assurance: run-tests; layers: status | `workspace-write` |
| `independent-assurance-engineer` (reviewer) | G | L20 | layers: status, verify; quality-assurance: contracts; reasoning: review | `state-write` |
| `github-integration-release-engineer` | H | L10, L11 | master-release: spec, provenance, eligibility | `none` |
| `claude-code-integration-engineer` | H | L02, L05 | master-router: route; capability-registry: list | `none` |

Every engine and action named above is registered in `governance/engines.json`. The registry
itself is an engine: `layers` (L04, `engineering_os.adapters:layers`) with `status` (side effect
`none`) and `verify` (`state-write`: it writes receipts under the control plane's private state
directory, in `layers/`). Through `control_plane.invoke` the Security Governor decides first;
the verify action still runs tests as ordinary subprocesses, not in `governor.sandbox_run`.

## Layers

### L01 Owner, Policy & Governance — المالك والسياسات والحوكمة

Responsibilities:
- Hold the owner's policy: lifecycle states, review gates and zero-budget defaults.
- Validate layer, engine, grant and receipt records against the shared contracts.
- Keep the agent-role registry and its least-privilege default grant templates.
- Refuse catalog approvals that lack a pinned revision and license, security and commercial review.

- **Contracts (interfaces):** `engineering_os.contracts:validate_grant`, `engineering_os.contracts:validate_layers`, `engineering_os.contracts:side_effect_rank`, `engineering_os.layers:validate_roles`, `engineering_os.layers:instantiate_grant`, `hub:registry`, `engineering_os.governor:check`, `engineering_os.governor:check_payload`, `engineering_os.governor:audit`, `engineering_os.contracts:scenario_report`
- **Inputs:** owner policy records; capability catalog entries; grant requests; agent-role registry
- **Outputs:** validated grants; contract errors naming the field at fault; approved catalog view
- **Depends on:** none
- **Permissions:** `read:repo`, `read:registry`, `secrets:none`, `read:state`, `write:state`
- **Tools:** `python3`
- **Skills:** `skills/priority-capability-selection/SKILL.md`, `skills/hub-capabilities/SKILL.md`
- **Agents:** `chief-engineering-architect`, `twenty-layer-architecture-engineer`, `enterprise-security-privacy-engineer`
- **Tests:** `tests/test_contracts.py`, `tests/test_layers.py`, `tests/test_hub.py`, `tests/test_governor.py`, `tests/test_layer_scenarios.py`
- **Scenarios:** E — `tests/test_governor.py` `CheckTests`, `PayloadTests`, `AuditTests`
- **Evidence boundary:** Local policy/receipt validators; provider administration is separate
- **Evidence status:** VERIFIED — 5/5 test files, 116 test cases passed; 45 sources bound (`source_sha256` fd5ef47be2c061b9…).

### L02 AI Intelligence & Model Routing — الذكاء الاصطناعي وتوجيه النماذج

Responsibilities:
- Select a model deterministically from a validated registry and the task's constraints.
- Fail closed when operational, pricing or quality receipts are missing or stale.
- Never invoke a provider, reserve quota or spend money while routing.

- **Contracts (interfaces):** `engineering_os.model_router:select_model`, `engineering_os.model_router:validate_registry`
- **Inputs:** model registry; routing request (task, privacy, budget, latency); evaluator receipts
- **Outputs:** selected model with reasons; routing refusal
- **Depends on:** L01
- **Permissions:** `read:registry`, `secrets:none`
- **Tools:** `python3`
- **Skills:** `skills/ai-integration/SKILL.md`
- **Agents:** `context-token-economics-engineer`, `claude-code-integration-engineer`
- **Tests:** `tests/test_model_router.py`
- **Scenarios:** none bound
- **Evidence boundary:** Deterministic policy routing; actual model access must be evidenced
- **Evidence status:** VERIFIED — 1/1 test files, 15 test cases passed; 4 sources bound (`source_sha256` 8418dd6424beca3d…).

### L03 Adaptive Agent Orchestration — التنسيق التكيّفي للوكلاء

Responsibilities:
- Coordinate specialist tasks through private, file-backed leases and handovers.
- Plan which agent takes which task within a bounded concurrency limit.
- Verify the coordination state on every load; refuse tampered or public state.

- **Contracts (interfaces):** `engineering_os.orchestration:TaskStore`, `engineering_os.orchestration:verify_state`, `swarm.scheduler:plan`, `swarm.scheduler:simulate`, `engineering_os.orchestrator:plan`, `engineering_os.orchestrator:schedule`, `engineering_os.orchestrator:lifecycle`, `engineering_os.orchestrator:review_assignment`, `engineering_os.orchestrator:worktree_plan`
- **Inputs:** task definitions; agent roster; lease and handover requests
- **Outputs:** task leases; handover records with receipt hashes; schedules
- **Depends on:** L01, L02
- **Permissions:** `read:state`, `write:state`, `secrets:none`
- **Tools:** `python3`, `git`
- **Skills:** `skills/nextgen-intelligence/SKILL.md`
- **Agents:** `adaptive-agent-orchestration-engineer`, `agent-isolation-security-engineer`
- **Tests:** `tests/test_os_orchestration.py`, `tests/test_swarm.py`, `tests/test_orchestrator.py`, `tests/test_w2_fixes_orchestration.py`, `tests/test_w2_fixes_orchestrator.py`, `tests/test_heal_fixes_2_orchestrator.py`
- **Scenarios:** H — `tests/test_orchestrator.py` `ScenarioHTests`
- **Evidence boundary:** Explicit invocations/file-state coordination; no continuous daemon claim
- **Evidence status:** VERIFIED — 3/3 test files, 72 test cases passed, 1 skipped; 25 sources bound (`source_sha256` 36e25dea649003d3…).

### L04 Engineering Control Plane — مستوى التحكم الهندسي

Responsibilities:
- Expose the hub's registries, architecture, capability and health projections.
- Dispatch offline engine operations through one entry point shared by Codex and Claude Code.
- Report the twenty-layer architecture and each layer's receipt-backed status.
- Invoke every engine, the layer registry included, only under a grant the Security Governor allows.

- **Contracts (interfaces):** `engineering_os.control:architecture`, `engineering_os.control:capabilities`, `engineering_os.control:health`, `engineering_os.intelligence:dispatch`, `hub:audit`, `engineering_os.layers:architecture`, `engineering_os.layers:status`, `engineering_os.control_plane:invoke`, `engineering_os.adapters:layers`
- **Inputs:** CLI commands; engine operation requests; registry files
- **Outputs:** JSON projections; layer status table; engine results
- **Depends on:** L01, L03
- **Permissions:** `read:repo`, `read:registry`, `read:state`, `secrets:none`
- **Tools:** `python3`
- **Skills:** `skills/hub-capabilities/SKILL.md`, `skills/nextgen-intelligence/SKILL.md`
- **Agents:** `chief-engineering-architect`, `twenty-layer-architecture-engineer`, `control-plane-integration-engineer`
- **Tests:** `tests/test_os_control.py`, `tests/test_hub.py`, `tests/test_intelligence.py`, `tests/test_layers.py`, `tests/test_control_plane.py`
- **Scenarios:** none bound
- **Evidence boundary:** Existing CLI, checksummed SDK and additive operational commands
- **Evidence status:** VERIFIED — 5/5 test files, 99 test cases passed; 48 sources bound (`source_sha256` 621e295f61c8b4d9…).

### L05 Universal Integration Intelligence — ذكاء التكامل الشامل

Responsibilities:
- Serve the read-only MCP and JSON-RPC surface of the engineering SDK.
- Report each integration program from its own probe evidence, never from a catalog name.
- Resolve a capability to exactly the pinned files it imports.

- **Contracts (interfaces):** `sdk.engineering_sdk:rpc`, `sdk.engineering_sdk:mcp`, `engineering_os.control:integrations`, `hublink:resolve`
- **Inputs:** MCP/JSON-RPC requests; integration probe evidence; capability ids
- **Outputs:** read-only RPC responses; integration availability report; resolved file lists
- **Depends on:** L04
- **Permissions:** `read:repo`, `read:registry`, `secrets:none`
- **Tools:** `python3`
- **Skills:** `skills/engineering-sdk/SKILL.md`
- **Agents:** `control-plane-integration-engineer`, `claude-code-integration-engineer`
- **Tests:** `tests/test_sdk.py`, `tests/test_os_control.py`, `tests/test_engine_motion_link.py`
- **Scenarios:** none bound
- **Evidence boundary:** Local MCP/CLI implemented; other protocols remain per-adapter candidates
- **Evidence status:** VERIFIED — 3/3 test files, 33 test cases passed; 7 sources bound (`source_sha256` 74c0d949ded965e1…).

### L06 Software Engineering — هندسة البرمجيات

Responsibilities:
- Discover a project's engineering surfaces without executing its code.
- Recommend reviewed skills and capabilities for web, backend, mobile and SaaS work.
- Onboard a project to the shared foundation without overwriting its files.

- **Contracts (interfaces):** `engineering_os.gaie_inventory:inventory`, `hub:recommend`, `hub:onboard`
- **Inputs:** project checkout path; capability query; reviewed hub revision
- **Outputs:** surface inventory and upgrade matrix; recommendations; onboarding plan or files
- **Depends on:** L04, L05
- **Permissions:** `read:repo`, `write:workspace`, `secrets:none`
- **Tools:** `python3`
- **Skills:** `skills/system-builder/SKILL.md`, `skills/saas-platform/SKILL.md`, `skills/project-onboarding/SKILL.md`
- **Agents:** `master-build-engine-engineer`, `master-upgrade-engine-engineer`
- **Tests:** `tests/test_gaie_factory.py`, `tests/test_hub.py`
- **Scenarios:** none bound
- **Evidence boundary:** Existing shared skills; project implementations remain private
- **Evidence status:** VERIFIED — 2/2 test files, 32 test cases passed; 15 sources bound (`source_sha256` f3da97fb932f0fe7…).

### L07 Data & Knowledge Intelligence — ذكاء البيانات والمعرفة

Responsibilities:
- Read bounded JSON requests, refusing duplicate keys and non-finite numbers.
- Search the capability catalog and skills as a discovery index, not an allowlist.
- Route knowledge operations (memory search, index, graph) through the shared dispatcher.

- **Contracts (interfaces):** `engineering_os.intelligence:read_request`, `engineering_os.intelligence:dispatch`, `sdk.engineering_sdk:catalog`, `hub:recommend`
- **Inputs:** knowledge queries; request files; catalog and skill text
- **Outputs:** ranked discovery results; knowledge operation results
- **Depends on:** L04
- **Permissions:** `read:repo`, `read:registry`, `read:state`, `secrets:none`
- **Tools:** `python3`
- **Skills:** `skills/ai-integration/SKILL.md`, `skills/hub-capabilities/SKILL.md`
- **Agents:** `knowledge-intelligence-integration-engineer`
- **Tests:** `tests/test_intelligence.py`, `tests/test_sdk.py`, `tests/test_hub.py`
- **Scenarios:** none bound
- **Evidence boundary:** No shared production database provisioned; project-level verification required
- **Evidence status:** VERIFIED — 3/3 test files, 31 test cases passed; 22 sources bound (`source_sha256` 7f96f4a5325a22a9…).

### L08 Cinematic, Motion & GPU — السينما والحركة ومعالجة الرسوميات

Responsibilities:
- Index motion recipes and report implemented, tested and runtime-verified counts separately.
- Keep the Universal Motion SDK, motion runtime and expansion catalog deterministic and offline.
- Treat a GPU API's presence as different from a successful render receipt.

- **Contracts (interfaces):** `engineering_os.control:motions`, `hub:audit`
- **Inputs:** motion catalog and component manifests; motion runtime receipts
- **Outputs:** motion evidence report; deterministic motion samples
- **Depends on:** L04, L06
- **Permissions:** `read:repo`, `read:registry`, `secrets:none`
- **Tools:** `python3`, `node`
- **Skills:** `skills/universal-motion/SKILL.md`, `skills/digital-motion/SKILL.md`, `skills/chromium-engineering/SKILL.md`
- **Agents:** `motion-sdk-animation-engineer`, `gpu-3d-digital-twin-engineer`, `cinematic-production-engineer`
- **Tests:** `tests/test_os_control.py`, `tests/test_hub.py`, `tests/test_motion_catalog.py`, `tests/test_motion.py`, `tests/test_motion_runtime.mjs`, `tests/test_universal_motion_sdk.mjs`, `tests/test_motion_expansion.mjs`, `tests/test_chromium_stack_options.mjs`, `tests/test_motion_lab.py`, `tests/test_motion_sdk_pack.py`, `tests/test_chromium_stack.py`, `tests/test_native_motions_digital.mjs`, `tests/test_ported_motions.py`
- **Scenarios:** none bound
- **Evidence boundary:** Preserve verified CSS/WAAPI/WebGL; new engines need their own runtime proof
- **Evidence status:** VERIFIED — 12/12 test files, 96 test cases passed; 42 sources bound (`source_sha256` 3094723f878c2a54…).

### L09 Security & Quality Intelligence — ذكاء الأمن والجودة

Responsibilities:
- Scan tracked files for credential shapes and unsafe Python without printing values.
- Audit dependency locks for pinned, integrity-checked packages.
- Run worker-written code only inside a resource-limited, network-walled cage.
- Gate agent shells and writes to their lane.

- **Contracts (interfaces):** `scripts.security_scan:scan`, `scripts.security_scan:secret_findings`, `scripts.security_scan:python_findings`, `scripts.security_scan:audit_locks`, `swarm.phase3.cage:run`, `swarm.phase3.lane_guard:allowed`, `swarm.phase2.guard:allowed`, `engineering_os.governor:sandbox_run`, `engineering_os.security_audit:run`, `engineering_os.security_audit:audit_anchor`, `engineering_os.workspace_policy:validate_workspace`, `engineering_os.workspace_policy:WorkspaceSupervisor`
- **Inputs:** tracked file index; dependency locks; agent tool calls; worker commands
- **Outputs:** findings with rule ids and locations; allow/deny decisions; bounded run results
- **Depends on:** L01, L04
- **Permissions:** `read:repo`, `exec:sandbox`, `secrets:none`
- **Tools:** `python3`, `git`
- **Skills:** `skills/security-review/SKILL.md`
- **Agents:** `agent-isolation-security-engineer`, `enterprise-security-privacy-engineer`, `testing-self-healing-engineer`
- **Tests:** `tests/test_security_scan.py`, `tests/test_security.py`, `tests/test_p3_cage.py`, `tests/test_p3_team.py`, `tests/test_swarm_phase2.py`, `tests/test_governor.py`, `tests/test_security_enterprise.py`, `tests/test_workspace_policy.py`, `tests/test_master_audit_permissions.py`, `tests/test_isolation_fixes_git.py`, `tests/test_isolation_fixes_planted_git.py`, `tests/test_isolation_fixes_relaunch.py`, `tests/test_isolation_fixes_governor.py`
- **Scenarios:** E — `tests/test_governor.py` `StrictSandboxTests`, `SandboxTests`
- **Evidence boundary:** SHA-pinned CI and test/audit evidence; no blanket compliance claim
- **Evidence status:** VERIFIED — 9/9 test files, 201 test cases passed; 40 sources bound (`source_sha256` 41a26f47eb955ab6…).

### L10 Independent Product Ecosystem — منظومة المنتجات المستقلة

Responsibilities:
- Keep every product in its own repository, data, permissions and runtime.
- Register pinned capabilities into a project selectively and verify them offline.
- Validate the public project registry; keep private inventories out of the hub.

- **Contracts (interfaces):** `hublink:projects`, `hublink:validate_projects`, `hublink:validate_manifest`, `hublink:register`, `hublink:verify`, `engineering_os.project_registry:resolve`, `engineering_os.project_registry:register`, `engineering_os.project_registry:get`
- **Inputs:** project manifests; reviewed hub revision; capability ids
- **Outputs:** registration plan or files; verification findings; registry audit
- **Depends on:** L01, L04, L06
- **Permissions:** `read:repo`, `read:registry`, `write:workspace`, `secrets:none`, `read:state`, `write:state`
- **Tools:** `python3`, `git`
- **Skills:** `skills/project-onboarding/SKILL.md`, `skills/hub-capabilities/SKILL.md`
- **Agents:** `nl-router-project-registry-engineer`, `github-integration-release-engineer`
- **Tests:** `tests/test_link.py`, `tests/test_engine_motion_link.py`, `tests/test_project_registry.py`
- **Scenarios:** none bound
- **Evidence boundary:** Private registry outside public Git; local preparation differs from remote completion
- **Evidence status:** VERIFIED — 3/3 test files, 40 test cases passed; 13 sources bound (`source_sha256` b85527cfe3dfc840…).

### L11 Cloud & Deployment Intelligence — ذكاء السحابة والنشر

Responsibilities:
- Bind release eligibility to exact-commit workflow runs and required jobs.
- Refuse spoofed, pending, failed or stale provenance.
- Check deployment identity per project; never deploy across project boundaries.

- **Contracts (interfaces):** `scripts.verify_release:approved_runs`, `scripts.verify_release:approved_jobs`, `sdk.engineering_sdk:release`, `sdk.engineering_sdk:target`
- **Inputs:** workflow run documents; release evidence; project identity
- **Outputs:** release eligibility decision; blocking reasons
- **Depends on:** L09, L10
- **Permissions:** `read:repo`, `read:registry`, `secrets:none`
- **Tools:** `python3`
- **Skills:** `skills/release-engineering/SKILL.md`, `skills/gaie-release/SKILL.md`
- **Agents:** `github-integration-release-engineer`
- **Tests:** `tests/test_release_provenance.py`, `tests/test_sdk.py`, `tests/test_review_fixes_sdk_submodules.py`
- **Scenarios:** none bound
- **Evidence boundary:** Existing provider projects preserved; incomplete permissions block relinking
- **Evidence status:** VERIFIED — 2/2 test files, 18 test cases passed; 5 sources bound (`source_sha256` 39a862e5a5d7f3ad…).

### L12 Continuous Technology Intelligence — الذكاء التقني المستمر

Responsibilities:
- Discover technology candidates in bounded batches; never install or approve them.
- Withdraw a recorded runtime claim when its source or time-bound evidence changes.
- Report lifecycle states from reviewed records only.

- **Contracts (interfaces):** `scripts.discover_technology:discover`, `scripts.discover_technology:probe`, `engineering_os.control:runtime_review`, `engineering_os.control:capabilities`
- **Inputs:** catalog entries; upstream metadata responses; runtime receipts
- **Outputs:** discovery candidates; lifecycle states; withdrawn claims
- **Depends on:** L04, L09
- **Permissions:** `read:registry`, `net:fetch`, `secrets:none`
- **Tools:** `python3`
- **Skills:** `skills/priority-capability-selection/SKILL.md`
- **Agents:** `knowledge-intelligence-integration-engineer`
- **Tests:** `tests/test_technology_discovery.py`, `tests/test_os_control.py`, `tests/test_capability_activation.py`
- **Scenarios:** none bound
- **Evidence boundary:** Read-only discovery and reviewed update proposals; no automatic execution
- **Evidence status:** VERIFIED — 3/3 test files, 25 test cases passed; 7 sources bound (`source_sha256` ad7ed7b9a5677905…).

### L13 Advanced Engineering Reasoning — الاستدلال الهندسي المتقدم

Responsibilities:
- Rank supplied alternatives against declared constraints and evaluator receipts.
- Compute dependency schedules and refuse cycles and impossible budgets.
- Review a planned decision against independent reviews and verification.
- Order root-cause candidates from observations and declared dependencies.

- **Contracts (interfaces):** `engineering_os.reasoning:plan`, `engineering_os.reasoning:review_decision`, `engineering_os.reasoning:root_causes`, `engineering_os.reasoning:decompose`, `engineering_os.reasoning:analyze_dependencies`, `engineering_os.reasoning:trade_off`, `engineering_os.reasoning:validate_decision`
- **Inputs:** planning request with nodes and constraints; reviews; verification receipts; observations
- **Outputs:** ranked plan and schedule; decision review; root-cause ranking
- **Depends on:** L02, L03
- **Permissions:** `read:state`, `secrets:none`
- **Tools:** `python3`
- **Skills:** `skills/nextgen-intelligence/SKILL.md`
- **Agents:** `engineering-reasoning-engineer`
- **Tests:** `tests/test_reasoning.py`, `tests/test_reasoning_cases.py`, `tests/test_w2_fixes_reasoning.py`, `tests/test_heal_fixes_2_reasoning.py`
- **Scenarios:** none bound
- **Evidence boundary:** Deterministic ranking of supplied alternatives and schedules; no model reasoning or inferred causality
- **Evidence status:** VERIFIED — 2/2 test files, 75 test cases passed; 7 sources bound (`source_sha256` c65d4bfcefef4ecd…).

### L14 Persistent Engineering Memory — الذاكرة الهندسية الدائمة

Responsibilities:
- Keep private, project-scoped memory outside every Git repository.
- Store decisions, failures, repairs and checkpoints; never mix projects.
- Refuse credential-shaped content and detect tampering through checksums and hash chains.

- **Contracts (interfaces):** `engineering_os.memory:MemoryStore`, `engineering_os.gaie_memory:Memory`
- **Inputs:** memory records; project id; search queries; checkpoints
- **Outputs:** retrieved records; knowledge-graph links; restored checkpoints
- **Depends on:** L04, L07, L09
- **Permissions:** `read:state`, `write:state`, `secrets:none`
- **Tools:** `python3`
- **Skills:** `skills/nextgen-intelligence/SKILL.md`
- **Agents:** `persistent-memory-engineer`
- **Tests:** `tests/test_engineering_memory.py`, `tests/test_gaie_factory.py`, `tests/test_memory_unified.py`, `tests/test_gaie_memory_journal.py`, `tests/test_review_fixes_memory_readonly.py`, `tests/test_review_fixes_memory_resume_cli.py`, `tests/test_review_fixes_memory_secrets.py`
- **Scenarios:** D — `tests/test_memory_unified.py` `ScenarioDTests`
- **Evidence boundary:** Private file-backed memory outside Git; lexical retrieval, not embeddings; checksums detect corruption only
- **Evidence status:** VERIFIED — 3/3 test files, 59 test cases passed; 14 sources bound (`source_sha256` 710ad550f12e7e17…).

### L15 Requirements & Specification Intelligence — ذكاء المتطلبات والمواصفات

Responsibilities:
- Turn an owner's Arabic or English command into clauses, a task class and a target.
- Stop with needs-clarification instead of guessing a project or repository.
- Validate bounded request documents and stage contracts before work starts.

- **Contracts (interfaces):** `engineering_os.gaie_router:normalize`, `engineering_os.gaie_router:route`, `engineering_os.gaie_router:remote_slug`, `engineering_os.intelligence:read_request`, `engineering_os.factory:validate_stage`, `engineering_os.requirements:parse`, `engineering_os.requirements:refine`, `engineering_os.requirements:validate_spec`, `engineering_os.requirements:diff_specs`, `engineering_os.requirements:acceptance_checks`
- **Inputs:** owner command text; project registries; request documents
- **Outputs:** normalized clauses; route or needs-clarification; stage validation result
- **Depends on:** L06, L13, L14
- **Permissions:** `read:repo`, `read:registry`, `secrets:none`
- **Tools:** `python3`
- **Skills:** `skills/gaie-master-router/SKILL.md`
- **Agents:** `nl-router-project-registry-engineer`, `engineering-reasoning-engineer`
- **Tests:** `tests/test_gaie_router.py`, `tests/test_intelligence.py`, `tests/test_factory.py`, `tests/test_requirements.py`, `tests/test_build_fixes_requirements.py`
- **Scenarios:** none bound
- **Evidence boundary:** Deterministic command parsing and bounded request validation; engineering_os/requirements.py is wave 2
- **Evidence status:** VERIFIED — 4/4 test files, 117 test cases passed; 21 sources bound (`source_sha256` 8382dc082fbd1ec1…).

### L16 Autonomous Software Factory — مصنع البرمجيات الذاتي

Responsibilities:
- Plan delivery stages for web, backend, mobile, AI, database and API targets.
- Evaluate artifacts against supplied evaluator receipts and stage contracts.
- Route build and upgrade commands to the GAIE skills and their gates.
- Install the GAIE skills idempotently without touching foreign files.

- **Contracts (interfaces):** `engineering_os.factory:plan_factory`, `engineering_os.factory:evaluate_factory`, `engineering_os.factory:validate_stage`, `engineering_os.gaie_router:policy`, `engineering_os.gaie_router:route`, `scripts.gaie_bootstrap:install`, `scripts.gaie_bootstrap:verify`, `engineering_os.build_engine:plan`, `engineering_os.build_engine:build`, `engineering_os.build_engine:evaluate`, `engineering_os.upgrade_engine:upgrade`
- **Inputs:** factory request; artifact receipts; owner command; GAIE route policy
- **Outputs:** factory plan; stage evaluation; routed engine and skills
- **Depends on:** L06, L09, L11, L13, L14, L15
- **Permissions:** `read:repo`, `read:registry`, `read:state`, `write:workspace`, `secrets:none`, `exec:sandbox`
- **Tools:** `python3`, `node`, `git`
- **Skills:** `skills/gaie-master-router/SKILL.md`, `skills/gaie-build/SKILL.md`, `skills/gaie-upgrade/SKILL.md`, `skills/gaie-audit/SKILL.md`
- **Agents:** `master-build-engine-engineer`, `master-upgrade-engine-engineer`, `nl-router-project-registry-engineer`
- **Tests:** `tests/test_factory.py`, `tests/test_gaie_router.py`, `tests/test_gaie_factory.py`, `tests/test_build_engine.py`, `tests/test_build_engine_e2e.py`, `tests/test_upgrade_engine.py`, `tests/test_review_fixes_upgrade_scope.py`, `tests/test_build_fixes_app.py`, `tests/test_upgrade_fixes_clauses.py`, `tests/test_upgrade_fixes_journal.py`, `tests/test_upgrade_fixes_linked_db.py`, `tests/test_upgrade_fixes_origin.py`, `tests/test_upgrade_fixes_original.py`, `tests/test_upgrade_fixes_requests.py`, `tests/test_upgrade_fixes_schema_memory.py`, `tests/test_upgrade_fixes_schema_modules.py`, `tests/test_upgrade_fixes_sql.py`, `tests/test_upgrade_fixes_wal.py`
- **Scenarios:** A — `tests/test_build_engine_e2e.py` `ScenarioATests`; B — `tests/test_upgrade_engine.py` `ScenarioB`
- **Evidence boundary:** Plans and checks artifacts against supplied receipts; generates no complete application and deploys nothing
- **Evidence status:** VERIFIED — 6/6 test files, 162 test cases passed; 28 sources bound (`source_sha256` 4fb0a1e7f3a88919…).

### L17 Self-Healing & Recovery Intelligence — ذكاء الإصلاح الذاتي والتعافي

Responsibilities:
- Turn bound failure evidence into ranked repair proposals.
- Verify a repair with fixed declarative checks over disposable artifacts.
- Never execute candidate code, shell commands or providers.

- **Contracts (interfaces):** `engineering_os.healing:analyze`, `engineering_os.healing:verify_repair`, `engineering_os.healing:artifact_digest`, `engineering_os.healing:heal`, `engineering_os.detectors:run_all`
- **Inputs:** failure evidence; candidate repair files; declarative checks
- **Outputs:** repair proposals; repair verification result; artifact digests
- **Depends on:** L09, L12, L13, L14
- **Permissions:** `read:state`, `secrets:none`, `write:workspace`, `exec:sandbox`
- **Tools:** `python3`, `node`
- **Skills:** `skills/nextgen-intelligence/SKILL.md`
- **Agents:** `testing-self-healing-engineer`
- **Tests:** `tests/test_healing.py`, `tests/test_self_healing_loop.py`, `tests/test_w2_fixes_healing.py`, `tests/test_w2_fixes_patch.py`, `tests/test_heal_fixes_2_findings.py`, `tests/test_heal_fixes_2_healing.py`
- **Scenarios:** F — `tests/test_self_healing_loop.py` `ScenarioF`
- **Evidence boundary:** Repair proposals and fixed declarative checks; candidate code is never executed
- **Evidence status:** VERIFIED — 2/2 test files, 67 test cases passed; 9 sources bound (`source_sha256` ddf31fcf7fe122b6…).

### L18 Advanced Cinematic Intelligence — الذكاء السينمائي المتقدم

Responsibilities:
- Keep the cinematic inventory source-bound and its namespaces distinct.
- Withdraw a browser proof when its source, harness or budget changes.
- Resolve an engine-native motion to exactly the engine files it imports.

- **Contracts (interfaces):** `engineering_os.cinematic:audit_inventory`, `hublink:resolve`, `engineering_os.video_pipeline:validate_storyboard`, `engineering_os.video_pipeline:render`, `engineering_os.video_pipeline:qa_media`
- **Inputs:** cinematic inventory; browser proof receipts; engine-motion ids
- **Outputs:** inventory audit; activation status per browser; resolved engine files
- **Depends on:** L08, L13
- **Permissions:** `read:repo`, `read:registry`, `secrets:none`, `write:workspace`, `exec:sandbox`
- **Tools:** `python3`, `node`, `ffmpeg`, `ffprobe`
- **Skills:** `skills/gaie-cinematic/SKILL.md`, `skills/cinematic-production/SKILL.md`
- **Agents:** `cinematic-production-engineer`, `gpu-3d-digital-twin-engineer`
- **Tests:** `tests/test_cinematic_intelligence.py`, `tests/test_engine_motion_link.py`, `tests/test_nextgen_camera.mjs`, `tests/test_video_pipeline.py`, `tests/test_digital_show.py`, `tests/test_render_options.mjs`
- **Scenarios:** C — `tests/test_video_pipeline.py` `ScenarioCTests`
- **Evidence boundary:** Source-bound inventory and engine-motion resolution; every render needs its own browser receipt
- **Evidence status:** VERIFIED — 6/6 test files, 109 test cases passed, 1 skipped; 16 sources bound (`source_sha256` eab7e9b3bfc78ed0…).

### L19 Engineering Economics & Resource Intelligence — اقتصاديات الهندسة وذكاء الموارد

Responsibilities:
- Summarize source-bound usage ledgers by feature, MVP and enterprise scope.
- Keep tokens, price estimates, charged amounts and subscription quota separate.
- Estimate a worker's starting context size and flag definitions over budget.

- **Contracts (interfaces):** `engineering_os.economics:summarize`, `engineering_os.economics:recommend_model`, `swarm.phase3.context_budget:budget`, `swarm.phase3.context_budget:check`, `engineering_os.economics:recommend_concurrency`, `engineering_os.economics:measured_baseline`
- **Inputs:** usage ledgers; model registry; agent definitions
- **Outputs:** cost and usage summary; model recommendation; context budget report
- **Depends on:** L01, L02, L12
- **Permissions:** `read:repo`, `read:state`, `secrets:none`
- **Tools:** `python3`
- **Skills:** `skills/ultra-context-optimization/SKILL.md`, `skills/headroom-context-engineering/SKILL.md`
- **Agents:** `context-token-economics-engineer`
- **Tests:** `tests/test_economics.py`, `tests/test_p3_context_budget.py`, `tests/test_economics_measured.py`, `tests/test_context_optimization.py`, `tests/test_headroom_context.py`, `tests/test_headroom_pack.py`
- **Scenarios:** none bound
- **Evidence boundary:** Offline accounting over supplied ledgers; tokens, cost and subscription quota stay separate
- **Evidence status:** VERIFIED — 6/6 test files, 120 test cases passed, 4 skipped; 23 sources bound (`source_sha256` fa08c965b268ccea…).

### L20 Independent Engineering Assurance — الضمان الهندسي المستقل

Responsibilities:
- Accept a claim only from a receipt bound to the SHA-256 of current sources.
- Run each layer's listed tests and record a verification receipt in private state.
- Check review decisions against independent reviews and release provenance.
- Keep the reviewer of a change separate from its producer.

- **Contracts (interfaces):** `engineering_os.contracts:validate_receipt`, `engineering_os.control:runtime_review`, `engineering_os.reasoning:review_decision`, `scripts.verify_release:approved_runs`, `engineering_os.layers:verify`, `engineering_os.layers:receipt_status`
- **Inputs:** layer records; test files; source files; review and provenance documents
- **Outputs:** verification receipts; VERIFIED/FAILED/INCOMPLETE/UNVERIFIED status; blocking reasons
- **Depends on:** L01, L09, L11, L13
- **Permissions:** `read:repo`, `read:state`, `write:state`, `exec:sandbox`, `secrets:none`
- **Tools:** `python3`, `node`
- **Skills:** `skills/gaie-audit/SKILL.md`, `skills/security-review/SKILL.md`
- **Agents:** `independent-assurance-engineer`, `twenty-layer-architecture-engineer`
- **Tests:** `tests/test_layers.py`, `tests/test_os_control.py`, `tests/test_reasoning.py`, `tests/test_release_provenance.py`, `tests/test_layer_scenarios.py`, `tests/test_evidence.py`
- **Scenarios:** none bound
- **Evidence boundary:** Source-bound test receipts; engineering_os/assurance.py is not yet integrated; hashes do not authenticate reviewers
- **Evidence status:** VERIFIED — 6/6 test files, 100 test cases passed; 46 sources bound (`source_sha256` 63902b4bb52e4a02…).

## Evidence status

Produced by `GAIE_HOME=<private dir> python3 hub.py layers --verify --layer Lxx`, one layer at
a time for L01…L20, on branch `gaie/r-reg-layers` at commit `b297c9f` (2026-11-28, Python
3.13.18, node v22.23.5, ffmpeg 6.1.1, Playwright Chromium present; 4 shared CPUs, load average
3.8–4.9). Every run exited 0; no layer was re-run. The registry now lists 62 of the 104 test
files under `tests/`; the other 42 are named, with their reasons, in "Test files outside the
registry". From these receipts `contracts.scenario_report` gives A, B, C, D, E, F and H
`VERIFIED` and G and I `UNBOUND`. Commits after `b297c9f` in this lane change only this
document, which no receipt binds, so `python3 hub.py layers` still reports these rows.

Skipped cases (each inside a file that passed): L03 1 (`tests/test_orchestrator.py`, the live
metrics file of Scenario H lives outside the repository), L18 1 (`tests/test_video_pipeline.py`,
sample media is kept outside Git), L19 4 (the real Headroom SDK cases: `tests/test_headroom_context.py`
2 and `tests/test_headroom_pack.py` 1 run only with `HEADROOM_CONTEXT_INTEGRATION=1` in the
reviewed SDK environment; `tests/test_context_optimization.py` 1 needs the reviewed SDK, which is
not installed here).

The receipts are private state, not part of the repository; this table is a copy for
review and becomes outdated the moment a bound source changes — `python3 hub.py layers`
is the authority. Deterministic test execution only; no model reasoning is involved.

| Layer | Status | Test files passed | Test cases passed | Skipped cases | Sources bound | source_sha256 |
|---|---|---|---|---|---|---|
| L01 | VERIFIED | 5/5 | 116 | 0 | 45 | `fd5ef47be2c061b9…` |
| L02 | VERIFIED | 1/1 | 15 | 0 | 4 | `8418dd6424beca3d…` |
| L03 | VERIFIED | 3/3 | 72 | 1 | 25 | `36e25dea649003d3…` |
| L04 | VERIFIED | 5/5 | 99 | 0 | 48 | `621e295f61c8b4d9…` |
| L05 | VERIFIED | 3/3 | 33 | 0 | 7 | `74c0d949ded965e1…` |
| L06 | VERIFIED | 2/2 | 32 | 0 | 15 | `f3da97fb932f0fe7…` |
| L07 | VERIFIED | 3/3 | 31 | 0 | 22 | `7f96f4a5325a22a9…` |
| L08 | VERIFIED | 12/12 | 96 | 0 | 42 | `3094723f878c2a54…` |
| L09 | VERIFIED | 9/9 | 201 | 0 | 40 | `41a26f47eb955ab6…` |
| L10 | VERIFIED | 3/3 | 40 | 0 | 13 | `b85527cfe3dfc840…` |
| L11 | VERIFIED | 2/2 | 18 | 0 | 5 | `39a862e5a5d7f3ad…` |
| L12 | VERIFIED | 3/3 | 25 | 0 | 7 | `ad7ed7b9a5677905…` |
| L13 | VERIFIED | 2/2 | 75 | 0 | 7 | `c65d4bfcefef4ecd…` |
| L14 | VERIFIED | 3/3 | 59 | 0 | 14 | `710ad550f12e7e17…` |
| L15 | VERIFIED | 4/4 | 117 | 0 | 21 | `8382dc082fbd1ec1…` |
| L16 | VERIFIED | 6/6 | 162 | 0 | 28 | `4fb0a1e7f3a88919…` |
| L17 | VERIFIED | 2/2 | 67 | 0 | 9 | `ddf31fcf7fe122b6…` |
| L18 | VERIFIED | 6/6 | 109 | 1 | 16 | `eab7e9b3bfc78ed0…` |
| L19 | VERIFIED | 6/6 | 120 | 4 | 23 | `fa08c965b268ccea…` |
| L20 | VERIFIED | 6/6 | 100 | 0 | 46 | `63902b4bb52e4a02…` |

History: the previous copy of this table was produced on branch `gaie/w1-layers` at commit
`a17f258`, when the registry listed 35 test files and bound no scenario (L17 23 cases, L18 20).
After the control-plane merge those receipts were withdrawn automatically (9 VERIFIED, 11
UNVERIFIED as stale) until they were re-run. In an earlier run at a load average near 20 on four
shared CPUs, `tests/test_p3_cage.py` (L09) failed 2 of 9 cases; the same cases failed on an
untouched export of the base commit under that load (machine-wide per-user process and timing
limits), and L09 passed when re-run.
