# MASTER security acceptance

This revision hardens the existing MASTER routes, tools and workspace launcher.
Natural-language routes never issue write grants, even with a verified workspace.
A trusted operator separately approves and dispatches a scoped write.

## Required behavior

- A direct audit request in either language produces only the four static
  `master-audit` operations and a `none` mutation ceiling. Audit-only language
  mixed with a mutation, broad no-change constraints, questions and illustrative
  commands carry no write grant. Explicit release remains approval-gated.
- An audit runs through the fixed control-plane entrypoint. The target must be
  in the grant. Project files are read through bounded descriptor-based access.
  Project tests, build commands and provider calls require separate work. The
  audit role cannot write engineering memory or snapshots, even when the caller
  supplies a task ID. Only the private decision log and usage ledger record the
  invocation. Memory reads separately avoid creating a lock or migrating state.
- Writing scopes use one clean, private worktree for a verified registered
  repository and non-default branch, or one empty private directory outside Git
  for a new build. The workspace supervisor assigns disjoint roots to operator-
  selected agents and revalidates each one at launch. The strict governor gives
  the child one writable mount with protected Git metadata and no network or
  ambient credentials. If the boundary is unavailable, the command is refused.
- The workspace preflight runs Git offline and without the checkout's programs:
  fsmonitor, hooks and the untracked cache are off; every transport is refused
  (`protocol.allow=never` plus an empty `GIT_ALLOW_PROTOCOL`, which also
  overrides a checkout's `protocol.<name>.allow`); lazy fetching is off where
  Git honours `GIT_NO_LAZY_FETCH` (Git 2.43.0-1ubuntu7.4 on the measured host
  does; it has no `--no-lazy-fetch` option). The origin is verified before any
  object lookup. A checkout config with includes, URL rewrites, filters,
  `core.hooksPath`, `core.sshCommand`, `core.gitProxy`, any `protocol.*` key, a
  promisor remote (`remote.<x>.promisor` or `.partialCloneFilter`), a remote
  program (`.uploadpack`, `.receivepack`, `.vcs`) or a repository extension
  other than `worktreeConfig` and `objectFormat` is refused
  (`tests/test_isolation_fixes_git.py`).
- Only an existing `.git` pointer is overlaid read-only, so after every run the
  supervisor re-inspects the writable root. A new `.git` (any letter case), a
  directory holding `HEAD` next to `objects`, `refs` or `commondir`, a link or a
  special file makes the run fail (`hub.py workspace-run` prints
  `"status": "failed"` with the child's result and exits 1). Nothing is removed;
  the operator inspects the tree before running Git there, and the next launch
  of that agent is refused. The build engine's Git helper runs without hooks,
  fsmonitor, untracked cache, lazy fetch or any transport except a push's own
  https or local destination, and refuses a repository whose config names a
  program, filter, include, URL rewrite, promisor, credential helper or HTTP
  setting (`tests/test_isolation_fixes_planted_git.py`).
- Strict mode hides `/etc` and everything outside the system directories, so
  the governor resolves the requested program on the host and executes its
  real file (argv[0] unchanged); an `/etc/alternatives` link therefore cannot
  dangle. For that program and for the sandbox's own interpreter (pid 1
  imports C modules such as `resource` after `pivot_root`, which failed on
  GitHub runners whose Python lives in `/opt/hostedtoolcache`) a strict run
  mounts read-only only their bin directory, a Python interpreter's standard
  library directory and the shared libraries their ELF interpreter, DT_RPATH
  and DT_RUNPATH name, never `share/`, `etc/` or the whole install prefix
  (recheck item 1: a strict child had printed a secret planted in
  `<prefix>/share/keyrings/`). A program under a home directory or in a
  directory a non-root user can change is refused unless it is the hub's own
  interpreter. No mount is `/`, a whole top-level directory such as `/opt`, a
  system directory, or a directory holding `/tmp` or a home directory, and none
  may overlap the writable workspace. The result's `mounts` is the table pid 1
  read back from `/proc/self/mountinfo`. A strict program that cannot be
  resolved is refused (`program-not-visible`) instead of exiting 127
  (`tests/test_isolation_fixes_governor.py`, `tests/test_isolation_fixes_mounts.py`).
  Legacy and loopback calls still mount the whole prefix of `cmd[0]` and of
  the hub's interpreter, except a `cmd[0]` prefix under a home directory or in
  a directory a non-root user can change.
- The strict seccomp filter also refuses `unshare` and `clone` with
  `CLONE_NEWUSER`, and answers `clone3` with `ENOSYS` so the C library falls
  back to `clone`. Measured before: a strict child created a nested user
  namespace with a full capability set inside it (the mount walls held). After:
  `EPERM`, `CapEff` 0, `unshare -U` fails, while fork, exec and threads work.
  Other kernel interfaces (keyctl, bpf, perf_event_open, userfaultfd) are not
  filtered, and legacy calls install no filter; `isolation_report()` states both.
- A Claude Code audit forks into the verifier's Read/Grep/Glob-only tool scope.
  Native host settings and hooks determine path and tool enforcement. Treat a
  validated plugin as artifact evidence and use the governed static audit when
  the host's actual bounds cannot be verified. Treat the owner CLI and dispatcher
  as trusted. A grant JSON file is a local authorization input, not authentication
  for an arbitrary worker under the same account.

## Local workspace execution

An operator creates a private JSON file outside Git with mode `0600`. It maps
each assigned agent to `path` and `intent`. Existing-project assignments also
carry `expected_repository` and, when registered, `registered_path`. The
operator selects the agent and command. A worker cannot select another agent,
root or environment through the supervisor API.

```sh
python3 hub.py workspace-run --assignments /private/assignments.json \
  --agent build-fixture --timeout 20 -- python3 -c 'print("workspace ready")'
```

Each call validates the selected agent in full: identity, Git metadata, links
and, on a first launch, an empty build directory or a clean worktree. Add
`--relaunch` once that agent's workspace holds its own work; every check except
emptiness or cleanliness still applies. The other assignments are checked only
for canonical, private roots that do not overlap the selected one, so one
agent's writes never lock out its own relaunch or another agent
(`tests/test_isolation_fixes_relaunch.py`).

This starts a single local work unit. It never creates a remote repository or
publishes a project. The control-plane `master-build` and `master-upgrade`
engines remain plan and artifact-evaluation functions. The deterministic
`engineering_os.build_engine` and `engineering_os.upgrade_engine` are separate
local entry points that a trusted operator calls directly. A route gives them
no grant. The build engine writes only under the operator's build workspace.
It reaches a remote and records the project in the private registry only
through its approved `publish` step. The upgrade engine's own writes go only
under the caller's `workdir` and never change the target; the target's tests
that it runs execute in the governor's OS sandbox where the host has the full
tier (the copy read-only, one writable directory per run, no host network,
nothing of the host outside the system directories), and are refused where it
does not, unless the caller explicitly opts into the recorded process-only
mode, which is no boundary (SEC-07, sec-isolation lane). The build engine's
`run_suites` still runs the generated application's own unit, API and browser
suites as plain child processes with a reduced environment, outside the
governor sandbox; the app's tests need a loopback server, which the strict
profile denies (pr30-isolation F5, build part, open). A command that names a
registered project runs only on that project's verified isolated worktree.
Native autonomous execution requires a trusted dispatcher to authenticate the
selected agent.

## Evidence

The focused router, control-plane, governor, workspace and CLI tests cover each
regression. The governor tests measure a real restricted child where the system
supports full namespaces. On other hosts they verify refusal and unchanged
sentinels, separately from the kernel socket-filter test. A refusal result does
not certify a positive filesystem-isolated worker run.
