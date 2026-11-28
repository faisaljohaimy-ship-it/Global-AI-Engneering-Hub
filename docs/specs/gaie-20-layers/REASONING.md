# L13 — Advanced Engineering Reasoning

Status: implemented in `engineering_os/reasoning.py` (extends the existing planner;
no second engine). Tests: `tests/test_reasoning.py`, `tests/test_reasoning_cases.py`.
Shared rules: [CONTRACTS.md](CONTRACTS.md).

The engine reasons **only over the structured facts and evidence it is given**. It
does not read files, the network, the process environment or secrets, and it never
calls a model. Where a step would need model judgement, it returns a routing
decision from `model_router.select_model` and says that no call was made.

## 1. Determinism and receipts

Every output, including the original `plan`, `review_decision` and `root_causes`, carries:

```json
{"mode": "deterministic", "operation": "trade-off", "provider_calls": 0,
 "receipt": {"engine": "reasoning", "layer": "L13", "operation": "trade-off",
             "mode": "deterministic", "input_sha256": "…", "output_sha256": "…"}}
```

- `input_sha256` = SHA-256 of the canonical JSON of the action payload (sorted keys,
  compact separators, UTF-8, no NaN). For `review` the payload is
  `{"plan", "reviews", "verification"}`; for `root-causes` it is `{"observations", "dependencies"}`.
- `output_sha256` = SHA-256 of the output without `receipt`. `plan()` then adds its
  existing `plan_sha256` over everything else, so `plan_sha256` keeps its old definition.
- Operations that depend on time take an explicit `now` and record it
  (`evaluated_at`, or `planned_at` for `plan`). Same payload + same clock → same bytes.
- `verify_receipt(output, payload)` checks the hashes. `replay(action, payload, output)`
  recomputes the output at its recorded clock and returns `True` only if it is identical.
- A payload that is not canonical JSON (sets, NaN, objects) is refused with `ReasoningError`.

Receipts bind input to output. They do not authenticate whoever supplied the evidence.

## 2. Engine contract

`engineering_os.reasoning:engine(action, payload, ctx)` dispatches; `ctx` may carry
`now` and `credentials_present` (a list of environment variable *names*).
`engineering_os.reasoning:health()` runs a side-effect-free self check.
`reasoning.ENGINE_RECORD` is a ready record for `governance/engines.json` and validates
with `contracts.validate_engine(..., check_imports=True)`. Every action has side effect
`none` and permission `secrets:none`.

| Action | Function | Clock | Purpose |
|---|---|---|---|
| `plan` | `plan(request, now=)` | yes | wave schedule + evidenced alternatives (existing) |
| `review` | `review_decision(plan, reviews, verification, now=)` | yes | review/verification gate (existing) |
| `root-causes` | `root_causes(observations, dependencies)` | no | earliest observed failures (existing) |
| `strategy` | `select_strategy(request)` | no | quick / standard / deep, with the reason |
| `decompose` | `decompose(request)` | no | goal → milestones → tasks → planner nodes |
| `plan-goal` | `plan_goal(request, now=)` | yes | decompose, then the existing wave planner |
| `constraints` | `evaluate_constraints(request)` | no | hard constraints hold, soft constraints scored |
| `dependencies` | `analyze_dependencies(request)` | no | critical path, slack, ready, blocked |
| `rca` | `analyze_root_causes(request)` | no | evidence-weighted competing hypotheses |
| `counterfactual` | `counterfactual(request)` | no | what changes when an assumption flips |
| `uncertainty` | `detect_uncertainty(request, now=)` | yes | missing/stale/conflicting evidence |
| `perspectives` | `review_perspectives(request)` | no | architecture, security, quality, cost, operability |
| `validate-decision` | `validate_decision(request, now=)` | yes | evidence for every critical criterion |
| `trade-off` | `trade_off(request)` | no | weighted matrix + weight sensitivity |
| `route-model` | `route_model(request, credentials_present=, now=)` | yes | routing decision only |

All new requests carry `"schema_version": 1` and must have exactly the listed fields;
unknown or missing fields, booleans where numbers are expected, NaN/∞, duplicate ids,
unknown references and credential-shaped identifiers raise `ReasoningError`.
Identifiers are lowercase slugs (`[a-z0-9][a-z0-9_-]{0,79}`).

## 3. Strategies and adaptive depth

`select_strategy` takes `risk`, `complexity`, `novelty`, `reversibility` and
`evidence_coverage`, all in 0..1. The score is a fixed weighted sum:

| Factor | Weight |
|---|---|
| risk | 0.30 |
| complexity | 0.20 |
| novelty | 0.15 |
| irreversibility (1 − reversibility) | 0.20 |
| evidence gap (1 − evidence_coverage) | 0.15 |

Score ≥ 0.60 → `deep`, ≥ 0.30 → `standard`, otherwise `quick`. Hard triggers can only
raise the depth: `high_risk` (risk ≥ 0.8 → deep), `irreversible_and_risky`
(reversibility ≤ 0.2 and risk ≥ 0.5 → deep), `weak_evidence` (coverage ≤ 0.5 → standard,
or deep when risk ≥ 0.5) and `novel_problem` (novelty ≥ 0.8 → standard).

| Depth | `plan_max_depth` | Actions to run | Model steps |
|---|---|---|---|
| quick | 2 | constraints, validate-decision | — |
| standard | 3 | decompose, constraints, dependencies, trade-off, uncertainty, validate-decision | — |
| deep | 5 | standard + counterfactual, perspectives | independent-review (routed, not called) |

Example reasons produced by the code:

```
standard: weighted score 0.310 selects standard; largest contributors: irreversibility 0.100, risk 0.090
deep: weighted score 0.505 selects standard; escalated by high_risk (risk 0.85 >= 0.80),
      irreversible_and_risky (reversibility 0.10 <= 0.20 with risk 0.85 >= 0.50); ...
```

`detect_uncertainty(...)['critical_evidence_coverage']` is designed to be fed back as
`evidence_coverage`, so missing evidence deepens the reasoning automatically.

## 4. Operations

**Decomposition** — `{"goal", "milestones": [{"id", "depends_on", "tasks": [{"id", "depends_on",
"minutes", "risk", "novelty", "confidence"}]}]}`. A milestone dependency makes every task of
the dependent milestone wait for the prerequisite's *exit tasks* (tasks nothing else in
that milestone depends on). The output's `plan_nodes` are valid `plan()` nodes.
`plan_goal({"decomposition", "plan"})` takes a plan request **without** `nodes`, runs
`plan()`, and adds `waves_by_milestone` and the critical path. Ids are unique across
goal, milestones and tasks. Empty milestones and cycles are refused, and the cycle is
named (`Dependency cycle among tasks: a -> b -> a`, where `->` means "depends on").

**Constraints** — options carry `attributes` (boolean, number or slug). Hard and soft
constraints use `==, !=, <, <=, >, >=, in, not_in`; ordering needs numbers and types must
match. `infeasible` = some hard constraint fails. `undetermined` = an attribute a hard
constraint needs is missing; such an option is never silently passed. When an
undetermined option could still beat the selection, the status is `provisional` and it
appears in `needs_evidence`. The soft score is the satisfied weight divided by the total weight.

**Dependencies** — items `{"id", "depends_on", "minutes", "status": done|in_progress|todo|blocked}`.
The critical path runs over the remaining minutes (done = 0). Ties break by the smallest id.
The output also has slack per item, `ready` (todo items whose dependencies are done),
`blocked` (each item with the blocked items it waits on, transitively) and `status_conflicts`
(done/in-progress items waiting on unfinished work).

**Root-cause analysis** — reuses `root_causes` for the structural picture. Each
hypothesis `{"id", "node", "prior"}` is scored as
`logistic(logit(prior) + structure + Σ ±3·weight·reliability)`. The structural term is
+1.0 for an observed root, +0.5 for an unobserved node upstream of a root, −1.0 for
downstream of a failure, −1.0 for not upstream of any failure, and −2.0 for observed
passing. Log rules are **literal substring matches** (no regular expressions, so there is
no ReDoS risk), counted once per rule using the most reliable matching log, and reported
by line number only. Log text is never echoed. Credential-shaped log lines are refused, so
redact logs first. The conclusion is `leading` (supported, net evidence support ≥ 0.3,
score ≥ 0.7, margin ≥ 0.2), `contested` (rivals within 0.2: lists the competing hypotheses
and asks for discriminating evidence and direct observation of unobserved nodes) or
`insufficient_evidence`. Hypotheses with strong evidence on both sides are marked
`conflicting`. Each hypothesis reports `support`, `refutation`, `net_support` (support −
refutation, log-odds units) and `structural_score` (prior and structure only) next to its
`score`. The minimum net support (`MIN_SUPPORT` = 0.3, one fully reliable row of weight 0.1)
exists because structure alone can reach 0.7 (an observed root at prior 0.5 scores 0.731):
without it, one supporting row of negligible weight (1e-9) turned `insufficient_evidence`
into `leading` with the score unchanged. A leading score is therefore always above its
`structural_score` by the evidence it carries; the `weak_support` request names the three
values that fell short.
`causality_proven` is always `false`.

**Counterfactuals** — `{"assumptions", "metrics", "rules": [{"id", "when", "effects", "flags"}],
"gates", "flips": [{"id", "set"}]}`. The effects of fired rules apply `set`, then `add`,
then `multiply`, so rule order does not matter. Two rules that `set` one metric to
different values raise an error. Each flip reports changed metrics, gate transitions,
raised/cleared flags, the go/no-go verdict change and a one-line summary.

**Uncertainty** — claims `{"id", "type": requirement|assumption, "criterion", "critical",
"evidence_kinds", "max_age_seconds"}` and evidence `{"id", "claim", "kind",
"verdict": supports|contradicts|inconclusive, "confidence", "at", "sha256"}`. Status
precedence: conflicting → contradicted → covered → low_confidence → inconclusive →
stale → missing. Wrong-kind and future-dated evidence never count and are flagged.
`defaults_applied` is always `[]`. `can_proceed` requires every critical claim to be covered.

**Decision validation** — same evidence semantics, with `criteria` and `"criterion"` links.
`validated` only when every critical criterion is covered by fresh evidence of an accepted
kind with confidence ≥ `min_confidence`. Contradicting evidence rejects. At least one
critical criterion is required. Gaps in non-critical criteria become warnings.

**Multi-perspective review** — a fixed, documented catalogue of 19 checks over a fact
vocabulary (`reasoning.FACTS`; unknown or mistyped facts are refused). The policy
thresholds are reported in the output. A check whose facts are missing yields
`needs_evidence`, never a pass. Conditional facts (for example `auth_implemented`) are
required only when they apply. Verdict per perspective: `fail` (high/critical) >
`insufficient_evidence` > `concerns` > `pass`. `approved` is true only for `pass` or `concerns`.

**Trade-off** — values are min–max normalised per criterion (`direction`: higher|lower;
equal values score 1). Weights must sum to 1. For each criterion, one weight is varied
while the others are rescaled proportionally. Totals are linear in that weight, so the
exact flip point, the new winner and the full weight vector at the flip are reported. Only
strict overtakes inside [0, 1] count; a tie reached only at the boundary is not a flip.
`robust` is false when some flip lies within `robustness_margin`.

**Routing hook** — `{"step", "registry", "routing", "evidence"}`. A deterministic step
(any action name) returns `requires_model: false` and must not carry routing metadata. A
model step (`design-critique`, `hypothesis-generation`, `independent-review`,
`natural-language-summary`, `unstructured-log-interpretation`) calls
`model_router.select_model` and returns its decision with `model_called: false` and
`invocation: "not-performed"`. Credential presence is passed as a list of names and turned
into `{name: "present"}`, so secret values never reach the engine.

## 5. Worked examples (synthetic data, from the tests)

| Case | Result |
|---|---|
| SQLite vs Postgres for a small project-management demo, budget ≤ $10/month (simulated prices) | Postgres `infeasible` (demo-budget); SQLite selected, soft score 0.7. A hosted option with an unknown price is `undetermined`, so the result is `provisional`. |
| Trade-off for the same choice | SQLite 0.55 vs Postgres 0.45. The smallest flip is scalability 0.30 → 0.3636 (+0.0636), which makes Postgres the winner, so the result is not robust at margin 0.1. |
| Failing build: `npm-install` failed; ERESOLVE in the log; lockfile diff evidence | Candidate root `npm-install`. `lockfile-drift` leads (0.959). The registry outage is refuted by a successful fetch line; the compiler regression is downstream (0.027). |
| Skip integration tests before release | `go → no-go`. Blockers `contract-coverage` and `defect-risk` fail. The flip saves 2 hours, raises the escaped-defect estimate by 0.25 and raises the unverified-contract flags. |
| p95 latency requirement with no benchmark | `missing_evidence` plus `wrong_evidence_kind` (a review was supplied). `can_proceed: false`. With risk 0.6, the strategy escalates to `deep`. |
| Storage decision with no evidence | `rejected: within-budget: missing, write-throughput: missing`. |

## 6. Deterministic here vs what would need a model

| Deterministic (this module) | Would need a model (routed only, never called here) |
|---|---|
| scoring, thresholds, schedules, critical paths, cycles | proposing hypotheses, options or milestones that were not supplied |
| literal log-rule matching, evidence weighting | interpreting unstructured logs or stack traces |
| constraint, gate and counterfactual evaluation over declared rules | estimating the effects of a change that no rule models |
| fact-based perspective checks | reading code or design documents to derive the facts |
| evidence freshness, kind and confidence gates | judging whether evidence is genuine or relevant |
| weight sensitivity | eliciting weights or summarising trade-offs in natural language |

Model output, if ever produced by an approved runner, must arrive as new structured
evidence with its own receipt. It is never mixed into these deterministic results.

## 7. Limits

Figures in tests and examples are simulated. Scores are ranking weights, not calibrated
probabilities. Critical paths assume declared minutes, including for blocked items.
Receipts prove consistency, not truth. The CLI `engineering_os/intelligence.py` still
exposes only `reasoning-plan`, `reasoning-review` and `root-causes`; the new actions are
reachable through `reasoning.engine`.
