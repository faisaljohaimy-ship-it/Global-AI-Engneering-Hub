# L14 — Persistent engineering memory

Status: implemented on `gaie/w1-memory`. One storage engine, `engineering_os/memory.py`
(`MemoryStore`); `engineering_os/gaie_memory.py` (`Memory` + CLI) is a facade over it.
Tests: `tests/test_memory_unified.py` (new), `tests/test_engineering_memory.py`,
`tests/test_gaie_factory.py`, `tests/test_intelligence.py`.

## 1. Why one engine, and which one

PR #25 (`MemoryStore`) and PR #26 (`gaie_memory.Memory`) each stored engineering
knowledge. `MemoryStore` had the stronger validation and integrity: an fcntl lock,
atomic private writes through `orchestration`, refusal of Git, symlinked, group/world
readable or hard-linked state, exact-schema checks, content-addressed identities,
same-project link checks and a state checksum. It is the engine. `gaie_memory` kept
its API and CLI and became a facade: each project is an isolated engine store.

| Before | Now |
|---|---|
| `MemoryStore(state_dir)`: one `memory.json` (schema 1) | same API; `memory.jsonl` (schema 2); schema-1 files and checkpoints migrate on open/restore with identities unchanged |
| `gaie_memory.Memory(project)`: `entries.jsonl` hash chain | `MemoryStore.for_project($GAIE_HOME/memory, project)`; an existing journal is verified and imported once (`import_report`) |
| two secret filters | one guard (both patterns plus `security_scan` and private markers) applied to every stored string |

When `gaie_memory.py` is vendored **alone** (the skill engine directory from
`scripts/gaie_bootstrap.py`, or the `gaie-factory` pack) it cannot import the engine.
It then runs the frozen PR #26 journal (`backend == "portable-journal"`) for
add/search/related/promote only, and it refuses any project that already has an engine
store, so the two never diverge. Vendoring `memory.py`, `orchestration.py` and
`security_scan.py` beside it switches it to the engine (proven by a test).

## 2. Data model

A store is a private directory (mode 0700, user-owned, outside every Git work tree,
no symlinked ancestor) holding `memory.jsonl` (0600) and `memory.lock`.

```
line 1   {"format":"gaie-engineering-memory","schema_version":2,"revision":R,"project":P|null,
          "records":N,"symbol_files":M,"state_sha256":S}
line 2.. {"type":"record","id":ID,"row":ROW}            one per record, ascending seq
then     {"type":"symbols","project":P,"path":REL,"file":FILE}   sorted by (project, path)
```

Every line must be canonical JSON (sorted keys, no whitespace); `S` is the SHA-256 of
the canonical logical state. Editing, removing, reordering or truncating any line, or
rewriting it non-canonically, is refused (`IntegrityError`).

**Record** (identity `id = sha256(canonical(record minus provenance))`):

| Field | Rule |
|---|---|
| `project`, `kind`, `title` (≤200, one line), `summary` (≤4000, may be multi-line) | required |
| `tags` (≤30), `symbols` (≤100), `links` (untyped, ≤100 ids) | required lists |
| `provenance` | `{engine: codex\|claude-code, source_sha256}` |
| `relations` | optional typed edges `{relation, target}`; relation ∈ references, supersedes, caused-by, fixes, depends-on, relates-to, explains, verifies, concerns, implements; target must be an **earlier** record of the same project (the graph is acyclic by construction) |
| `evidence` | optional `{kind, sha256}` digests (claims, not verification) |
| `sources` | optional `{path, sha256}`: source-bound evidence, *fresh / stale / missing / unchecked* |
| `attributes` | per kind: `adr` {adr_id, context, consequences, supersedes?}; `task` {task_id, status, done[], remaining[]}; `failure` {signature} |

Kinds: architecture, decision, solution, failure, recovery, checkpoint, symbol,
pattern, root-cause, repair, test-result, quality-standard, performance, release,
lesson, adr, task. Empty optional fields normalise away, so schema-1 ids are stable.

**Row**: `{seq, created, record, provenances[], verification, merged[], lifecycle}` —
`provenances` lists every engine/source that asserted the same content; `merged`
lists near-duplicate variants folded into this record (`content_sha256`, `title`,
`provenance`); `verification` is a bound receipt (solutions and repairs only);
`lifecycle` exists only for ADRs (`status`, `history[]`, `superseded_by`).

**Symbol file**: `{sha256 of the file, module, definitions[{qualname, kind, line,
end_line, signature}]}` — kinds class, function, method, async-function, async-method.
Names, signatures and line numbers only; **no bodies, docstrings or comments**.

**Checkpoint**: `{schema_version: 2, format: "gaie-memory-checkpoint", project, state,
state_sha256}`, written exclusively (never overwritten) into a private directory.
`checkpoint()` returns `checkpoint_sha256` = SHA-256 of the file bytes.

## 3. Isolation rules

1. `MemoryStore.for_project(root, project)` derives the directory `root/<project>`
   from a slug (`[a-z0-9][a-z0-9_-]{0,79}`); callers never pass a project path.
   A root containing `..`, a symlinked or non-directory project entry, or a resolved
   path that is not exactly `realpath(root)/<project>` is refused.
2. The store is **bound**: the header carries the project and every load re-checks that
   every record and symbol file belongs to it. A state file copied from another
   project, or a multi-project store opened as a project store, is refused.
3. Every method checks its `project` argument against the binding; any other project
   raises `IsolationError`. Links and relations to another project's ids are refused.
   There is no listing method: a project handle cannot enumerate its siblings.
4. Checkpoints carry their project. Restoring one into another project, or a
   multi-project checkpoint into a project store, is refused.
5. Read-only use (`create=False`, the facade's reads, `invoke` read actions) never
   creates a directory or file for an unknown project (`MissingMemory`).
6. The legacy `MemoryStore(state_dir)` (used by `engineering_os.intelligence`) is still
   a multi-project store that filters by project in code; new callers use
   `for_project`, which is what the facade and `invoke` always do.

## 4. API (engine; every method takes the project first unless noted)

| Area | Methods |
|---|---|
| records | `put(record)`, `put_many(records)`, `import_batch(items)`, `get(id)`, `entries()` |
| graph | `graph()`, `neighbours(node, relation=None, direction="both")`, `graph_path(source, target, max_depth=6, relations=None)`; nodes are entry ids and `symbol:<path>[#<qualname>]`; derived edges `contains` (module → class → method) and `mentions` (entry → symbol) |
| ADRs | `adr_add(title, context, decision, consequences, status="proposed", supersedes=None, sources=…)`, `adr_status(adr_id, "accepted")`, `adr(adr_id)`, `adrs(status=None)`, `why(question)` |
| solutions | `verify(id, source_root, receipt_path, receipt_sha256)` (alias `verify_solution`), `solutions(source_root=None)` — statuses `unverified` (labelled UNVERIFIED), `evidence-recorded`, `source-matches-recorded-test`, `stale` |
| failures | `record_failure(signature, summary, root_cause=None, fix=None)`, `record_recovery(failure_id, …)`, `recall_failure(signature)`, `failure_signature(text)` (module function) |
| tasks | `task_progress(task_id, title, done, remaining, decisions=…)`, `next_steps(task_id=None)`, `brief()` |
| symbols | `index_repository(source_root, paths=None)`, `index_python(path, source_root, engine)` (schema-1), `where(name)`, `symbol_status(source_root)` |
| retrieval | `retrieve(query=None, kinds=None, tags=None, include_symbols=True)`; `search(query)` keeps the schema-1 scoring |
| evidence | `evidence_status(id, source_root=None)` |
| checkpoints (no project) | `checkpoint(destination)`, `restore(checkpoint, expected_sha256=None)` — restore needs an empty store |
| contract | `invoke(action, payload, ctx)`, `health()`, `ENGINE_RECORD` (validates with `contracts.validate_engine(check_imports=True)`) |

Rules worth knowing: an exact content duplicate only adds provenance; a near-duplicate
(same kind, same title words ignoring case, punctuation, order and stopwords, and the
same structured fields) is merged into the first record with its provenance recorded;
ADR, task and symbol records are never title-merged. Superseded ADRs and task versions
stay visible, flagged, at half retrieval score. ADR transitions: proposed → accepted;
accepting an ADR that supersedes another moves the older one to superseded; superseded
is terminal. Task progress is versioned: each call adds a record that supersedes the
previous version, nothing is rewritten.

Facade (`gaie_memory.Memory(project, environ)`): `add`, `search`, `related`,
`promote`, `entries` as in PR #26 (statuses `stored`, `duplicate`, `merged`),
`store()` for the bound engine store and `call(method, …)`. CLI:
`python3 -m engineering_os.gaie_memory --project P <cmd>` with `add search related
promote` plus `brief next where why adr adr-accept task failure recall solutions index
status checkpoint restore`.

## 5. How a new Claude Code session resumes work

The previous session ends with: `task` (done/remaining), any `adr`, then
`checkpoint --to <private dir>/<task>.json`, and records the printed
`checkpoint_sha256` in its hand-off (e.g. `/home/user/gaie-state/checkpoints/<id>.json`).
The new session:

```bash
P=my-project                     # the project slug
M="python3 -m engineering_os.gaie_memory --project $P"
# 1. Same machine: the store is already in $GAIE_HOME/memory/$P; skip to 2.
#    New machine or fresh GAIE_HOME: restore, authenticated by the hash from the hand-off.
$M restore --from /private/dir/task.json --sha256 <checkpoint_sha256>
# 2. Orient without reading the repository.
$M brief                         # open tasks with next step, ADRs by status, failures, index size
$M next --task checkout          # done / remaining / next, and the ADRs it rests on
$M where Cart.total              # path, line, signature (source_status "unchecked")
$M why ADR-0001                  # context, decision, consequences, status, supersession
$M recall "TypeError: ..."       # known root cause and fix, verified or UNVERIFIED
# 3. Before editing, re-check memory against the checkout (hashes files, stores nothing).
$M status --root .               # each indexed file: fresh, stale or missing
$M solutions --source-root .     # receipts still matching current source, or STALE
$M index --root .                # refresh the symbol index after changes
# 4. Continue, then hand off again.
$M task --id checkout --title "Checkout flow" --done "..." --remaining "..." --decision ADR-0001
$M checkpoint --to /private/dir/task-2.json
```

Acceptance Scenario D (`ScenarioDTests`) proves this end to end: process 1 indexes a
synthetic repository, records an ADR and task progress and writes a checkpoint; the
repository is renamed and deleted; process 2 — a new interpreter with a fresh state
directory and an audit hook on file opens — restores with the expected SHA-256,
answers *what's next*, *where is `Cart.total`* and *why integer cents*, records the
next version of the task and writes a new checkpoint. The hook records no access under
the old repository paths, and a deliberate control read is detected.

## 6. Limitations (honest)

- Retrieval is deterministic lexical and concept matching (folded Arabic/English
  terms, a small concept vocabulary); no embeddings, no model call, no semantics
  beyond shared words.
- The secret guard refuses credential shapes and explicit private markers
  (`[private]`, `<private>`, `gaie:private`, `*_PRIVATE_MARKER`, upper-case
  `CONFIDENTIAL`, `DO NOT SHARE`, …). It cannot recognise arbitrary client data or a
  secret in an unknown format; curate what you store. It also refuses some prose
  (e.g. "password: …", "token is …").
- Checksums detect corruption and casual edits, not a writer who recomputes every
  hash. A checkpoint is authenticated only when `restore` receives `expected_sha256`
  through a trusted channel. Storage is single-machine; the lock is advisory (fcntl).
- "Verified" means a supplied receipt with `status: passed` matched the current source
  digests; memory never runs tests. Evidence digests in `evidence` are claims.
- Near-duplicate merging keeps the first record's text; a merged variant keeps only
  its title, content hash and provenance.
- Bounds: 5000 records, 2000 indexed files, 20000 definitions, 8 MiB state file;
  every write rewrites the file atomically, so very large stores get slower.
- The private directory checks refuse a store under a symlinked path (e.g. macOS
  `/tmp`); `GAIE_HOME` is resolved, `MemoryStore` paths are not.
- Until the integrator vendors the engine (below), skill/pack copies of
  `gaie_memory.py` run the portable journal: no ADR/task/symbol commands there, and
  they refuse projects the engine manages.

## 7. Integration requests (outside this layer's owned paths)

- Vendor `engineering_os/memory.py`, `engineering_os/orchestration.py` and
  `scripts/security_scan.py` beside `gaie_memory.py` in `scripts/gaie_bootstrap.py`
  (`ENGINE`) and in `catalog/packs.json` (`gaie-factory.files`, as `memory.py`,
  `orchestration.py`, `security_scan.py`); then the portable journal can be removed.
- The control plane reaches memory only through `engineering_os/adapters.py`
  (`memory_store`, `record_checkpoint`, `memory`, `memory_health`; the `memory` record in
  `governance/engines.json`: put, search, graph, index, checkpoint, restore, verify). That
  adapter opens the multi-project `MemoryStore(<state>/memory)` (isolation rule 6) and
  detects an existing store by the engine's own file names. `memory.invoke` /
  `memory.ENGINE_RECORD` offer the wider, always project-isolated action set (adr-add,
  why, brief, task-progress, failure-record, where, …); exposing those to the control
  plane means adding them to the engines.json `memory` record and the adapter.
- List `tests/test_memory_unified.py` for L14 (Scenario D) in `governance/layers.json`.
- `docs/GAIE_FACTORY.md` still describes the PR #26 journal format.
