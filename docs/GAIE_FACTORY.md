# GAIE software factory

Say what you want in Arabic or English; the router turns it into a plan and names
the engine that carries it out. The factory reuses the hub's existing registries,
skills, SDK, orchestration and motion library. It adds no service, provider call,
paid resource or background agent.

| You say | Engine | Skill | Writes? |
|---|---|---|---|
| «طور سديد» · "upgrade Sadeed" | MASTER_UPGRADE, comprehensive | `gaie-upgrade` | isolated branch of the target |
| «طور فيديوهات سديد» | CINEMATIC | `gaie-cinematic` | isolated branch / media outside Git |
| «سرّع سديد» | MASTER_UPGRADE, performance | `gaie-upgrade` | isolated branch |
| «أصلح أخطاء سديد» | MASTER_UPGRADE, self-healing | `gaie-upgrade` | isolated branch |
| «افحص سديد» | AUDIT | `gaie-audit` | never |
| «انشر سديد» | RELEASE | `gaie-release` | only with explicit authorization |
| «طور جميع مشاريعي» | MASTER_UPGRADE per registered project | `gaie-upgrade` | one branch per project |
| «ابنِ نظامًا جديدًا …» | MASTER_BUILD | `gaie-build` | isolated local workspace with a host grant. Repository creation requires separate owner approval |

Explicit commands: `/gaie-build`, `/gaie-upgrade`, `/gaie-audit`, `/gaie-cinematic`,
`/gaie-release` (and `/gaie-master-router`). As a plugin they are namespaced
`/gaie:gaie-build` and so on.

## Components

| Part | Path | What it does |
|---|---|---|
| Master router | `engineering_os/gaie_router.py`, `governance/policies/gaie-routes.json` | Normalizes Arabic and English, classifies the verb and focus, honours negation, resolves the project, selects engine, skills, workstreams, gates. `hub.py route "<text>" [--workspace DIR]` |
| Build engine | `prompts/MASTER_BUILD.md`, `skills/gaie-build`, `engineering_os/build_engine.py` | Phases A–G from requirements to verified release; `build_engine` plans, generates, tests and evaluates an application in a private workspace (Scenario A) |
| Upgrade engine | `prompts/MASTER_UPGRADE.md`, `skills/gaie-upgrade`, `engineering_os/upgrade_engine.py` | Discovery, baseline, coverage matrix, upgrade, self-healing, independent verification (Scenario B) |
| Audit | `skills/gaie-audit` | Read-only engineering and security review in the restricted verifier or through a governed audit action |
| Cinematic | `skills/gaie-cinematic` | Media inventory to rendered, verified films; engines chosen by evidence |
| Release | `skills/gaie-release` | Identity, checks, preview, rollback, authorized promotion; uses SDK `target`/`release` |
| Project registry | `projects/registry.json`, `projects/aliases.json`, private `$GAIE_HOME/projects.json` | Public names in Git; private projects only in the overlay |
| Engineering memory | `engineering_os/memory.py` (engine), `engineering_os/gaie_memory.py` (facade and CLI) | Private per-project store outside Git: integrity-checked, secret-refusing, lexical search, typed links, ADRs, task progress, symbol index, sealed checkpoints |
| Inventory | `engineering_os/gaie_inventory.py` | Read-only project discovery and the starting coverage matrix. `hub.py inventory DIR` |
| Verifier | `agents/gaie-verifier.md` | Read-only independent review subagent |
| Control plane | `engineering_os/control_plane.py`, `engineering_os/adapters.py`, `governance/engines.json`; `hub.py engines`, `engine-health`, `invoke` | Grant-checked engine actions, each with a private decision-log row and a usage-ledger record. `master-build` and `master-upgrade` reach only `spec`, `plan` and `evaluate` (`engineering_os/factory.py`); `build_engine` and `upgrade_engine` are not registered yet (in progress) |

Adding a verb, phrase, focus area, supporting skill or workstream is an edit to
`gaie-routes.json`; adding a project name is an edit to `aliases.json` or the
private overlay. Neither master prompt needs rewriting when a capability is
approved: the prompts tell the engine to query `hub.py capabilities`, `recommend`
and `motions` at run time.

## Targeting rules

- A verb is a command only as an imperative at the start of a clause or after
  "and"/«و»/«ثم». Questions, statements and nouns ("release notes for Sadeed",
  «هل ننشر سديد؟», «ماذا حدث في سديد») return `needs-clarification`.
- Any verb after a negation in its clause is `prohibited`. A release sentence that
  contains any negation, or several projects named with a negation, is not routed.
- A project resolves only by an exact registered name or alias. Close spellings are
  reported as suggestions and never selected.
- No match, two operations, a build verb on an existing project, or a clash between
  registries returns `needs-clarification` (exit code 2) with `write_allowed: false`.
- «لا تنشر», "do not deploy" and similar put that operation in `prohibited`.
- `--workspace DIR` checks the worktree and branch for an existing target or a
  dedicated workspace for a new project. An operation with write intent remains
  a plan even when the workspace passes validation. A trusted operator
  separately authorizes a scoped launch. The router never authorizes writes.
- Registries are refused when an alias contains a command word or matches inside
  another project's alias.
- `repository_verified` is always false in a plan: reachability is checked by the
  agent in its environment.
- Route version 2 also gives the control-plane `engine_id`, the agent `roles`,
  `capabilities`, a read-only audit `grant_template`, the `execution_scope`, the
  `tests` and `evidence` to save, and the registry's `repository_check`. A route is
  never executable by itself (`executable_by_route: false`).
- Hard rules enforced in code: audit is read-only (`max_side_effect: none`). Speed-up,
  repair, upgrade and cinematic work is capped at `repo-write` on an isolated branch.
  A new system gets `workspace-write`, and creating its repository is a separate
  `external-write` step that needs approval. A release is always `needs-approval`
  with a `production` ceiling.
- A project the catalog knows by name (BILTIX, KPI, Security Lab, the portfolio) but
  without a registered repository returns `needs-clarification` with a `register`
  next step. Register it with `python3 -m engineering_os.project_registry register
  … --apply`; the record goes to `$GAIE_HOME/projects.json`, outside Git.
- Full route table, rules, examples and limitations:
  `docs/specs/gaie-20-layers/ROUTER.md`.

## Private state

`$GAIE_HOME` (default `~/.gaie`) must be outside every Git repository.

```sh
# private project overlay: $GAIE_HOME/projects.json
{"schema_version": 1, "projects": [
  {"id": "my-project", "repository": "https://github.com/OWNER/REPO", "aliases": ["الاسم", "NAME"]}]}

M="python3 -m engineering_os.gaie_memory --project my-project"   # run from the hub checkout
$M add --kind decision --title "…" --body "…" --tag architecture --evidence unit-tests=<sha256>
$M search "query" --kind failure
$M brief                                          # open tasks, ADRs, failures, index size
$M checkpoint --to /private/dir/task.json         # prints checkpoint_sha256
$M restore --from /private/dir/task.json --sha256 <checkpoint_sha256>
```

Each project's memory is a private directory `$GAIE_HOME/memory/<project>/` (mode
0700) holding `memory.jsonl` (schema 2: canonical JSON lines with a state checksum,
mode 0600) and `memory.lock`. An older per-project `entries.jsonl` journal is verified
and imported once. When `gaie_memory.py` is copied alone (a bootstrap or `gaie-factory`
pack install) it cannot load the engine and runs that older portable journal for
`add`, `search`, `related` and `promote` only. Format, isolation rules and the resume
procedure: `docs/specs/gaie-20-layers/MEMORY.md`; Scenario D in
`tests/test_memory_unified.py` (`ScenarioDTests`) resumes from a checkpoint in a new
interpreter. The `-m` form needs the hub checkout as working directory; from anywhere
else run `python3 <hub>/engineering_os/gaie_memory.py`. Open review findings on the
portable journal (no lock between concurrent writers; SEC-10, no owner or link check)
are being fixed.

Deployment targets, database targets and security policies stay in the project's
own repository and its private registry (`sdk/engineering_sdk.py registry`).

## Installation in Claude Code

Files in GitHub are not automatically available to every session. Use the mechanism
that fits the environment. Status words: *tested* (an automated test passes),
*host-verified* (observed in a real Claude Code session at the final head),
*unverified*. None of these mechanisms is host-verified at this base (`5805d31`);
the install proof is in progress and is to be completed at the final head.

| Environment | Mechanism | Status at this base | Evidence |
|---|---|---|---|
| Sessions opened on this hub | `.claude/skills/gaie-*`, `.claude/agents/gaie-verifier.md`, committed | tested: the committed copies match `skills/` and `agents/`. Clean sessions listed the skills before later router fixes; not repeated since | `tests/test_gaie_factory.py` (`test_hub_checkout_install_matches_sources`); `docs/evidence/2026-11-28-gaie-factory.md` |
| An independent project | `python3 scripts/gaie_bootstrap.py install --scope project --target DIR --apply` | tested: 16 files, `verify` reports all `current`, and `DIR/.claude/skills/gaie-master-router/engine/gaie_router.py route "طور سديد"` returns `routed`, `MASTER_UPGRADE`, `write_allowed: false` (run at `5805d31` in a scratch Git project). The installed `gaie-master-router` skill names three other router paths, none of which exist after this install (fix in progress) | `tests/test_gaie_factory.py` (`BootstrapTests`) |
| A workstation, all projects | `python3 scripts/gaie_bootstrap.py install --scope user --apply` | tested in a temporary home directory; persistence across real sessions unverified | `tests/test_gaie_factory.py` (`test_installed_engine_routes_from_the_skill_directory`) |
| A registered product repository | `python3 hub.py register <project> --revision <reviewed main SHA> --capability pack:gaie-factory --apply`, commit through a PR | needs `main`: `main` (`65c84fe`) has no `gaie-factory` pack, so registration is refused until PR #31 is merged | `tests/test_gaie_factory.py` (`test_pack_registers_and_runs_vendored_in_a_project`, main ancestry mocked) |
| Any Claude Code, as a plugin | `claude plugin marketplace add <hub checkout or repository>`, then `claude plugin install gaie@gaie-hub` | unverified at this base. Installing from GitHub needs `main`, which has no `.claude-plugin/` yet | `.claude-plugin/marketplace.json`, `.claude-plugin/plugin.json`; `tests/test_gaie_factory.py` (`test_plugin_manifests_stay_inside_the_repository`) |
| Cloud sessions | Start from a clone that holds the committed project install | `~/.claude` does not persist in a cloud container; enabling the plugin on an account is unverified | — |

```sh
python3 scripts/gaie_bootstrap.py install   --scope user            # dry-run
python3 scripts/gaie_bootstrap.py install   --scope user --apply
python3 scripts/gaie_bootstrap.py verify    --scope user            # current / outdated / modified / missing
python3 scripts/gaie_bootstrap.py uninstall --scope user --apply    # rollback
python3 scripts/gaie_bootstrap.py install   --scope project --target /path/to/project --apply
```

The bootstrap updates or removes only files it installed and that are unchanged
since; any other file, a local edit or a symlink is preserved and reported. Update
by pulling a reviewed hub revision and re-running `install`. Roll back with
`uninstall`, or for a registered project `hub.py register … --remove pack:gaie-factory`.
After editing `skills/gaie-*` in the hub, re-run
`python3 scripts/gaie_bootstrap.py install --scope project --target . --apply`;
a test fails if the committed copies drift.

## Read-only review boundary

In Claude Code, `gaie-audit` runs in a fork of the `gaie-verifier` subagent. The
subagent's tool list contains only Read, Grep and Glob. The skill passes an
approved local checkout and scope as explicit arguments. If the fork or its tool
restriction is unavailable, use an already governed `master-audit` result or
report the blocker. General-purpose Claude sessions and external hosts require
their own verified boundary. Skill `allowed-tools` controls pre-approval and the
subagent `tools` field controls the fork's tool availability.

For Codex, use a host session with read-only enforcement and with write-capable
connectors removed. The CLI supports `--sandbox read-only --ask-for-approval never`.
When deploying either host configuration, verify that its active permissions,
hooks and connectors preserve the boundary. In the absence of verified
restrictions, review already-provided receipts in the conversation.

Audit reports are returned in the conversation. A fresh test or build uses
a separate QA action and its own grant and workspace. The router invocation
and read-only review require no engineering memory or checkpoint writes.

## Capability coverage

Status words: *implemented* (code exists), *tested* (automated tests pass),
*host-verified* (observed in a real Claude Code session at the final head), *not
implemented*. Clean-session observations in `docs/evidence/2026-11-28-gaie-factory.md`
were made before later router fixes and are not counted as host-verified here.

| Capability | Path | Version | License | Dependencies | Security | Status and evidence | Limits |
|---|---|---|---|---|---|---|---|
| gaie.router | `engineering_os/gaie_router.py` | 1.0.0 | MIT | Python stdlib, git | fail-closed targeting, no network | tested (`tests/test_gaie_router.py`); clean-session use observed before later fixes | Lexical rules, not a language model; unlisted phrasing returns clarification |
| gaie.build | `prompts/MASTER_BUILD.md`, `skills/gaie-build` | 1.0.0 | MIT | hub CLI | no secrets, private-by-default repos | tested: Scenario A builds a synthetic bilingual application, runs its generated suites and serves it without the hub (`tests/test_build_engine_e2e.py`, `ScenarioATests`; `tests/test_build_engine.py`) | No owner product built; repository creation not exercised; `build_engine` not reachable through the control plane yet |
| gaie.upgrade | `prompts/MASTER_UPGRADE.md`, `skills/gaie-upgrade` | 1.0.0 | MIT | hub CLI | workspace-origin guard | tested: Scenario B upgrades a fixture project (`tests/test_upgrade_engine.py`, `ScenarioB`) | No owner product upgraded (by owner instruction); `upgrade_engine` not reachable through the control plane yet |
| gaie.audit | `skills/gaie-audit` | 1.0.0 | MIT | restricted host or governed audit action | Claude verifier tool allowlist and read-only control-plane grant | tested for integrity and routing | Each host's active restriction needs separate acceptance evidence |
| gaie.cinematic | `skills/gaie-cinematic` | 1.0.0 | MIT | motion library, renderer | license and paid-credit gates | tested: Scenario C renders a bilingual sample storyboard to MP4 with subtitles and QA at preview size (`tests/test_video_pipeline.py`, `ScenarioCTests`) | No owner film produced; the full-size sample media is kept outside Git; Remotion, Blender, WebGPU remain unverified engines |
| gaie.release | `skills/gaie-release` | 1.0.0 | MIT | SDK target/release | explicit authorization, no CI bypass | tested for integrity and routing | No deployment performed; simulated only by routing tests |
| gaie.registry | `projects/aliases.json`, private overlay | 1.0.0 | MIT | — | private names outside Git, conflict refusal | tested | Repository reachability is not checked offline |
| gaie.memory | `engineering_os/memory.py`, `engineering_os/gaie_memory.py` | 1.0.0 | MIT | Python stdlib | 0700/0600 private store, secret refusal, state checksum, per-project isolation | tested (`tests/test_memory_unified.py`, Scenario D; `tests/test_engineering_memory.py`) | Lexical retrieval; no embeddings; single-machine store; secret filter is best-effort; checksums do not stop a writer who recomputes them; copied alone it runs the portable journal |
| gaie.inventory | `engineering_os/gaie_inventory.py` | 1.0.0 | MIT | Python stdlib | read-only, no symlinks, no content output | tested | Path heuristics; counts are not quality |
| gaie.bootstrap | `scripts/gaie_bootstrap.py` | 1.0.0 | MIT | Python stdlib | never overwrites foreign files, symlinks refused | tested; project scope applied to this hub | User scope not persistent in cloud sessions; installed skills name router paths a project-scope install lacks (fix in progress); the install manifest is trusted as the directory owner's record |
| gaie.plugin | `.claude-plugin/` | 1.0.0 | MIT | Claude Code | paths inside repository | `claude plugin validate .` passed (`docs/evidence/2026-11-28-gaie-factory.md`); not re-validated at this base | Install from GitHub needs `main`; unverified at this base |
| gaie.verifier | `agents/gaie-verifier.md` | 1.0.0 | MIT | Claude Code | Read, Grep and Glob only | tested for installation integrity | Fresh runtime tests run separately with an isolated QA grant |

## Before and after

| | Before | After the factory change | At `5805d31` |
|---|---|---|---|
| Owner command | Long engineering prompt each time | One sentence, routed deterministically | same |
| Skills | 14 | 20 (six `gaie-*`) | 22 (`python3 hub.py audit`) |
| Registration packs | 4 | 5 (`gaie-factory`) | 5 (`catalog/packs.json`) |
| `hub.py` commands | 13 | 15 (`route`, `inventory`) | 20 (`python3 hub.py --help`) |
| Project names | Repository ids only | Arabic/English aliases plus private overlay | same |
| Engineering memory | Orchestration checkpoints only | Per-project private memory with search and links | one engine (`engineering_os/memory.py`) behind the same CLI |
| Claude Code discovery in this hub | None committed | Project skills, verifier agent, plugin manifest | same |

## Not included, by design or by evidence

- The swarm experiment, context optimization, native motion engines and
  next-generation intelligence were merged into the twenty-layer integration
  (`b7097df`, `f366bf0`, `6bee21a`, `e72a98a`), which reached this branch as
  `0986919` (PR #27 onto `main` at `65c84fe`); none of it is on `main` yet. Later
  commits on some of those source branches are not included. The swarm stack is
  frozen (`swarm/phase3/FREEZE.json`, 162 files) and cited, not re-run; its
  1,000-worker figure stays "reported, not measured" (`swarm/phase3/RESUME.md`).
  Motions that exist only on earlier branches are being ported (in progress). A skill
  becomes a routed supporting skill only when it is listed under `supporting_skills`
  in `gaie-routes.json`.
- Serena, Context7, LSP, ast-grep, Inspect AI, Promptfoo, Pydantic AI and Chrome
  DevTools MCP are not installed or approved in the hub. Headroom is approved for
  its documented local scope only.
- No token, cost or productivity figure was measured for the factory itself.
- No repository was created, no product was changed and nothing was deployed. The
  release state is "recorded, tag pending" (`docs/specs/gaie-20-layers/RESUME.md`).
