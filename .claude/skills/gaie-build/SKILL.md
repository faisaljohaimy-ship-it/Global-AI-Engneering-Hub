---
name: gaie-build
description: GAIE Master Build Engine — build a new software system from idea to verified release. Use when the owner asks to build or create a new system, platform, app or product («ابنِ نظامًا جديدًا», «أنشئ منصة», "build a new system"), or when the router returns engine MASTER_BUILD.
argument-hint: "[what to build]"
---

1. If no router plan is in context, run `gaie-master-router` first with the owner's
   words; continue only when it returns `engine: MASTER_BUILD`.
2. Read the master prompt and follow it phase by phase (A requirements, B repository,
   C architecture, D full stack, E AI, F design and motion, G verified release). Use
   the first that exists: `prompts/MASTER_BUILD.md` (hub checkout),
   `.engineering/gaie/MASTER_BUILD.md` (registered project), `MASTER_BUILD.md` beside
   this file (user-level bootstrap).
3. Repository creation: confirm no repository exists for the system; create a private
   one only when this environment has GitHub permission to do so; otherwise report
   the blocker. Never create test or placeholder repositories in the owner's account.
4. Link the new project with `hub.py onboard`, `register` and `verify --strict` at a
   reviewed hub revision, and add it to the private project overlay.
5. Select supporting skills from the plan (`system-builder`, `saas-platform`,
   `ai-integration`, `security-review`, `project-onboarding`) and load only those the
   current phase needs.
6. Deliver the evidence listed in the prompt's Delivery section. Production release
   goes through `gaie-release`.
