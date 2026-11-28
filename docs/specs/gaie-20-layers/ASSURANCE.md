# L20 Independent Engineering Assurance — الضمان الهندسي المستقل

Status: implemented in `engineering_os/assurance.py`, tested by `tests/test_assurance.py`.
Registration in `governance/engines.json` and `governance/layers.json` is a separate step
(see "Registration" below); until it lands the module is reached as a Python API and a CLI,
not through `control_plane.invoke`.

## What L20 enforces

1. **The reviewer is never the producer.** `assign` refuses a reviewer equal to the producer,
   an unknown role, and a reviewer that owns any changed path. Ownership is the `owns` patterns
   of `governance/agent-roles.json`, compared with `orchestrator.overlaps` (conservative for
   patterns). Without a requested reviewer, `assign` reuses `orchestrator.review_assignment`
   (the role with the `reviewer` flag, `independent-assurance-engineer`, first; else the
   testing capacity of the approval panel) and then takes the next panel candidate that owns
   none of the changed paths. If none is left, the request is refused.
2. **A review counts only from a source-bound receipt.** `record` writes the receipt; `verify`
   accepts it only while it is intact, internally consistent, independent, and every bound
   file still has the recorded bytes.
3. **The gate fails closed.** A work item passes only with a VERIFIED receipt, a verdict other
   than `block`, and no open `critical` or `high` finding.

## Receipt

Stored at `<state>/<key>.json`: a regular, user-owned, single-link file with mode 0600 in a
user-owned 0700 directory outside any Git work tree, written atomically. The state directory
is `--state DIR`, or `ctx["state_dir"]/assurance` for the engine, or `$GAIE_HOME/assurance`
(default `~/.gaie/assurance`). A directory inside Git, with a symlinked ancestor or with group
or world permissions is refused; a receipt reached through a symlink, with another mode or
with a second hard link is not read. JSON with duplicate keys or NaN/Infinity is refused.

| Field | Meaning |
|---|---|
| `schema_version`, `kind` | `1`, `gaie-independent-review` |
| `key`, `target` | from the findings document (`key` is a slug and names the file) |
| `producer`, `reviewer` | role ids of `governance/agent-roles.json`; caller assertions |
| `commit` | subject commit (40 or 64 hex) or `null`; `--base` records `HEAD` |
| `files` | `{path: sha256}` of every reviewed file, read without following symlinks |
| `deleted` | paths the change removes; they must stay absent |
| `source_sha256` | SHA-256 of `{"files", "deleted"}` |
| `verdict` | `approve`, `approve-with-fixes` or `block` |
| `findings` | the reviewer's findings, normalized: `severity` (`critical`/`high`/`medium`/`low`) required, `id` defaults to `F<n>`, `status` to `open` (`open`/`fixed`) |
| `tried`, `summary` | optional reviewer notes |
| `review_sha256` | SHA-256 of the findings document as supplied |
| `authenticated` | always `false` |
| `at`, `duration_ms` | UTC time and measured duration of the record call |
| `contract_receipt` | valid under `contracts.validate_receipt`; `side_effect` `state-write` |
| `receipt_sha256` | SHA-256 over every other field |

All digests are `contracts.sha256` (SHA-256 of canonical JSON, or of the raw bytes for files).
A new `record` for the same key replaces the earlier receipt.

`record` refuses: self-review, an owning reviewer, a reviewed path that is missing, a
directory or reached through a symlink, a deleted path that is present, a path with `..`,
`.git`, control or glob characters, an `approve` verdict with an open critical/high finding
(contradictory: use `approve-with-fixes` or `block`), unknown fields, and credential-shaped
text (redact it first).

## Verification

`verify` reports `VERIFIED`, or `UNVERIFIED` with the reason of the first check that fails, in
this order (missing and stale files are reported together, with their paths):

| Reason | Cause |
|---|---|
| `no receipt` / `unreadable receipt (…)` | absent; symlink, unsafe mode or links, duplicate keys, bad JSON |
| `receipt fields do not match the schema` | a field added or removed |
| `receipt digest mismatch (tampered or corrupt receipt)` | the body no longer matches `receipt_sha256` |
| `receipt body invalid (…)` | a field outside its contract, including a contradictory verdict |
| `receipt digests are inconsistent with its body` | `source_sha256` or the contract receipt does not match |
| `self-review: the reviewer is the producer` | even with every digest recomputed |
| `… owns N bound path(s); the review is not independent` | checked against the current registry |
| `missing file: …` | a bound file is absent or no longer a regular file reached without symlinks |
| `stale receipt: N bound path(s) changed` | a bound file has other bytes, or a deleted path is back |

Editing one byte of a bound file withdraws `VERIFIED`; restoring the bytes restores it.

## Gate

`gate` takes work items, each a key or `{"key", "producer"?, "paths"?, "commit"?}`. An item is
approved only when its receipt is VERIFIED, the verdict is not `block`, no finding is open at
`critical` or `high`, and — when given — the producer and commit match and every listed path is
bound. Output (`gaie.assurance-gate/1`): `passed` (true only when every item is approved),
`approved`, `not_approved`, one row per item with its `reasons` and `open_findings`, and
`"authenticated": false`. Open `medium`/`low` findings do not fail the gate; they are counted.
A release engine can take this JSON as its independent-review input.

## Commands

```
python3 -m engineering_os.assurance assign --producer ROLE [--reviewer ROLE] [--paths P ...] [--json]
python3 -m engineering_os.assurance record --review FINDINGS.json --producer ROLE --reviewer ROLE \
        (--paths P ... [--deleted P ...] | --base REV) [--root DIR] [--state DIR] [--json]
python3 -m engineering_os.assurance verify KEY [--root DIR] [--state DIR] [--json]
python3 -m engineering_os.assurance gate KEY ... | --items ITEMS.json [--root DIR] [--state DIR] [--json]
python3 -m engineering_os.assurance status [--root DIR] [--state DIR] [--json]
```

Exit status: 0 success / VERIFIED / gate passed; 1 UNVERIFIED or gate failed; 2 refused request.
`--root` is the tree whose files are bound (default: the checkout the module runs from); the
role registry is always read from that checkout. `--base REV` binds every path changed in
`REV...HEAD` of `--root` (present files hashed, removed files listed as deleted), records the
`HEAD` commit, and refuses when any of those paths differs from `HEAD` in the working tree, so
the commit and the bound bytes agree. It runs only read-only `git rev-parse`, `git diff
--name-only` and `git status` with a fixed environment (`workspace_policy._git`); `REV` must be
a plain revision name.

Engine actions (`engine(action, payload, ctx)`, record `ENGINE_RECORD`, id
`independent-assurance`, layer L20): `assign` (none), `record` (state-write), `verify`, `gate`,
`status` (none). Files are read under `ctx["root"]`; receipts live in
`ctx["state_dir"]/assurance`. No payload field names an absolute filesystem location.

## From a reviewer's findings to a receipt

A reviewer writes the findings JSON of `REVIEWER_RULES` (`{"key", "target", "verdict",
"tried", "findings": [{"id", "severity", "file", "line", "summary", "scenario", "poc",
"poc_result", "fix"}]}`). Then:

```
# 1. who may review this change (never the producer, never an owner of a changed path)
python3 -m engineering_os.assurance assign --producer master-build-engine-engineer \
        --paths $(git diff --name-only main...HEAD)
# reviewer: independent-assurance-engineer (producer master-build-engine-engineer, 2 changed path(s))

# 2. bind the reviewer's findings to the reviewed bytes and the HEAD commit
python3 -m engineering_os.assurance record --review findings.json \
        --producer master-build-engine-engineer --reviewer independent-assurance-engineer --base main
# recorded feature: approve-with-fixes, ..., 1 file(s) and 1 deletion(s) bound -> .../assurance/feature.json

# 3. check it, and gate on it
python3 -m engineering_os.assurance verify feature   # VERIFIED, exit 0; after a source edit: UNVERIFIED, exit 1
python3 -m engineering_os.assurance gate feature --json
```

The outputs above were produced on 2026-11-28 on a synthetic two-commit repository (one
modified, one deleted file). For a branch built by several lanes, record one receipt per lane
(work item) with that lane's producer role and its paths (`--paths`, or `--base` in the lane's
checkout), then gate on all lane keys; passing `{"key", "producer", "paths"}` items makes the
gate also check that each receipt binds the paths that lane changed.

## Limits — what a receipt does not prove

- **Who reviewed.** Producer and reviewer are role ids asserted by the caller under one OS
  account. The digests detect staleness (a bound file changed) and corruption (the receipt was
  edited); they do not authenticate anyone. Whoever can write the state directory can write a
  consistent receipt, including one with forged roles; only self-review, ownership and the
  bound bytes are re-checked.
- That the review was thorough, or that its findings are true or complete. `fixed` is the
  reviewer's statement, not a re-test.
- Anything about files the receipt does not bind, or about a commit given with `--paths`
  (without `--base` the `commit` is `null`).
- Ownership patterns describe coordination, not OS access control (see `LAYERS.md`).

No model is called, nothing is simulated, nothing remote is touched; the module is standard
library only.

## Registration

Not part of this change (other owners): the `independent-assurance` engine record in
`governance/engines.json` with its adapter sources, the L20 interfaces and test in
`governance/layers.json` and `LAYERS.md`, role grants in `governance/agent-roles.json`, an
optional `hub.py` subcommand, and the stale "wave 2" wording in `ARCHITECTURE.md` and
`engineering_os/layers.py` (`EVIDENCE_BOUNDARY["L20"]`). The exact additions are filed as a
request for those owners.
