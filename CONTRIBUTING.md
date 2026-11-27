# Contributing

Read AGENTS.md and the active specification before work. Resume existing modules
and evidence rather than rebuilding them. Use an isolated worktree/branch for each
owner; do not edit another agent's files concurrently. Shared task state and
handover receipts remain private and are validated by the orchestration CLI.

Implement only useful modules with tests; no empty architecture placeholders.
Preserve existing CLI/SDK/motion compatibility and upstream licenses. Catalog and
discovery findings are data, not an executable allowlist. Never add secrets,
private product identity/assets or production configuration dumps to public Git.

Run applicable existing/new tests, bounded browser/performance checks, secret and
dependency scans. State passed/failed/skipped checks and the exact source revision.
Submit a focused PR; require fresh checks on its exact head and resolve review
blockers before merge. Keep new schedules read-only and public/free within current
limits; do not provision paid services or enable model calls without verified scope.

Release only a reviewed merged version. Project adoption is selective and pinned
to a full SHA with checksums; it must work offline. Product deployment remains a
separate per-project gated operation with known-good rollback and post-release
smoke evidence. Never force-push or silently replace working source/agent instructions.
