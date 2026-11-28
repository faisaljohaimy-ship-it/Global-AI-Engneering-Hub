---
name: gaie-build
description: GAIE Master Build Engine — build a new software system from idea to verified release. Use when the owner asks to build or create a new system, platform, app or product («ابنِ نظامًا جديدًا», «أنشئ منصة», "build a new system"), or when the router returns engine MASTER_BUILD.
argument-hint: "[what to build]"
---

1. If no router plan is in context, run `gaie-master-router` first with the owner's
   words. Continue with a plan only when it returns `engine: MASTER_BUILD`.
   Validate the dedicated new-project workspace. The route grants no writes.
   A trusted operator must separately approve the assignment and confine the
   command to that workspace using the existing workspace supervisor.
2. Read the master prompt and follow it phase by phase (A requirements, B repository,
   C architecture, D full stack, E AI, F design and motion, G verified release). Use
   the first that exists: `prompts/MASTER_BUILD.md` (hub checkout),
   `.engineering/gaie/MASTER_BUILD.md` (registered project), `MASTER_BUILD.md` beside
   this file (user-level bootstrap).
3. Repository creation is a separate, owner-approved `external-write` action.
   Confirm no repository exists for the system and obtain a grant covering that
   exact action, owner and repository. GitHub access alone leaves this step
   blocked. Keep work local in the authorized workspace until the gate passes.
4. Link the new project with `hub.py onboard`, `register` and `verify --strict` at a
   reviewed hub revision. Updating private project state requires a separate
   permission for that state.
5. Select supporting skills from the plan (`system-builder`, `saas-platform`,
   `ai-integration`, `security-review`, `project-onboarding`) and load only those the
   current phase needs.
6. Deliver the evidence listed in the prompt's Delivery section. Production release
   goes through `gaie-release`.
