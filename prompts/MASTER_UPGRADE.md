# GAIE MASTER UPGRADE ENGINE

Permanent upgrade prompt of the Global AI Engineering Hub. Loaded by
`skills/gaie-upgrade` when the router returns `engine: MASTER_UPGRADE`, and by
`skills/gaie-cinematic` for media scope. An upgrade is comprehensive unless the
owner or the router narrows it (`scope`: comprehensive, focused, performance,
self-healing, media). It always starts from the current state of the system.

## Operating rules

1. Confirm the target first. The router names the project and repository; verify the
   repository is reachable here and that the checkout's origin matches before any
   write (`route --workspace`). Similar names never authorize editing another project.
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
`performance` or `test-result` entry in project memory.

## Step 3 — Plan and distribute

Group matrix rows into independent workstreams with explicit path ownership and one
branch or worktree each (`engineering_os.orchestration`). Use the router's
workstreams as the upper bound; spawn fewer agents when work overlaps or a smaller
team is faster, never more than 20. Give each agent only its rows, its paths and
the capabilities it needs. Record significant choices as Architecture Decision
Records with options, constraints and trade-offs.

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

The implementer is never the only reviewer. An independent verifier re-runs tests,
reviews the diff against the matrix, and checks the interface visually at several
viewport sizes and in both directions. Cover core journeys, permissions, data, AI
behaviour, integrations, media, languages, mobile, desktop, performance and
recoverability. Failed tests are reported, not hidden.

## Step 7 — Deliver

Open a documented pull request from the isolated branch; pass mandatory checks;
prepare a preview. Production release follows `skills/gaie-release` and needs
explicit owner authorization. Deliver the completed coverage matrix, the
before-and-after measurements, test results, security status, costs incurred
(expected: none) and remaining limitations. Save decisions, proven fixes, root
causes and checkpoints to project memory after every phase so a new session can
resume.

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
  scope and network are refused, as are breaking requested changes (field or entity removal).
- It works only in a copy under `workdir` (outside the target and outside every Git
  repository): baseline tests, data checksums and asset hashes first; then audit
  (`gaie_inventory`, `detectors`, spec checks), an ordered plan (`reasoning`), and one gated,
  receipted step at a time. A step stays only if every baseline-passing test still passes,
  its new tests failed before and pass after, every table keeps its rows, and nothing is
  deleted without proof of non-use and a verified backup; otherwise it is rolled back.
- Deliver its `upgraded/` copy, `upgrade.patch`, `rollback.patch` and `rollback/` through the
  isolated branch of Step 7; never apply them to production. Report `unmet_requests`,
  `rejected` steps and the `limits` field plainly; `requires_human_review` is always true.
