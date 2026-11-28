# Security Governor (layers L01 and L09)

Code: `engineering_os/governor.py`. Evidence: `tests/test_governor.py` (acceptance Scenario E),
`tests/test_isolation_enforcement.py` and `docs/evidence/gaie-20-layers/isolation.json` (what this
host enforces, measured with real children per launcher; see §10).
Contracts: `docs/specs/gaie-20-layers/CONTRACTS.md` §2–§4, validators in `engineering_os/contracts.py`.

The governor is the code that stands between an agent and an engine action. It is deny by
default and fail closed: every refusal raises `GovernorDenied` (a `PermissionError`) whose
`reason` is a short machine-readable word. No rule here is enforced by a text instruction;
each rule below names the test that proves it.

## 1. Public API

```python
GovernorDenied(PermissionError)            # .reason (machine word), .detail (never a payload or secret)

check(grant, engine_id, action, action_spec, *, paths=(), approval_token=None, now=None, base=None)
    -> {"allowed": True, "grant_id": str, "side_effect": str, "reason": "granted" | "approved"}
check_payload(payload) -> None             # GovernorDenied("secret-in-payload") on a credential look-alike
audit(state_dir, event, *, now=None) -> None
verify_audit(state_dir) -> int             # records in an intact chain
approval_token_sha256(token) -> str        # the digest a grant's approval stores
payload_sha256(payload) -> str
sandbox_run(cmd, *, cwd, timeout, network=False, env_allow=(), allowed_paths=(), read_paths=(),
            cpu_seconds=None, memory_mb=1024, file_mb=64, nofile=256,
            require_fs_isolation=False, read_only=False, loopback=False)
    -> {"returncode", "stdout", "stderr", "limit", "network_isolated", "fs_isolated"}
isolation_probe() -> dict                  # measured once per process; decides the sandbox tier
isolation_report() -> dict                 # public-safe form written to isolation.json
```

The keyword arguments after `paths`/`now` and after `allowed_paths` are optional additions.
Callers that use only the arguments of the shared brief get the defaults shown.

## 2. Reasons

| reason | raised when |
|---|---|
| `invalid-grant` | `contracts.validate_grant` fails, `expires_at` is not a real date, or a relative grant path climbs with `..` or resolves outside `base` |
| `invalid-action-spec` | the spec is not an object, its `side_effect` is unknown, or it names an unknown permission |
| `invalid-time` | `now` is not an aware/naive datetime, ISO-8601 text with an offset, or epoch seconds |
| `grant-expired` | `now >= expires_at` (the expiry second itself is already expired) |
| `engine-not-granted` / `action-not-granted` | the engine, or the action under it, is not in `grant["engines"]` |
| `side-effect-exceeds-grant` | `side_effect_rank(action) > side_effect_rank(max_side_effect)` |
| `approval-missing` | a gated class (`external-write`, `production`) has no token, or no approval names this engine, action and class |
| `approval-mismatch` | approvals for this engine/action/class exist but none carries the token's digest |
| `invalid-path` / `path-outside-grant` | a path is malformed / resolves (realpath) outside every granted path |
| `secret-in-payload`, `invalid-payload`, `payload-too-large` | `check_payload` found a credential, cannot scan the value, or the value exceeds 8 MiB of text |
| `invalid-audit-event`, `audit-in-repository`, `audit-failed`, `audit-tampered` | `audit`/`verify_audit` refusals |
| `invalid-command`, `invalid-env-name`, `invalid-limit`, `allowed-path-too-broad`, `network-isolation-unavailable`, `sandbox-setup-failed`, `invalid-sandbox-mode`, `filesystem-isolation-unavailable` | `sandbox_run` preconditions and refusals (§7) |

## 3. `check` — decision order

1. `validate_grant` (any exception, any field) → `invalid-grant`.
2. The action spec gives the side-effect class → `invalid-action-spec`.
3. Expiry against `now` (default: the real UTC clock; a naive datetime is read as UTC).
4. Engine granted, then action granted.
5. Rank of the class ≤ rank of `max_side_effect`. `production` is the top rank, so only a
   grant whose `max_side_effect` is `production` can pass this step for a production action.
6. Gated classes need an approval whose `engine`, `action` and `side_effect` all match and
   whose `token_sha256` equals the digest of `approval_token`. Digest is
   `approval_token_sha256(token)` = SHA-256 of the token's UTF-8 bytes. Also accepted, for
   callers that hash with the shared helper: `contracts.sha256(token)` (SHA-256 of the JSON-quoted
   text). Both forms need the token itself. Comparison is constant-time.
7. Paths: see §4.

`action_spec` must come from the validated engine registry (`governance/engines.json`), never
from the requesting agent. The governor cannot detect a caller that lies about the class.

## 4. Paths and the base directory

- `base` (keyword) is the directory relative paths resolve against. **Default: the current
  working directory at call time.** It is realpath'ed first.
- Relative grant paths are joined to `base` and realpath'ed. They must not contain `..` and
  must resolve inside `base`. If they don't, that is `invalid-grant`. Absolute grant paths are realpath'ed as given.
- Every requested path is joined to `base` (absolute paths stay absolute) and realpath'ed. It
  must equal a granted root or lie below it (component-wise: `workspace-evil` is not inside
  `workspace`). `..`, absolute paths outside the grant, symlinks (file, directory, relative,
  dangling) that point outside are all refused. A symlink that stays inside is allowed.
- `paths` must be a list or tuple. A bare string is refused as `invalid-path`, so it is never iterated
  character by character.

Tests: `CheckTests.test_paths_inside_the_grant_are_allowed`, `…test_traversal_absolute_and_prefix_paths_are_refused`,
`…test_symlink_escapes_are_refused`, `…test_grant_paths_resolve_under_the_base_and_absolute_grants_are_honoured`,
`…test_default_base_is_the_current_directory`.

## 5. `check_payload`

Walks the payload (keys and values, nested lists/dicts, text and bytes) and also scans its
canonical JSON. It uses the repository's own scanner, `scripts/security_scan.secret_findings`:
private-key PEM headers, GitHub (`gh?_…`, fine-grained PAT), AWS access-key ids,
OpenAI/Anthropic `sk-…` keys, Slack `xox?-…`, Google, Stripe, Supabase, bearer tokens,
credential URLs, token query strings, JWT service roles and quoted `api_key = "…"`-style
assignments. A hit raises `secret-in-payload`. The detail lists rule names only, never the value.
Values that are not plain JSON data (non-text keys, objects, NaN/Infinity, nesting deeper
than 64) are refused as `invalid-payload`, because what cannot be scanned is not passed.

Tests: `PayloadTests.*`. The look-alike tokens are built at run time from fragments; none is tracked.

## 6. `audit`

`<state_dir>/governor-audit.jsonl`. One canonical-JSON line per decision:
`seq, at, decision, reason, grant_id, engine, action, side_effect, payload_sha256, prev_sha256,
record_sha256`.

- The payload is hashed (`payload_sha256`), never written. Any other field of the event
  (tokens, paths, prompts) is dropped. Text fields that look like a credential are written
  as `[redacted]`. Fields are truncated, and non-text values are written as `[invalid]`.
- `decision` is `allow`/`deny`, or is derived from `allowed: bool` (so a `check` result plus
  `engine`/`action` is a valid event). Anything else is `invalid-audit-event`.
- Append-only: the log is opened with `O_NOFOLLOW` relative to a descriptor of `state_dir`, which
  must not pass through a symlink and must be caller-owned with no group/other bits (created 0700
  when missing). The log must be a regular, caller-owned, single-link file without group/other
  bits, checked after open and again under the exclusive `flock` (`audit-failed`); the append is
  `O_APPEND` and is followed by `fsync`. Each record carries the previous record's hash.
  `verify_audit` opens the log the same way under a shared `flock` (`audit-tampered`), returns 0
  when it is missing, recomputes the chain and raises `audit-tampered` on an edited, removed,
  reordered or truncated line. An incomplete last line also blocks further appends.
- `state_dir` must not lie inside a Git work tree (`audit-in-repository`). The log is private
  state, never repository content.

Tests: `AuditTests.*` (no payload text, no token, no path in the file; chain; tampering;
4 concurrent writers × 20 records give one valid chain; symlinked log refused).

## 7. `sandbox_run`

### Preconditions (every host)
`cmd` is an argv list (no shell string). `timeout` and the limits are finite numbers in range.
`allowed_paths` and `read_paths` exist. They may not be `/`, contain a system directory, or lie in
`/proc`, `/sys` or `/dev`. `cwd` (realpath'ed, so a symlink cannot escape) is a directory inside an
allowed directory. `env_allow` holds variable names. Tests: `SandboxArgumentTests.*`.

**Strict profiles** (`require_fs_isolation=True` for governed execution, `read_only=True` for
audits) refuse with `invalid-sandbox-mode`: `network=True` or any `env_allow`; `/tmp`, `/var/tmp`
or the caller's home as an allowed or read path; anything but exactly one private (caller-owned,
no group/other bits) writable workspace that does not overlap a read path; with `read_only`, any
writable path, and `cwd` must lie under `read_paths`; a hard-linked file or a special file (FIFO,
socket, device) in the scope, and a `.git` that is not a single-link pointer file. They never run
on the plain tier (`filesystem-isolation-unavailable`). Tests: `StrictSandboxTests.*`.

**`loopback=True`** (non-strict full tier only) gives the sandbox's own network namespace a
working `lo`: a server and a client inside one sandbox reach each other on 127.0.0.1, while the
host's loopback and every host address stay unreachable (errno 101). It is the profile for
untrusted target code, so `/etc` is hidden there as in the strict profiles. It is refused with
`network=True` or a strict profile (`invalid-sandbox-mode`; the strict seccomp filter denies
sockets anyway) and on the plain tier (`network-isolation-unavailable`). Tests:
`LoopbackSandboxTests.*`.

### Environment
Empty, then `PATH=/usr/local/bin:/usr/bin:/bin` and `LANG=C` (cage's environment),
`HOME=<cwd>`, and the parent's value of each name in `env_allow`. Nothing else is inherited,
so parent secrets never reach the command. Test: `SandboxTests.test_parent_secrets_do_not_leak_into_the_environment`.

### Limits and process group (reused from `swarm/phase3/cage.py`)
`cage._child` sets RLIMIT_CPU (default `ceil(timeout)`), RLIMIT_AS, RLIMIT_FSIZE (also caps
captured stdout/stderr, which go to unlinked temporary files), RLIMIT_NOFILE and no core files.
The process runs in its own session/process group, which `cage._kill` kills whole on timeout and
after every run. The module is loaded by path under a private name. It is read, never modified or copied.
`limit` is `"timeout"`, `"cpu"`, `"file"` or `None`.

### Tiers
`isolation_probe()` runs once per process. When `unshare` can make user, mount and pid
namespaces, it runs the full sandbox on a probe program and checks the walls from inside and
from the host. If every wall holds, the tier is **full**. Otherwise it is **plain**.

**Full tier** (this host). The command line is
`unshare --user --map-root-user --mount --propagation private --pid --fork --kill-child [--net] -- python3 -I -B -S -c <governor._sandbox_init> <spec>`.
As pid 1 of the new pid namespace, `_sandbox_init`:

1. opens every bind source as an `O_PATH` handle and checks that its real path is exactly the
   expected realpath (a path swapped for a symlink after the caller's check is refused);
2. builds a new root on a private tmpfs. It contains: `/usr /etc /bin /sbin /lib*` and
   `read_paths` bound read-only, `nosuid,nodev`; the install prefix of `cmd[0]`
   when it is outside the system directories (e.g. `/opt/node22` for `node`), read-only.
   Strict calls omit `/etc` and the `cmd[0]` install prefix and mount a linked worktree's `.git`
   pointer read-only;
   `allowed_paths` bound read-write, `nosuid,nodev`; a fresh `/proc` of the pid namespace,
   read-only; a private `/dev` holding only null, zero, full, random, urandom, tty (no block
   devices) and a private `/dev/shm`; and a private 64 MiB `/tmp`;
3. `pivot_root`s into it and detaches the old root, so the host tree is not in the namespace at all,
   then remounts `/` read-only;
4. with `loopback=True`, sets `IFF_UP` on `lo` (one `SIOCSIFFLAGS` ioctl) and detaches the `/etc`
   bind mount; strict calls re-inspect the mounted workspace;
5. empties the bounding set, sets locked securebits (no root privilege on exec), clears ambient
   and all capability sets, and sets `PR_SET_DUMPABLE 0` and `no_new_privs`; strict calls then
   install a seccomp filter that denies `socket` and `io_uring_setup` (EPERM);
6. forks the command (as pid 2), reaps every child, reports the command's real wait status
   through a close-on-exec pipe, and exits. That ends the pid namespace, which kills anything the
   command left behind.

Without `network=True` the namespace has only loopback, down unless `loopback=True`: no host
port, no public host, no DNS, and the abstract unix sockets of the host are not reachable.

**Plain tier** (hosts without user namespaces, e.g. AppArmor-restricted CI). The same
preconditions, environment, limits and process group. The network is cut with cage's root
network namespace or `unshare --user --map-root-user --net`. If neither works and
`network=False`, the call is refused (`network-isolation-unavailable`): it never runs silently
with network. `fs_isolated` is `False`: there writes are limited only by ordinary file
permissions of the calling user. Strict calls are refused (`filesystem-isolation-unavailable`)
and so is `loopback=True` (`network-isolation-unavailable`); neither enters the plain runner.
Tests: `SandboxArgumentTests.test_fallback_tier_reports_no_filesystem_isolation_honestly`,
`StrictSandboxTests.test_strict_audit_and_agent_never_enter_plain_runner`,
`LoopbackSandboxTests.test_loopback_argument_is_checked_on_every_host`.

### Callers that run target code

| caller | profile | where the full tier is missing |
|---|---|---|
| `quality-assurance.run-tests` (`adapters.py`) | strict, hub read-only, one private temp workspace | refused |
| `WorkspaceSupervisor.run` (`workspace_policy.py`) | strict, the assigned worktree as the one workspace | refused |
| `detectors.Sandbox` (self-healing, upgrade, runtime detectors; SEC-07) | loopback: target read-only, one fresh writable directory per run, exact environment via `env -i`, HTTP probes sent from inside the sandbox | each run returns `status: "refused"` and executes nothing; `isolation="process-only"` is an explicit opt-in that writes an allow record to the governor audit log in the sandbox scratch directory and is recorded in every result |
| `layers._run` (`layers.verify`; SEC-12) | strict (repository and linked-worktree git metadata read-only, `/etc/ld.so.cache` and `/etc/alternatives` only), exact environment (PATH, private HOME and TMPDIR, LANG) | the same scrubbed environment as a plain subprocess; every test row and the receipt's `execution` record the profile, tier and reason. Files on `layers.PROCESS_ONLY_TESTS` (measured: the cage's chown, and tests whose subject builds its own governor sandbox, which cannot be nested) run that way on every host |

Tests: `tests/test_isolation_enforcement.py` (`Sec07Tests`, `Sec12Tests`, `PropertyMatrixTests`).

### What the tests prove on this host (full tier)

| wall | test |
|---|---|
| writes land only in `allowed_paths`; `/usr`, `/etc`, `/` and other host directories are refused; `/tmp` is private and vanishes | `SandboxTests.test_writes_land_only_in_allowed_paths` |
| host files outside the sandbox (other temp dirs, `/root`, the repository) do not exist inside; `/dev` has no block devices | `…test_host_files_outside_the_sandbox_are_not_even_readable` |
| `read_paths` readable, never writable | `…test_read_paths_are_visible_but_read_only` |
| all capability sets zero, `NoNewPrivs` 1; remount rw, tmpfs over `/usr` and umount `/proc` fail; remount rw fails also from a nested user namespace (its copied mounts are locked); `/proc` read-only, `/sys` absent; pid 1's fds cannot be opened | `…test_no_capability_no_remount_no_kernel_writes` |
| no loopback/host listener, public IP or DNS without `network=True`; the same program connects with `network=True` | `…test_no_network_unless_asked` |
| a host unix socket outside the sandbox is out of reach | `…test_host_unix_sockets_are_out_of_reach` |
| host pids invisible; a `setsid` background child does not survive the run | `…test_own_pid_namespace_and_nothing_survives_the_run` |
| timeout, CPU, memory and file-size limits | `…test_timeout_and_cpu_limits_are_enforced`, `…test_memory_and_file_size_limits_are_enforced` |

## 8. Threat model

Actors: an agent that requests engine actions (it may be confused or adversarial), code that
the agent wrote and asks to run, and payload text that may carry instructions or credentials.
Assets: the owner's repositories and accounts, the host and other sessions on it, credentials
in the environment and on disk, and the integrity of the audit trail.

| threat | control |
|---|---|
| an agent calls an engine/action it was not granted, or a more dangerous class | `check` steps 4–5 |
| a stale grant is replayed | expiry, step 3 |
| a remote write or production action without the owner | gated approval with a token digest, step 6 |
| writes escape the workspace by `..`, absolute paths or symlinks | realpath containment, §4, and the mount sandbox for executed code |
| a credential is passed in a payload or ends up in a log | `check_payload`; `audit` writes digests and redacts |
| the audit trail is edited after the fact | hash chain + `verify_audit` |
| executed code reads host secrets, writes host files, reaches the network, signals or ptraces host processes, or regains privileges | full-tier sandbox, §7 |
| executed code exhausts CPU/time/memory/disk | cage limits + timeout + process-group kill |

## 9. Non-guarantees (honest limits)

- **Process count is not capped.** The full sandbox maps the caller's uid. As root that is kuid 0,
  which the kernel exempts from RLIMIT_NPROC. A fork bomb is bounded only by the timeout, the
  memory limit per process and the pid-namespace teardown. `test_known_limitation_process_count_is_not_capped`
  records this. A cgroup `pids.max` would close it. It is not attempted here.
- **Legacy (non-strict) calls can connect to visible unix sockets.** A socket inside
  `allowed_paths` or `read_paths` is reachable even on a read-only bind; strict calls deny
  `socket` and refuse special files in their scope. Do not expose directories that hold daemon sockets.
- **`network=True` (legacy calls only) is the host network**, including loopback services and abstract sockets.
- **System directories are readable.** `/usr`, `/bin`, `/sbin`, `/lib*` in every profile; legacy
  calls without `loopback` also see `/etc`, which may hold host configuration (and, for a root
  caller, root-owned files such as `/etc/shadow`, because the sandbox's uid 0 maps to the caller).
  Credentials in `/root`, `/home` and `/tmp` are not visible.
- **Seccomp only in the strict profiles**, and there only for `socket` and `io_uring_setup`.
  Legacy and loopback calls reach the kernel's whole system-call surface; kernel bugs are out of scope.
- **The loopback profile's writable paths are the caller's choice.** A `.git` pointer inside a
  writable workspace stays writable there (measured: `git_pointer_write` not-enforced for that
  launcher); `detectors.Sandbox` keeps the target directory read-only for this reason.
- **The process-only mode of `detectors.Sandbox` and `layers._run` is not a boundary.** It keeps
  the exact environment, the Python socket guard, timeouts, the output bound and (in
  `detectors.Sandbox`) the sweep of marked processes; files, network and processes of the host
  are reachable, and the evidence records them as not-enforced.
- **Path checks are point-in-time.** `check` resolves paths when called. An engine that later
  opens a path must still do so inside the sandbox (or re-check), or a swapped symlink can win the race.
- **`check` trusts `action_spec`** to come from the engine registry.
- **`cmd` is visible on the host.** Arguments appear in `/proc/<pid>/cmdline` of the launcher;
  pass credentials (when unavoidable) by `env_allow`, never in `cmd`.
- **The secret scanner is a pattern filter, not proof.** Unknown credential formats, or
  credentials split or encoded, pass.
- **The plain tier has no filesystem isolation** and says so (`fs_isolated: False`).
- **Audit integrity is tamper-evident, not tamper-proof.** Someone who can write the state
  directory can rewrite the whole chain. Anchor the latest `record_sha256` elsewhere if that matters.

## 10. Evidence

`python3 scripts/isolation_evidence.py --out docs/evidence/gaie-20-layers/isolation.json`
rewrites the evidence from a fresh measurement (`measured: true`, `simulated: false`). The file
is `isolation_report()` (the base namespace probe; `python3 -m engineering_os.governor` prints
that part alone) plus the isolation property matrix: every launcher above runs one fixed probe
program as a real child, and each property (write outside, read a planted file, `/etc/passwd`,
the caller's home, an ambient variable, AF_INET to the host's loopback and address, AF_INET6,
an outside AF_UNIX socket, `.git` pointer write, host pid visibility, capabilities, a child, a
`setsid` descendant) is recorded as `enforced`, `not-enforced`, `refused` or `not-available`
with what was observed. The refusal rows force the probe to the plain tier inside the generator.
The file states the host it was measured on (kernel, uid, IPv6, libseccomp, user-namespace
sysctls); it is not re-asserted on other hosts. It holds no host name, user or path.
`sources` holds function-level digests of the measured code; `tests/test_isolation_enforcement.py`
fails when that code changes without a regeneration, and on a matching host compares a live
measurement with the file. `--require-full` exits 2 unless the full tier is built (for CI).

Positive enforcement has been measured only on hosts like the one in the file (full tier, as
root and, for the governor, as uid 65534). In GitHub CI the tier was plain, so the positive
tests skipped or took their refusal branch; a CI job that enables user namespaces and runs with
`GAIE_REQUIRE_FULL_SANDBOX=1` fails instead. The governor makes no model calls: everything above
is deterministic code.
