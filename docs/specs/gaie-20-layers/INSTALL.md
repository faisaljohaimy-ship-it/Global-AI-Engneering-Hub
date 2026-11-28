# GAIE install and Scenario I

Scenario I asks one question: does the GAIE factory work when it is installed into a
project that is not the hub, by a user whose `~/.claude` has never seen it? This page
states the install modes, the vendored file set, the acceptance criteria, how they are
tested and recorded, and what this host cannot prove.

Test: `tests/test_gaie_install_scenario_i.py` (classes `ScenarioI`, `ScenarioIClaudeCode`,
`ScenarioIEvidence`). Evidence: `docs/evidence/gaie-20-layers/scenario-i.json`. Installer:
`scripts/gaie_bootstrap.py`. Vendored set: the `gaie-factory` pack in `catalog/packs.json`.

## Install modes

| Mode | Command | Where the skills land | Where the router runs from |
|---|---|---|---|
| Hub checkout | none: `.claude/skills/gaie-*` and `.claude/agents/gaie-verifier.md` are committed | `<hub>/.claude/` | `python3 hub.py route` from the hub root |
| Project scope (bootstrap) | `python3 scripts/gaie_bootstrap.py install --scope project --target <project> --apply` | `<project>/.claude/skills/`, `<project>/.claude/agents/` | `<project>/.claude/skills/gaie-master-router/engine/gaie_router.py` |
| User scope (bootstrap) | `python3 scripts/gaie_bootstrap.py install --scope user --apply` | `~/.claude/skills/`, `~/.claude/agents/` | `~/.claude/skills/gaie-master-router/engine/gaie_router.py` |
| Plugin | `claude plugin marketplace add <hub path or owner/repo>` then `claude plugin install gaie@gaie-hub --scope project` | the plugin cache copy of the hub, names prefixed `gaie:` | `<plugin root>/hub.py` (the plugin root is a copy of the hub) |
| Registered project (pack) | `python3 hub.py register <project> --revision <main SHA> --capability pack:gaie-factory --apply` | `<project>/.claude/skills/`, `.claude/agents/`, `.agents/skills/` | `<project>/.engineering/gaie/gaie_router.py` |

Every bootstrap command is a dry run without `--apply`. `verify` reports each file as
current, outdated, modified or missing; `uninstall --apply` removes only files the
manifest recorded and that are unchanged, plus the `__pycache__` entries of the modules
it removed. A symlinked `--target`, a symlinked `.claude` and any symlinked path inside it
are refused before anything is written.

### What each mode proves, and what it does not

- **Project scope** proves that a committed, reviewable `.claude/` in an independent
  repository carries the six skills, the verifier agent and a working engine
  (router, project registry, unified memory). It does not prove that a session opened
  there discovers them; only a new session shows that (`fresh_session` below).
- **User scope** proves the same files work from `~/.claude` and from any directory. It
  does not prove persistence: a cloud container starts with a fresh `~/.claude`.
- **Plugin** proves that `claude plugin validate` accepts the hub, that a local
  marketplace install into a fresh HOME succeeds without network or account, that
  `claude plugin details` lists the six `gaie-*` skills and `gaie-verifier`, and that the
  router runs from the installed plugin root. A folder marketplace reads the plugin from
  the hub checkout, so it proves nothing about the GitHub source, the default branch,
  trust prompts or account-level enablement.
- **Hub checkout** and **pack** are covered by the existing tests
  (`IntegrityTests.test_hub_checkout_install_matches_sources`,
  `IntegrityTests.test_pack_registers_and_runs_vendored_in_a_project`; the pack test mocks
  main ancestry and skips on a dirty tree).

## Path resolution for the skills

`scripts/gaie_bootstrap.py` holds the exact strings the skills name, per mode, in
`LOCATIONS`. `${CLAUDE_SKILL_DIR}` is the directory of the SKILL.md that names the path;
Claude Code 2.1.332 fills it in when it loads a skill (and states "Base directory for this
skill" as well). Other paths are relative to the session's project directory.

| Item (skill) | Bootstrap, project or user | Plugin | Hub checkout | Registered project |
|---|---|---|---|---|
| router (`gaie-master-router`) | `${CLAUDE_SKILL_DIR}/engine/gaie_router.py` | `${CLAUDE_SKILL_DIR}/../../hub.py` | `hub.py` | `.engineering/gaie/gaie_router.py` |
| build prompt (`gaie-build`) | `${CLAUDE_SKILL_DIR}/MASTER_BUILD.md` | `${CLAUDE_SKILL_DIR}/../../prompts/MASTER_BUILD.md` | `prompts/MASTER_BUILD.md` | `.engineering/gaie/MASTER_BUILD.md` |
| upgrade prompt (`gaie-upgrade`) | `${CLAUDE_SKILL_DIR}/MASTER_UPGRADE.md` | `${CLAUDE_SKILL_DIR}/../../prompts/MASTER_UPGRADE.md` | `prompts/MASTER_UPGRADE.md` | `.engineering/gaie/MASTER_UPGRADE.md` |
| inventory (`gaie-upgrade`) | `${CLAUDE_SKILL_DIR}/../gaie-master-router/engine/gaie_inventory.py` | `${CLAUDE_SKILL_DIR}/../../hub.py inventory` | `hub.py inventory` | `.engineering/gaie/gaie_inventory.py` |

The skills try them in that order and use the first that exists. Scenario I checks that
every bootstrap, plugin and hub-checkout path exists after the matching install, and the
pack test checks the registered-project column. The skill texts themselves are edited in a
later pass (the corrected wording is filed as a request); until then the installed
`gaie-master-router` text does not name the project-scope path.

## The vendored set is data

The `gaie-factory` pack in `catalog/packs.json` is the only list. `hub.py register` copies
each `source: destination` pair as written. The bootstrap derives its plan from the same
pack:

- each pack skill goes to `skills/<name>/SKILL.md`;
- a `.claude/agents/<name>.md` destination goes to `agents/<name>.md` (also in a hub checkout);
- `.engineering/gaie/MASTER_BUILD.md` and `MASTER_UPGRADE.md` go beside `gaie-build` and
  `gaie-upgrade`;
- every other `.engineering/gaie/<file>` goes to `skills/gaie-master-router/engine/<file>`,
  so that directory mirrors the registered project's `.engineering/gaie/`;
- any other destination, a nested path, or two sources for one destination is refused.

Pack 1.1.0 adds `project_registry.py`, `memory.py`, `orchestration.py` and
`security_scan.py`, so an installed `gaie_memory.py` loads the unified engine (store
`memory.jsonl`, `brief`/`adr`/`task` commands) instead of the portable journal, and the
installed router resolves names through the project registry (public catalog rows)
instead of the legacy loader. `contracts.py` is not vendored: no vendored module imports it
when run as a script, and the router carries tested copies of its constants.

To ship one more file, add one line to the pack's `files` and bump the pack `version`:

```json
"engineering_os/agent_team.py": ".engineering/gaie/agent_team.py",
"governance/policies/agent-team.json": ".engineering/gaie/agent-team.json",
"engineering_os/master_docs.py": ".engineering/gaie/master_docs.py",
"governance/policies/master-prompts.json": ".engineering/gaie/master-prompts.json",
"agents/gaie-specialist.md": ".claude/agents/gaie-specialist.md"
```

Nothing else changes in the bootstrap. A vendored module must find its data file beside
itself first (`pathlib.Path(__file__).with_name("agent-team.json")`) with the hub path as
the fallback, as `gaie_router.py` does for `gaie-routes.json`, and must import its siblings
by plain name when `__package__` is empty. The plugin needs no change: it is the whole hub,
and a new `agents/*.md` file is picked up from the default `agents/` directory. After the
change, re-run `python3 scripts/gaie_bootstrap.py install --scope project --target . --apply`
in the hub (agents are mirrored into `.claude/agents/`), then
`python3 -m unittest tests.test_gaie_factory` (`VendoredSetTests` checks that every listed
file exists and that the installed copy imports and runs outside the hub) and re-record
Scenario I.

## Plugin manifest

`.claude-plugin/plugin.json` declares no component paths. With
`"agents": ["./agents/gaie-verifier.md"]`, Claude Code 2.1.332 `claude plugin details`
printed `Agents (0)`; without the field the default `agents/` directory is used and it
prints `Agents (1)  gaie-verifier`. `claude plugin validate` passes. `--strict` exits 1 on
two warnings that are accepted for now:

| Warning | Reason it stays |
|---|---|
| `CLAUDE.md at the plugin root is not loaded as project context` | The plugin root is the repository root (`source: "./"`). Clearing it needs a dedicated plugin directory, which is the open packaging decision (six GAIE skills or all 22, a 15-19 MB cache copy). |
| `agents/orchestrator/README.md: No frontmatter block found` | The file is documentation of the orchestration CLI, not an agent; `details` does not count it. Moving it out of `agents/` is requested from its owner (README.md links to it). |

The plugin-directory check `ICON_MISSING` does not change the result. No icon is added: the
first icon submitted becomes the listing icon permanently, which is the owner's choice.

## Scenario I acceptance criteria

All in a new short temporary directory, with a new empty HOME per mode, `GAIE_HOME` outside
every repository, and a brand-new independent Git project (`git init` plus one empty
commit) outside the hub. Subprocesses get only PATH, HOME, LANG, GAIE_HOME, TMPDIR and
GIT_CONFIG_NOSYSTEM.

1. Project scope: the dry run reports every planned file as `would create` and writes
   nothing; `--apply` creates them all; `verify` reports all `current`; a second
   `--apply` reports all `unchanged`; `git status` of the project shows only `.claude/`.
2. The installed router, run from the project, routes an Arabic command
   («طور فيديوهات سديد» to CINEMATIC / biz-pulse-ar) and an English one ("upgrade Sadeed"
   to MASTER_UPGRADE / biz-pulse-ar), with `write_allowed: false` and every `gaie-*` skill
   available.
3. The installed memory is the unified engine: backend `engine`, a stored entry in
   `memory.jsonl`, no `entries.jsonl`, and `brief` answers. The installed router's project
   list includes `public-catalog` rows (the project registry module).
4. A symlinked `--target`, a symlinked `.claude` and a symlinked `.claude/skills` pointing
   outside are refused with exit code 1; nothing is written outside, and nothing at all is
   written for the refused project.
5. Uninstall dry run reports `would remove`; `--apply` removes every file and leaves only the
   shared `agents/` and `skills/` directories; a second uninstall is a no-op; a reinstall
   creates everything again and a further run is `unchanged`.
6. User scope: the same install, verify and rerun states in a fresh HOME; the router routes
   both commands from an empty directory; memory is the engine; a symlinked `~/.claude` is
   refused; uninstall, a second uninstall and reinstall behave as in 5.
7. Every bootstrap, plugin-layout and hub-checkout path in `LOCATIONS` exists, and
   `hub.py` reached through the plugin path routes from the independent project.
8. With the `claude` binary on PATH (skipped with the reason otherwise): `claude --version`;
   `claude plugin validate --json <hub>` passes and lists the six `gaie:gaie-*` skills and
   `gaie:gaie-verifier`, with no finding beyond the two accepted warnings (also under
   `--strict`); a project-scope local-marketplace `marketplace add` and `install` succeed;
   `plugin list --json` shows `gaie@gaie-hub` enabled at the plugin.json version;
   `plugin details` lists the six skills and exactly the pack's agents; the project's
   `.claude/settings.json` holds `enabledPlugins`; the router runs from the installed plugin
   root; the fresh HOME holds no `policy-limits.json` or `remote-settings.json`.
   The CLI runs only `--version` and `plugin validate|marketplace add|install|list|details`
   (any other argument list, `-p` or `--print` is refused by the test helper), with
   `HTTP(S)_PROXY` pointing at a refused local port: no step reaches a host, and no
   model-backed session can start.
9. The evidence file passes the same judge (`failures()`), is bound to the SHA-256 of every
   file the scenario installs or runs, contains no host path, and states what it does not
   prove.

## Recording the evidence

```sh
python3 -m unittest tests.test_gaie_install_scenario_i      # about 1 minute with the CLI, seconds without
python3 tests/test_gaie_install_scenario_i.py record        # rewrites docs/evidence/gaie-20-layers/scenario-i.json
```

`record` runs the same steps as the tests and refuses to write if any expectation fails.
The file is bound to its sources (the bootstrap, the pack, the plugin manifests, `hub.py`,
the test file and every installed source file); after any of them changes, the evidence
test fails until `record` is run again. A recorded `fresh_session` is kept only while the
sources are unchanged.

### Fresh-session check (model-backed, run once by the integrator on the final head)

```sh
python3 tests/test_gaie_install_scenario_i.py record          # on the final head first
python3 tests/test_gaie_install_scenario_i.py prepare-session --root /tmp/gi-session
# prints, and the integrator runs, exactly one headless session:
cd /tmp/gi-session/project && env -i PATH="$PATH" HOME=/tmp/gi-session/home LANG=C.UTF-8 \
  claude -p "Reply with two lists and nothing else: the names of the skills you can invoke whose names contain 'gaie', and the names of the agents (subagent types) you can delegate to. Do not call any tool." \
  --output-format stream-json --verbose --strict-mcp-config --no-session-persistence \
  --max-budget-usd 0.25 --disallowedTools Bash,Edit,Write,NotebookEdit,WebFetch,WebSearch \
  > /tmp/gi-session/session.jsonl
python3 tests/test_gaie_install_scenario_i.py record-session --root /tmp/gi-session
```

`prepare-session` makes a fresh HOME and an independent project holding both a
project-scope bootstrap install and a project-scope plugin install (no model). The session
uses the host's login; if the host needs a proxy or CA bundle, pass those variables through
`env -i` too, never a token on the command line. `record-session` reads the harness's own
`system/init` event (`skills`, `slash_commands`, `agents`, `plugins`, `claude_code_version`)
and the `result` event (turns, cost), refuses if the sources changed since the record, and
writes `fresh_session` with `passed: true` only when the six un-namespaced `gaie-*` skills,
the six `gaie:gaie-*` skills, `gaie-verifier` and `gaie:gaie-verifier` are all listed. It
proves discovery by a new process in an independent project; it does not prove that the
model follows the skills.

## Cannot be proven on this host

- User-scope persistence across cloud sessions: each cloud container starts with a fresh
  `~/.claude`.
- Interactive `/plugin install`, marketplace trust prompts, and plugin enablement on a
  claude.ai account.
- Anything installed from `main`: before the integration branch is merged, `main` has no
  `.claude-plugin/`, no `gaie-factory` pack and no bootstrap.
- That a model uses the skills correctly.

### Post-merge checklist (owner or integrator, after the merge to `main`)

```sh
SHA=$(git ls-remote https://github.com/faisaljohaimy-ship-it/Global-AI-Engneering-Hub refs/heads/main | cut -f1)
# 1. Pack registration from main into an independent project checkout
python3 hub.py register <project> --revision "$SHA" --capability pack:gaie-factory          # dry run
python3 hub.py register <project> --revision "$SHA" --capability pack:gaie-factory --apply
python3 hub.py verify <project> --strict                                                    # expect ok: true, level verified
python3 <project>/.engineering/gaie/gaie_router.py route "افحص سديد"                        # expect AUDIT
# 2. GitHub marketplace install in a fresh HOME (no model)
export HOME=$(mktemp -d) && cd <project>
claude plugin marketplace add --scope project faisaljohaimy-ship-it/Global-AI-Engneering-Hub
claude plugin install gaie@gaie-hub --scope project
claude plugin details gaie@gaie-hub                                                         # expect Agents (1) gaie-verifier
# 3. Interactive, in a Claude Code session: /plugin marketplace add faisaljohaimy-ship-it/Global-AI-Engneering-Hub,
#    then /plugin install gaie@gaie-hub; note the trust prompt and that /gaie:gaie-master-router is offered.
# 4. Workstation persistence: python3 scripts/gaie_bootstrap.py install --scope user --apply, then open two
#    separate later sessions in other directories and confirm both list the six gaie-* skills.
# 5. Re-run `record` and the fresh-session check above on the merged main SHA.
```

Until each item has a record bound to the SHA it ran on, it stays unverified.
