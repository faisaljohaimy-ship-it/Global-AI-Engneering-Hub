---
name: gaie-master-router
description: Route an owner's natural-language engineering command, in Arabic or English, to the right GAIE engine. Use when the owner asks to build a new system, upgrade or develop a project, speed it up, audit or inspect it, fix its errors, upgrade its videos, upgrade all projects, or release it — e.g. «طور سديد», «ابنِ نظامًا جديدًا», «سرّع سديد», «افحص سديد», «أصلح أخطاء سديد», «طور فيديوهات سديد», «طور جميع مشاريعي», «انشر سديد», "upgrade Sadeed", "build a new system".
---

Turn the owner's sentence into a verified plan before doing any work.

1. Run the router with the owner's exact words. Find the engine in this order and use the first that exists: `python3 hub.py route` (hub checkout), `python3 .engineering/gaie/gaie_router.py route` (registered project), `python3 ~/.claude/skills/gaie-master-router/engine/gaie_router.py route` (user-level bootstrap).
   Add `--workspace <checkout>` when a checkout is open, so writes are blocked if its
   origin is not the target repository.
2. If the status is `needs-clarification`, relay the reason and ask the owner. Never
   guess a project or repository, and never act on a suggestion the router did not
   select. A project missing from the registries must be registered first (private
   projects in `$GAIE_HOME/projects.json`, outside Git).
3. If the status is `routed`, load the skill named in `skill` and follow it with the
   plan: `gaie-build`, `gaie-upgrade`, `gaie-audit`, `gaie-cinematic` or
   `gaie-release`. Respect `write_allowed`, `read_only`, `prohibited` and every gate.
4. Verify each target repository is reachable in this environment before writing.
   For "all projects", prepare an independent branch and plan per project; one
   project's failure or missing access never blocks or touches another.
5. Use the plan's workstreams as an upper bound for agents; use fewer when work is
   not independent. Skills marked `available: false` are not installed here: say so.
6. Search project memory before planning and save decisions, results and checkpoints
   after each phase (`gaie_memory.py --project <id> search|add`, beside the router).

The plan is routing evidence only. Repository access, skill invocation, tests and
deployment each need their own evidence in the final report.
