# Local engineering orchestration

`engineering_os.orchestration` is an executable file-backed coordination protocol
for Codex (primary), Claude Code (secondary) and the listed specialist roles. It
does not spawn an agent, call a model, schedule a daemon or deploy a project.
Existing agents can exchange state and handover receipts through it.

State belongs in a private directory outside every Git repository. Repository
names and business context stay there, never in this public hub. A project key is
an opaque local identifier. All task fields are allowlisted; provider credentials
and raw test/production payloads are not accepted as evidence. Evidence references
use `{"kind":"unit-tests","sha256":"<64 lowercase hex characters>"}`.

```sh
python3 -m engineering_os.orchestration --help
python3 -m engineering_os.orchestration --state-dir /private/task-state status
python3 -m engineering_os.orchestration --state-dir /private/task-state create \
  --spec /private/task.json --revision 0 \
  --actor lead --engine codex --role orchestrator
python3 -m engineering_os.orchestration --state-dir /private/task-state claim \
  --task architecture-review --version 1 \
  --actor architect --engine codex --role architecture --ttl 900
```

Task specification fields: `id`, `project`, `branch`, `paths`, `title`, `priority`.
Optional `role` defaults to development; optional `engine` restricts the task to
Codex or Claude Code (absent means either). `route --actor ... --engine ... --role
...` recommends the highest-priority compatible claimable task without claiming
it. `claim` atomically enforces the same role/engine and branch-ownership rules.
Priority is an integer P0–P3. Branches must use `codex/` or `claude/`; production
branches cannot be claimed. File scopes are explicit relative paths or directory
prefixes, with no traversal, Git metadata or globs. Only one active task may own a
project/branch, even if its declared file list differs. Separate worktrees and
branches can own overlapping files; integrating their changes still needs review.

Every mutation compares the task version (creation compares the store revision).
`claim` returns a lease ID; `renew`, `handover`, `submit` and `fail` require that ID,
the current owner and an unexpired lease. Handover clears the lease, allowing the
other engine to claim the next version. `submit` requires receipt digests and enters
review. Distinct testing, security and release reviewers approve before `done`;
self-review and one reviewer filling multiple independent roles are rejected.
Rejected review blocks the task. Failed/blocked/expired work requires explicit
orchestrator `recover`; stale workers cannot mutate with their old lease/version.

`checkpoint --output /private/snapshots/checkpoint.json` creates a checksummed
snapshot without overwriting an existing file. `restore --input ...` works only
in a new empty state store. The OS file lock serializes concurrent writers, and
state updates are fsynced and atomically replaced. Audit events form a SHA256 chain
including the current task digest; edits to tasks or previous events are detected.
This is local integrity evidence, not a signed authority or proof that a review
actually happened. Actors are assertions by the same OS account. File leases do
not prevent someone editing source outside this protocol.

`governance/policies/orchestration.json` documents the enforced defaults. Its values
are a versioned policy description, not a writable runtime override or authority
to enable a service. Project release and security policies remain separate gates.

## Model selection

`engineering_os.model_router.select_model(registry, request, evidence)` selects a
model only after all filters pass: exact reviewed pin/model ID, project-specific
operational/test receipts, task and complexity, context capacity, measured quality,
latency, privacy, permissions, remaining requests/tokens, current pricing and cost
authority. Remote models also require their named credential to exist in the
calling process; the credential is never returned. Zero-priced remote operation
needs explicit verified free allowance. Local runtimes need matching artifact
digests. Missing, stale, future, nonfinite or malformed constraints fail closed.
Monetary inputs support at most twelve fractional decimal places and use a
64-digit calculation context; extreme exponents cannot underflow into free work.

The default `catalog/models/registry.json` contains five provider placeholders and
zero available model versions. It never treats a ChatGPT/Claude session or an
installed CLI as an authenticated API model. No model API calls, paid resources,
fallback retries or quota reservations occur. Evaluator receipts must originate
from a trusted evaluator; this module validates supplied records, not their
real-world truth. Revalidate and reserve usage before an eventual provider call.

```sh
python3 -m engineering_os.model_router --registry catalog/models/registry.json \
  --request /private/request-metadata.json --evidence /private/evaluation.json
```

Exit codes: 0 eligible, 2 no eligible model, 1 malformed input. Unit tests use
explicitly synthetic local/remote fixtures, never actual model calls or invented
provider availability. Orchestration and routing both remain usable offline.
