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
   C architecture, D full stack, E AI, F design and motion, G verified release).
   `${CLAUDE_SKILL_DIR}` is this skill's base directory. Print the prompt with the
   loader from the first location that exists, and stop if it reports drift, a missing
   file or a symlink:
   - bootstrap install (project or user scope):
     `python3 "${CLAUDE_SKILL_DIR}/../gaie-master-router/engine/master_docs.py" show MASTER_BUILD`
   - plugin install: `python3 "${CLAUDE_SKILL_DIR}/../../engineering_os/master_docs.py" show MASTER_BUILD`
   - registered project: `python3 .engineering/gaie/master_docs.py show MASTER_BUILD`
   - hub checkout: `python3 engineering_os/master_docs.py show MASTER_BUILD`
   Only an install without a loader reads the file directly, the first that exists of
   `${CLAUDE_SKILL_DIR}/MASTER_BUILD.md` (bootstrap install),
   `${CLAUDE_SKILL_DIR}/../../prompts/MASTER_BUILD.md` (plugin install),
   `.engineering/gaie/MASTER_BUILD.md` (registered project) and `prompts/MASTER_BUILD.md`
   (hub checkout); then report that its bytes were not verified.
3. Staff the build with the standing team of `governance/policies/agent-team.json`
   (`agents.team` in the plan; `python3 -m engineering_os.agent_team show --intent build`
   in a hub checkout, `agent_team.py show --intent build` beside the installed router).
   Give each work item to one role through the `gaie-specialist` agent and record roles
   without work as omitted with a reason (`agent_team check PLAN.json --intent build`).
   Run waves no larger than `effective`. A reviewer never reviews its own work.
4. Repository creation is a separate, owner-approved `external-write` action.
   Confirm no repository exists for the system and obtain a grant covering that
   exact action, owner and repository. GitHub access alone leaves this step
   blocked. Keep work local in the authorized workspace until the gate passes.
5. Link the new project with `hub.py onboard`, `register` and `verify --strict` at a
   reviewed hub revision. Updating private project state requires a separate
   permission for that state.
6. Select supporting skills from the plan (`system-builder`, `saas-platform`,
   `ai-integration`, `security-review`, `project-onboarding`) and load only those the
   current phase needs.
7. Deliver the evidence listed in the prompt's Delivery section. Production release
   goes through `gaie-release`.
