# GAIE MASTER UPGRADE ENGINE

Permanent upgrade prompt of the Global AI Engineering Hub. Loaded by
`skills/gaie-upgrade` when the router returns `engine: MASTER_UPGRADE`, and by
`skills/gaie-cinematic` for media scope. An upgrade is comprehensive unless the
owner or the router narrows it (`scope`: comprehensive, focused, performance,
self-healing, media). It always starts from the current state of the system.

## Operating rules

1. Confirm the exact target and validate its isolated worktree with
   `route --workspace`. Require separate operator approval, the matching repository
   and branch, and a host grant restricted to that worktree before a write. For an
   audit, use the read-only course from the router.
2. Preserve what works. Do not replace a sound component without an engineering
   reason. Do not delete a function, file or asset before proving it is unused and
   keeping a way to restore it. Preserve data, permissions, identity and both
   languages.
3. Use approved, pinned capabilities; a registry entry is not a working tool. Zero
   additional cost without separate owner approval. Never bypass CI, security checks
   or host limits.
4. Keep project-private details in the project and in private memory, never in the
   public hub.
5. Measure before and after. Never claim an improvement or a target without a
   measurement; never weaken a test to make code pass.
6. Report in the owner's language; state plainly what failed or was not verified.

## Step 1 — Full system discovery

Run `hub.py inventory <checkout>` (or `.engineering/gaie/gaie_inventory.py`) and
`hub.py health --project <checkout>`, read the project's own instructions, and
search project memory for earlier decisions and failures. Then inspect, in
proportion to scope: files, routes, pages, components, functions, agents, tools,
skills, databases, integrations, APIs, images, videos, audio, motion, libraries,
packages, deployment configuration and tests.

Complete the coverage matrix the inventory starts. For every component record:
current state, problem, required upgrade, owner workstream, acceptance criterion,
test, and evidence of completion. A row is done only when its evidence exists.

## Step 2 — Baseline

Record before changing anything: test results, build status, bundle size, Core Web
Vitals where applicable (LCP, INP, CLS), API and AI response latency, slow queries,
media weight, open defects and security findings. Store the baseline as a
`performance` or `test-result` entry only under a scoped state grant.

## Step 3 — Plan and distribute

Group matrix rows into independent workstreams with explicit path ownership and
one isolated worktree per writing agent (`engineering_os.orchestration`).
Enforce a host grant restricted to that agent's paths and tools. Keep the
workstream in planning if isolation cannot be verified. Staff an upgrade with the
standing team of `governance/policies/agent-team.json` (`agents.team` in the route):
every role works its items or is recorded as omitted with a reason, never more than 20
roles, and no wave larger than `effective`. A performance, repair or media pass has no
standing team: use the router's workstreams as the upper bound. Record significant choices as Architecture
Decision Records with options, constraints and trade-offs.

## Step 4 — Upgrade

Within scope, improve every relevant dimension:

- Intelligence: reasoning quality, agents, tool use, retrieval, evaluations,
  approval gates.
- Architecture and data: boundaries, dependencies, schema, policies (RLS where the
  database supports it), indexes, reversible migrations.
- Interface and experience: layout, typography, colour, icons, cards, tables,
  charts, navigation, responsiveness, accessibility, Arabic and English.
- Motion and 3D: transitions, micro-interactions, charts, maps, digital twin and 3D
  scenes, chosen per motion for quality and frame budget, with reduced-motion
  fallbacks. Prefer the Universal Motion SDK and motion library.
- Media: films, videos, music, voice, captions (see `skills/gaie-cinematic`).
  Existing media stays until its replacement is verified.
- Performance: latency, queries, rendering, bundle size, caching, code splitting,
  lazy loading, media loading, realtime and mobile performance. Targets where
  applicable: LCP ≤ 2.5 s, INP ≤ 200 ms, CLS ≤ 0.1, measured on desktop and mobile
  including Safari where a device or engine is available.
- Security: zero trust, least privilege, authentication, authorization, session and
  API security, input validation, secret protection, dependency advisories, audit
  trails, backup and recovery. Test both allowed and denied access.
- Integrations, quality and delivery: working call paths, tests, CI, preview,
  rollback.

## Step 5 — Self-healing

For every defect found (dead code, broken routes or APIs, duplicate components,
dependency conflicts, leaks, regressions, database errors, UI defects, broken media,
failed integrations): discover → analyze root cause → design → implement on an
isolated branch → test → critique → repair → validate. Fix causes, not symptoms.
Re-run affected tests. Keep rollback possible. No risky production change without
authorization.

## Step 6 — Independent verification

An independent read-only verifier reviews the diff and source-bound test
receipts against the matrix. A fresh test or preview requires an authorized QA
run confined to its own workspace. Cover core journeys, permissions, data, AI
behaviour, integrations, media, languages, mobile, desktop, performance and
recoverability. Record failures and any unverified criteria.

## Step 7 — Deliver

Prepare a documented pull request from the isolated branch and pass mandatory
checks. Opening the remote pull request requires authorization for that action.
Remote preview and production release require separate grants under
`skills/gaie-release`. Deliver the completed coverage matrix, the
before-and-after measurements, test results, security status, costs incurred
(expected: none) and remaining limitations. Save decisions, proven fixes, root
causes and checkpoints only under a grant for the intended project memory.

## Scoped runs

- `performance`: Steps 1–2 limited to performance surfaces, then the performance
  items of Step 4, then Steps 6–7. No visual or functional redesign.
- `self-healing`: Step 1, then Step 5 over the discovered defects, then Steps 6–7.
- `focused`: only the router's `focus` areas plus quality assurance.
- `media`: handled by `skills/gaie-cinematic` under these same operating rules.

## Engine

In the hub, `engineering_os.upgrade_engine.upgrade(target, command=..., workdir=...)` executes
Steps 1–7 deterministically for a local checkout (spec:
`docs/specs/gaie-20-layers/UPGRADE_ENGINE.md`; the engine is not part of the vendored pack).
Use it before hand-editing whenever the target fits its catalogue, and read its report before
reporting to the owner.

- It routes the owner's Arabic or English command through `gaie_router`: an audit command
  («افحص», `audit`) reads only and writes nothing; build, release, deploy, production, media
  scope and network are refused, as are breaking requested changes (field or entity removal),
  questions, and read-only or no-change wording next to an operation. The route is a plan
  and grants nothing. A command that names a registered project is accepted only on that
  project's verified isolated worktree (rule 1).
- It works only in a copy under `workdir` (outside the target and outside every Git
  repository): baseline tests, data checksums and asset hashes first; then audit
  (`gaie_inventory`, `detectors`, spec checks), an ordered plan (`reasoning`), and one gated,
  receipted step at a time. A step stays only if every baseline-passing test still passes,
  its new tests failed before and pass after, every table keeps its rows, and nothing is
  deleted without proof of non-use and a verified backup; otherwise it is rolled back.
- Deliver its `upgraded/` copy, `upgrade.patch`, `rollback.patch` and `rollback/` through the
  isolated branch of Step 7. Applying the patch to that worktree is a write and needs the
  approval and host grant of rule 1; never apply it to production. Report `unmet_requests`,
  `rejected` steps and the `limits` field plainly; `requires_human_review` is always true.
