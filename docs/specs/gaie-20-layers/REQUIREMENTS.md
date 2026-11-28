# L15 — Requirements & Specification Intelligence

Status: implemented and tested (`engineering_os/requirements.py`, `governance/domains/`,
`tests/test_requirements.py`). Deterministic code only: **no language model is called**.
Every output carries the SHA-256 of its input and `"mode": "deterministic"`.

The engine turns an owner command or a longer brief, in Arabic or English, into a
`gaie.spec/1` requirement specification for the Master Build Engine (L16) and the Master
Upgrade Engine. Anything the text does not settle becomes an **open question**; nothing is
guessed. Defaults taken from a domain pack are not silent: each one is listed in
`assumptions` (Arabic and English).

```
owner text ──► gaie_router.route()           (which engine? build / upgrade …)
           └─► requirements.parse()          (what exactly? gaie.spec/1)
                   │ open_questions? ──► owner answers ──► requirements.refine()
                   ▼ ready spec
               build engine (new system)  /  upgrade engine: diff_specs(old, new)
```

## 1. Public API

| Callable | Returns | Notes |
|---|---|---|
| `parse(text, *, language=None, base=None, answers=None, domains_dir=None)` | `gaie.spec/1` dict | `language` overrides detection (`ar` when the text has Arabic letters). `base` = the current, complete spec of an existing system (change commands). `answers` is strict: an answer to a question the command does not raise is refused. |
| `refine(spec, answers, *, base=None)` | new spec | Answers must be ids of the spec's open questions and one of their `choices`. Re-parses the command with all answers so far, so the result equals a fully answered `parse`. The `base` question is answered with `base=`. An answer made moot by another answer (e.g. `intent=change`) is dropped and recorded as `answer-moot:<id>`. The input spec is never mutated. |
| `validate_spec(spec)` | `{ok, schema, spec_sha256, ready, open_questions, mode}` | Raises `SpecError`; `error.errors` lists **every** problem found. |
| `is_ready(spec)` | bool | Valid and no open question — the build engine may consume it. |
| `diff_specs(old, new)` | `gaie.spec-diff/1` dict | Added/removed/changed entities, fields, relations, features, roles, integrations, NFRs, scalars; `breaking` list. |
| `acceptance_checks(spec)` | `{mode, spec_sha256, checks}` | Every acceptance criterion as `{feature, index, criterion, method, path, condition, status, expect, placeholders}`. |
| `parse_acceptance(text)` | dict | One criterion; `SpecError` when it does not follow the grammar (§4). |
| `load_knowledge(dir=None)`, `validate_pack(pack)`, `validate_lexicon(lex)`, `domain_packs()` | | Strict loading of `governance/domains/*.json` (duplicate JSON keys, symlinks, id ≠ file name, a phrase claimed by two packs are refused). |
| `engine(action, payload, ctx=None)` / `health()` | | Control-plane facade with the `(action, payload, ctx)` signature of CONTRACTS.md §2. Actions `parse`, `refine`, `validate`, `diff`, `acceptance`, `packs`; all side-effect class `none`. Payloads are data, never instructions; unknown keys are refused. |
| CLI | | `python3 -m engineering_os.requirements parse "…" \| validate f.json \| acceptance f.json \| diff a.json b.json \| packs` (exit 0 ready, 2 open questions, 1 refused). |

## 2. Pipeline (all steps deterministic)

1. **Input** — 1–20,000 characters; `source.sha256` = SHA-256 of the exact UTF-8 text.
2. **Normalization** — reused from the master router (`gaie_router.normalize`): NFKC, case
   folding, Arabic diacritics and tatweel removed, `أ إ آ ٱ → ا`, `ى ئ → ي`, `ؤ → و`, `ة → ه`.
   Hyphenated words are split. Each command token also matches without the Arabic clitic
   prefixes `و ف ب ل ك ال لل` (router `_strip` plus `لل`) and without English plural endings.
   Keywords are written in bare form (no `ال`) in the packs.
3. **Segmentation** — sentences (`. ; ! ? ؟ ؛` and new lines) and clauses (`, ، : ( )`).
4. **Lexicon matching** — longest phrase wins; ties by category (domain > locale >
   integration > ai > product > database > feature > entity > field > role > nfr).
   A phrase after a negation in its clause (`بدون، دون، بلا، لا، without, no, not, except…`)
   is negated. A remove verb (`احذف، أزل، remove, delete, drop`) switches a clause to removal
   only as a command (clause start, after a coordinator, or with `و/ف` attached), so
   "members can delete their own tasks" removes nothing.
5. **Intent** — the router's own verb classifier (`gaie_router.classify`): `build` or the
   word new/جديد → `new-system`; upgrade/accelerate/repair verbs or add/remove/change verbs →
   `change`; neither → open question `intent`. `base=` implies `change`; a build command with
   `base=` is refused.
6. **Domain** — exactly one pack with a strong keyword → that pack. Otherwise entity names
   alone may identify one pack (recorded as `domain-weak`). Two or more candidates, or none,
   → open question `domain` (choices: the candidates, or every pack). Never guessed.
7. **Skeleton** — the pack's core entities, relations whose two ends exist, roles,
   product type; optional entities only when mentioned. A change command starts from a deep
   copy of `base` instead.
8. **Mentions** — per sentence: entities (activate optional / adopt a *portable* entity of
   another pack / exclude / remove), fields, generic features, integrations, AI use cases,
   roles, NFR keywords, product type, database, locale.
   A locale or role named right after a remove verb or a negation (only filler words such as
   "the", "language", «اللغة» between, before the name also want/need words — "we dont need",
   «لا نريد», «لا حاجة لـ» — and the name ending the phrase — "no arabic title" names a field)
   is removed: "remove the Arabic locale", "remove the en locale", «واحذف الإنجليزية»,
   «وإزالة اللغة الإنجليزية», "stop supporting english", "without english", «من غير
   الإنجليزية», «لا نريد اللغة العربية», "remove the user role", «احذف دور المستخدم», «وأزل دور
   العضو», "without managers", «بدون مدير المشروع». So is a name that opens its clause (or
   follows "and"/و) and is followed only by "is not needed/required" or «غير مطلوبة/ضرورية»
   ("english is not needed"). Besides the lexicon's control words, `requirements.py` knows a
   few more remove/negation wordings for this purpose only (`_EXTRA_SIGNALS`: «إزالة», «حذف»,
   «إلغاء», "stop (supporting)", «من غير», …). A role is named by its id, label or lexicon
   keywords; next to the word role/دور also by the first word of its label («دور العضو» → the
   member role). A role name is then not read as an entity. Without the word role/دور, a role
   name that an entity name covers entirely ("remove members": the member role and the Member
   entity) is ambiguous: it becomes the open question `role_or_entity:<role>` and neither changes
   until it is answered; a longer role label wins over the entity word inside it ("remove project
   managers" is the manager role, not the Project entity). A new system simply does not get it (`excluded:locale-<id>` /
   `excluded:role-<id>`); a change removes it (`removed:…`, which `diff_specs` flags as
   breaking). A negation in a change command, or a removal of the only locale, the only role or
   the only `*` role, is never applied silently: it becomes the open question below.
   A field or feature attaches to the entity named right after it when a linking word joins
   them ("add priority **to** tasks", «أولوية **المهام**», «**للمهام**»), or to the entity
   before it when that entity "has" it ("tasks **with** priority", «المهام **مع** الأولوية»,
   "projects **have** a budget"). With no link: a field that already exists is satisfied,
   otherwise `field_entity:<field>` is asked; a feature applies to the pack's primary entity.
   Fields added to an existing entity by a change command are optional unless they have a
   default (recorded as `optional-field`), so existing rows stay valid.
9. **State questions** — an entity without any relation (in a spec with 2+ entities) →
   `relation:<Entity>`; AI needed without provider → `ai_provider`; generic "AI" without a
   use case → `ai_use_case`; a paid integration under `no_paid_services` → `integration:<id>`.
10. **Features** — per entity `manage-<plural>` (CRUD + validation criteria generated from the
    fields and relations), pack features whose entities are present (and whose criteria do not
    name an excluded field), generic features, `ai-<use case>`, then `auth`, `rbac`,
    `ui-locales` (no UI features for `api-service`). A change keeps the base order and
    regenerates `manage-*` only for touched entities.
11. **NFRs, constraints** — lexicon defaults + pack additions + mentioned NFR keywords;
    `i18n` always starts with `ar rtl` / `en ltr` for the spec's locales. Constraints default to
    `python3-stdlib`, `sqlite`, `no_paid_services: true`.
12. **Self-check** — the result is validated with `validate_spec` before it is returned.

## 3. `gaie.spec/1` reference

The shape of `/home/user/gaie-state/SPEC_FORMAT.md`, with these additions (all validated; every
identifier pattern — PascalCase, snake_case, kebab-case, feature, role and question ids, SHA-256
digests, acceptance criteria — must match the whole string, so a trailing newline is refused):

| Key | Rule |
|---|---|
| `mode` | **required**, always `"deterministic"` |
| `intent` | optional key; `new-system` \| `change` (`null` only with open questions) |
| `assumptions` | optional key; `[{id, ar, en}]` — every pack default and decision applied |
| `source` | `command`, `language`, `sha256` (must equal SHA-256 of `command`); optional `answers`, `knowledge_sha256` (hash of the packs used), `base_sha256` (hash of the base spec of a change) |
| `title`, `slug`, `product_type`, `domain` | `null` allowed only while open questions exist |
| `roles[]` | `{id, permissions, label?}`; permissions ⊆ `* read read:own write write:own delete approve export manage:users` |
| `entities[]` | `{name: PascalCase, fields, label?: {ar,en}, plural?: kebab (API path)}`; duplicate names (case-insensitive) and plurals refused |
| `fields[]` | `{name: snake_case, type, required, label?, max?, min?, values? (enum), default?, unique?}`. Types: `text int number bool date datetime enum email`. `id`, `created_at`, `updated_at` are implicit and reserved. Enum values: unique snake_case, at least one; `default` must match the type/enum. |
| `relations[]` | `{from, to, kind, required, field?}`; kinds `many-to-one one-to-many many-to-many`; both ends must exist; the foreign key of a many-to-one is `<field>_id` (default `field` = snake_case of `to`) and must not collide with a field |
| `features[]` | `{id, title: {ar,en}, acceptance: [≥1 testable criterion], acceptance_ar?: [same length], entities?: [existing entities]}` |
| `nfr` | exactly `security performance accessibility i18n`; `i18n` contains `ar rtl` when `ar` ∈ locales and `en ltr` when `en` ∈ locales |
| `ai` | `{needed, use_cases, provider?}`; use cases only when needed; needed ⇒ provider or an `ai_provider` question |
| `integrations[]` | `{id, title, paid, network, approved}`; paid ∧ ¬approved ∧ `no_paid_services` ⇒ an `integration:<id>` question |
| `constraints` | exactly `{runtime, database ∈ sqlite/postgresql/mysql, no_paid_services}` |
| `open_questions[]` | `{id, question: {ar,en}, choices: [..] \| null}` |

Invariant: a spec **without** open questions has a title, slug, domain, product type, at least
one entity, one feature and one role. Specs produced by `parse` additionally carry labels,
plurals and `acceptance_ar` everywhere.

### Open questions

| id | choices | answered by |
|---|---|---|
| `intent` | `new-system`, `change` | `refine` |
| `base` | — | `refine(spec, {}, base=<current spec>)` |
| `domain` | candidate packs, or all packs | `refine` |
| `product_type`, `database` | the conflicting mentions | `refine` |
| `field_entity:<field>` / `remove_field:<field>` | entity names | `refine` |
| `feature_entity:<feature>` | entities with an enum field | `refine` |
| `relation:<Entity>` | other entities + `none` | `refine` (`none` → `standalone:<Entity>` assumption) |
| `ai_use_case` | lexicon use cases | `refine` |
| `ai_provider` | `local-model`, `approved-paid-api`, `drop` | `refine` (`drop` removes the AI part) |
| `integration:<id>` | `approve`, `exclude` | `refine` |
| `locale_removal:<locale>` / `role_removal:<role>` | `remove`, `keep` | `refine` (a negation in a change command) |
| `locale_needed:<locale>` / `role_needed:<role>` | `keep` | `refine` (the only locale, the only role or the only `*` role cannot be removed) |
| `role_or_entity:<role>` | `role`, `entity` | `refine` (a removed or negated name is both that role and an entity: `role` applies it to the role, `entity` to the entity) |

## 4. Acceptance grammar (machine-checkable)

```
METHOD /path [condition] returns NNN [and expectation]
```

`METHOD` ∈ GET POST PUT PATCH DELETE; `path` starts with `/`, may hold a query string and
placeholders `{id}`, `{member_id}`…; `NNN` is the HTTP status. `acceptance_checks()` returns
the parsed form. Conventions the build engine implements and its tests assert: JSON bodies;
collection paths `/api/<entity plural>`; many-to-one foreign keys sent as `<field>_id`;
`400` validation error, `401` no session, `403` role or ownership denied, `404` unknown id,
`405` method not allowed, `409` conflict (duplicate unique value, state rule), `413` file too
large, `503` no AI model configured (never a fabricated result); `as <role>` in a condition
means a signed-in user with that role. Examples from the project-management spec:

```
POST /api/tasks with a project_id that does not exist returns 400
PATCH /api/tasks/{id} with assignee_id of an existing member returns 200 and the updated record
GET /api/tasks?overdue=true returns 200 and only tasks with due_date before today and status not done
DELETE /api/tasks/{id} as member returns 403
GET /?lang=ar returns 200 and html with dir=rtl and lang=ar
```

## 5. Domain knowledge packs (`governance/domains/`)

| Pack | Core entities | Optional | Product | Pack features (besides generated CRUD/auth/rbac/ui) |
|---|---|---|---|---|
| `project-management` | Project, Task, Member, Milestone | Comment | web-app | assign-tasks, track-task-status, task-due-dates, project-tasks, project-progress, milestones, project-membership, task-comments |
| `inventory` | Product, Warehouse, StockMovement, Supplier | PurchaseOrder | web-app | stock-movements, stock-on-hand, low-stock, supplier-products, receive-purchase-orders |
| `crm` | Customer, Deal, Activity, SalesRep | — | web-app | deal-pipeline, customer-timeline, customer-search, deal-ownership |
| `hse-incident-reporting` | Incident, Investigation, CorrectiveAction, Employee | — | web-app | report-incident, triage-severity, corrective-actions, close-incident, investigations, incident-statistics, reporter-privacy |
| `kpi-dashboard` | Kpi, Measurement, Department | — | dashboard | record-measurements, kpi-status, dashboard-summary, kpi-trend |

Portable entities (adopted by other domains when named, with a `relation:` question):
Comment, Supplier, Customer, Employee, Department.

**Project management — Milestones, not Comments, by default.** A milestone ties tasks to a
dated deliverable, so schedule progress and slippage are machine-checkable (`project-progress`,
"a milestone cannot be reached while a linked task is open"); comments are free text that
never changes project state and add content-moderation risk. Comment stays available: the
command «…مع تعليقات على المهام» / "with comments" activates it with its `task-comments`
feature. «ابنِ نظامًا جديدًا لإدارة المشاريع» yields Projects, Tasks (title, status
todo/in_progress/done, priority, due date, assignee → Member, project, milestone), Members
(unique email, role), Milestones (due date, open/reached), 14 features and 64 acceptance
criteria, all parsed by `acceptance_checks`.

**Pack format** (`gaie.domain/1`, validated by `validate_pack`): `id` (= file name), `version`,
bilingual `title`, `summary`, `rationale`, `keywords {ar, en}` (strong domain phrases),
`product_type`, `primary` (a core entity), `roles`, `entities` (spec entity + bilingual
`synonyms`, `optional`, `portable`; fields may carry `keywords` to be addable elsewhere),
`relations`, `features` (`id`, `requires`, bilingual `title`, `acceptance: [{en, ar}]` with
`en` in the grammar), `nfr` additions. `_common.json` (`gaie.lexicon/1`) holds the shared
control words, addable fields, generic feature templates, integrations (paid flag), AI use
cases, roles, product/database/locale words, NFR keywords and defaults. A new pack is one
JSON file; `load_knowledge` refuses it if any phrase is already claimed by another pack.

## 6. `diff_specs` — `gaie.spec-diff/1`

`{schema, mode, old_sha256, new_sha256, identical, entities{added, removed, changed[{name,
fields{added, removed, changed[{name, before, after}]}, meta_changed}]}, relations{added,
removed, changed}, features{added, removed, changed[{id, title_changed, acceptance{added,
removed}}]}, roles, integrations, nfr{added, removed}, scalars{key: {before, after}},
breaking[], summary{added, removed, changed, breaking}}`. Breaking kinds:
`entity-removed`, `entity-path-changed`, `field-removed`, `required-field-added`,
`field-type-changed`, `field-now-required`, `field-now-unique`, `enum-values-removed`,
`relation-removed`, `relation-changed`, `required-relation-added`, `feature-removed`,
`role-removed`, `locale-removed`, `field-tightened` (same type, a lower `max`, a higher `min`, or a bound where there was none: `{constraint, before, after}`; a text field without `min` counts as `min` 0). Upgrade flow: `new = parse(command, base=old)` →
`diff_specs(old, new)`.

## 7. Registration (for the integrator — not edited by L15)

Proposed `governance/engines.json` record:

```json
{"id": "requirements", "layer": "L15", "title": {"en": "Requirements & Specification Intelligence", "ar": "ذكاء المتطلبات والمواصفات"},
 "entrypoint": "engineering_os.requirements:engine", "health": "engineering_os.requirements:health",
 "actions": {"parse": {"side_effect": "none", "permissions": ["read:registry", "secrets:none"], "summary": "command or brief to gaie.spec/1"},
             "refine": {"side_effect": "none", "permissions": ["read:registry", "secrets:none"], "summary": "resolve open questions"},
             "validate": {"side_effect": "none", "permissions": ["secrets:none"], "summary": "validate a spec"},
             "diff": {"side_effect": "none", "permissions": ["secrets:none"], "summary": "spec change set for upgrades"},
             "acceptance": {"side_effect": "none", "permissions": ["secrets:none"], "summary": "structured acceptance checks"},
             "packs": {"side_effect": "none", "permissions": ["read:registry", "secrets:none"], "summary": "list domain packs"}},
 "supersedes": []}
```

Layer interfaces: `engineering_os.requirements:parse`, `:refine`, `:validate_spec`,
`:diff_specs`, `:acceptance_checks`; tests: `tests/test_requirements.py`.

## 8. Limitations (honest)

- **No LLM is called.** Understanding is lexicon matching over normalized tokens. Words that
  are not in a pack or in `_common.json` are invisible: a domain without a pack (library,
  clinic, school…) always ends in the `domain` question, and new entity types cannot be
  invented from free text.
- Arabic morphology is approximated: clitic prefixes and listed singular/plural forms only;
  no stemmer, no pronoun suffixes (`مهامها`), no dual forms unless listed.
- Field/feature ownership follows a few linking words; complex sentences, coreference
  ("its", «لها» far from the noun) and numbers inside prose (limits, quantities, dates) are
  not extracted. Field constraints come from the lexicon, not from the text.
- Negation is clause-scoped and lexical; double negation and sarcasm are not handled.
- Acceptance criteria are templates: they describe the HTTP behaviour a generated system must
  show, not business rules the owner did not state. Arabic criterion lines are hand-written
  for packs and templated for generated features.
- Paid services are never assumed: AI provider and paid integrations always need an answer.

What needs a model later (to be reported separately from deterministic results): extracting
entities and fields for domains without a pack, paraphrase and synonym coverage, resolving
references across sentences, turning prose business rules into acceptance criteria,
prioritizing features, and drafting new domain packs for human review. Any such step must
label its output as model-generated and pass the same `validate_spec` gate.
