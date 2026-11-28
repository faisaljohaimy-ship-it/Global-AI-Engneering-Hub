# L16 (with L06 and L17) — Master Upgrade Engine

Status: implemented on `gaie/w2-upgrade`. Code: `engineering_os/upgrade_engine.py`.
Acceptance: Scenario B, `tests/test_upgrade_engine.py`. Fixture (the "existing system"):
`tests/fixtures/upgrade/taskapp`. Prompt: the "Engine" section of `prompts/MASTER_UPGRADE.md`.

The engine upgrades an **existing** system. It never builds from scratch and never edits the
target in place: every change is made in a copy inside `workdir`, proved step by step with the
target's own tests and data checksums, and delivered as an upgraded copy, a patch and a
verified rollback. It reuses the hub's engines instead of duplicating them.

| Reused engine | Used for |
|---|---|
| `gaie_router.route` / `classify` | Arabic or English command → intent (upgrade, accelerate, repair, audit), scope, focus; release, build and media are refused |
| `gaie_inventory.inventory` | component map and the coverage matrix (L06) |
| `detectors.run_all`, `detectors.Sandbox` | defects (static; runtime ones on a disposable copy when `healing.json` declares an app) and every sandboxed test run |
| `healing.heal`, `healing.safe_destination`, `healing.apply_patch`, `healing._snapshot` | the `code` step (L17), the only write path, patch verification, tree snapshots |
| `requirements.validate_spec` / `parse(base=)` / `diff_specs` / `acceptance_checks` | the system's spec, the requested change, refused breaking changes, generated acceptance tests |
| `reasoning.decompose` / `trade_off` / `validate_decision` | ordered plan, index choice, final accept/reject |
| `memory.MemoryStore` | stage checkpoints (`task_progress`), the ADR, a sealed checkpoint file |
| `economics.Tokens` / `Money` / `Seconds` | typed usage (zero tokens and money; measured seconds) |

## 1. Public API

| Callable | Side effects | Purpose |
|---|---|---|
| `upgrade(target, *, command, workdir, now=None, tests=None, policy=None, extra_steps=None, environ=None)` | `workspace-write` (a new `workdir/upgrade-*` run directory); none in audit mode | The pipeline below; returns the report. |
| `route_command(command, *, environ=None, workspace=None)` | none | Router decision plus the engine's refusals; `mode`, `scope`, `focus`, `areas`. |
| `requested_changes(command, spec)` | none | Requirements diff of the command against the spec: `ok`, `refused-breaking`, `unmet` additions. |
| `data_manifest(path, columns=None)` / `data_preserved(before, after_path)` | none (read-only, `immutable=1`) | Per-table row count and SHA-256 over the original columns; problems list. |
| `classify_migration(sql)` / `split_sql(sql)` | none | Statement verdicts; raises `UpgradeError` on any statement that can lose or rewrite data. |
| `migrate_database(path, up, down, scratch)` | scratch copies only | Applies `up` to a copy, proves data preservation and that `down` restores the schema; returns the migrated bytes. |
| `asset_references(root, rel, files)` | none | Static proof of use or non-use of one asset. |
| `audit_html`, `fix_html`, `audit_queries`, `audit_validation` | none | The audit checks and the template fixer (deterministic). |
| `verify_receipts(receipts)` | none | Recomputes every receipt hash and chain link. |
| `engine(action, payload, ctx)`, `health()`, `ENGINE_ACTIONS` | see actions | Control-plane contract: `audit` (`none`) and `upgrade` (`workspace-write`). |

`UpgradeError` is raised for every refusal; the target is never changed.

`tests` is `{"start", "pattern"}` (unittest discovery inside the target); otherwise the
manifest's `tests`, otherwise `tests/test*.py`. The optional manifest `gaie-upgrade.json`:

```json
{"schema_version": 1, "name": "task-manager",
 "tests": {"start": "tests", "pattern": "case_*.py"}, "spec": "gaie-spec.json",
 "app": {"module": "app", "routes_variable": "ROUTES", "dispatch": "dispatch",
         "connection": {"module": "store", "connect": "connect", "init": "init", "memory": ":memory:"}},
 "schema": ["schema.sql"], "databases": ["data/tasks.db"], "templates": ["templates"], "assets": ["static"]}
```

Without it, SQLite files are found by their header, schemas by `CREATE TABLE`, templates by
`.html`, assets by extension; the input-validation generator then has no app convention and
reports itself not applicable.

## 2. Pipeline

```
ROUTE → BASELINE → AUDIT → PLAN → APPLY (one receipt per step) → REGRESSION → REPORT
```

1. **ROUTE** (before anything is created) — `route_command`: `release`/deploy (also inside a
   multi-operation command), `build`, the `cinematic` media scope, all-projects runs,
   production words (`production`, «الإنتاج»), unroutable or ambiguous commands are refused,
   and so are questions and commands that mix an operation with read-only or no-change
   wording (the router returns a clarification without an intent). A command that names one
   registered project must be run on that project's verified isolated worktree: for an
   upgrade the router's `workspace_matches` (a clean, private linked worktree of the
   registered repository on a `codex/` or `claude/` branch), for an audit the same
   `workspace_policy.validate_workspace` identity check without the cleanliness rule. Several
   named projects are refused for one target. Otherwise the target is an explicit local
   path. The route is a plan and never a write grant; the engine writes only under the
   caller's `workdir`. Policy refusals:
   `network`, `deploy`, any `environment` other than `isolated-copy`, unknown fields.
   `workdir` must be outside the target and outside every Git repository. A requested change
   that `diff_specs` marks breaking is refused here.
2. **BASELINE** — snapshot the target (SHA-256 per file), copy it to
   `workdir/upgrade-*/upgraded`, run the suite twice in disposable copies (disagreeing tests
   are `flaky` and excluded), record every passing test id, the logical manifest of every
   SQLite file (tables, rows, SHA-256 over all columns, indexes, `user_version`,
   `quick_check`), the SHA-256 of every asset, every top-level function/class/method and every
   route. No passing baseline test → `blocked`, nothing is changed.
3. **AUDIT** — `gaie_inventory.inventory`, `detectors.run_all`, and the upgrade checks:
   write routes of a spec entity without a 4xx rejection path, templates without
   `lang`/`dir`, viewport or labels, filtered SQL literals whose `EXPLAIN QUERY PLAN` is a full
   `SCAN`, assets with no internal reference, and the requested change (`requested_changes`).
   The target's schema SQL is data: it runs only in a throwaway `:memory:` database
   (`detectors.schema_memory`) whose authorizer denies `ATTACH` and `VACUUM` (`VACUUM INTO`
   writes a file), `DETACH`, `load_extension` and every `PRAGMA` except schema introspection,
   `foreign_keys` and `user_version`; the attached-database limit is 0, extension loading is
   off and each script's work is bounded. A refused statement stops that script and is
   reported as `unsafe-schema-sql` (severity high), by the detectors and by the query audit.
4. **PLAN** — one step per area from a bounded generator catalogue (§3), filtered by the
   command's scope (by primary area), ordered with `reasoning.decompose` (areas in the order
   `code, architecture, database, performance, security, ui, assets, tests, docs`, the notes
   last). The ADR (keep the architecture, add only reversible layers) is recorded in memory.
   Every spec NFR is traced to the step or detector that covers it, or marked not addressed.
5. **APPLY** — per step: generate against the current copy; check every path with
   `healing.safe_destination` and the step rules (no edit of existing tests, the manifest or
   the spec; migrations classified; an asset leaves only with proof); run the suite with the
   step's new tests added (they must fail: **red**); apply; run the suite again; gates:
   suite completed, every baseline-passing test passes, every new test passes (**green**),
   every baseline table keeps rows and checksum, Python parses, no new security finding,
   functions and routes preserved, test files byte-identical, every asset present or backed up.
   Any failed gate rolls the step back and the rollback is verified against the pre-step tree.
6. **REGRESSION** — final suite; data, assets, functions, routes, test oracle; the target's
   snapshot re-taken; `upgrade.patch` applied to the original text files gives the upgraded
   ones and `rollback.patch` restores them (`healing.apply_patch`); a full restore (reverse
   text, original bytes from `rollback/`) of a copy of the upgraded tree reproduces the
   original snapshot exactly. `reasoning.validate_decision` accepts the result only with
   supporting evidence for every critical criterion (no test regression, data preserved,
   assets recoverable, functions preserved, original unchanged, rollback verified).
7. **REPORT** — artifacts in the run directory: `upgraded/`, `upgrade.patch` (or
   `rejected.patch`), `rollback.patch`, `rollback/<file>` (original bytes, databases
   included), `backup/<asset>`, `receipts.json`, `report.json`, `memory/` and
   `memory-checkpoint.json`. Status: `upgraded`, `upgraded-with-rejections`,
   `partially-upgraded` (requested additions not implemented), `no-change`, `rejected`,
   `blocked`; `audited` in audit mode.

Audit mode («افحص», «راجع», `audit`, `review`…) runs ROUTE, a static BASELINE (no tests),
AUDIT and PLAN on the target itself and writes nothing anywhere: not the target, not
`workdir`, not memory; detectors run without a sandbox. The report carries the proof
(`target_unchanged`, `workdir_untouched`).

Each receipt is `{stage, step, status, input_sha256, output_sha256, source_sha256,
side_effect, at, previous_sha256, receipt_sha256}`; the chain is deterministic for a fixed
`now`.

## 3. Step catalogue (deterministic; anything else is reported, not guessed)

| Step | Area | Precondition | Change | New tests |
|---|---|---|---|---|
| `code-repair-defects` | code | medium+ detector findings or failing baseline tests | `healing.heal` on a copy of the current tree; its validated files | the failing tests themselves |
| `security-input-validation` | security (+architecture, code) | spec entity, declared app convention, write handler without a 4xx path | `validation.py` generated from the spec fields (required, type, max, values, defaults) and a guard at the top of each handler | spec acceptance criteria for the route (`with a valid body`, `without X`, `with X=V`, `with X longer than N characters`) plus a non-object body |
| `ui-accessibility-rtl` | ui | template without `lang`/`dir`, viewport or labels | `lang`/`dir` (page language from its text, else the spec), viewport meta, `<label for>` with the spec field label, `required`/`maxlength` from the spec | every template: lang/dir consistent, viewport, every control labelled; the spec's page criterion through `dispatch` |
| `performance-query-indexes` | performance (+database) | filtered literal with a full `SCAN` | index chosen by `reasoning.trade_off` (scan avoided 0.5, sort avoided 0.3, write overhead 0.2) over measured plans; `migrations/NNNN_*.sql` and `.down.sql`; `CREATE INDEX IF NOT EXISTS` appended to the schema file that defines the table; the migration applied to every database with the table | the query plan uses the index (and no temp sort when chosen); the index exists in the shipped data |
| `assets-backup-unused` | assets | an asset with `proof: no-internal-reference` | the asset is copied to `backup/`, verified by SHA-256, then removed from the copy | — (structural proof) |
| `requested-<id>` | caller's | `extra_steps` | `replace` (exactly one occurrence), `add-file` (new only), `migration` | caller-supplied, must be red then green |
| `docs-upgrade-notes` | docs | at least one applied step | `UPGRADE.md` (Arabic and English): steps, migrations, backups, unmet requests, rollback | — |

Migrations accept only `CREATE [UNIQUE] INDEX`, `DROP INDEX`, `CREATE TABLE`, `CREATE VIEW`,
`DROP VIEW`, `ALTER TABLE … ADD COLUMN` and `PRAGMA user_version = N`, after comments are
stripped. `DROP TABLE`, `DELETE`, `UPDATE`, `INSERT`/`REPLACE`, `ALTER … DROP/RENAME`,
`VACUUM`, `ATTACH`, other pragmas and triggers are refused. Independently of the classifier,
the migration runs in a transaction on a scratch copy and is refused when any baseline row is
lost or changed; a `down` migration must restore the schema, the `user_version` and the data.

## 4. Guarantees (enforced in code, each covered by a test)

- **No loss of data**: every baseline table keeps its row count and the SHA-256 of its rows
  over the original columns after every step and at the end; data-losing migrations are
  refused statically and dynamically; the original database bytes are kept in `rollback/`.
- **No loss of functions**: every baseline top-level function, class, method and route still
  exists; existing test files are never edited; every baseline-passing test passes after every
  step (a step that breaks one is rejected and rolled back, verified).
- **No loss of assets**: an asset leaves the copy only with a `no-internal-reference` proof and
  a SHA-256-verified backup; referenced assets are untouched.
- **Never in place, never from scratch**: the target snapshot is identical before and after;
  `workdir` inside the target, empty or missing targets and build commands are refused.
- **Only the copy is written**: every write goes through `healing.safe_destination`
  (absolute paths, `..`, symlinks and escapes are refused).
- **Offline and non-production**: no deployment, no production, no network (policy refusal;
  target code runs behind the loopback-only socket guard), no shell, no model or provider call.
  Deterministic results and measured durations are labelled separately; nothing is simulated.
- **Improvements are proved**: a step's new tests must fail before it and pass after it.

## 5. Scenario B evidence (`tests/test_upgrade_engine.py`, 45 tests)

On the fixture, «طور نظام إدارة المهام بالكامل» and "Upgrade the task management system
completely" apply the same five steps (identical diffs apart from the notes). The 11 original
tests pass after every step; 10 new tests (6 validation, 2 accessibility, 2 query plan) were
red before and green after; the 300 rows keep their checksum through migration `0001`, whose
down migration is verified; `static/old-banner.png` moves to `backup/` while the referenced
logo and stylesheet stay; the fixture is byte-identical; the patch, the reverse patch and the
full rollback verify; the upgraded copy's 21 tests also pass when re-run independently.
Negative cases: audit commands write nothing (not even `workdir`); a step that breaks
`test_health` is rejected and rolled back; `DROP TABLE` and `DROP COLUMN` migrations are
refused with the data intact; a `DELETE` is still refused when the static guard is bypassed;
writes to `../../escape.txt` and to an absolute path are refused; editing an existing test is
refused; a test reaching 203.0.113.7 fails with the guard's `PermissionError`; release,
deploy, production, build, network and in-place policies, breaking requests, unsafe workdirs
and malformed steps are refused before anything is created.

## 6. Limits

- The generators are a bounded catalogue. Input validation needs the declared dispatch
  convention and a spec; other frameworks get the audit and the plan, not code. Structural
  additions requested by the command (a new field, entity or feature) are reported as unmet,
  never half-implemented; breaking changes are refused.
- Asset non-use is a static proof over internal references; external links to a served file
  cannot be ruled out (hence the backup); directory listings in code make it unprovable.
- Data proofs cover SQLite files only; other stores are copied and hashed but not compared
  row by row. Index choice uses query plans over the declared schema, not production data
  distributions; measured timings are not used as gates.
- Template fixes never invent content: images without `alt` are reported for the owner. Label
  text comes from the spec, otherwise from the control's name.
- Tests prove only what they check; a validated upgrade is not a release approval. Only
  Python `unittest` suites run, inside `detectors.Sandbox` (Python-level socket guard, not an OS
  sandbox).
- Not registered yet: the control-plane record (`governance/engines.json`) and the layer
  interfaces (`governance/layers.json`) are owned by the integrator; `ENGINE_ACTIONS` and the
  contract test give the record to add.
