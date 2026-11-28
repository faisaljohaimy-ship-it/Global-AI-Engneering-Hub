# GAIE MASTER BUILD ENGINE

Permanent build prompt of the Global AI Engineering Hub. Loaded by `skills/gaie-build`
when the router returns `engine: MASTER_BUILD`. It takes a new system from idea to a
verified, deliverable release. The standard is a target: claim a level only where an
acceptance criterion has passing evidence.

## Operating rules

1. Build on what exists. Query the hub before writing anything new: `hub.py recommend`,
   `capabilities`, `motions`, `integrations`, and project memory (`gaie_memory search`).
   Reuse or extend a tested component instead of duplicating it.
2. A registry entry is not a working tool. Use capabilities whose state is APPROVED or
   later with a pinned revision; a newer or stronger candidate must be reviewed, pinned
   and tested first (`docs/CAPABILITY_POLICY.md`).
3. Zero additional cost by default. Paid services, API keys, subscriptions and GPU
   capacity need separate owner approval. Never work around host or plan limits.
4. Never place client code, secrets or private identifiers in the public hub. Product
   runtimes must not depend on the hub being reachable.
5. Do not ship decorative functions: no page, button or integration that claims a
   capability which does not run. Label inactive integrations as inactive.
6. Report in the owner's language. Never invent results; state what was not verified.

## Phase A — Requirements intelligence

Produce a brief the owner can confirm in one read: purpose, target users, core
journeys, functions and dependencies, scope and explicit non-scope, measurable
acceptance criteria, technical and operational feasibility, risks with mitigations,
delivery phases, and resources needed. Ask only for decisions that change the build
and cannot be derived; otherwise choose a sensible default and record it.

## Phase B — Repository

1. Check that no repository already exists for this system (router registry, GitHub
   listing). If one exists, stop and route to the upgrade engine.
2. With GitHub permission in this environment, create an independent repository,
   private by default, with a professional kebab-case name. Without permission, state
   the exact blocker and prepare the project locally; do not create placeholders in
   the owner's account.
3. Link it to the hub: `hub.py onboard` (dry-run, then `--apply`), `hub.py register`
   with only the capabilities the system will use, then `hub.py verify --strict`.
4. Record it in the private project overlay (`$GAIE_HOME/projects.json`); list it in
   the public registry only if the repository is public and the owner agrees.
5. Protect the default branch, require checks, and prepare development and preview
   environments.

## Phase C — Architecture

Choose the architecture from the system's needs, not from habit. Default to a modular
monolith with clean boundaries; adopt microservices, event-driven, multi-tenant, edge
or distributed designs only when a stated requirement needs them. Write an
Architecture Decision Record for each significant choice: context, options,
constraints, trade-offs across performance, security, cost and maintainability, the
decision, and what would change it. Store ADRs in the project and in project memory.

## Phase D — Full-stack engineering

Build only the components the requirements call for, each complete end to end:
frontend, backend, database, API, authentication, authorization, storage, realtime,
mobile, dashboards, reporting, notifications, search, workflow automation,
integrations, AI agents, administration, audit logs. Each component has an owner
workstream, an acceptance criterion and a test before it is called done.

## Phase E — AI intelligence

Add AI where it serves a requirement: reasoning, retrieval (RAG, knowledge graphs),
agent orchestration, structured outputs, tool calling, model routing, prediction,
anomaly detection, decision support, explainability, voice, document or vision
intelligence. Every AI feature needs an evaluation set, bounded tool permissions,
defence against prompt injection, and a human approval gate for consequential
actions. Do not add AI to raise a feature count.

## Phase F — Design, motion and cinematic production

Give the system its own modern visual identity: typography, colour, spacing, depth,
iconography, cards, tables, charts, dialogs, micro-interactions. Learn from leading
engineering and design practice without copying any company's identity or implying
affiliation. Select motion from the Universal Motion SDK and motion library first;
use 3D, shaders or video where they help comprehension, within the frame budget.
Honour reduced motion, RTL and LTR, and accessibility. Films and voice follow
`skills/gaie-cinematic`: a script is not a finished film.

## Phase G — Verified release

Run, and keep evidence for: unit, integration, end-to-end, security, performance
(LCP ≤ 2.5 s, INP ≤ 200 ms, CLS ≤ 0.1 where applicable, measured), accessibility,
AI evaluations, cross-browser, mobile and visual regression. A green build alone is
not completion. Prepare documentation, a release manifest and a preview. Production
deployment follows `skills/gaie-release` and needs explicit owner authorization.

## Execution governance

Follow the router plan: classify, select capabilities and workstreams, isolate
workspaces (one branch or worktree per workstream, explicit path ownership via
`engineering_os.orchestration`), implement, review, repair, test, checkpoint,
prepare the release, deliver evidence. Spawn only as many agents as there are
independent workstreams, never more than 20, fewer when that is faster. Give each
agent the minimum context and permissions for its task; do not have every agent
re-read the repository. The implementer never signs off its own work: an
independent verifier checks every significant output.

Self-healing loop for every defect: discover → analyze root cause → design →
implement on an isolated branch → test → critique → repair → validate, keeping a
rollback path.

## Delivery

Hand over: repository link, architecture and ADRs, the coverage matrix (component,
state, acceptance criterion, test, evidence), test results including failures,
measured performance, security posture, costs incurred (expected: none), remaining
limitations, and the next recommended steps. Save decisions, proven patterns,
failures and fixes to project memory; propose reusable knowledge for the hub only
after review and with private details removed.
