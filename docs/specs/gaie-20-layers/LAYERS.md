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

## Additive rule and wave 2

`governance/layers.json` changes only additively: append interfaces and tests to a record,
never repoint or drop an existing one without the owner's review. Any change to a record
changes its `record_sha256`, so every earlier receipt of that layer becomes `UNVERIFIED`
until it is verified again.

- **L15** has no dedicated module yet. It points at the closest real callables: command
  normalization and routing (`engineering_os.gaie_router`), bounded request reading
  (`engineering_os.intelligence:read_request`) and stage contracts
  (`engineering_os.factory:validate_stage`). Wave 2 adds `engineering_os/requirements.py`
  and its test; their interfaces are appended to L15.
- **L20** has no dedicated module yet. It points at the evidence and provenance validators
  that exist (`contracts:validate_receipt`, `control:runtime_review`,
  `reasoning:review_decision`, `scripts.verify_release:approved_runs`) and at this layer
  verifier. Wave 2 adds `engineering_os/assurance.py` (producer/reviewer separation from
  receipts) and its test; their interfaces are appended to L20.
- **Scenarios** `A`–`I` are not yet defined in `CONTRACTS.md`, so every `scenarios` list is
  empty; the acceptance work adds them per layer.

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

- **Contracts (interfaces):** `engineering_os.contracts:validate_grant`, `engineering_os.contracts:validate_layers`, `engineering_os.contracts:side_effect_rank`, `engineering_os.layers:validate_roles`, `engineering_os.layers:instantiate_grant`, `hub:registry`
- **Inputs:** owner policy records; capability catalog entries; grant requests; agent-role registry
- **Outputs:** validated grants; contract errors naming the field at fault; approved catalog view
- **Depends on:** none
- **Permissions:** `read:repo`, `read:registry`, `secrets:none`
- **Tools:** `python3`
- **Skills:** `skills/priority-capability-selection/SKILL.md`, `skills/hub-capabilities/SKILL.md`
- **Agents:** `chief-engineering-architect`, `twenty-layer-architecture-engineer`, `enterprise-security-privacy-engineer`
- **Tests:** `tests/test_contracts.py`, `tests/test_layers.py`, `tests/test_hub.py`
- **Evidence boundary:** Local policy/receipt validators; provider administration is separate
- **Evidence status:** UNVERIFIED until `python3 hub.py layers --verify` writes a current receipt.

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
- **Evidence boundary:** Deterministic policy routing; actual model access must be evidenced
- **Evidence status:** UNVERIFIED until `python3 hub.py layers --verify` writes a current receipt.

### L03 Adaptive Agent Orchestration — التنسيق التكيّفي للوكلاء

Responsibilities:
- Coordinate specialist tasks through private, file-backed leases and handovers.
- Plan which agent takes which task within a bounded concurrency limit.
- Verify the coordination state on every load; refuse tampered or public state.

- **Contracts (interfaces):** `engineering_os.orchestration:TaskStore`, `engineering_os.orchestration:verify_state`, `swarm.scheduler:plan`, `swarm.scheduler:simulate`
- **Inputs:** task definitions; agent roster; lease and handover requests
- **Outputs:** task leases; handover records with receipt hashes; schedules
- **Depends on:** L01, L02
- **Permissions:** `read:state`, `write:state`, `secrets:none`
- **Tools:** `python3`
- **Skills:** `skills/nextgen-intelligence/SKILL.md`
- **Agents:** `adaptive-agent-orchestration-engineer`, `agent-isolation-security-engineer`
- **Tests:** `tests/test_os_orchestration.py`, `tests/test_swarm.py`
- **Evidence boundary:** Explicit invocations/file-state coordination; no continuous daemon claim
- **Evidence status:** UNVERIFIED until `python3 hub.py layers --verify` writes a current receipt.

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
- **Evidence boundary:** Existing CLI, checksummed SDK and additive operational commands
- **Evidence status:** UNVERIFIED until `python3 hub.py layers --verify` writes a current receipt.

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
- **Evidence boundary:** Local MCP/CLI implemented; other protocols remain per-adapter candidates
- **Evidence status:** UNVERIFIED until `python3 hub.py layers --verify` writes a current receipt.

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
- **Evidence boundary:** Existing shared skills; project implementations remain private
- **Evidence status:** UNVERIFIED until `python3 hub.py layers --verify` writes a current receipt.

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
- **Evidence boundary:** No shared production database provisioned; project-level verification required
- **Evidence status:** UNVERIFIED until `python3 hub.py layers --verify` writes a current receipt.

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
- **Tests:** `tests/test_os_control.py`, `tests/test_hub.py`, `tests/test_motion_catalog.py`, `tests/test_motion.py`, `tests/test_motion_runtime.mjs`, `tests/test_universal_motion_sdk.mjs`, `tests/test_motion_expansion.mjs`, `tests/test_chromium_stack_options.mjs`
- **Evidence boundary:** Preserve verified CSS/WAAPI/WebGL; new engines need their own runtime proof
- **Evidence status:** UNVERIFIED until `python3 hub.py layers --verify` writes a current receipt.

### L09 Security & Quality Intelligence — ذكاء الأمن والجودة

Responsibilities:
- Scan tracked files for credential shapes and unsafe Python without printing values.
- Audit dependency locks for pinned, integrity-checked packages.
- Run worker-written code only inside a resource-limited, network-walled cage.
- Gate agent shells and writes to their lane.

- **Contracts (interfaces):** `scripts.security_scan:scan`, `scripts.security_scan:secret_findings`, `scripts.security_scan:python_findings`, `scripts.security_scan:audit_locks`, `swarm.phase3.cage:run`, `swarm.phase3.lane_guard:allowed`, `swarm.phase2.guard:allowed`
- **Inputs:** tracked file index; dependency locks; agent tool calls; worker commands
- **Outputs:** findings with rule ids and locations; allow/deny decisions; bounded run results
- **Depends on:** L01, L04
- **Permissions:** `read:repo`, `exec:sandbox`, `secrets:none`
- **Tools:** `python3`, `git`
- **Skills:** `skills/security-review/SKILL.md`
- **Agents:** `agent-isolation-security-engineer`, `enterprise-security-privacy-engineer`, `testing-self-healing-engineer`
- **Tests:** `tests/test_security_scan.py`, `tests/test_security.py`, `tests/test_p3_cage.py`, `tests/test_p3_team.py`, `tests/test_swarm_phase2.py`
- **Evidence boundary:** SHA-pinned CI and test/audit evidence; no blanket compliance claim
- **Evidence status:** UNVERIFIED until `python3 hub.py layers --verify` writes a current receipt.

### L10 Independent Product Ecosystem — منظومة المنتجات المستقلة

Responsibilities:
- Keep every product in its own repository, data, permissions and runtime.
- Register pinned capabilities into a project selectively and verify them offline.
- Validate the public project registry; keep private inventories out of the hub.

- **Contracts (interfaces):** `hublink:projects`, `hublink:validate_projects`, `hublink:validate_manifest`, `hublink:register`, `hublink:verify`
- **Inputs:** project manifests; reviewed hub revision; capability ids
- **Outputs:** registration plan or files; verification findings; registry audit
- **Depends on:** L01, L04, L06
- **Permissions:** `read:repo`, `read:registry`, `write:workspace`, `secrets:none`
- **Tools:** `python3`, `git`
- **Skills:** `skills/project-onboarding/SKILL.md`, `skills/hub-capabilities/SKILL.md`
- **Agents:** `nl-router-project-registry-engineer`, `github-integration-release-engineer`
- **Tests:** `tests/test_link.py`, `tests/test_engine_motion_link.py`
- **Evidence boundary:** Private registry outside public Git; local preparation differs from remote completion
- **Evidence status:** UNVERIFIED until `python3 hub.py layers --verify` writes a current receipt.

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
- **Tests:** `tests/test_release_provenance.py`, `tests/test_sdk.py`
- **Evidence boundary:** Existing provider projects preserved; incomplete permissions block relinking
- **Evidence status:** UNVERIFIED until `python3 hub.py layers --verify` writes a current receipt.

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
- **Tests:** `tests/test_technology_discovery.py`, `tests/test_os_control.py`
- **Evidence boundary:** Read-only discovery and reviewed update proposals; no automatic execution
- **Evidence status:** UNVERIFIED until `python3 hub.py layers --verify` writes a current receipt.

### L13 Advanced Engineering Reasoning — الاستدلال الهندسي المتقدم

Responsibilities:
- Rank supplied alternatives against declared constraints and evaluator receipts.
- Compute dependency schedules and refuse cycles and impossible budgets.
- Review a planned decision against independent reviews and verification.
- Order root-cause candidates from observations and declared dependencies.

- **Contracts (interfaces):** `engineering_os.reasoning:plan`, `engineering_os.reasoning:review_decision`, `engineering_os.reasoning:root_causes`
- **Inputs:** planning request with nodes and constraints; reviews; verification receipts; observations
- **Outputs:** ranked plan and schedule; decision review; root-cause ranking
- **Depends on:** L02, L03
- **Permissions:** `read:state`, `secrets:none`
- **Tools:** `python3`
- **Skills:** `skills/nextgen-intelligence/SKILL.md`
- **Agents:** `engineering-reasoning-engineer`
- **Tests:** `tests/test_reasoning.py`
- **Evidence boundary:** Deterministic ranking of supplied alternatives and schedules; no model reasoning or inferred causality
- **Evidence status:** UNVERIFIED until `python3 hub.py layers --verify` writes a current receipt.

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
- **Tests:** `tests/test_engineering_memory.py`, `tests/test_gaie_factory.py`
- **Evidence boundary:** Private file-backed memory outside Git; lexical retrieval, not embeddings; checksums detect corruption only
- **Evidence status:** UNVERIFIED until `python3 hub.py layers --verify` writes a current receipt.

### L15 Requirements & Specification Intelligence — ذكاء المتطلبات والمواصفات

Responsibilities:
- Turn an owner's Arabic or English command into clauses, a task class and a target.
- Stop with needs-clarification instead of guessing a project or repository.
- Validate bounded request documents and stage contracts before work starts.

- **Contracts (interfaces):** `engineering_os.gaie_router:normalize`, `engineering_os.gaie_router:route`, `engineering_os.gaie_router:remote_slug`, `engineering_os.intelligence:read_request`, `engineering_os.factory:validate_stage`
- **Inputs:** owner command text; project registries; request documents
- **Outputs:** normalized clauses; route or needs-clarification; stage validation result
- **Depends on:** L06, L13, L14
- **Permissions:** `read:repo`, `read:registry`, `secrets:none`
- **Tools:** `python3`
- **Skills:** `skills/gaie-master-router/SKILL.md`
- **Agents:** `nl-router-project-registry-engineer`, `engineering-reasoning-engineer`
- **Tests:** `tests/test_gaie_router.py`, `tests/test_intelligence.py`, `tests/test_factory.py`
- **Evidence boundary:** Deterministic command parsing and bounded request validation; engineering_os/requirements.py is wave 2
- **Evidence status:** UNVERIFIED until `python3 hub.py layers --verify` writes a current receipt.

### L16 Autonomous Software Factory — مصنع البرمجيات الذاتي

Responsibilities:
- Plan delivery stages for web, backend, mobile, AI, database and API targets.
- Evaluate artifacts against supplied evaluator receipts and stage contracts.
- Route build and upgrade commands to the GAIE skills and their gates.
- Install the GAIE skills idempotently without touching foreign files.

- **Contracts (interfaces):** `engineering_os.factory:plan_factory`, `engineering_os.factory:evaluate_factory`, `engineering_os.factory:validate_stage`, `engineering_os.gaie_router:policy`, `engineering_os.gaie_router:route`, `scripts.gaie_bootstrap:install`, `scripts.gaie_bootstrap:verify`
- **Inputs:** factory request; artifact receipts; owner command; GAIE route policy
- **Outputs:** factory plan; stage evaluation; routed engine and skills
- **Depends on:** L06, L09, L11, L13, L14, L15
- **Permissions:** `read:repo`, `read:registry`, `read:state`, `write:workspace`, `secrets:none`
- **Tools:** `python3`
- **Skills:** `skills/gaie-master-router/SKILL.md`, `skills/gaie-build/SKILL.md`, `skills/gaie-upgrade/SKILL.md`, `skills/gaie-audit/SKILL.md`
- **Agents:** `master-build-engine-engineer`, `master-upgrade-engine-engineer`, `nl-router-project-registry-engineer`
- **Tests:** `tests/test_factory.py`, `tests/test_gaie_router.py`, `tests/test_gaie_factory.py`
- **Evidence boundary:** Plans and checks artifacts against supplied receipts; generates no complete application and deploys nothing
- **Evidence status:** UNVERIFIED until `python3 hub.py layers --verify` writes a current receipt.

### L17 Self-Healing & Recovery Intelligence — ذكاء الإصلاح الذاتي والتعافي

Responsibilities:
- Turn bound failure evidence into ranked repair proposals.
- Verify a repair with fixed declarative checks over disposable artifacts.
- Never execute candidate code, shell commands or providers.

- **Contracts (interfaces):** `engineering_os.healing:analyze`, `engineering_os.healing:verify_repair`, `engineering_os.healing:artifact_digest`
- **Inputs:** failure evidence; candidate repair files; declarative checks
- **Outputs:** repair proposals; repair verification result; artifact digests
- **Depends on:** L09, L12, L13, L14
- **Permissions:** `read:state`, `secrets:none`
- **Tools:** `python3`
- **Skills:** `skills/nextgen-intelligence/SKILL.md`
- **Agents:** `testing-self-healing-engineer`
- **Tests:** `tests/test_healing.py`
- **Evidence boundary:** Repair proposals and fixed declarative checks; candidate code is never executed
- **Evidence status:** UNVERIFIED until `python3 hub.py layers --verify` writes a current receipt.

### L18 Advanced Cinematic Intelligence — الذكاء السينمائي المتقدم

Responsibilities:
- Keep the cinematic inventory source-bound and its namespaces distinct.
- Withdraw a browser proof when its source, harness or budget changes.
- Resolve an engine-native motion to exactly the engine files it imports.

- **Contracts (interfaces):** `engineering_os.cinematic:audit_inventory`, `hublink:resolve`
- **Inputs:** cinematic inventory; browser proof receipts; engine-motion ids
- **Outputs:** inventory audit; activation status per browser; resolved engine files
- **Depends on:** L08, L13
- **Permissions:** `read:repo`, `read:registry`, `secrets:none`
- **Tools:** `python3`, `node`
- **Skills:** `skills/gaie-cinematic/SKILL.md`, `skills/cinematic-production/SKILL.md`
- **Agents:** `cinematic-production-engineer`, `gpu-3d-digital-twin-engineer`
- **Tests:** `tests/test_cinematic_intelligence.py`, `tests/test_engine_motion_link.py`, `tests/test_nextgen_camera.mjs`
- **Evidence boundary:** Source-bound inventory and engine-motion resolution; every render needs its own browser receipt
- **Evidence status:** UNVERIFIED until `python3 hub.py layers --verify` writes a current receipt.

### L19 Engineering Economics & Resource Intelligence — اقتصاديات الهندسة وذكاء الموارد

Responsibilities:
- Summarize source-bound usage ledgers by feature, MVP and enterprise scope.
- Keep tokens, price estimates, charged amounts and subscription quota separate.
- Estimate a worker's starting context size and flag definitions over budget.

- **Contracts (interfaces):** `engineering_os.economics:summarize`, `engineering_os.economics:recommend_model`, `swarm.phase3.context_budget:budget`, `swarm.phase3.context_budget:check`
- **Inputs:** usage ledgers; model registry; agent definitions
- **Outputs:** cost and usage summary; model recommendation; context budget report
- **Depends on:** L01, L02, L12
- **Permissions:** `read:repo`, `read:state`, `secrets:none`
- **Tools:** `python3`
- **Skills:** `skills/ultra-context-optimization/SKILL.md`, `skills/headroom-context-engineering/SKILL.md`
- **Agents:** `context-token-economics-engineer`
- **Tests:** `tests/test_economics.py`, `tests/test_p3_context_budget.py`
- **Evidence boundary:** Offline accounting over supplied ledgers; tokens, cost and subscription quota stay separate
- **Evidence status:** UNVERIFIED until `python3 hub.py layers --verify` writes a current receipt.

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
- **Tests:** `tests/test_layers.py`, `tests/test_os_control.py`, `tests/test_reasoning.py`, `tests/test_release_provenance.py`
- **Evidence boundary:** Source-bound test receipts; engineering_os/assurance.py is wave 2; hashes do not authenticate reviewers
- **Evidence status:** UNVERIFIED until `python3 hub.py layers --verify` writes a current receipt.

## Evidence status

No receipt has been produced for this text yet: every layer is UNVERIFIED here.
