# Engineering instructions
Use the registry as a discovery index, not an executable allowlist. Review licenses, security and pinned revisions before importing external code. No paid resources without explicit approval. Never overwrite existing project files, expose secrets, or deploy across project boundaries. Use independent branches and tests. Consult relevant skills under skills/. Never put client-specific or proprietary assets in this public repository.

Resume docs/specs/operating-system/ before changing the control plane. Inspect
`python3 hub.py capabilities`, `motions`, `health` and `integrations` for scoped
evidence. Use engineering_os.orchestration with a private state directory outside
Git for task leases/handover; coordinate exact branches/paths before editing.
Leases are advisory coordination, not authenticated OS access control. Review
ARCHITECTURE.md and source-bound receipts; do not infer tool/host/provider access
from a manifest. Claude Code availability must be tested separately from Codex.

Before a large task, and whenever a command prints a lot or code must be explored, read
`skills/ultra-context-optimization/SKILL.md`: compress output with the original kept
retrievable, query code by symbol, one measured tool per kind of content.
