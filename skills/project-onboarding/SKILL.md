---
name: project-onboarding
description: Connect an existing or new project to the shared engineering foundation.
---

Inventory existing configuration. Run hub.py onboard in dry-run first. Review generated files and pin hub revision. Use a separate branch and PR. Do not overwrite existing instructions.

To make the link verifiable, follow docs/REGISTRATION.md: run `hub.py register` in dry-run, then with `--apply`, choosing only the capabilities the project will use; add the workflow from templates/hub-link.yml; run `hub.py verify` and report its level. A manifest with no capability is declared-only, not linked. List only public repositories in projects/registry.json.
