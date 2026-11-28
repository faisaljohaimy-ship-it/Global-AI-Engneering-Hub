# L17 — Self-Healing & Recovery

Status: implemented on `gaie/w1-healing`. Code: `engineering_os/detectors.py`,
`engineering_os/healing.py`. Acceptance: Scenario F, `tests/test_self_healing_loop.py`.
Unit tests: `tests/test_healing.py`. Fixture: `tests/fixtures/healing/webapp`.

The engine finds defects in a target directory, traces them to candidate root causes,
and repairs what it can **only in an isolated copy**, proving each repair with the
target's own tests. It produces a unified diff, rollback data and one hash-chained
receipt per stage. It never edits the target, never deploys, never calls a model or
provider, and never uses a shell.

## 1. Public API

| Callable | Side effects | Purpose |
|---|---|---|
| `healing.heal(target, *, workdir, tests, now=None, policy=None, ffprobe="auto")` | `workspace-write` (a new run directory under `workdir`) | The governed loop below. |
| `healing.analyze(request, *, now)` | none | Existing: ranks supplied evidence (now also reused as the regression cross-check). |
| `healing.verify_repair(request)` | none (temp dir) | Existing: artifact/rollback check of disposable copies (now reused in VALIDATE). |
| `healing.apply_patch(files, patch)` | none | Exact (no fuzz) unified-diff applier used to verify the patch and the reverse patch. |
| `healing.verify_receipts(receipts)` | none | Recomputes every stage receipt and its chain link. |
| `healing.safe_destination(base, rel)` | none | The write guard: refuses absolute paths, `..`, backslashes, symlink components and escapes. |
| `healing.mutation_candidates(source, qualname, line)` | none | The bounded mutation catalogue as minimal source edits. |
| `healing.handler_source(route, spec, ...)` | none | Generates a route handler from a declared spec template, or refuses. |
| `detectors.run_all(root, manifest=None, *, runtime=False, ...)` | none unless `runtime=True` | All detectors; runtime ones execute target code and only run when asked. |
| `detectors.detect_*`, `detectors.Sandbox` | see §2 | Individual detectors and the child-process runner. |

`tests` is `{"start": "<dir>", "pattern": "<glob>.py"}` (unittest discovery inside the
target). An optional `healing.json` manifest in the target declares the app, route
spec, contracts, dependency files, schema, memory checks and performance baseline;
without it, only auto-discoverable detectors run and the rest report `not-configured`.

## 2. Detectors

Every finding is `{id, key, detector, kind, location{path,line,symbol}, evidence, severity}`
with severity `info < low < medium < high < critical`. `key` is stable across line moves
(used to prove a finding was resolved); `id` is unique per location. Evidence never
contains a matched secret value. Each detector report carries `status`
(`ran | partial | skipped | not-configured | error`), a `reason` and its `method`.

| Detector | Method (deterministic unless noted) | Kinds |
|---|---|---|
| broken-routes | AST of the literal route table vs module definitions/imports vs `routes.json` vs `href/src/action` in HTML | `missing-route-handler`, `route-missing-from-table`, `undeclared-route`, `broken-internal-link`, `duplicate-route` |
| broken-apis | start the app via `Sandbox.http` on 127.0.0.1 and probe declared GET routes from inside the same sandbox, check status and JSON shape | `app-start-failed`, `api-unreachable`, `api-error-status`, `api-status-mismatch`, `api-shape-mismatch` |
| integrations | consumer contract runner (`contracts.json`) against the same loopback app: status, shape, exact JSON | `contract-failed` |
| dead-code | top-level definitions with no reference in code, string literals, `__all__` or text files; self-references ignored | `dead-code` with `proof: no-static-reference` or `unproven-dynamic-access` |
| duplicates | SHA-256 of the AST with name, docstring and local names alpha-renamed (min size 24 nodes) | `duplicate-component` |
| dependencies | pip requirements (incl. `-r`, markers, hashes) vs exact pins vs lock (`{"packages":…}` JSON, Pipfile.lock, hashed text lock); PEP 440 subset | `pin-lock-mismatch`, `range-violation`, `conflicting-pins`, `unlocked-requirement`, `unpinned-requirement`, `unparsed-requirement` |
| memory | `tracemalloc` in a child process: 4 rounds of N calls; leak only if total growth ≥ threshold and every round grew (**measured**) | `memory-growth`, `memory-check-failed` |
| performance | median per-call `perf_counter` time vs stored baseline × tolerance (**measured, noisy**) | `performance-regression`, `performance-check-failed` |
| security | `eval`/`exec`, `shell=True`/`os.system` (reuses `scripts/security_scan.py`), unsafe loaders, credential look-alikes (reused scanner), disabled TLS (`verify=False`, `CERT_NONE`, `_create_unverified_context`, `check_hostname=False`, `NODE_TLS_REJECT_UNAUTHORIZED=0`, `rejectUnauthorized: false`, `curl -k`); fingerprints compared to a baseline (`known`/`new`); the baseline is a multiset, one listed fingerprint per instance, so a second line identical to a known one is `new` | `dynamic-code-execution`, `shell-execution`, `unsafe-deserialization`, `insecure-temp-file`, `hard-coded-secret`, `tls-verification-disabled` |
| database | declared schema into an in-memory SQLite DB, `EXPLAIN` every SQL literal (never executed), `PRAGMA quick_check` on DB files opened read-only; a `query-error` is identified by file + whitespace-normalised statement + error class (symbol `sql:<16 hex>`), never by its line | `schema-error`, `query-error`, `database-integrity` |
| media | magic-byte signatures always; decoding with `ffprobe` when installed, otherwise `status: partial` with the reason (never a silent pass) | `media-signature-mismatch`, `broken-media` |

`Sandbox` runs target code with `python -s -B -c <fixed driver> <json>` (never a shell)
in the governor's OS sandbox (`governor.sandbox_run`, full tier, loopback profile; see
SECURITY_GOVERNOR.md §7): own user, mount, pid and network namespaces, no capabilities,
a private loopback, `/etc` hidden, the target directory read-only, one fresh writable
directory per run (HOME, TMPDIR, the result), and exactly the constructed environment
(PATH, private HOME/TMPDIR, `PYTHONHASHSEED=0`, no proxies, no `PYTHONPATH`) set with
`env -i`. Inside it the Python socket guard (connect, connect_ex, sendto, sendmsg and
getaddrinfo refuse non-loopback addresses) still runs; the OS boundary does not depend on
it. Output is capped at 32 MiB per file and only its tail is read; the run ends with its
pid namespace, so nothing it started survives. Where the host cannot build the full tier,
every run returns `status: "refused"`, executes nothing, and the runtime detectors report
`refused`; `heal` then stops as `blocked`. `Sandbox(..., isolation="process-only")` (or
`detectors.DEFAULT_ISOLATION`) is the explicit opt-in for such hosts: an ordinary child
process with the same environment, guard, timeout and output cap, whose marked processes are
all killed afterwards; it writes an allow record to `governor-audit.jsonl` in the sandbox
scratch directory, and every result's `isolation` field records the mode and tier used.
The test driver records per-test outcomes, failure frames, functions executed
(`sys.settrace`) and files opened (audit hook) for localization.

## 3. The governed loop

```
DISCOVER → ANALYZE → DESIGN → IMPLEMENT → TEST → CRITIQUE → REPAIR ─┐
   ▲                                                                │ progress and
   └──────────────────────── next iteration ◄───────────────────────┘ iteration < max
                                   └──────────────► VALIDATE (once, at the end)
```

1. **DISCOVER** — snapshot the target (SHA-256 per file), copy it into
   `workdir/heal-*/candidate`, run all detectors (runtime ones on the copy) and the
   suite twice in iteration 1 (with and without tracing; disagreeing tests are
   `flaky` and never targeted or counted). The non-traced run is the baseline.
2. **ANALYZE** — build an explicit DAG: failing test → files it executed or opened
   → causal findings located there (route, pin, schema/query); API finding → route
   finding for the same path; contract finding → API and route findings; query error
   → schema error. `reasoning.root_causes` returns failed nodes with no failed
   ancestor. Each failing-test root is localized with an Ochiai spectrum over traced
   functions in the allowed files. Roots are candidates, `causality_proven: false`.
3. **DESIGN** — one plan item per root, ordered pin → route → dead code → mutation:
   `align-pin-to-lock` (exact `==` pin vs a lock entry that carries an integrity
   hash), `restore-route-handler` (route declared in the spec with a `sql-scalar`,
   `sql-rows` or `static-json` template and the `conn-query->status-type-body`
   convention; the query must be one parameterless SELECT that EXPLAINs against the
   declared schema), `remove-dead-code` (opt-in, `proof: no-static-reference` only),
   `safe-mutation-search` (top-3 suspicious functions). Anything else is recorded
   `no-safe-repair` with its reason.
4. **IMPLEMENT** — write one candidate into the copy through `safe_destination`;
   only allowed files (default: non-test `.py` and `requirements*.txt`; never tests,
   locks, specs, contracts or baselines).
5. **TEST** — the affected (target) tests first; only if they pass, the full suite.
6. **CRITIQUE** — accept only if targets pass in the full suite, no test that passed
   in the current accepted state fails (own set logic cross-checked by `analyze`),
   the edit parses, stays within `max_patch_lines`, adds no new security finding, and
   for structural repairs the finding's `key` is gone (plus a live API probe for a
   restored route).
7. **REPAIR** — keep the accepted candidate, or restore the pre-candidate bytes and
   verify them byte-for-byte before the next candidate.
8. **VALIDATE** — re-run the full suite and all detectors on the final copy. Passes
   only if: at least one repair was accepted; every targeted baseline failure now
   passes; no baseline-passing test fails; the target's snapshot is unchanged; the
   copy's untouched files are intact; `patch.diff` applied to the originals gives the
   repaired files and `reverse.diff` restores them (`apply_patch`); `verify_repair`
   accepts the artifact and rollback checks.

Mutation catalogue: reuses `swarm/phase3/mutate.py` (comparison flip, `and`/`or`,
`not` removal, int ±1 both ways, returned boolean inversion) plus `+`/`-` swap, one
site at a time, in fixed order (comparison, binop, boolop, not, return, int; then line,
column). Each candidate is a minimal byte splice that must re-parse to exactly the
mutated AST; the first candidate that survives CRITIQUE wins.

Outputs in the run directory: `patch.diff` (or `rejected.diff`), `reverse.diff`,
`rollback/<file>` (original bytes), `receipts.json`, `report.json`. Each receipt is
`{stage, iteration, status, input_sha256, output_sha256, source_sha256, side_effect,
at, previous_sha256, receipt_sha256}`; the chain is deterministic for a fixed `now`.
Report `status`: `repaired`, `partially-repaired`, `no-safe-repair`,
`validation-failed`, `blocked`, `no-defects-found`; `defects` is a ledger mapping every
initial defect to its root causes and `repaired | resolved-indirectly | unrepaired`.

## 4. Guarantees (each enforced in code and covered by a test)

- The target is never written: work happens in a fresh copy; the target snapshot is
  compared before and after; a workdir inside the target is refused before anything
  is created; targets with absolute or escaping symlinks are refused.
- Writes go only through `safe_destination` and only to allowed files; tests are the
  oracle and can never be edited.
- Bounded: `max_iterations` 1–10, `max_candidates` 1–200 per item, `test_timeout_s`
  1–900, `max_patch_lines` 1–2000, at most 400 trials. `network: true`, any
  `environment` other than `isolated-copy` (production, in-place) and unknown policy
  fields raise `HealingError`.
- A defect with no safe repair is reported with a reason, never "fixed"; a candidate
  that breaks another test is rejected and rolled back (verified).
- No shell, no model or provider calls, no deployment; `requires_human_review: true`.
  Deterministic results and measured timings/memory samples are labelled separately;
  nothing is simulated.

## 5. Limitations — what is not detectable or repairable deterministically

- Root causes are graph roots over declared and observed dependencies, not proof of
  cause; coverage-based attribution can blame a file that merely ran.
- Repairs are only as good as the tests. A mutation that passes every test can still
  be wrong (e.g. removing a `not` in an authorization check that no test covers), and
  the first validated mutation may be unidiomatic (`size - 1` → `size - 0`). Only
  single-site mutations from the catalogue are tried; multi-line logic errors,
  wrong formulas, string/constant mistakes and missing features are reported only.
- Dead-code proof is static: any dynamic name access (`globals()`, computed
  `getattr`, `eval`, computed imports) makes removal unprovable; reflection from
  outside the target (plugins, entry points, other repositories) is invisible.
- Route checks need a literal route table; decorator-registered routes (Flask,
  FastAPI) and templated paths are not modelled; only GET routes are probed.
- Dependency checks use a PEP 440 subset and declared files only: no resolver, no
  transitive conflicts, no CVE lookup (that needs network); npm/Cargo are not parsed.
- Security patterns are syntactic: no taint analysis, no obfuscated or indirect calls.
- Memory and performance results are measurements, not proofs: tracemalloc sees only
  Python allocations, timings depend on the machine and load.
- Database checks EXPLAIN statements against the declared schema only; data-dependent
  errors (constraints, triggers) and f-string/dynamic SQL are not checked.
- Media decoding requires ffprobe; without it only signatures are checked
  (`status: partial`).
- Isolation is as strong as the tier the host provides. With the full tier target code
  cannot read or write outside its read-only copy and its per-run directory, reach the
  host network or host processes, or keep a process alive after the run (measured per
  property in `docs/evidence/gaie-20-layers/isolation.json`). It still sees the system
  directories read-only (`/usr`, `/bin`, `/sbin`, `/lib*`), runs as uid 0 of a user namespace
  mapped to the caller (all capabilities dropped), can use the whole system-call surface
  (no seccomp in the loopback profile) and is not limited in process count. Without the
  full tier nothing runs unless the process-only mode is chosen; that mode is no boundary:
  the Python guard is bypassable by native code, `ctypes` or `_socket`, and files and
  processes of the host are reachable (recorded as not-enforced in the evidence).
- The heal report does not yet carry the sandbox summary (`Sandbox.summary()`); its
  `guarantees.os_sandbox_claimed` stays `false` until healing.py records it (requested from
  that file's owner). The per-run `isolation` records are in each `Sandbox` result and in the
  runtime detector reports; the heal report does not copy them yet.
- Only Python `unittest` suites are run; flaky tests are detected by two baseline
  runs only.
