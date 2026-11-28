# Engineering instructions
Use the registry as a discovery index, not an executable allowlist. Review licenses, security and pinned revisions before importing external code. No paid resources without explicit approval. Never overwrite existing project files, expose secrets, or deploy across project boundaries. Use independent branches and tests. Consult relevant skills under skills/. Never put client-specific or proprietary assets in this public repository.

Resume docs/specs/operating-system/ before changing the control plane. Inspect
`python3 hub.py capabilities`, `motions`, `health` and `integrations` for scoped
evidence. Use engineering_os.orchestration with a private state directory outside
Git for task leases/handover; coordinate exact branches/paths before editing.
Leases are advisory coordination, not authenticated OS access control. Review
ARCHITECTURE.md and source-bound receipts; do not infer tool/host/provider access
from a manifest. Claude Code availability must be tested separately from Codex.

For scoped tool-output context preparation, discover
`skills/headroom-context-engineering/SKILL.md` and
`docs/headroom-context-engineering.md`. Headroom is an optional reviewed local SDK
capability; preserve protected/short inputs and verified originals. Do not infer
native host/MCP activation, exact token/billing savings or production authority.

For an owner command in natural language (Arabic or English) to build, upgrade,
speed up, audit, fix or release a project, or to upgrade its videos, run
`python3 hub.py route "<the owner's words>"` and follow the skill it names under
`skills/gaie-*` (see `docs/GAIE_FACTORY.md`). A `needs-clarification` result means
ask; never guess a project or repository. A route is a plan, not execution evidence.
