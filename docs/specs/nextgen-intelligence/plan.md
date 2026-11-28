# Plan and shared context

All lanes start from latest fetched main 6d65015 in separate codex/nextgen-*
branches and worktrees. Exact scopes/leases are held outside Git in the existing
engineering_os.orchestration.TaskStore. Seven simultaneous agents including the
coordinator is this host limit; ten is not claimed. Only relevant tool metadata
and task context is loaded. No swarm benchmark is repeated.

Integrate reasoning and memory first; factory and healing depend on those
contracts at the workflow level. Economics and cinematic are independent.
Use a modular monolith with stdlib Python modules; reuse existing validators and
state primitives. The existing hub CLI/SDK and licensed recipes remain compatible.

| Proposed extension | Existing layers reused | Added responsibility |
|---|---|---|
| L13 reasoning | L02, L03 | Constraint planning and decision review |
| L14 memory | L04, L07 | Project knowledge and checkpoints |
| L15 requirements | L06 | Acceptance traceability |
| L16 factory | L06, L09, L11 | Artifact lifecycle gates |
| L17 healing | L09, L12 | Diagnostic and repair proposals |
| L18 cinematic intelligence | L08 | Original-motion proof and selection |
| L19 engineering economics | L01, L02, L12 | Usage and cost accounting |
| L20 assurance | L01, L09, L11 | Source-bound evidence and human review |

These are proposed responsibilities over existing modules, not eight new
services or a rewrite of the canonical twelve-layer control-plane projection.

Validation: unit/negative tests per lane, shared CLI synthetic integration,
full existing Python suite, existing Node tests appropriate to motion change,
bounded Chromium desktop/mobile proof, tracked secret/AST and dependency scans,
hub audit. Remote mandatory workflows remain required on the exact PR head;
local checks cannot waive them. No merge/release until review and gates pass.
