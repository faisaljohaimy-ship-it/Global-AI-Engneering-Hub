---
name: gaie-master-router
description: Route an owner's natural-language engineering command, in Arabic or English, to the right GAIE engine. Use when the owner asks to build a new system, upgrade or develop a project, speed it up, audit or inspect it, fix its errors, upgrade its videos, upgrade all projects, or release it — e.g. «طور سديد», «ابنِ نظامًا جديدًا», «سرّع سديد», «افحص سديد», «أصلح أخطاء سديد», «طور فيديوهات سديد», «طور جميع مشاريعي», «انشر سديد», "upgrade Sadeed", "build a new system".
---

Turn the owner's sentence into a verified plan before doing any work.

1. Use the reviewed deterministic router and pass the owner's exact words as a
   single argument. Supported entry points are `python3 hub.py route` (hub checkout),
   `python3 .engineering/gaie/gaie_router.py route` (registered project), and
   `python3 ~/.claude/skills/gaie-master-router/engine/gaie_router.py route`
   (user-level bootstrap). Pass `--workspace <checkout>` only to validate an
   identified workspace. Routing is planning.
2. If the status is `needs-clarification`, relay the reason and ask the owner. Never
   guess a project or repository, and never act on a suggestion the router did not
   select. A project missing from the registries must be registered first (private
   projects in `$GAIE_HOME/projects.json`, outside Git).
3. For a read-only plan, pass its verified checkout and scope to the restricted
   `gaie-audit` review or request a governed `master-audit` result. Return the
   report in the conversation. If the boundary cannot be verified, stop with
   that blocker.
4. For other routed plans, use the named skill and respect `write_allowed`,
   `read_only`, `prohibited` and every gate. Verify each target and enforce a
   separate host grant before writing.
   For "all projects", prepare an independent branch and plan per project; one
   project's failure or missing access never blocks or touches another.
5. For a build or upgrade, staff `agents.team`, the standing team of
   `governance/policies/agent-team.json`: each role works its items through the
   `gaie-specialist` agent or is recorded in `omitted` with a reason. Run waves no larger
   than `effective` from `agent_team show --intent <intent>` and never more than
   `agents.maximum` at once. When `agents.team_policy.status` is `not-installed`, say so.
   Other intents and a missing policy use the workstreams as an upper bound; use fewer
   when work is not independent. Skills marked `available: false` are not installed
   here: say so.
6. Keep this routing step free of memory writes and checkpoints. A separately
   authorized development phase may update state within its own grant.

The plan is routing evidence only. Repository access, skill invocation, tests and
deployment each need their own evidence in the final report.
