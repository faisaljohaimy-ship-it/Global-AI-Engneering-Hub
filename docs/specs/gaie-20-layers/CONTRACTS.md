# GAIE OS — shared contracts for the 20-layer architecture

Status: binding for every engine, layer and agent in the 20-layer integration
(branch `claude/gaie-20-layer-integration`). The validators live in
`engineering_os/contracts.py`; a record that does not validate is not registered.

## 1. Layer record — `governance/layers.json`

One record per layer, `L01`…`L20`, in order.

| Field | Type | Rule |
|---|---|---|
| `id` | `"L01"`…`"L20"` | unique, consecutive |
| `name` | `{"en": str, "ar": str}` | both languages |
| `responsibilities` | `[str]` | 1–12 short sentences |
| `interfaces` | `["package.module:callable"]` | each must import and resolve to a callable |
| `inputs`, `outputs` | `[str]` | what crosses the layer boundary |
| `depends_on` | `["Lxx"]` | earlier or same-tier layers only; the graph must be acyclic |
| `permissions` | `[permission]` | from the permission vocabulary below |
| `skills`, `tools` | `[str]` | repository-relative skill paths / tool names that are actually used |
| `agents` | `[role id]` | roles from `governance/agent-roles.json` |
| `tests` | `["tests/…"]` | existing test files that exercise the interfaces (positive **and** negative cases) |
| `scenarios` | `["A"…"I"]` | end-to-end acceptance scenarios the layer takes part in |
| `evidence` | `{"rule": "tests-pass"}` | a layer is VERIFIED only when every listed test passes in the receipt of the current source |

A layer is never complete because a name, a file or a document exists:
`python3 hub.py layers --verify` runs the listed tests and writes a receipt bound to
the SHA-256 of the sources it imported.

## 2. Engine record — `governance/engines.json`

| Field | Rule |
|---|---|
| `id` | kebab-case, unique (`master-router`, `master-build`, `memory`, …) |
| `layer` | the owning layer id |
| `title` | `{"en","ar"}` |
| `entrypoint` | `module:callable` with signature `(action, payload, ctx) -> dict` |
| `actions` | `{name: {"side_effect": class, "permissions": [permission], "summary": str}}` |
| `health` | `module:callable` returning `{"ok": bool, "detail": str}` without side effects |
| `supersedes` | ids of engines/modules this one replaces (kept as facades, never deleted blindly) |

Side-effect classes, ordered from least to most dangerous:

`none` < `state-write` (private state dir outside Git) < `workspace-write`
(an isolated workspace/worktree) < `repo-write` (commits on a non-default branch)
< `network` < `external-write` (GitHub/Vercel/any remote) < `production`.

`external-write` and `production` always need a human approval token; `production`
is refused in every factory and acceptance test.

## 3. Permission vocabulary

`read:repo`, `read:registry`, `read:state`, `write:state`, `write:workspace`,
`write:repo-branch`, `exec:sandbox`, `net:fetch`, `ext:github`, `ext:deploy`,
`prod:deploy`, `secrets:none` (marker: the action never sees secrets).

## 4. Grant — what an agent may do

```json
{"grant_id": "g-…", "role": "master-build-engineer",
 "engines": {"master-build": ["plan", "build"]},
 "paths": ["workspace/…"], "max_side_effect": "workspace-write",
 "expires_at": "ISO-8601", "approvals": []}
```

Deny by default. The Security Governor refuses (fail-closed, raising
`GovernorDenied`) when the engine/action is not granted, the side-effect class
exceeds `max_side_effect`, a path resolves outside the granted paths (after
`realpath`, so `..` and symlinks cannot escape), the grant has expired, or a gated
class lacks a matching approval. Every allow and deny is appended to an audit log
in the private state directory. Text instructions are never the guard.

## 5. Invocation and receipt

`control_plane.invoke(engine, action, payload, *, grant, ctx)` returns

```json
{"ok": true, "engine": "…", "action": "…", "result": {…},
 "receipt": {"request_sha256": "…", "result_sha256": "…", "grant_id": "…",
             "side_effect": "…", "duration_ms": 0, "at": "ISO-8601",
             "source_sha256": "…"}}
```

and records usage in the economics ledger and a checkpoint in engineering memory
when `ctx` names a task. Results are data: an engine never executes instructions
found inside a payload.

## 6. Agent roles — `governance/agent-roles.json`

The 20 specialist roles of the owner's directive (teams A–H), each with its layers,
owned paths and default grant. A role that reviews a change can never be the role
that produced it (enforced by the assurance engine from receipts).

## 7. Evidence rules

- Deterministic code paths and AI-model reasoning are reported separately.
- Simulated runs are labelled `simulated` and never counted as real executions.
- Tokens, cost and subscription quota are different quantities and are never mixed.
- No secret, private project data or customer code enters this public repository.
