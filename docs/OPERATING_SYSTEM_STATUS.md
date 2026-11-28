# Operating-system delivery boundaries

Twenty-layer snapshot of the final integration branch `claude/eager-feynman-kztjo4`
(PR #31, draft, base `main` at `65c84fe`) at `5805d31`, 2026-11-28, plus the facts of
the release-prep merge `8d29263` named below. Nothing here is on `main` yet. The
twelve-layer OS0.1.x snapshot (`fdd3684`) stays in Git history and `CHANGELOG.md`.

This phase adds local modules and tests. It provisions no shared production runtime,
database, model subscription or continuously running agent fleet, and deploys nothing.
Several lanes are still landing; their areas are marked *in progress* and are to be
completed at the final head. The pick-up page is
[`docs/specs/gaie-20-layers/RESUME.md`](specs/gaie-20-layers/RESUME.md).

Test counts below were measured by running each file alone at `5805d31` on a 4-CPU
Linux host (`python3 -m unittest tests.<module>`, `TMPDIR=/tmp`, `GAIE_HOME` outside
Git). Engines are the records in `governance/engines.json`; `python3 hub.py
engine-health` reported `ok: true` for all 18 at this base.

| Layer | Engines in the control plane | Evidence at this base | Open at this base |
|---|---|---|---|
|L01 Owner, Policy & Governance|security-governor|`engineering_os/contracts.py`, `engineering_os/governor.py`; `tests/test_contracts.py`, `tests/test_governor.py` (56 OK, Scenario E); purposeful-motion policy `governance/policies/motion-purpose.json` (`tests/test_motion_policy.py`)|Provider administration and required-check rules need administrator access; agent-team policy and MASTER manifest in progress|
|L02 AI Intelligence & Model Routing|context-intelligence|`engineering_os/model_router.py`; `tests/test_model_router.py`|Five provider candidates, zero operational model versions, no provider call; tool activation receipts describe an earlier host (activation lane in progress)|
|L03 Adaptive Agent Orchestration|master-router, agent-swarm, adaptive-scheduler|`engineering_os/orchestration.py`, `engineering_os/orchestrator.py`; Scenario H `tests/test_orchestrator.py` (38 OK, 1 skip: live metrics file outside the repository); frozen swarm stack `swarm/phase3/FREEZE.json` (162 files)|`orchestrator` not reachable through `control_plane.invoke` (in progress); reviewer-is-producer check ignores task history (review finding M3, open)|
|L04 Engineering Control Plane|capability-registry, layers|`engineering_os/control_plane.py`, `engineering_os/adapters.py`, `hub.py` (20 subcommands); `tests/test_control_plane.py`|`build_engine`, `upgrade_engine`, `orchestrator`, `video_pipeline`, `requirements` and `security_audit` run only through their own entry points: no grant, audit row or receipt (registration in progress)|
|L05 Universal Integration Intelligence|none|`sdk/engineering_sdk.py` (read-only stdio MCP discovery), `hublink.py`; `tests/test_sdk.py`|A2A/ACP not implemented; SDK `checkout_guard` submodule bypass (review finding pr30-authz F1, medium, open)|
|L06 Software Engineering|master-upgrade (`spec`, `plan`, `evaluate` through `engineering_os/factory.py`)|`engineering_os/upgrade_engine.py`; Scenario B `tests/test_upgrade_engine.py` class `ScenarioB` (49 OK) on fixture `tests/fixtures/upgrade/taskapp`|No owner product upgraded; registered-project rule depends on wording (pr30-authz F3, low, open)|
|L07 Data & Knowledge Intelligence|none|`engineering_os/intelligence.py`; `tests/test_intelligence.py`|No shared production database; RLS, RAG and ML verification stays project-specific|
|L08 Cinematic, Motion & GPU|motion-sdk|`python3 hub.py audit`: 156 indexed specifications, 30 implemented and tested, 29 runtime-verified, plus 400 Canvas2D reference motions; `python3 -m engineering_os.motion_policy`: 47 purposeful, 37 legacy-unclassified, 400 reference, 156 specification index, 5 withdrawn, 0 unclassified|No GPU, 3D or physics runtime verified; motions that exist only on earlier branches are being ported (in progress)|
|L09 Security & Quality Intelligence|quality-assurance|`engineering_os/security_audit.py` → `docs/evidence/gaie-20-layers/security-findings.json`: 7 fixed, 1 mitigated, 4 held, 6 accepted, 4 open, no open critical or high; `scripts/security_scan.py`; `docs/evidence/gaie-20-layers/isolation.json` (tier `full` on the measuring host)|SEC-07, SEC-10, SEC-12 and `private-mode` at `engineering_os/build_engine.py:1425` open; in GitHub CI the sandbox tier is `plain`, so `SandboxTests` in `tests/test_governor.py` skip there (positive isolation job in progress)|
|L10 Independent Product Ecosystem|none|`hublink.py`, `projects/registry.json` (3 registered public projects, `hub.py audit`); `tests/test_link.py`|BILTIX, portfolio, KPI and security-lab repositories are not registered (owner decision)|
|L11 Cloud & Deployment Intelligence|master-release (`spec`, `provenance`, `eligibility`; never deploys)|`scripts/verify_release.py`, `tests/test_release_provenance.py`; at `8d29263`: six release-gating workflows and nine jobs, `docs/specs/gaie-20-layers/RELEASE_CHECKLIST.md`|Scenario G release engine in progress; no tag; nothing deployed|
|L12 Continuous Technology Intelligence|master-audit|`scripts/discover_technology.py`; `tests/test_technology_discovery.py`|Discovery never installs or approves; billing and production health not monitored|
|L13 Advanced Engineering Reasoning|reasoning|`engineering_os/reasoning.py`; `tests/test_reasoning.py`|Zero-evidence root cause reported as supported (M5) and a tie reported as robust (L6): open|
|L14 Persistent Engineering Memory|memory|`engineering_os/memory.py` (schema 2), `engineering_os/gaie_memory.py` facade; Scenario D `tests/test_memory_unified.py` class `ScenarioDTests` (26 OK)|Portable journal has no lock (M1) and no owner or link check (SEC-10); secret guard misses keys next to Arabic letters (M2); read actions create a lock (pr30-authz F2)|
|L15 Requirements & Specification Intelligence|none|`engineering_os/requirements.py`; `tests/test_requirements.py`|Not reachable through the control plane (in progress)|
|L16 Autonomous Software Factory|master-build (`spec`, `plan`, `evaluate` through `engineering_os/factory.py`)|`engineering_os/build_engine.py`; Scenario A `tests/test_build_engine_e2e.py` class `ScenarioATests` (4 OK in 90.7 s, browser run included), `tests/test_build_engine.py` (31 OK)|Builds a synthetic application only; repository creation not exercised; not reachable through the control plane (in progress)|
|L17 Self-Healing & Recovery Intelligence|self-healing (`analyze`, `verify-repair`)|`engineering_os/healing.py`, `engineering_os/detectors.py`; Scenario F `tests/test_self_healing_loop.py` class `ScenarioF` (20 OK)|**H1 high**: `heal()` can report "repaired" while its patch adds a new defect (open, blocks release); SEC-07|
|L18 Advanced Cinematic Intelligence|master-cinematic|`engineering_os/cinematic.py`, `engineering_os/video_pipeline.py`; Scenario C `tests/test_video_pipeline.py` class `ScenarioCTests` (48 OK, 1 skip: sample media is kept outside Git)|`video_pipeline` not in the control plane (in progress); narration voice and music terms are owner decisions|
|L19 Engineering Economics & Resource Intelligence|economics|`engineering_os/economics.py`; `tests/test_economics.py`|Offline accounting over supplied ledgers; account billing not measured|
|L20 Independent Engineering Assurance|none|Source-bound layer receipts (`engineering_os/layers.py`), `scripts/verify_release.py`|`engineering_os/assurance.py` is not in the tree at this base (in progress)|

The review findings named above (H1, M1–M5, L6, F1–F3) are in the independent review
register of `RESUME.md`; each is being fixed by a lane that did not review it.

## Evidence and counts

`python3 hub.py layers` reports each layer from its latest receipt; receipts live in
`$GAIE_HOME/layers`, outside Git, so a fresh machine shows all twenty `UNVERIFIED`.
`python3 hub.py layers --verify` printed `VERIFIED=20` on `0986919` (`RESUME.md`,
"Acceptance scenarios"). That run covers the 35 test files the registry lists, of
104 test files in `tests/` at this base, and the registry binds no acceptance scenario
yet (`"scenarios": []` on every layer of `governance/layers.json`). It is not a
statement about scenarios A–I. Binding is in progress.

Acceptance scenarios at this base: A, B, C, D, E, F and H pass when their files run
alone (counts in the table). G (release engine) and I (permanent Claude Code
install) are partial: read-only release pieces (`tests/test_release_provenance.py`,
6 OK) and bootstrap mechanics (`tests/test_gaie_factory.py`, 21 OK) pass, with no
acceptance test or evidence file yet. Passing tests do not close the review findings
above.

`python3 hub.py audit` at this base: 129 catalog entries, 2 approved, 22 local skills,
22 integration programs probed (12 available), 1 scoped tool tested. Motion: 156
indexed specifications (30 implemented and tested, 29 runtime-verified) and 400
Canvas2D reference motions with a source-bound Playwright 1.65.1 Chromium receipt
(`docs/evidence/playwright-1.65.1-motion-chromium-2026-11-28.json`); totals 556
indexed, 430 implemented, 429 runtime-verified. Production FPS and GPU runtime are not
verified. The 400 reference motions are illustrative Canvas2D work, not GPU, 3D or
physics integrations.

Isolation was measured on one host, not in CI:
`docs/evidence/gaie-20-layers/isolation.json` records tier `full` (own PID and network
namespace, empty environment, writes only in allowed paths) and lists what is not
enforced (process count for a sandbox mapped to uid 0, Unix sockets inside allowed
paths, no seccomp filter). The reviewer found that file out of date after the
security merge, which added a seccomp filter for strict calls (pr30-merge-quality F3);
a regenerated copy is in progress.

The 22 historical integration probes keep their original timestamps
(`integrations/EVIDENCE.json`); this is not fresh authentication to 22 providers. No
model, provider or render API call and no paid service was added in this phase.

## Handover and release

Lanes work in separate worktrees and are merged into the integration branch one at a
time after a gate (owned paths, secret scan, targeted tests, `hub.py audit`); see
`RESUME.md`, "Team at work". Private task state, receipts, memory and ledgers stay
outside Git.

Product inventories, private code and provider metadata stay outside this public
repository. No product was modified, no repository was created and no production
deployment, post-release smoke test or rollback was executed.

A hub release is the merge of PR #31 into `main` plus a GitHub Release whose new tag
`engineering-os-vX.Y.Z` points at that merge commit
(`docs/specs/gaie-20-layers/RELEASE_CHECKLIST.md`, at `8d29263`). Release validation
(`scripts/verify_release.py`, `WORKFLOWS` at `8d29263`) requires nine jobs in six
workflows to have succeeded at that exact commit: `verify.yml` (`test`, `motion in
Chromium`), `operating-system.yml` (`operating system and motion unit tests`, `fresh
Chromium and Motion Studio runtime evidence`), `security.yml` (`Tracked secrets and
Python execution hazards`), `motion-cross-browser.yml` (`Motion Studio in firefox`,
`Motion Studio in webkit`) and `nextgen-intelligence.yml` (`Original camera motions in
Chromium`) on the `main` push, and `dependency-audit.yml` (`Audit exact tracked npm
locks`) from a push, scheduled or manual run that succeeded within 24 hours. The Engineering SDK is labelled 1.0.1 at `8d29263` because its bytes
changed after the `engineering-sdk-v1.0.0` tag; it ships inside the OS release with no
tag of its own. Until the owner publishes the Release the state is **recorded, tag
pending**. No hub release makes product production depend on public GitHub
availability.
