# Enterprise security and privacy review (layer L09)

Status: review of every engine merged on `claude/gaie-20-layer-integration` @41af803 (control plane,
governor, adapters, memory and gaie_memory, router and project registry, requirements, reasoning,
economics, healing and detectors, video pipeline, layers, factory, `hub.py`, `scripts/gaie_bootstrap.py`,
and the SDK the release engine calls).

- Repeatable audit: `python3 -m engineering_os.security_audit` (code: `engineering_os/security_audit.py`).
- Evidence: `docs/evidence/gaie-20-layers/security-findings.json`, written by
  `python3 -m engineering_os.security_audit --out docs/evidence/gaie-20-layers/security-findings.json`.
- Tests: `python3 -m unittest tests.test_security_enterprise` (77 tests: a regression test for each
  fixed finding, the audit's positive and negative cases, behavioural probe tests, and a live run checked against the
  evidence, and the `exec:sandbox` contract), `tests/test_sec_fixes_2_*.py` (recheck-security items 1-5) and `python3 -m unittest tests.test_gaie_memory_journal` (25 tests, SEC-10
  and the portable journal).
- Re-measured after the MASTER security hardening (`MASTER_SECURITY_ACCEPTANCE.md`) was merged: SEC-03 and
  SEC-05 keep their status under the stricter descriptor-based checks. Later reviews (pr30-authz, pr30-isolation,
  pr30-merge-quality) reopened SEC-09 and sharpened the SEC-09, SEC-11 and SEC-13 probes; SEC-10 and the build
  engine's `private-mode` hit were fixed; SEC-16 and SEC-17 were registered. On the final integration branch the
  governor sandbox for target code (sec-isolation) fixed SEC-07 and SEC-12, and the offline Git preflight
  (pr30-isolation F1) fixed SEC-09. The security re-check (recheck-security) then found the exception list of
  `layers.verify` keyed by path only: SEC-12 now reads mitigated (section 4), the SEC-07 probe also measures the
  network wall, the governor reads back only the tail of a run's output and caps the growth of its writable
  directories, process-only helpers are reaped without the environment marker, and an existing empty build target is
  made private. The evidence file was rewritten by the command above after each change.

The audit makes no network request and no model call, and it reads no clock. Each status in the evidence
comes from a probe that re-runs the exploit in a private temporary directory, or checks the control, on
every run. No status is copied from this document. No probe reads source text: each one plants the exploit, runs
the engine function and observes the result, and a stand-in that only names the right controls is reported open
(`BehaviouralProbeTests`). A probe whose planted code neither ran nor was refused raises `ProbeInconclusive`, and its
finding reads open. The probes of SEC-07, SEC-12, SEC-16 and SEC-17 depend on the governor sandbox tier, so the
report records `sandbox_tier` (`full` on the host that wrote the committed file) and marks those rows
`host_dependent`; the evidence test compares their status only on a host of the same tier, and compares every other
registered row and every static row (rule, path, function, status) everywhere. The repository scanner `scripts/security_scan.py scan`
passes on this branch with 0 findings. The audit's own privacy rules (e-mail addresses, phone numbers,
Saudi IBANs) report no open finding in the tracked tree.

## 1. Trust boundaries

| Actor or input | Trusted for | Not trusted for |
|---|---|---|
| **Owner** (repository owner, holder of approval tokens) | grants, approvals, the private state directory, `GAIE_HOME`, global Git config | nothing beyond what they sign |
| **Agent** (a grant holder: Claude Code or Codex, possibly confused or adversarial) | the engines, actions, paths and side-effect class of its grant, until `expires_at` | any action outside the grant, any authority claimed in text |
| **Payload** (JSON given to `control_plane.invoke`) | data for the named action | instructions, credentials, authorization, paths outside the grant |
| **Target repository or checkout** (project repos, release checkouts, healing targets, workspaces an agent wrote) | file contents as data | its `.git/config`, hooks, filters, attributes, symlinks, FIFOs, code it contains |
| **Generated application** (factory output) | nothing until tests and review pass | network exposure, authentication (none is generated, see residual R5) |
| **External services** (GitHub, Vercel, npm, model providers) | nothing is called by this code | n/a: `external-write` and `production` need an approval token, and `production` is refused in tests |
| **Host and other sessions** | the kernel, the system directories | other users' files and processes, shared `/tmp` |

Where these meet:
1. agent → control plane (`invoke`: grant, payload, ctx);
2. control plane → engine (the adapter receives only data);
3. engine → filesystem (private state, workspaces, target checkouts);
4. engine → child process (Git, test runners, node/ffmpeg, the sandbox);
5. repository → public (everything tracked is public).

## 2. STRIDE per engine

S spoofing · T tampering · R repudiation · I information disclosure · D denial of service · E elevation of privilege.
Each cell names the control and says whether it is enforced in code (**code**) or left to the owner (**proc.**).
"SEC-nn" is a finding in §4.

| Engine (layer) | Main threats | Controls |
|---|---|---|
| security-governor (L01) | E: an ungranted action, a higher side-effect class, a stale grant, a path escape. R/T: an edited audit trail | code: `check` deny by default (`GovernorDenied`), realpath containment, gated approvals by token digest, hash-chained append-only audit (SEC-03 fixed: private single-link file, private dir), anchor for tail truncation (SEC-06 mitigated), full-tier mount, pid and net sandbox |
| control plane (L04) | E: authority smuggled in a payload. I: a credential in a payload. D: huge payloads. T: state written into a directory others can reach | code: authority only from grant and `ctx['approval_token']` (SEC-13 held), `secrets:none` enforced by `check_payload` (SEC-02 fixed), 1 MiB payload / 16 MiB result bounds (SEC-15 held), private state dir checked before any engine runs (SEC-05 fixed), allow audited before the run |
| adapters (L04) | E: a path field the governor never checked. I: payload text in errors | code: `PATH_FIELDS` checked by the governor; error audit rows keep the class name only. proc.: new path-bearing actions must be added to `PATH_FIELDS` (see R7) |
| master-release / SDK (L11) | E/T: Git in a checkout an agent prepared runs its programs (`core.fsmonitor`, `post-index-change`, filter drivers), or is redirected (`core.worktree`, `GIT_DIR`) or blinded (assume-unchanged) | code: SEC-01 fixed. `sdk.engineering_sdk.git` runs with fsmonitor, hooks and the untracked cache off, no system or global config, no inherited `GIT_*`, no index writes, no transport or lazy fetch (`GIT_NO_LAZY_FETCH=1`, an empty `GIT_ALLOW_PROTOCOL`, `-c protocol.allow=never`) and stdin closed. `checkout_guard` refuses a partial clone (`remote.<x>.promisor`, `extensions.partialClone` or `remote.<x>.partialCloneFilter` in its own, worktree, included or `.git/modules` config) before reading the index, filter programs (local, worktree, included and submodule configs), nested submodules, a foreign work tree and hidden index entries. SEC-11 fixed: `verify` reads through `read_audit_file`, no FIFO or device reads |
| master-router, project registry (L03/L15) | T/I: a private registry that others can swap or read. T: `git remote` in a workspace | code: `GAIE_HOME` outside Git, 0600 file through `mkstemp`, home must be caller-owned and not writable by group or others (SEC-04 fixed); the router launches no Git itself: `workspace_policy._git` checks a `--workspace` with fsmonitor and the untracked cache off, no system or global config, a fixed environment without inherited `GIT_*`, no index writes, and a write scope refuses filter, hook-path, include and URL-rewrite settings. SEC-09 fixed (pr30-isolation F1): `workspace_policy._git` runs offline (`protocol.allow=never`, an empty `GIT_ALLOW_PROTOCOL`, `GIT_NO_LAZY_FETCH=1`), and a write scope also refuses `core.sshCommand`/`gitProxy`, `protocol.*`, promisor and `partialCloneFilter` remotes, remote upload/receive-pack and vcs programs, and extensions other than `worktreeConfig` and `objectFormat`, before any object lookup |
| memory, gaie_memory (L14) | I: secrets or private data in memory. T: an edited store or checkpoint. D: unbounded stores | code: secret guard, 0600/0700, locked atomic writes, owner/mode/link checks (`_open_private`), sealed checkpoints that restore only into an empty store (SEC-14 held), size bounds. The frozen portable journal opens its file the same way (SEC-10 fixed): regular, caller-owned, one link, mode 0600, in caller-owned 0700 directories; a journal that fails is refused with the fix command, never repaired |
| reasoning, requirements, economics (L13/L15/L19) | E: text treated as instructions. D: large inputs | code: pure deterministic functions over bounded JSON; no eval/exec, no subprocess, no network (static rules, 0 hits). `economics --out` writes where the owner points it (proc.) |
| self-healing, detectors (L17) | E/I: target repository code runs (tests, servers, timing probes) | code: a disposable copy, fixed driver (no shell); every run in `governor.sandbox_run` (full tier, loopback profile: own user, mount, pid and network namespaces, no capabilities, a private loopback, `/etc` hidden, the copy read-only, one fresh writable directory per run, an exact environment set with `env -i`, output capped at 32 MiB per file and read back as its last 1 MiB, the run directory's growth capped at 256 MiB,
nothing survives the run); HTTP probes are sent from inside the sandbox; where the full tier is missing every run is refused and executes nothing; `isolation="process-only"` is an explicit opt-in recorded in every result and in the governor audit log, run under a
child subreaper that ends every helper the run leaves. **Fixed (SEC-07)**; the probe also connects from a child to host
TCP listeners; measured per property in `docs/evidence/gaie-20-layers/isolation.json` |
| layers (L04/L20) | E: a repository test runs | code: every probe and test gets exactly PATH, a private HOME and TMPDIR and LANG (all hosts); where the full tier exists it runs in the strict governor profile (repository read-only, one private workspace per run, no network, socket() denied); no whole install prefix is shown to a strict test (a tool adds its bin directory only, from a root-controlled place outside every home directory); every test on a host without the full tier runs as a scrubbed subprocess; the seven measured `layers.PROCESS_ONLY_TESTS` files do too, but only while their bytes and the fixture trees they execute match the SHA-256 digests recorded at review (an edited one runs strict; a matching one runs from the hashed bytes under `python -I` with `tests/` off `sys.path`); each test row and the receipt's `execution` record the profile, tier and reason. **Mitigated (SEC-12)**: the reviewed exception files and the repository modules they import still run outside the sandbox |
| factory, master-build/upgrade (L16/L06) | T: an artifact root reached through a symlink. E: the generated application's tests run | code: every component opened with `O_NOFOLLOW`; the generated application is created 0700 with 0600 files. **Open (SEC-16, low):** `build_engine.run_suites` runs the generated tests with a reduced environment but no OS sandbox (measured: a planted test read and wrote outside the application) and its timeout kills the direct child only |
| cinematic, video pipeline (L18) | T/I: media written into the repository, or into a directory others can read | code: the output path is validated first (real path outside the repository, no symbolic link in the path), then created with mode 0700 and re-checked (SEC-08 held); voice and music inputs inside the repository are refused. **Open (SEC-17, low):** ffmpeg, ffprobe and the node renderer start with the caller's whole environment (measured: a caller variable reached all four children) and without an OS sandbox |
| context-intelligence (L02) | T: a retrieval id that climbs out of the store | code: ids are SHA-256 hex only; the store lives under private state |
| hub.py, gaie_bootstrap (L01/L16) | T: writes through symlinks into target projects | code: exclusive creates (`open("x")`, `O_EXCL|O_NOFOLLOW`), symlink components refused, an install manifest limited to known paths |
| quality-assurance (L09) | E: tests escape | code: strict `governor.sandbox_run(require_fs_isolation=True)`: one temporary writable workspace, the hub read-only, no network, no environment passthrough; refused when the full sandbox tier is unavailable |

## 3. Controls per layer: what code enforces and what the owner must do

| Layer | Enforced in code (tested) | Left to the owner or the process |
|---|---|---|
| L01 Owner & governance | grants deny by default; approval tokens checked as SHA-256 digests in constant time; audit chain; anchor (`audit_anchor`/`verify_audit_anchor`) | keep approval tokens off the command line; store the anchor outside the state directory |
| L02 Model routing | provider credentials never read from the environment (`environ={}` in the adapter) | provider keys stay outside this repository |
| L03 Orchestration | lease, version and revision checks; private task state | n/a |
| L04 Control plane | everything in the control-plane row of §2 | state directory on a single-user disk |
| L05/L10 Integration, ecosystem | SDK checksums, symlink-free paths, regular files only; clone URLs limited to `https://github.com/…` | verify upstream with `hub.py verify --strict` |
| L06/L16 Engineering, factory | `O_NOFOLLOW` reads; exclusive writes; the generated application is created 0700 with 0600 files | review generated code |
| L07/L15 Knowledge, requirements | symlinked knowledge files refused; bounded JSON | curate what enters memory |
| L08/L18 Motion, cinematic | media outside the repository | SEC-08 |
| **L09 Security & quality** | this audit; `scripts/security_scan.py`; governor sandbox; `tests/test_security_enterprise.py` | run `python3 -m engineering_os.security_audit` before merge; exit code 1 means an open critical or high finding |
| L11 Release | SEC-01 hardening; evidence bound to the exact commit; never deploys | promotion is a human step with provider receipts |
| L12 Technology intelligence | bounded, read-only | n/a |
| L13 Reasoning | pure functions | model reasoning is reported apart from deterministic results |
| L14 Memory | §2 memory row | the secret guard is a pattern filter, so client data must still be curated |
| L17 Self-healing | §2 healing row | SEC-07 |
| L19 Economics | tokens, charges and quota kept apart; no provider calls | n/a |
| L20 Assurance | receipts bound to source digests; the reviewer is never the producer | independent review |

## 4. Findings

Full machine-readable list: `security-findings.json` (registered findings with a measured status, and
static hits with path:line and rule, never a value).

Counts in the committed evidence (`sandbox_tier` full): 24 findings, 17 registered and 7 static. By status: open 2
(SEC-16, SEC-17), fixed 9, held 4, mitigated 2 (SEC-06, SEC-12), accepted 7 (all static). By severity: high 4,
medium 8, low 9, info 3. Open critical or high: none, so the audit exits 0.

| ID | Sev. | Status | Finding | Where | Proof |
|---|---|---|---|---|---|
| SEC-01 | high | fixed | release target check ran the checkout's own Git programs (fsmonitor, index hook, filters); `core.worktree`, `GIT_DIR` and assume-unchanged could hide changes | `sdk/engineering_sdk.py` `target` | `GitCheckoutTests` (12 tests, the exploit premise shown on plain Git first) |
| SEC-02 | high | fixed | `secrets:none` was declared on all 53 actions but not enforced; a credential-shaped payload reached the engine | `engineering_os/control_plane.py` `invoke` | `PayloadSecretTests` |
| SEC-03 | medium | fixed | the audit log was appended although others could read it, it was hard-linked to another file, another user owned it, or its directory was writable by others; `verify_audit` followed a swapped path and blocked on a FIFO. Now both open the log relative to the descriptor of a caller-owned mode 0700 directory | `engineering_os/governor.py` `audit`, `verify_audit` | `AuditLogTests` |
| SEC-04 | medium | fixed | the private project registry was written into a `GAIE_HOME` that another user owned or could write | `engineering_os/project_registry.py` `_write` | `RegistryHomeTests` |
| SEC-05 | medium | fixed | a state directory open to others was refused only after the engine had written state | `engineering_os/control_plane.py` `_context` | `StateDirectoryTests` |
| SEC-06 | low | mitigated | the hash chain cannot see records removed from its end, or the whole log removed | `governor.verify_audit` | `AnchorTests` (anchor helper in `security_audit`) |
| SEC-07 | medium | **fixed** | self-healing ran target code without an OS sandbox | `engineering_os/detectors.py` `Sandbox` | behavioural probe (reads, writes, the caller's environment, and since recheck-security item 2 a child's TCP connect to listeners on the host's loopback and address: a host-network stub now reads open); tests/test_isolation_enforcement.py::Sec07Tests; isolation.json |
| SEC-08 | low | held | video output directory was created (umask mode) before the "outside the repository" check; now validated first and created 0700 | `engineering_os/video_pipeline.py` `_outside_repository` | probe, `tests/test_video_pipeline.py` `OutputDirectoryTests` |
| SEC-09 | low | **fixed** | `route --workspace` ran Git in a worktree an agent may have prepared: fsmonitor, index hooks, inherited `GIT_*`, the router's own `git remote get-url` (removed), and a partial clone's promisor remote whose upload-pack or `core.sshCommand` ran during a lazy fetch (pr30-isolation F1). Now `workspace_policy._git` runs offline (`protocol.allow=never`, an empty `GIT_ALLOW_PROTOCOL`, `GIT_NO_LAZY_FETCH=1`) and a write scope refuses promisor, protocol, remote-program and unknown extension settings before any object lookup. The probe drives the router's own `_verified_write_scope` (pr30-merge-quality F1) and `_git` directly | `engineering_os/workspace_policy.py` `_git` | probe (fsmonitor, index hook, `GIT_TRACE`, promisor upload-pack, promisor ssh command, promisor upload-pack with `protocol.file.allow=always`); `WorkspaceGitTests` (10 tests, the exploit premise shown on plain Git first); tests/test_isolation_fixes_git.py |
| SEC-10 | low | fixed | frozen gaie_memory journal was appended without an owner, mode or link check (measured: an append through a hard link wrote into the other file); now an `O_NOFOLLOW` and `O_NONBLOCK` open, then `fstat` of the descriptor, for reads and appends | `engineering_os/gaie_memory.py` `_journal_add` | probe (hard link, mode 0644), `tests/test_gaie_memory_journal.py` |
| SEC-11 | low | fixed | SDK `verify` accepted a FIFO or device named in the manifest and would block on it; `verify` now reads every manifest file through `read_audit_file` (directory descriptors, `O_NOFOLLOW`, a regular file with one link, `O_NONBLOCK`, rechecked by `fstat`) | `sdk/engineering_sdk.py` `read_audit_file` | probe (runs `verify` on a manifest-named FIFO with a timeout), `test_fifo_capability_file_is_refused_without_blocking` |
| SEC-12 | medium | **mitigated** | `layers.verify` declared `exec:sandbox`/`secrets:none` but ran repository tests unsandboxed with the caller's environment. Every test now runs strict on the full tier except `layers.PROCESS_ONLY_TESTS` (seven files whose subject builds its own sandbox, or the frozen cage test). Those were keyed by path, so an edited `tests/test_healing.py` ran outside the sandbox (recheck-security: it read a planted secret and `/etc/shadow` and reached host listeners); they are now keyed by path and the SHA-256 of the reviewed bytes and fixture trees, run from those bytes with `tests/` off `sys.path`, and an edited one runs strict. Mitigated, not fixed, while the list is non-empty: the reviewed files and the repository modules they import still run as a scrubbed subprocess outside the sandbox | `engineering_os/layers.py` `_run`, `PROCESS_ONLY_TESTS` | behavioural probe (an unlisted test, an edited file at a listed path, and a pinned test with a shadowing module and bytecode beside it); tests/test_isolation_enforcement.py::Sec12Tests; tests/test_sec_fixes_2_layers.py |
| SEC-13 | info | held | authority smuggled in a payload (token, grant, instruction) grants nothing | `control_plane.invoke` | probe (open if the engine started, which surfaces as `EngineFailure`, or the audit log records an allow), `InjectionTests`, test_control_plane INJECTION |
| SEC-14 | info | held | memory checkpoints are 0600 and sealed; a tampered one does not restore | `memory.checkpoint`/`restore` | `BackupTests` |
| SEC-15 | info | held | oversized payloads are refused before authorization | `control_plane.invoke` | `PayloadSecretTests` |
| SEC-16 | low | **open** | the build engine runs the generated application's tests (`python3 -I manage.py test`, the node E2E) without the governor's OS sandbox; environment reduced, timeout kills the direct child only | `engineering_os/build_engine.py` `run_suites` | probe (plants a `manage.py` test, runs `run_suites`, host-dependent) |
| SEC-17 | low | **open** | the video pipeline starts ffmpeg, ffprobe and the node renderer with the caller's whole environment and without the governor's OS sandbox | `engineering_os/video_pipeline.py` `_run`, `_node`, `_render_frames` | probe (stand-in `node`/`ffmpeg` programs record what they received, host-dependent) |

Static hits that were reviewed and accepted (rule, enclosing function, reason in the JSON). Re-examined at this
revision; each acceptance still holds:
- `authority-from-payload` in `adapters.security_governor` (high), `engineering_os/adapters.py:991` and `:1006`.
  `:991` passes `payload["grant"]` to `contracts.validate_grant` and returns only `{valid, reason}`. `:1006` passes it to
  `governor.check`, which is pure (no audit write, no state, no subprocess): the action spec comes from
  `control_plane.load_registry()`, never from the payload, and `approval_token=None`, so a gated side effect is always
  refused with `approval-missing`. The result is marked `dry_run` and no code in `engineering_os` consumes it. The control
  plane authorizes only from its own `grant` argument and `ctx["approval_token"]` (SEC-13 probe). Residual (info): the
  dry run resolves the payload's `paths` with `realpath`, so its answer shows where a path resolves relative to the
  payload grant's roots; it reads no file content.
- `private-mode` in `governor._sandbox_init`, `engineering_os/governor.py:1269` and `:1287`: device nodes and bind-mount
  targets inside the sandbox's private tmpfs root, in a mount namespace with private propagation that is read-only
  after `pivot_root`; not state files.
- `private-mode` in `master_docs._write` (`engineering_os/master_docs.py:390`): `pin` rewrites the tracked manifest
  `governance/policies/master-prompts.json` inside the repository checkout (public, committed to Git) with mode 0644;
  it is never private state. The temporary file is created `O_EXCL|O_NOFOLLOW` beside it and replaced atomically.
- `git-dynamic-subcommand` in `hublink._git` (`hublink.py:29`): only in the hub's own checkout, with fixed subcommands
  (rev-parse, cat-file -e, merge-base --is-ancestor, show `<revision>:<path>`, ls-tree). In `scripts/security_scan.git`
  (`scripts/security_scan.py:181`): fixed plumbing (ls-files --stage, diff --cached --name-only, cat-file -s/blob) on
  the hub or a root the owner names with `--root`. None of them reads the work tree, refreshes the index or runs
  fsmonitor, filters or hooks; measured here: `git show <revision>:<path>` and `cat-file blob` do not run a configured
  textconv program (only `--textconv` does).

Registered findings re-examined: SEC-08 (the probe calls `_outside_repository` with a path inside the repository and
checks that nothing was created), SEC-13 (now also open when the engine started or an allow was audited), SEC-14
(tampered checkpoint, checkpoint mode) and SEC-15 (2 MiB payload) are behavioural and still held.

Static hit closed by a code change: `private-mode` in `build_engine._write_files` (medium) created the generated
application directory with mode 0755. It now creates that directory and every directory below it 0700 and every file
0600 (exclusive, `O_NOFOLLOW`), with one exception: `manage.py` is 0700, because the generated repository records it as
executable (Git mode 100755) and that bit is part of the committed tree. Measured: the Git modes and every blob of the
source commit are unchanged apart from `.gaie/link.json`, which binds the engine's own source digest
(`tests/test_build_engine.py` `GeneratedFileModeTests`, run with umask 0; Scenario A passes). An empty directory the
operator created (which `check_target` accepts) used to keep its mode (measured: 0777); `_write_files` now sets it to
0700 through a descriptor opened without following links, or refuses it when another user owns it
(`tests/test_sec_fixes_2_build.py`). Files the later build steps add (Git metadata, `.gaie/factory/`) follow the
caller's umask and sit inside the 0700 directory.

Read-only cross-check with `swarm/phase3/SECURITY.md` and its reviews:
- Links written through: kit faults 1/2. Same class here is SEC-03 (audit log).
- Default modes: kit fault 3. Same class here is SEC-04, SEC-05, SEC-08 (held) and SEC-10 (fixed).
- Tracebacks that leak host paths: kit F4. Here error audit rows already keep only the class name.
- "git aliases and option forms": lane net F8. Same class here is SEC-01.
- Here-document hiding: F7. No shell strings are built in `engineering_os`; the static rules find 0 `shell=True`.

The swarm itself was not changed.

## 5. Residual risks

- **R1. Isolation of target code depends on the host tier** (SEC-07 fixed, SEC-12 mitigated). With the full tier,
  healing, upgrade and layer runs are OS-sandboxed (measured per property in `isolation.json`, on this host only),
  except the reviewed `layers.PROCESS_ONLY_TESTS` files, which run as scrubbed subprocesses while their digests
  match (a concurrent writer that swaps an executed fixture between the check and the run is detected after the run
  and reported as an error, not prevented); system
  directories stay readable, the loopback profile has no seccomp filter and process count is not capped. Without the
  full tier healing and upgrade runs are refused unless the process-only mode is chosen explicitly, and layer tests run
  as scrubbed subprocesses, recorded in each receipt. Positive enforcement has not yet been observed in CI (plain tier
  there); the namespaces job with `GAIE_REQUIRE_FULL_SANDBOX=1` closes that. The build engine's suites and the video
  pipeline's children still run without an OS sandbox (SEC-16, SEC-17 open): route `build_engine.run_suites` and the
  video pipeline's children through `governor.sandbox_run` with a minimal environment. `governance/engines.json`
  declares `exec:sandbox` on actions that reach `governor.sandbox_run` only on the full tier or not at all;
  `ExecSandboxTruthTests` lists each as an explicit exception with the reason.
- **R2. Pattern filters are not proof.** The secret scanner, the memory guard and the PII rules miss unknown formats and values
  that are split or encoded. Names and free-text personal data (addresses, identity numbers) are not detected.
- **R3. The audit chain is tamper-evident, not tamper-proof.** Anyone who can write the state directory can rewrite the
  whole chain. The anchor detects this only if it was kept somewhere they cannot write.
- **R4. Path checks happen at one point in time.** The governor resolves paths when it checks them. Engines that later open
  a path must refuse symlinks themselves. Memory, factory, healing and the SDK do. A new engine must as well.
- **R5. Generated apps have no authentication.** This is documented by the build engine (OI-AUTH), and they bind to
  loopback only.
- **R6. Git checkouts with nested embedded submodules** (a submodule inside a non-absorbed submodule) are not scanned for
  filter programs. The `-c` hardening still reaches them, so fsmonitor and hooks stay off. A filter configured there would
  still run.
- **R7. Engines registered later** (for example `video_pipeline.invoke` with `out_dir`/`path`, or `requirements`) need their
  path fields in `adapters.PATH_FIELDS`, or the governor never sees those paths.
- **R8. Governor limits** (SECURITY_GOVERNOR.md §9): no process-count cap for uid-0-mapped sandboxes. Legacy
  (non-strict) calls install no seccomp filter, and their `network=True` means the host network. Only the strict
  profiles (`require_fs_isolation`, `read_only`) deny socket creation, hide `/etc` and refuse to run without the full tier.
- **R9.** Session identifiers appear in `swarm/` runbooks. They are not credentials, and swarm/ is out of scope for changes.

## 6. Operating the audit

```
python3 -m engineering_os.security_audit                 # JSON to stdout; exit 1 if an open critical/high finding exists
python3 -m engineering_os.security_audit --skip-probes   # static rules only (seconds)
python3 -m engineering_os.security_audit --out docs/evidence/gaie-20-layers/security-findings.json
```

`audit_anchor(state_dir)` returns `{"records", "record_sha256"}`. Keep it outside the state directory, then call
`verify_audit_anchor(state_dir, anchor)`, which raises `GovernorDenied("audit-tampered")` when the log is shorter
than the anchor or the anchored record changed.
