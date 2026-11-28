# GAIE OS — Master Router and Project Registry (layers L02, L10)

Status: implemented and tested on branch `gaie/w1-router`.
Code: `engineering_os/gaie_router.py` (router), `engineering_os/project_registry.py`
(registry), `governance/policies/gaie-routes.json` (lexicon and control-plane
templates), `projects/aliases.json` (public-safe catalog).
Tests: `tests/test_gaie_router.py`, `tests/test_project_registry.py`.

The router turns one owner sentence, in Arabic or English, into a **plan**. It is
deterministic, offline and makes no model call. It never executes anything:
`executable_by_route` is always `false`. The control plane issues the grant, and the
Security Governor enforces it.

## 1. What a route states

Each `routed` result (route version 2) keeps every version-1 field (`engine`,
`skill`, `targets`, `write_allowed`, `gates`, `agents`, and so on) and adds:

| Field | Meaning |
|---|---|
| `intent` | `build`, `upgrade`, `accelerate`, `repair`, `cinematic`, `audit`, `release` |
| `project` | the single target's id; `null` for a new system or several targets |
| `repository_check` | what the registry knows: `registered-public`, `registered-private`, `unverified`, or `not-applicable` (new system). It never claims reachability |
| `engine_id` | control-plane engine: `master-build`, `master-upgrade`, `self-healing`, `master-cinematic`, `master-audit`, `master-release` |
| `roles` | `lead`, `support`, `verifier`. The verifier is never the lead or a supporter |
| `capabilities` | GAIE capability ids from `docs/GAIE_FACTORY.md` (`gaie.upgrade`, `gaie.audit`, …) |
| `permissions` | from the contract vocabulary, each under the side-effect ceiling |
| `grant_template` | the contract's grant shape, with `grant_id` and `expires_at` left `null` and `approvals` empty. `grant_from_template()` fills the two placeholders and validates the result against `contracts.validate_grant` |
| `side_effect` | the template's `max_side_effect` |
| `approvals_required` | gated steps (`external-write`, `production`), each needing an owner approval token |
| `execution_scope` | `read-only`, `repo-branch` (branch `claude/gaie-<intent>-<project>`), `workspace` or `release-gated`; `default_branch_writes` is always `false` |
| `tests`, `evidence`, `evidence_location` | what to run, and what to save under `$GAIE_HOME/evidence/<project>` |
| `decision` | `ready-for-grant`, `blocked` (workspace mismatch), `needs-approval` (always for release) |
| `blockers` | for example a release without a registered deployment target |

For several targets (for example «طور جميع مشاريعي»), each target carries its own
`grant_template` and `execution_scope`: one grant per project, never one shared
grant. Projects without a registered repository are listed in `skipped`.

## 2. Route table

| Owner says | English equivalent | Intent | Engine id | Lead role | Ceiling | Scope | Decision |
|---|---|---|---|---|---|---|---|
| «طور سديد بالكامل» | "fully upgrade Sadeed" | upgrade | `master-upgrade` | master-upgrade-engine-engineer | `repo-write` | repo-branch | ready-for-grant |
| «طور فيصل الجهيمي بورتفوليو» | "upgrade the Faisal Aljuhaimy Portfolio" | upgrade | `master-upgrade` | master-upgrade-engine-engineer | `repo-write` | repo-branch, the registered folder only | needs-clarification until the repository is registered privately |
| «طور بلتكس» | "upgrade BILTIX" | upgrade | `master-upgrade` | master-upgrade-engine-engineer | `repo-write` | repo-branch | needs-clarification until the repository is registered privately |
| «طور فيديوهات سديد» | "upgrade Sadeed's videos" | cinematic | `master-cinematic` | cinematic-production-engineer | `repo-write` | repo-branch | ready-for-grant |
| «سرّع سديد» | "speed up Sadeed" | accelerate | `master-upgrade` (performance) | master-upgrade-engine-engineer | `repo-write` | repo-branch | ready-for-grant |
| «افحص سديد» | "audit Sadeed", "inspect Sadeed" | audit | `master-audit` | independent-assurance-engineer | `none` | read-only | ready-for-grant |
| «أصلح أخطاء سديد» | "fix Sadeed's bugs" | repair | `self-healing` | testing-self-healing-engineer | `repo-write` | repo-branch | ready-for-grant |
| «ابنِ نظامًا جديدًا لإدارة المشاريع» | "build a new project management system" | build | `master-build` | master-build-engine-engineer | `workspace-write` | workspace `workspace/new-project`; repository creation is a separate `external-write` step | ready-for-grant (workspace only) |
| «انشر سديد» | "deploy Sadeed", "release Sadeed" | release | `master-release` | release-deployment-engineer (provisional id) | `production` | release-gated: `preview` (external-write) and `promote` (production) | needs-approval, always |
| «طور المشروع» | "upgrade the project" | upgrade | `master-upgrade` | — | — | — | needs-clarification: no project is named |

The verifier is `independent-assurance-engineer` for every intent except audit, where
the audit lead is that role and `chief-engineering-architect` reviews the report.

## 3. Hard rules (code, not text)

`check_policy()` validates the control-plane section of the policy on every route,
and `_enforce()` checks the finished plan again. The rules are constants in
`gaie_router.py` (`HARD_CEILING`, `HARD_EXECUTION`, `PERMISSION_FLOOR`), so editing
the JSON policy cannot relax them. A policy that breaks one makes routing fail with
`RouteError`. The tests tamper with the policy 19 ways to check this.

1. **Audit is read-only.** Ceiling `none`, execution `read-only`. Permissions are
   only `read:*` and `secrets:none`. There are no gated steps, `write_allowed` is
   false, and the legacy `engines.audit.write` must be false.
2. **Performance and repair stay on a branch.** `accelerate`, `repair`, `upgrade` and
   `cinematic` are capped at `repo-write`, with `workspace` or `repo-branch`
   execution only. They get no `net:fetch`, `ext:*` or `prod:*`.
3. **Release always needs approval.** Its ceiling is a gated class, it has
   `approval_required: true`, and it includes a `production` promotion step. The
   decision is always `needs-approval`, `write_allowed` is false, and
   `executable_by_route` is false.
4. **A new system gets a workspace grant only.** Ceiling `workspace-write`. The
   `create-repository` step is `external-write`, needs approval and is never part of
   the base grant.
5. **Nothing is guessed.** An unknown, ambiguous, similar-but-different (for example
   «سديدة») or unregistered project returns `needs-clarification`, with
   `grant_template: null` and no targets. A missing deployment target is reported as a
   blocker and is never inferred.
6. **Least privilege per permission.** Each permission has a minimum side-effect
   class (`write:repo-branch` needs `repo-write`, `ext:deploy` needs `external-write`,
   `prod:deploy` needs `production`). It must not exceed its intent's ceiling.
7. **Separation of duties.** The lead, supporters and verifier of one intent are
   distinct. Every role id is listed in `control_plane.role_ids`.

## 4. Project registry

| Store | Path | Holds | In Git |
|---|---|---|---|
| Public registry | `projects/registry.json` | public repositories registered with the hub | yes |
| Public-safe catalog | `projects/aliases.json` → `catalog` | id, `names.en`/`names.ar`, aliases, `repository_status`, dated observation of public repositories | yes. URLs, hosts and accounts are refused by the loader |
| Private registry | `$GAIE_HOME/projects.json` (default `~/.gaie`) | repository URL and folder, approved hub revision, capability manifest, project skills, authorized integrations, deployment target, database target, release history, checkpoints, private aliases | **never**. GAIE_HOME inside a Git work tree is refused |

API (`engineering_os.project_registry`):

- `resolve(text)` returns `{"status": "resolved", "project": <public view>}`, or
  `needs-clarification` with `candidates` (close or multiple names) and
  `known_projects`.
- `get(project_id, private=False)` returns the public view. With `private=True` it
  adds **that project's** private record only.
- `register(project_id, *, apply=False, replace=False, **fields)` validates and is a
  dry run unless `apply=True`. It refuses credential-shaped values (the memory
  module's patterns), control characters, path traversal, non-`https://github.com`
  repositories, a repository and folder already registered to another project, an
  alias that is a command word or overlaps another project's alias, and a private
  repository that conflicts with a public one. Files are written atomically with mode
  0600, and symlinks are refused.
- `append(project_id, "release_history" | "checkpoints", entry, *, apply=False)`.
- CLI: `python3 -m engineering_os.project_registry list | resolve TEXT | get ID [--private] | register ID --repository URL [--path DIR] [--alias A] [--deployment k=v] [--database k=v] [--skill S] [--integration I] [--hub-revision SHA] [--manifest PATH] [--replace] [--apply] | append ID FIELD k=v… [--apply]`.

Normalization folds hamza and alef forms (أ إ آ ٱ → ا), ى → ي, ئ → ي, ؤ → و,
ة → ه, diacritics and tatweel, case, and English possessive `'s`. Attached Arabic
prefixes are read as optional groups, so «وبلتكس» is «و» + «بلتكس». Project names
are masked before focus detection, so «المختبر الأمني» or "Security Lab" is not a
security focus.

Covered projects, with verified facts only (read-only GitHub listing, 2026-11-28):

| Id | Names | Repository status |
|---|---|---|
| `biz-pulse-ar` | SADEED / سديد | registered-public; public repository observed |
| `biltix` | BILTIX / بلتكس | unverified: more than one candidate location exists, so the owner registers the exact one privately |
| `faisal-aljuhaimy-portfolio` | Faisal Aljuhaimy Portfolio / فيصل الجهيمي بورتفوليو | unverified in public. Its repository, folder and deployment details belong only in the private registry |
| `kpi` | KPI / مؤشرات الأداء | unverified |
| `security-lab` | Security Lab / المختبر الأمني | unverified |
| `wow-bus`, `n8n-docs` | Wow Bus / واو باص, n8n docs | registered-public; public repositories observed |

## 5. Examples

```sh
python3 hub.py route "افحص سديد"          # audit · master-audit · none · read-only
python3 hub.py route "deploy Sadeed"      # release · master-release · production · needs-approval
python3 hub.py route "طور بلتكس"           # needs-clarification (exit 2): repository not registered
python3 -m engineering_os.project_registry register biltix \
  --repository https://github.com/OWNER/REPO --apply   # private, outside Git
python3 hub.py route "upgrade BILTIX"     # upgrade · master-upgrade · repo-write · registered-private
python3 hub.py route "ابنِ نظامًا جديدًا لإدارة المشاريع"   # build · workspace-write · create-repository gated
python3 hub.py route "طور المشروع"          # needs-clarification: no project named
```

An abridged audit route:

```json
{"status": "routed", "decision": "ready-for-grant", "intent": "audit", "project": "biz-pulse-ar",
 "engine_id": "master-audit", "side_effect": "none",
 "roles": {"lead": "independent-assurance-engineer", "support": [], "verifier": "chief-engineering-architect"},
 "grant_template": {"grant_id": null, "role": "independent-assurance-engineer",
                    "engines": {"master-audit": ["audit"]}, "paths": ["workspace/biz-pulse-ar"],
                    "max_side_effect": "none", "expires_at": null, "approvals": []},
 "execution_scope": {"kind": "read-only", "default_branch_writes": false, "network": false, "production": false},
 "repository_check": {"status": "registered-public", "repository_known": true}, "executable_by_route": false}
```

## 6. Limitations

- The router uses lexical rules, not a language model. Phrasing outside the policy
  lexicon returns `needs-clarification` rather than a guess.
- `repository_check` reports the registry's knowledge only. Reachability, branch
  protection and credentials are checked by the executing agent.
- Engine **action names** (`plan`, `upgrade`, `verify`, `audit`, `diagnose`, `repair`,
  `render`, `preview`, `promote`, `create-repository`) and the role id
  `release-deployment-engineer` are provisional until `governance/engines.json` and
  `governance/agent-roles.json` exist. A test checks them against those files as soon
  as the files land.
- Vendored copies installed by `scripts/gaie_bootstrap.py` or the `gaie-factory`
  pack do not yet include `project_registry.py` or `contracts.py`. They fall back to
  the original loader, which ignores the catalog and the private record fields, and
  to built-in copies of the contract constants (tested equal).
- The secret filter is best-effort pattern matching, shared with `gaie_memory`.
- The SADEED → `biz-pulse-ar` mapping comes from the hub's existing public registry
  (PR #26). The repository's existence was observed, but its content was not
  inspected here.
