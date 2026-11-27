---
name: priority-capability-selection
description: Select and validate the priority AI, browser, evaluation, enterprise, motion, data and recovery capability packs. Use for reviewed capability adoption, not automatic installation.
---

1. Read catalog/priority-capability-packs.json and catalog/registry.json at a reviewed hub SHA. Select only the pack and candidate needed.
2. Confirm upstream identity, immutable version, license, commercial terms, security advisories and budget. If any are unknown, mark blocked; do not install.
3. Use an isolated environment, pinned lockfile and synthetic fixtures. Never send confidential data or credentials to external docs/model services.
4. Follow the selected pack acceptance criteria. Record host-specific tests for Codex and Claude Code separately, including unavailable metrics. MCP discovery is not proof of host invocation.
5. Use existing hub registration and release guards for approved capabilities. Do not represent proposed packs as installable hub capabilities before registration support and tests exist.
6. Submit reviewed changes in an independent branch. Do not modify production, alter permissions, incur additional cost or install all candidates merely to satisfy a count.
7. Preserve checkpoints privately and record non-sensitive evidence and unresolved blockers.
