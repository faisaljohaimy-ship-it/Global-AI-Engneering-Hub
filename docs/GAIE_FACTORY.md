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
| «ابنِ نظامًا جديدًا …» | MASTER_BUILD | `gaie-build` | new private repository when permitted |

Explicit commands: `/gaie-build`, `/gaie-upgrade`, `/gaie-audit`, `/gaie-cinematic`,
`/gaie-release` (and `/gaie-master-router`). As a plugin they are namespaced
`/gaie:gaie-build` and so on.

## Components

| Part | Path | What it does |
|---|---|---|
| Master router | `engineering_os/gaie_router.py`, `governance/policies/gaie-routes.json` | Normalizes Arabic and English, classifies the verb and focus, honours negation, resolves the project, selects engine, skills, workstreams, gates. `hub.py route "<text>" [--workspace DIR]` |
| Build engine | `prompts/MASTER_BUILD.md`, `skills/gaie-build` | Phases A–G from requirements to verified release |
| Upgrade engine | `prompts/MASTER_UPGRADE.md`, `skills/gaie-upgrade` | Discovery, baseline, coverage matrix, upgrade, self-healing, independent verification |
| Audit | `skills/gaie-audit` | Read-only engineering and security review (`allowed-tools` restricted) |
| Cinematic | `skills/gaie-cinematic` | Media inventory to rendered, verified films; engines chosen by evidence |
| Release | `skills/gaie-release` | Identity, checks, preview, rollback, authorized promotion; uses SDK `target`/`release` |
| Project registry | `projects/registry.json`, `projects/aliases.json`, private `$GAIE_HOME/projects.json` | Public names in Git; private projects only in the overlay |
| Engineering memory | `engineering_os/gaie_memory.py` | Private, per-project, append-only, integrity-checked, secret-refusing; lexical search and one-hop links |
| Inventory | `engineering_os/gaie_inventory.py` | Read-only project discovery and the starting coverage matrix. `hub.py inventory DIR` |
| Verifier | `agents/gaie-verifier.md` | Read-only independent review subagent |
| Control plane | existing `hub.py`, `hublink.py`, `engineering_os/orchestration.py`, SDK | Unchanged; leases, checkpoints and registration are reused |

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
- `--workspace DIR` compares the checkout's `origin` (github.com or the local Git
  proxy only) with the target repository; `write_allowed` is true only when every
  target matches.
- Registries are refused when an alias contains a command word or matches inside
  another project's alias.
- `repository_verified` is always false in a plan: reachability is checked by the
  agent in its environment.

## Private state

`$GAIE_HOME` (default `~/.gaie`) must be outside every Git repository.

```sh
# private project overlay: $GAIE_HOME/projects.json
{"schema_version": 1, "projects": [
  {"id": "my-project", "repository": "https://github.com/OWNER/REPO", "aliases": ["الاسم", "NAME"]}]}

python3 -m engineering_os.gaie_memory --project my-project add --kind decision \
  --title "…" --body "…" --tag architecture --evidence unit-tests=<sha256>
python3 -m engineering_os.gaie_memory --project my-project search "query" --kind failure
```

Deployment targets, database targets and security policies stay in the project's
own repository and its private registry (`sdk/engineering_sdk.py registry`).

## Installation in Claude Code

Files in GitHub are not automatically available to every session. Use the mechanism
that fits the environment:

| Environment | Mechanism | Persists? |
|---|---|---|
| Sessions opened on this hub | `.claude/skills/gaie-*`, `.claude/agents/gaie-verifier.md`, committed | Yes, with the repository |
| A product repository (local or cloud) | `python3 hub.py register <project> --revision <reviewed main SHA> --capability pack:gaie-factory --apply`, commit through a PR | Yes, with that repository |
| A workstation, all projects | `python3 scripts/gaie_bootstrap.py install --scope user --apply` | Yes, in `~/.claude` |
| Any Claude Code, as a plugin | `/plugin install gaie --marketplace faisaljohaimy-ship-it/Global-AI-Engneering-Hub` | Per user or project scope |
| Cloud sessions | Start from a fresh clone: `~/.claude` does not persist. Use the committed project install, or enable the plugin on the claude.ai account | Repository or account |

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

The router command needs Bash approval. To avoid the prompt, the owner can add
`Bash(python3 hub.py route:*)` to the permission allow-list; this repository does
not set permissions on the owner's behalf.

## Capability coverage

Status words: *implemented* (code exists), *tested* (automated tests pass),
*host-verified* (observed in a real Claude Code session), *not implemented*.

| Capability | Path | Version | License | Dependencies | Security | Status and evidence | Limits |
|---|---|---|---|---|---|---|---|
| gaie.router | `engineering_os/gaie_router.py` | 1.0.0 | MIT | Python stdlib, git | fail-closed targeting, no network | tested (`tests/test_gaie_router.py`); host-verified | Lexical rules, not a language model; unlisted phrasing returns clarification |
| gaie.build | `prompts/MASTER_BUILD.md`, `skills/gaie-build` | 1.0.0 | MIT | hub CLI | no secrets, private-by-default repos | tested for integrity and routing; host-verified invocation | No full system has been built through it yet; repository creation not exercised |
| gaie.upgrade | `prompts/MASTER_UPGRADE.md`, `skills/gaie-upgrade` | 1.0.0 | MIT | hub CLI | workspace-origin guard | tested for integrity and routing; host-verified invocation | No product upgrade run yet (by owner instruction) |
| gaie.audit | `skills/gaie-audit` | 1.0.0 | MIT | hub CLI | `allowed-tools` read-only | tested for integrity and routing; host-verified invocation | Bash can still write; the read-only rule is an instruction plus tool list, not a sandbox |
| gaie.cinematic | `skills/gaie-cinematic` | 1.0.0 | MIT | motion library, renderer | license and paid-credit gates | tested for integrity and routing; host-verified invocation | No film produced by it yet; Remotion, Blender, WebGPU remain unverified engines |
| gaie.release | `skills/gaie-release` | 1.0.0 | MIT | SDK target/release | explicit authorization, no CI bypass | tested for integrity and routing | No deployment performed; simulated only by routing tests |
| gaie.registry | `projects/aliases.json`, private overlay | 1.0.0 | MIT | — | private names outside Git, conflict refusal | tested | Repository reachability is not checked offline |
| gaie.memory | `engineering_os/gaie_memory.py` | 1.0.0 | MIT | Python stdlib | 0600 files, secret refusal, integrity hash, isolation | tested | Lexical retrieval; no embeddings; single-machine store; secret filter is best-effort; hash chain does not stop a deliberate full rewrite |
| gaie.inventory | `engineering_os/gaie_inventory.py` | 1.0.0 | MIT | Python stdlib | read-only, no symlinks, no content output | tested | Path heuristics; counts are not quality |
| gaie.bootstrap | `scripts/gaie_bootstrap.py` | 1.0.0 | MIT | Python stdlib | never overwrites foreign files, symlinks refused | tested; project scope applied to this hub | User scope not persistent in cloud sessions; the install manifest is trusted as the directory owner's record |
| gaie.plugin | `.claude-plugin/` | 1.0.0 | MIT | Claude Code | paths inside repository | `claude plugin validate .` passed | Marketplace install not exercised |
| gaie.verifier | `agents/gaie-verifier.md` | 1.0.0 | MIT | Claude Code | read-only tool list | listed by a clean session | Not yet used on a real review |

## Before and after

| | Before | After |
|---|---|---|
| Owner command | Long engineering prompt each time | One sentence, routed deterministically |
| Skills | 14 | 20 (six `gaie-*`) |
| Registration packs | 4 | 5 (`gaie-factory`) |
| `hub.py` commands | 13 | 15 (`route`, `inventory`) |
| Project names | Repository ids only | Arabic/English aliases plus private overlay |
| Engineering memory | Orchestration checkpoints only | Per-project private memory with search and links |
| Claude Code discovery in this hub | None committed | Project skills, verifier agent, plugin manifest |

## Not included, by design or by evidence

- The swarm experiment (lean workers, the path to 1,000 workers, its token
  measurements), context optimization, native motion engines and next-generation
  intelligence are open draft pull requests (#16, #17, #19, #22–#25), not merged to
  `main`. This change does not touch their files and does not use or claim their
  results. Once one is reviewed and merged, list its skill under
  `supporting_skills` in `gaie-routes.json`; the prompts need no rewrite.
- Serena, Context7, LSP, ast-grep, Inspect AI, Promptfoo, Pydantic AI and Chrome
  DevTools MCP are not installed or approved in the hub. Headroom is approved for
  its documented local scope only.
- No token, cost or productivity figure was measured for the factory itself.
- No repository was created, no product was changed and nothing was deployed.
