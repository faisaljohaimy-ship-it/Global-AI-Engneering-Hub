---
name: gaie-upgrade
description: GAIE Master Upgrade Engine — comprehensively upgrade an existing project from its current state, or run a scoped pass for performance or defect repair. Use when the owner asks to upgrade, develop, improve, speed up or fix a project («طور سديد», «سرّع سديد», «أصلح أخطاء سديد», "upgrade Sadeed", "speed up", "fix errors"), or when the router returns engine MASTER_UPGRADE.
argument-hint: "[project] [scope]"
---

1. If no router plan is in context, run `gaie-master-router` first with the owner's
   words; continue only when it returns `engine: MASTER_UPGRADE` with a resolved
   target. Honour its `scope` (comprehensive, focused, performance, self-healing).
2. Work only in the verified target's isolated worktree. Before each workstream's
   write, require explicit operator approval, a matching target and branch, and a
   host grant limited to its assigned paths. Stop at planning when the
   workspace or the grant is missing.
3. Read the master prompt and follow its steps in order. Use the first that exists:
   `prompts/MASTER_UPGRADE.md` (hub checkout), `.engineering/gaie/MASTER_UPGRADE.md`
   (registered project), `MASTER_UPGRADE.md` beside this file (user-level bootstrap).
4. Staff an upgrade route (`intent: upgrade`) with the standing team of
   `governance/policies/agent-team.json` (`agents.team` in the plan;
   `python3 -m engineering_os.agent_team show --intent upgrade` in a hub checkout,
   `agent_team.py show --intent upgrade` beside the installed router). Give each work
   item to one role through the `gaie-specialist` agent and record roles without work
   as omitted with a reason (`agent_team check PLAN.json --intent upgrade`). Run waves
   no larger than `effective`. A reviewer never reviews its own work. A performance or
   repair pass has no standing team: staff it from the plan's workstreams.
5. Start with the inventory (`hub.py inventory <checkout>` or
   `gaie_inventory.py <checkout>` beside the router) and complete its coverage matrix;
   record a measured baseline before changing anything.
6. Load supporting skills only as needed (`security-review`, `universal-motion`,
   `digital-motion`, `chromium-engineering`, `headroom-context-engineering`,
   `hub-capabilities`). Media work goes through `gaie-cinematic`.
7. Finish with independent verification, a documented pull request and the delivery
   evidence from the prompt. Production release goes through `gaie-release`.
