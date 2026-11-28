---
name: gaie-upgrade
description: GAIE Master Upgrade Engine — comprehensively upgrade an existing project from its current state, or run a scoped pass for performance or defect repair. Use when the owner asks to upgrade, develop, improve, speed up or fix a project («طور سديد», «سرّع سديد», «أصلح أخطاء سديد», "upgrade Sadeed", "speed up", "fix errors"), or when the router returns engine MASTER_UPGRADE.
argument-hint: "[project] [scope]"
---

1. If no router plan is in context, run `gaie-master-router` first with the owner's
   words; continue only when it returns `engine: MASTER_UPGRADE` with a resolved
   target. Honour its `scope` (comprehensive, focused, performance, self-healing).
2. Work in a checkout of the target repository on an isolated branch. If
   `write_allowed` is false or the checkout's origin is another repository, do not
   edit: obtain the right repository first.
3. Read the master prompt and follow its steps in order. Use the first that exists:
   `prompts/MASTER_UPGRADE.md` (hub checkout), `.engineering/gaie/MASTER_UPGRADE.md`
   (registered project), `MASTER_UPGRADE.md` beside this file (user-level bootstrap).
4. Start with the inventory (`hub.py inventory <checkout>` or
   `gaie_inventory.py <checkout>` beside the router) and complete its coverage matrix;
   record a measured baseline before changing anything.
5. Load supporting skills only as needed (`security-review`, `universal-motion`,
   `digital-motion`, `chromium-engineering`, `headroom-context-engineering`,
   `hub-capabilities`). Media work goes through `gaie-cinematic`.
6. Finish with independent verification, a documented pull request and the delivery
   evidence from the prompt. Production release goes through `gaie-release`.
