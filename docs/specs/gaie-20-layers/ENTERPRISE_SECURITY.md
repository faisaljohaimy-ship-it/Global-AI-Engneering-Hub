# Enterprise security and privacy review (layer L09)

Status: review of every engine merged on `claude/gaie-20-layer-integration` @41af803 (control plane,
governor, adapters, memory and gaie_memory, router and project registry, requirements, reasoning,
economics, healing and detectors, video pipeline, layers, factory, `hub.py`, `scripts/gaie_bootstrap.py`,
and the SDK the release engine calls).

- Repeatable audit: `python3 -m engineering_os.security_audit` (code: `engineering_os/security_audit.py`).
- Evidence: `docs/evidence/gaie-20-layers/security-findings.json`, written by
  `python3 -m engineering_os.security_audit --out docs/evidence/gaie-20-layers/security-findings.json`.
- Tests: `python3 -m unittest tests.test_security_enterprise` (58 tests: a regression test for each
  fixed finding, the audit's positive and negative cases, and a live run checked against the evidence).
- Re-measured after the MASTER security hardening (`MASTER_SECURITY_ACCEPTANCE.md`) was merged: SEC-03 and
  SEC-05 keep their status under the stricter descriptor-based checks, SEC-09 moved from accepted to fixed,
  and the evidence file was rewritten by the command above.

The audit makes no network request and no model call, and it reads no clock. Each status in the evidence
comes from a probe that re-runs the exploit in a private temporary directory, or checks the control, on
every run. No status is copied from this document. The repository scanner `scripts/security_scan.py scan`
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
| master-release / SDK (L11) | E/T: Git in a checkout an agent prepared runs its programs (`core.fsmonitor`, `post-index-change`, filter drivers), or is redirected (`core.worktree`, `GIT_DIR`) or blinded (assume-unchanged) | code: SEC-01 fixed. `sdk.engineering_sdk.git` runs with fsmonitor and hooks off, no system config, no inherited `GIT_*`, no index writes. `checkout_guard` refuses filter programs (local, worktree, included and submodule configs), a foreign work tree and hidden index entries. SEC-11 fixed: `verify` reads through `read_audit_file`, no FIFO or device reads |
| master-router, project registry (L03/L15) | T/I: a private registry that others can swap or read. T: `git remote` in a workspace | code: `GAIE_HOME` outside Git, 0600 file through `mkstemp`, home must be caller-owned and not writable by group or others (SEC-04 fixed); the router launches no Git itself: `workspace_policy._git` checks a `--workspace` with fsmonitor and the untracked cache off, no system or global config, a fixed environment without inherited `GIT_*`, no index writes, and a write scope refuses filter, hook-path, include and URL-rewrite settings. **Open (SEC-09, low):** a partial clone's promisor remote still runs its configured upload-pack or `core.sshCommand` during the lazy fetch of `rev-parse origin/main` (pr30-isolation F1; fix in `workspace_policy._git`: `protocol.allow=never` and refuse `extensions.*`, `remote.*.promisor`/`uploadpack`, `core.sshCommand`) |
| memory, gaie_memory (L14) | I: secrets or private data in memory. T: an edited store or checkpoint. D: unbounded stores | code: secret guard, 0600/0700, locked atomic writes, owner/mode/link checks (`_open_private`), sealed checkpoints that restore only into an empty store (SEC-14 held), size bounds. The frozen portable journal opens its file the same way (SEC-10 fixed): regular, caller-owned, one link, mode 0600, in caller-owned 0700 directories; a journal that fails is refused with the fix command, never repaired |
| reasoning, requirements, economics (L13/L15/L19) | E: text treated as instructions. D: large inputs | code: pure deterministic functions over bounded JSON; no eval/exec, no subprocess, no network (static rules, 0 hits). `economics --out` writes where the owner points it (proc.) |
| self-healing, detectors (L17) | E/I: target repository code runs (tests, servers, timing probes) | code: a disposable copy, fixed driver (no shell), environment reduced to PATH, HOME and TMPDIR, loopback-only socket guard, timeouts, process-group kill, an unchanged-target check afterwards. **Open (SEC-07, medium):** no OS sandbox, so the target code can read any file the user can read |
| layers (L04/L20) | E: a repository test runs with the owner's environment | **Open (SEC-12, medium):** `layers.verify` declares `exec:sandbox` and `secrets:none`, but its `_run` passes the caller's whole environment and has no sandbox. `quality-assurance.run-tests` already uses `governor.sandbox_run` |
| factory, master-build/upgrade (L16/L06) | T: an artifact root reached through a symlink | code: every component opened with `O_NOFOLLOW`, no code generation in this revision |
| cinematic, video pipeline (L18) | T/I: media written into the repository, or into a directory others can read | code: the output path is validated first (real path outside the repository, no symbolic link in the path), then created with mode 0700 and re-checked (SEC-08 held); voice and music inputs inside the repository are refused |
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
| L06/L16 Engineering, factory | `O_NOFOLLOW` reads; exclusive writes | review generated code |
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

| ID | Sev. | Status | Finding | Where | Proof |
|---|---|---|---|---|---|
| SEC-01 | high | fixed | release target check ran the checkout's own Git programs (fsmonitor, index hook, filters); `core.worktree`, `GIT_DIR` and assume-unchanged could hide changes | `sdk/engineering_sdk.py` `target` | `GitCheckoutTests` (12 tests, the exploit premise shown on plain Git first) |
| SEC-02 | high | fixed | `secrets:none` was declared on all 53 actions but not enforced; a credential-shaped payload reached the engine | `engineering_os/control_plane.py` `invoke` | `PayloadSecretTests` |
| SEC-03 | medium | fixed | the audit log was appended although others could read it, it was hard-linked to another file, another user owned it, or its directory was writable by others; `verify_audit` followed a swapped path and blocked on a FIFO. Now both open the log relative to the descriptor of a caller-owned mode 0700 directory | `engineering_os/governor.py` `audit`, `verify_audit` | `AuditLogTests` |
| SEC-04 | medium | fixed | the private project registry was written into a `GAIE_HOME` that another user owned or could write | `engineering_os/project_registry.py` `_write` | `RegistryHomeTests` |
| SEC-05 | medium | fixed | a state directory open to others was refused only after the engine had written state | `engineering_os/control_plane.py` `_context` | `StateDirectoryTests` |
| SEC-06 | low | mitigated | the hash chain cannot see records removed from its end, or the whole log removed | `governor.verify_audit` | `AnchorTests` (anchor helper in `security_audit`) |
| SEC-07 | medium | **open** | self-healing runs target code without an OS sandbox | `engineering_os/detectors.py` `Sandbox` | probe; SELF_HEALING.md limits |
| SEC-08 | low | held | video output directory was created (umask mode) before the "outside the repository" check; now validated first and created 0700 | `engineering_os/video_pipeline.py` `_outside_repository` | probe, `tests/test_video_pipeline.py` `OutputDirectoryTests` |
| SEC-09 | low | **open** | `route --workspace` runs Git in a worktree an agent may have prepared. Fixed: fsmonitor, index hooks, inherited `GIT_*`, and the router's own `git remote get-url` (removed). Still open: a partial clone's promisor remote runs its configured upload-pack or `core.sshCommand` during a lazy fetch (pr30-isolation F1). The probe drives the router's own `_verified_write_scope` (pr30-merge-quality F1) | `engineering_os/workspace_policy.py` `_git` | probe (fsmonitor, index hook, `GIT_TRACE`, promisor upload-pack, promisor ssh command); `WorkspaceGitTests` (9 tests, the exploit premise shown on plain Git first) |
| SEC-10 | low | fixed | frozen gaie_memory journal was appended without an owner, mode or link check (measured: an append through a hard link wrote into the other file); now an `O_NOFOLLOW` and `O_NONBLOCK` open, then `fstat` of the descriptor, for reads and appends | `engineering_os/gaie_memory.py` `_journal_add` | probe (hard link, mode 0644), `tests/test_gaie_memory_journal.py` |
| SEC-11 | low | fixed | SDK `verify` accepted a FIFO or device named in the manifest and would block on it; `verify` now reads every manifest file through `read_audit_file` (directory descriptors, `O_NOFOLLOW`, a regular file with one link, `O_NONBLOCK`, rechecked by `fstat`) | `sdk/engineering_sdk.py` `read_audit_file` | probe (runs `verify` on a manifest-named FIFO with a timeout), `test_fifo_capability_file_is_refused_without_blocking` |
| SEC-12 | medium | **open** | `layers.verify` declares `exec:sandbox`/`secrets:none` but runs repository tests unsandboxed with the caller's environment | `engineering_os/layers.py` `_run` | probe |
| SEC-13 | info | held | authority smuggled in a payload (token, grant, instruction) grants nothing | `control_plane.invoke` | `InjectionTests`, test_control_plane INJECTION |
| SEC-14 | info | held | memory checkpoints are 0600 and sealed; a tampered one does not restore | `memory.checkpoint`/`restore` | `BackupTests` |
| SEC-15 | info | held | oversized payloads are refused before authorization | `control_plane.invoke` | `PayloadSecretTests` |

Static hits that were reviewed and accepted (rule, enclosing function, reason in the JSON):
- `authority-from-payload` in `adapters.security_governor`: validate-grant and check are dry runs over a grant given as data.
- `private-mode` in `governor._sandbox_init`: mount points inside the sandbox's private tmpfs.
- `git-dynamic-subcommand` in `hublink._git` and `scripts/security_scan.git`: these run only in the hub's own checkout, with
  read-only subcommands.

Static hit that is open and not yet reviewed: `private-mode` in `build_engine._write_files` (medium). The build engine,
merged after this review, creates the generated application directory with mode 0755 when it does not exist yet. The default
workspace above it is created 0700, and a directory the operator created 0700 and verified with `route --workspace` keeps
its mode. Owner: build engine.

Read-only cross-check with `swarm/phase3/SECURITY.md` and its reviews:
- Links written through: kit faults 1/2. Same class here is SEC-03 (audit log).
- Default modes: kit fault 3. Same class here is SEC-04, SEC-05, SEC-08 (held) and SEC-10 (fixed).
- Tracebacks that leak host paths: kit F4. Here error audit rows already keep only the class name.
- "git aliases and option forms": lane net F8. Same class here is SEC-01.
- Here-document hiding: F7. No shell strings are built in `engineering_os`; the static rules find 0 `shell=True`.

The swarm itself was not changed.

## 5. Residual risks

- **R1. Healing and layers run code without an OS sandbox** (SEC-07, SEC-12). Fix: route `detectors.Sandbox.run`/`app` and
  `layers._run` through `governor.sandbox_run` (full tier on this host). Until then, do not heal or verify a checkout that an
  untrusted party wrote while secrets sit in readable files.
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
