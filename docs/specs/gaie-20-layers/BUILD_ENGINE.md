# L16 — Master Build Engine

Status: implemented and tested (`engineering_os/build_engine.py`, `templates/app-stdlib/`,
`tests/test_build_engine.py`, `tests/test_build_engine_e2e.py`). Deterministic code only:
**no language model and no provider is called**, nothing leaves the machine, and nothing is
deployed. The engine turns a ready `gaie.spec/1` (from L15, `engineering_os.requirements`)
into an **independent, working application** in an isolated workspace, proves it with the
application's own tests, and leaves factory receipts that `engineering_os.factory` revalidates.

```
owner text ─► gaie_router.route()  ─► requirements.parse()  ─► ready gaie.spec/1
                                                                   │
build_engine.build(spec, out_dir=…, hub_revision=…) ◄──────────────┘
  1 spec gate        requirements.validate_spec + is_ready, then app-stdlib support checks
  2 registry check   workspace links, project_registry (public + private), fail-closed
  3 model            entities, relations, labels (ar/en), roles, scoping, NFR numbers
  4 acceptance       every criterion → executable check (or unmapped, with the reason);
                     state rules (progress, overdue, completion) derived from criteria
  5 scaffold         render templates/app-stdlib → files (never overwrites; exclusive create)
  6 git              own repository, branch main, deterministic initial commit
  7 static checks    independence, secrets, code hazards, dependencies, migrations,
                     data isolation, accessibility, documentation, hub link
  8 tests            app's unit + API + acceptance suite (python3 -I) and Playwright E2E
  9 factory          10 stage artifacts, 18 check reports, receipts → evaluate_factory
 10 repository       .gaie/repository-request.json (private, awaiting approval)
 11 git              evidence commit (.gaie/factory, request)
publish(app, remote=…, grant=…, token=…)   gated external-write: push + private registry
```

## 1. Public API

| Callable | Side effect | Notes |
|---|---|---|
| `build(spec, *, out_dir, hub_revision, now=None, workspace=None, environ=None, registry=None, verify=True, e2e=True)` | workspace-write | Returns a `gaie.build-report/1`. `ok` is `true` only when `evaluate_factory` reports `delivery_review_ready`. `now` makes the source commit reproducible. `verify=False` generates and runs static checks only (the factory then stays blocked). |
| `plan(spec, *, allow_open_questions=False)` | none | Entities, collections, factory stages, expected test counts, executable vs unmapped criteria, derived rules, scoping, translation gaps, open items. |
| `validate_spec(spec, *, allow_open_questions=False)` | none | L15 validation, then `SpecError` / `OpenQuestions` / `UnsupportedSpec`. |
| `compile_acceptance(spec, model)` | none | `(checks, unmapped)`; see §4. |
| `evaluate(app_dir)` | none | Re-validates `.gaie/factory/receipts.json` against the app's current bytes. |
| `request_repository(app_dir)` | workspace-write | Writes the repository request; never contacts GitHub. |
| `publish(app_dir, *, remote, grant, token, now=None, environ=None)` | **external-write** | Needs a `contracts.validate_grant` grant for `master-build/publish` with `max_side_effect ≥ external-write`, not expired, an approval whose `token_sha256` equals SHA-256 of `token`, and the application directory (symlinks resolved) inside one of the grant's `paths` — checked first; an application outside them is refused before anything is read, written or pushed. Remote: `https://github.com/<owner>/<slug>(.git)` or a local bare repository (tests). After an approved GitHub push the project is registered in the private registry (`register_project`). |
| `register_project(app_dir, repository, *, environ=None, apply=False)` | state-write | `project_registry.register` (dry-run unless `apply`). |
| `engine(action, payload, ctx=None)` / `health()` / `ENGINE_RECORD` | | Control-plane facade, CONTRACTS.md §2. Actions `plan-app`, `build`, `evaluate-app`, `request-repository`, `publish` — distinct from the factory actions `spec`/`plan`/`evaluate` that `engineering_os.adapters:master_build` already serves, so both fit one `master-build` record. Unknown payload keys are refused; payloads are data. |
| CLI | | `python3 -m engineering_os.build_engine plan --spec f.json \| build --spec f.json --out DIR --hub-revision SHA [--workspace W] [--now T] [--no-verify] [--no-e2e] \| evaluate APP \| publish APP --remote URL --grant g.json --token-file t` |

Errors: `BuildError` ⊃ `SpecError` ⊃ {`UnsupportedSpec`, `OpenQuestions`}, `WorkspaceError`,
`DuplicateProject` (`.matches`), `ApprovalRequired`.

## 2. Gates (all fail-closed)

- **Specification** — `requirements.validate_spec` must pass and `is_ready` must be true
  (open questions go back to the owner through `requirements.refine`). The engine adds:
  no credential-shaped text and no control characters anywhere; and refuses as
  `UnsupportedSpec` (never silently drops): `product_type` other than `web-app`, AI,
  integrations, a runtime other than `python3-stdlib`/`sqlite`, no role with `*`, reserved
  table/field names (`app_account`, `app_session`, `schema_migrations`, `created_by`), required
  or self many-to-many relations, more than 80 features. Required many-to-one cycles are a
  `SpecError`.
- **Workspace** — `out_dir` must be an absolute, new or empty, kebab-case **direct child** of
  the workspace, reached without symlinks or `..`. The workspace (default
  `$GAIE_WORKSPACE` or `$GAIE_HOME/workspace`) must be outside the hub and outside every
  Git work tree.
- **Hub revision** — a full 40-hex commit that exists in this hub (`hublink.has_commit`);
  `pin_on_main` and `reproducible_from_pin` (every template byte equals the pinned commit)
  are recorded in `.gaie/link.json`, not assumed.
- **Duplicates** — a workspace app with the same `project.id`, or a `project_registry`
  record whose id, names, aliases or repository name match the slug or title, raises
  `DuplicateProject` (route to MASTER_UPGRADE). An unreadable registry refuses the build.
- **External writes** — see `publish`. Without approval: `ApprovalRequired`, and no Git
  network operation runs.

## 3. Generated application (`templates/app-stdlib` 2.0.0)

```
README.md  CHANGELOG.md  LICENSE-PENDING.md  docs/API.md  docs/ARCHITECTURE.md (ADR-001…005)
manage.py                       serve | migrate [--down N] | seed | create-account | test
app/model.py                    entity model from schema.json; validation (types, required,
                                length, range, enum, strict date/e-mail, PATCH merge)
app/db.py                       migrations, parameterized CRUD, unique, scoping, children,
                                links, progress (one aggregate query), state rules, sessions
app/auth.py                     PBKDF2-HMAC-SHA256 (600k, 16-byte salt), sessions, lockout
app/server.py                   http.server JSON API + static files; security headers
app/schema.json                 entities, relations, roles, scoping, rules, limits, NFR numbers
app/acceptance.json             the spec's criteria as executable checks
app/seed_data.json              synthetic records (label "synthetic"); no accounts
migrations/0001_initial.{up,down}.sql
static/index.{ar,en}.html       server-rendered lang/dir; login form; skip link; live regions
static/app.js app.css i18n.json vanilla JS (textContent only), logical CSS, ar/en strings
tests/test_validation.py test_migrations.py test_api.py test_acceptance.py run_tests.py
tests/e2e/ui.e2e.mjs            Playwright (Chromium): ar + en, signed in
package.json package-lock.json  dev-only Playwright pinned to the reviewed catalog version
.gaie/spec.json link.json repository-request.json factory/
```

API conventions (requirements §4): JSON bodies; `/api/<entity plural>`; many-to-one keys
`<field>_id`; 201 create, 200 read/update (PUT replaces, PATCH merges), 204 delete;
400 validation (including a reference that does not exist), 401 no session, 403 role or
CSRF or cross-origin, 404 unknown id/route, 405 method, 409 duplicate unique value,
dependent records or state rule, 411/413/415 body rules, 429 sign-in lockout.
Sub-resources: `/api/<parent>/{id}/<child plural>` (one FK), `/api/<source>/{id}/<link>`
(many-to-many, `POST {<target>_id}`), `/api/<parent>/{id}/progress` (when a criterion asks).
Lists: `limit`/`offset` (NFR "default N, max M", else 50/200), filters on references, enums
and booleans, `sort=<field>`/`-<field>` (nulls last), `overdue=true` when a criterion asks.

Security: every API route except health and login needs a session (`HttpOnly;
SameSite=Strict` cookie, random token, only its SHA-256 stored, 12 h) and the role
permission for its method (`read`→GET, `write`→POST/PUT/PATCH, `delete`→DELETE, `:own` =
records the account created). Writes need the session's `X-CSRF-Token`, JSON and a
same-origin request. A many-to-many link belongs to its source record: adding one needs
`write` on that record and removing one needs `write` and `delete` on it, with the same
`:own` ownership rule and the same CSRF and same-origin checks as a PATCH/DELETE of the
record itself. A sub-resource read (children, links, progress) is authorized like a GET
of the parent record (404 when the role cannot read it, `read:own` included) and returns
only children, link targets and counts the role can read directly. When the spec says
users "see only <entity> they belong to", roles without `*` see only those records (via
the many-to-many link to the principal entity — the entity with a required unique e-mail)
and records whose references lead to them, directly or through other entities (a comment
on a task of a visible project): at least one such reference must be set and every one
that is set must point to a visible record. A model in which one entity reaches the
scoped entity through more than 32 reference chains is refused (`UnsupportedSpec`).
An account is identified with the principal record whose e-mail equals the account's
(immutable) e-mail; once set, that e-mail field can be changed only by a `*` role (403
`read_only` otherwise), so a scoped role cannot re-point its own or another identity.
CSP `default-src 'self'`,
`frame-ancestors 'none'`, nosniff, DENY, no-referrer, COOP/CORP; body limit 64 KiB;
loopback bind unless `--allow-network`; no default account.

Independence: the application imports nothing from the hub (checked by AST and by a test
that renames the hub away and runs it); `.gaie/link.json` validates with
`hublink.validate_manifest` (same keys as `.engineering/capabilities.json`, no vendored
capability) and lists what was used: the template files with SHA-256, the reviewed
Playwright catalog entry, the requirements and factory engines, the `gaie-build` skill.

## 4. Acceptance criteria → executable tests

`compile_acceptance` matches each criterion (`METHOD /path [condition] returns NNN [and
expectation]`) against the forms that `tests/test_acceptance.py` implements, resolves every
name to the model (fields, foreign keys, entities by name/plural/label, roles, links) and
stores the result in `app/acceptance.json`. The generated test runs each one against a fresh
server and asserts the stated status and expectation.

A criterion compiles only when the handler for its route kind actually exercises both its
condition and its expectation (`build_engine.HANDLED`, mirrored as `EXERCISED` in the
generated `tests/test_acceptance.py`, which also refuses any other pair at run time):
records the scenario needs are created as the administrator, and the request the criterion
is about is made as the criterion says (`without a session` on every route except the page
and login, `as <role>` on collections and items); list expectations (`lists …`, `only …`,
`ordered by …`) need GET; body conditions apply to collection and item writes only. Any
other criterion is unmapped — not covered by any generated test — and never reported as
passed. A criterion is `passed` only when its generated test ran and passed.

| Conditions | Expectations |
|---|---|
| with a valid body · without a session · without `<field>` · with `<field>=<value>` · with `<field>=<value>` while a linked `<child>` is not `<value>` · with `<field>` longer than N characters · with a/an `<field>` that does not exist · with an unknown id · with a duplicate `<field>` · as `<role>` · with valid credentials · with a wrong password · with `<field>` of an existing `<entity>` · with an existing `<link key>` · with a `<target>` already in the `<source>` · for a `<parent>` without `<children>` | the (updated) record · lists the created records · only `<items>` assigned to that `<entity>` · only `<items>` with `<date>` before today and `<field>` not `<value>` · only `<items>` with `<field>` `<value>` · `<items>` ordered by `<field>` ascending with empty … last · only that `<parent>`'s `<children>` [ordered by `<field>`] · total_X, done_X and percent … rounded down · percent 0 · the membership · a session cookie · the session is no longer accepted · html with dir=… and lang=… · html where every form input has a label |

State rules are taken only from criteria that state them (progress endpoint, overdue
filter, "cannot become X while a linked child is not Y" → 409). A criterion that does not
match, names an unknown field/route, or needs an unstated rule is **unmapped** with its
reason; unmapped criteria fail the requirements stage, so nothing downstream verifies.
Non-functional statements map to named tests and checks only through a reviewed table of
whole-statement forms (`_nfr_rules`: the statements `requirements` writes, matched in full,
case-insensitive): no secrets in the repository → secret scan; parameterized SQL → injection
test; input validation (on every write endpoint) → the per-entity validation unit tests and
`test_validation_<table>` (POST, PUT with a full body and PATCH merged over the stored record:
unknown, read-only, required, wrong type and over-long values refused, nothing changed) plus
the link tests (link bodies); role check on every endpoint → `test_role_check_on_every_endpoint`
(collection and item routes for every role, and PUT, PATCH and DELETE of a visible record by
every non-admin role on its own and on another account's record, so a dropped `write:own`
check fails), `test_unauthenticated_requests_refused` (every route, sub-resources included),
the link, child and progress tests (per-role checks of those routes); CSRF token on
cookie sessions; passwords stored as salted PBKDF2-SHA256 hashes → PBKDF2 test; rate limit on
sign-in (N failures per M minutes) → lockout test only when (N, M) is `SIGNIN_LIMIT` (5, 15),
the numbers `app/auth.py` implements for one e-mail from one client address in a sliding
window and `test_login_lockout` proves (one wrong password per second for 30 minutes on a
fake clock: exactly 5 are checked in each 15 minutes, the rest get 429 with the wait until
the oldest failure is 15 minutes old); p95 API latency and pagination → their
tests when the stated numbers are the ones the test measures; keyboard; labels; focus; ISO
dates per locale; "ar rtl"/"en ltr" → server and E2E locale checks; one-aggregate progress;
the scoping statement. Any other statement — including one that merely contains such a
keyword (multi-factor sign-in, session expiry, password rotation, request rate limits,
audit logs, page render time) — is unmapped (no generated test or check covers it).

For «ابنِ نظامًا جديدًا لإدارة المشاريع» the real L15 spec yields 4 entities, 14 features,
64 criteria (all 64 executable) and 16 NFR statements (all mapped): 165 Python tests
(unit, API, acceptance) and 36 E2E cases.

## 5. Evidence and the factory

The plan is `factory.plan_factory` with targets `api, backend, database, web` → stages
requirements, architecture, database, api, backend, frontend, testing, security,
documentation, release (the pipeline's scaffold and git steps are evidenced inside the
architecture and release artifacts; "release" is release preparation —
`deployment_authorized` is always false). `source_revision` is the app's own initial
commit; requirements are the spec's features plus one `nfr-<category>` requirement each,
with acceptance ids `<feature>-a<n>`.

Per stage: `.gaie/factory/artifacts/<stage>.json` (factory document with stage content),
`checks/<stage>-<check>.json` (factory check report), `details/<stage>-<check>.json` (which
tests/checks decided it, with their status), plus `request.json`, `plan.json`,
`receipts.json`, `evaluation.json`. A check is `passed` only when every evidence id it names
passed in this run; `not-run` (for example without Node/Playwright, or `verify=False`) and
`failed` keep the stage blocked. Checks are this engine's deterministic evaluators (reviewer
`master-build-checks`): they bind real executions to the bytes, they are not an independent
review — `evaluate(app)` or `factory.evaluate_factory` can be re-run by the verifier, and
`python3 -I manage.py test` / `node tests/e2e/ui.e2e.mjs` re-execute the suites.

## 6. How a project is created end to end

1. `python3 hub.py route "ابنِ نظامًا جديدًا لإدارة المشاريع" --workspace <empty private dir>`
   → MASTER_BUILD. The route is a plan (`write_allowed: false`, no grant template): with a
   verified workspace its decision is `needs-approval`, without one it is `blocked`.
2. `spec = requirements.parse(text)`; answer open questions with `requirements.refine`.
3. After the operator separately approved the build and that workspace:
   `report = build_engine.build(spec, out_dir=$GAIE_HOME/workspace/project-management,
   hub_revision=<reviewed main SHA>)` → `report["ok"]` and `report["factory"]`.
4. Owner reviews `README.md`, `docs/`, `.gaie/factory/evaluation.json` and the open items.
5. Owner approves the repository: creates the private repository named in
   `.gaie/repository-request.json` (or lets an `ext:github` host tool do it) and issues an
   approval token; `publish(app, remote=…, grant=…, token=…)` pushes `main` and registers
   the project privately. Until then, no remote exists and nothing was pushed.
6. Further changes go through MASTER_UPGRADE (the duplicate check routes there).

## 7. What still needs the owner

- **OI-REPO** — approval to create the private GitHub repository and the approval token.
- **OI-LICENSE** — choose a license; `LICENSE-PENDING.md` grants none.
- **OI-DEPLOY** — choose a deployment target (TLS, reverse proxy, `--secure-cookies`); no
  environment is created and nothing is deployed.
- **OI-IDENTITY** — keep local PBKDF2 accounts or connect an identity provider; password
  reset and MFA are not implemented.
- **OI-I18N** (only when listed) — Arabic labels missing from the spec and the glossary.

## 8. Registration (for the integrator — not edited by L16)

`governance/engines.json` already has `master-build` → `engineering_os.adapters:master_build`
(factory `spec`/`plan`/`evaluate`). Proposed: add the five actions of
`build_engine.ENGINE_RECORD` (validated by `contracts.validate_engine(..., check_imports=True)`
in the tests) to that record and let the adapter delegate them to
`engineering_os.build_engine:engine`. Layer L16: add interfaces
`engineering_os.build_engine:build`, `:plan`, `:evaluate`, `:publish`, tests
`tests/test_build_engine.py`, `tests/test_build_engine_e2e.py`, scenario `A`.

## 9. Limitations (honest)

- One template: web-app, Python standard library, SQLite, threaded `http.server`. Suited
  to a team or local use, not high concurrency; no mobile, dashboard charts, AI, file
  uploads, e-mail or other integrations (refused, not faked).
- Acceptance coverage is limited to the forms in §4; anything else is reported unmapped.
  Domain rules come only from criteria; the engine does not infer business logic.
- Sign-in failures are limited per (e-mail, client address) (5), per client address (20)
  and per e-mail across addresses (20) in sliding 15-minute windows, in process memory
  (behind a reverse proxy all clients share its address; a restart resets the counters);
  the per-e-mail ceiling means failures from several addresses together make that e-mail
  wait at every address that has not signed in to it in the last 30 days. Unknown e-mails cost the same
  PBKDF2 work as wrong passwords, and a refused attempt costs none. No password reset, MFA,
  audit log or account UI
  (accounts are created with `manage.py create-account`). Many-to-many links have an API,
  not a UI.
- Accessibility evidence is automated (labels, keyboard order, focus outline, landmarks,
  lang/dir) — no screen-reader or contrast audit. Browser evidence is Chromium only, run
  with the Playwright found on the machine (version recorded in the report).
- The 200 ms p95 check is a local measurement on the build machine, not production.
- Check reports are self-evaluations of executed tests; independent verification is a
  separate role (assurance engine / gaie-verifier).
