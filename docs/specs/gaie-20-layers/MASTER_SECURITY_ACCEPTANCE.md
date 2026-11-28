# MASTER security acceptance

This revision hardens the existing MASTER routes, tools and workspace launcher.
A route describes a plan. The operator still issues the actual scoped grant.

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

This starts a single local work unit. It never creates a remote repository or
publishes a project. The existing build and upgrade engines remain plan and
artifact-evaluation functions. Native autonomous execution requires a trusted
dispatcher to authenticate the selected agent.

## Evidence

The focused router, control-plane, governor, workspace and CLI tests cover each
regression. The governor tests measure a real restricted child where the system
supports full namespaces. On other hosts they verify refusal and unchanged
sentinels, separately from the kernel socket-filter test. A refusal result does
not certify a positive filesystem-isolated worker run.
