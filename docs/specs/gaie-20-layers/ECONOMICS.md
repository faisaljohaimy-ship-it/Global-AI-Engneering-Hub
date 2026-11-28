# L19 Engineering Economics & Resource Intelligence

Status: implemented in `engineering_os/economics.py` (the single entry point), tested by
`tests/test_economics.py` and `tests/test_economics_measured.py`. Measured inputs are in
`docs/evidence/gaie-20-layers/economics-baseline.json`. Nothing here calls a model, runs
an agent or touches the network. All logic is deterministic. AI-model reasoning plays no
part in any figure.

## 1. One engine, reused parts

There is no third economics engine. `engineering_os/economics.py` extends the existing
ledger accounting (`summarize`) and loads the swarm's reviewed code read-only, by path,
with `sys.path` restored afterwards (`_swarm`):

| Reused | What it supplies |
|---|---|
| `swarm/phase3/adaptive.py:next_wave` | base wave-size rules under `recommend_concurrency` |
| `swarm/phase3/economics.py:per_task, factory, project, RECIPES, STAND_IN` | per-task rows, cheapest qualifying configuration per size, wall-time projection, recipes |
| `swarm/phase3/context_budget.py:budget, _instruction_files, _split, _field` | instruction-file discovery (`@` imports, one level) and frontmatter parsing |
| `engineering_os/model_router.py:select_model` | `recommend_model` (unchanged facade) |

`summarize(ledger)` with schema 1 behaves as before. All earlier tests pass unchanged.

## 2. Units

| Type | Unit | Built from | Never |
|---|---|---|---|
| `Tokens` | `tokens` | a non-negative integer count | a float, money or quota |
| `Money` | `USD` | int, `Decimal` or decimal string (never a float) | inferred from tokens |
| `Seconds` | `seconds` | a finite non-negative number | |
| `Quota` | `quota:<name>` | number + plan unit name (such as `weekly-percent`) | mixed with another quota name, tokens or money |
| `Unknown` | the unit it stands for | `None` or `"unknown"` through `measured()` | 0, `False`, or ordered |

Rules, enforced by `UnitError` (a subclass of `EconomicsError` and `TypeError`):

- `+`, `-` and ordering only between the same unit. A plain number is not a unit: `Tokens(1) + 1`, `sum([...])` and `Tokens(1) == 1` raise.
- `*` and `/` by a dimensionless number keep the unit. Same unit `/` same unit gives a dimensionless `Decimal`. Any other quotient raises.
- The only bridge from tokens to money is `price(tokens, usd_per_million_tokens)`, with an explicit rate. `per_million_tokens(count, tokens)` is the only "per token" rate.
- An unknown spreads: `Tokens(5) + Unknown("tokens")` is unknown, and division by zero is unknown, not 0 or infinity. `bool()` of a quantity or an unknown raises, so `if tokens:` cannot treat missing data as zero.
- JSON: `{"unit": "tokens", "value": 4175}`. Money values are exact decimal strings, ratios are decimal strings and an unknown is `"unknown"` (`as_json`).

## 3. Ledger metrics

Schema 1 (unchanged) has actors `coordinator` and `worker`, and input tokens that include
cached input. Schema 2 adds:

- a `reviewer` role;
- `cache_write_tokens` on each request: an inclusive subset of input, priced at `cache_write_per_million_usd`, or `null` when not reported;
- a `purpose` on each request: `work`, `review`, `coordination` or `rework`;
- `defects` on each task (`null` means unknown);
- a top-level `period` (`started_at` and `ended_at`, asserted by the caller), or `null`.

`assess(ledger)` returns typed metrics:

| Metric | Formula | Unit | Unknown when |
|---|---|---|---|
| tokens per verified task | (input + output of all requests, retries and unverified work included) / verified tasks | tokens | accounting incomplete, any proxy count, or no verified task |
| verified tasks per million tokens | verified x 10^6 / all tokens | dimensionless | as above |
| consumption by role | input, cache read, cache write, output, total, share, call seconds and cost, per coordinator, worker and reviewer | tokens, seconds, USD | schema 1 reviewer; role absent from an incomplete ledger |
| cache | reads, writes, read share of input | tokens | writes: any request without `cache_write_tokens` |
| retries | requests with `attempt > 1`: count, tokens, estimated and charged cost | tokens, USD | never (attempt is required); cost if rates or receipts are missing |
| rework | requests with purpose `rework`, plus `rework` overheads (seconds, estimate) | tokens, seconds, USD | usage part in schema 1 |
| waste | retries ∪ rework requests; share of all tokens | tokens | schema 1 |
| defect rate | verified tasks with defects > 0 / verified tasks | dimensionless | any verified task with `defects: null` |
| development time | `period.ended_at - period.started_at` | seconds | no period |
| productivity | verified / development hours; an upper bound over the observed call span | verified tasks per hour | no period |
| quality-adjusted productivity | verified tasks without known defects x (1 - waste share) / development hours | verified tasks per hour | defects, waste or period unknown |
| money | estimated (supplied rates) and charged (billed line items) | USD | any missing rate or receipt, or incomplete accounting |
| subscription quota | not observable from a ledger | `quota:subscription` | always |

Quality adjustment can only lower the figure: with no defects and no waste it equals
plain productivity. This is tested.

## 4. Adaptive-concurrency recommender

`recommend_concurrency(waves, limits)` takes the waves measured so far, oldest first:
`{agents, duration_seconds, tasks_verified, tokens, conflicts, failures}`, with optional
`batch`, `limit_errors`, `peak_concurrent_agents`, `label` and `source`. `None` means
unknown. `tokens` must be tokens: money or a float raises `UnitError`. `limits` are
`{start, max_agents, max_batch, tokens_left, tasks_left, min_efficiency_gain}`.

The rules, in order:

1. No wave yet: `next_wave` starts at `start` agents.
2. Any limit error in the last wave: stop. This is inherited from `next_wave` (agents 0, the shrink to zero).
3. **GAIE:** any conflict in the last wave: halve the agents (to at least 1) and keep the batch, within the task and token caps.
4. `next_wave` decides. That covers halving under 90 percent verified, the host-peak rule, the 10 percent throughput rule, batch steps and the caps.
5. **GAIE:** if that decision adds agents, it stands only if verified tasks per million tokens rose above the previous wave's value times `(1 + min_efficiency_gain)`. Otherwise hold the agents and the batch. One wave alone cannot show an improvement, so it holds.
6. **GAIE:** whichever rule spoke, never more than `max_agents`.

The output has `agents`, `batch` and `reason` (one sentence), plus `rule`, `stop`, the
figures of the last two waves, `unknown_inputs` and the untouched `next_wave_base`.
Unknown conflicts do not block growth, but they are listed. Unknown tokens make the
efficiency unknown, so the agents hold. A grid property test checks that the agents
never grow on a conflict, on a limit error, or without an efficiency gain.

The baseline runs the recommender on measured waves. Each wave's tokens are worker plus
orchestrator tokens:

| Waves (source) | Efficiency, previous to last (verified tasks per million tokens) | Decision |
|---|---|---|
| c1 to s10 (phase 2) | 2.56 to 11.45 | grow to 20 (`grow-efficiency-improved`) |
| s10 to s20 | 11.45 to 14.13 | stays at 20 (host ceiling of 20) |
| s20 to s25 | 14.13 to 13.56 | batch 2, capped at 20 agents |
| team to team2 (phase 3 development lanes) | 4.97 to 2.23, 1 conflict, 2 failures | shrink to 8 (`conflict-shrink`) |

`waves_from_evidence` turns the swarm's stage and ladder documents and team documents
into waves. Stage files record no conflicts, so their conflicts are unknown. In a team
document, a lane rejected for changing paths outside its lane counts as a conflict, and
a lane whose own tests failed counts as a failure.

## 5. Estimates (never measurements)

Every estimate carries `"kind": "ESTIMATE"`, `"measured": false`, a label, its
assumptions and a low–high range.

- `estimate_scope(scope, evidence, assumptions)` covers `feature` (3 small and 1 medium task, the swarm's "one feature"), `mvp` (40 small, 12 medium and 3 large, the swarm's "one system") and `enterprise` (an assumed 10 MVPs). For each size, the tokens per task come from the cheapest measured configuration that verified at least 90 percent (`factory`).
  - Tokens: `recipe tokens x task multiplier x (1 + second-attempt share) / (1 - coordinator share)`. The default task multiplier is 0.5–2 (0.5–3 for enterprise). The coordinator share is 0.152–0.656, the lowest and highest measured in phase-2 stages of 10 or more agents. The second-attempt share runs from the chosen configurations' failure share (low) to the worst measured failure rate of those sizes (high, 0.4 from `l5r`).
  - Time: agent seconds from the measured agent minutes per task. Wall time comes from each size's measured tasks per minute (`project`), with the sizes run one after another.
  - Money: `"unknown"` unless reviewed rates are supplied. All input is priced at the uncached rate, an upper bound.
  - Validity: the measured tasks are generated stand-ins (a function, a module-sized feature, a fix in an existing system). Read the result as an order of magnitude for agent work of that shape, not as a quote.
- `estimate_infrastructure({months, components})` sums the supplied monthly USD ranges. A component with an unknown cost makes the total unknown. No provider price is built in.
- `estimate_maintenance(build, {share_per_year, years})` scales the build estimate. The default of 0.15–0.25 a year is a planning assumption, not measured here.
- `estimate_rework(build, {rework_share}, measured_waste_share=)` uses a ledger's measured waste share when one is given. Otherwise it uses the build's measured second-attempt share.

The baseline's estimates, in tokens: a feature is 72,606–715,925 (input plus output), an
MVP 1,132,774–15,637,560 and an enterprise system 11,327,748–234,563,407. Money is unknown
because no rate is supplied. For comparison, the real development lanes of phase 3
(`swarm/phase3/evidence/team.json`) each built one module with its tests for 68,019–505,643
tokens (median 149,463.5).

## 6. Measured inputs and the re-measurement

All figures below are cited from files in this tree. `measured_baseline()` reads them and
records each with its source path and field. The baseline document also stores the
SHA-256 of every source.

| Figure | Before → after | Source | Could it be reproduced here? |
|---|---|---|---|
| First-request context of a worker | 222,067 → 5,486 tokens (−97.53%) | `swarm/evidence/tool-audit.json` (median), `swarm/phase2/evidence/stages.json` s20 | **Cited only.** It is a host-reported size of the whole first request (host system prompt, tool schemas, connectors, worker definition). Measuring it needs live agents. |
| Input tokens per verified small task, 20 agents | 801,572 → 50,307 (−93.72%) | `swarm/evidence/ladder.json` s20, `swarm/phase2/evidence/stages.json` s20 | **Arithmetic reproduced** (input_total / verified gives the same numbers). Not re-measured. |
| Tasks per minute, 20 agents | 29.64 → 76.57 (×2.58) | same files | **Arithmetic reproduced to rounding** (29.64 and 76.58 from the rounded wall seconds). Not re-measured. |
| `swarm/phase2/RESULTS.md` table | 20 rows | against `stages.json` | All 20 rows agree on tasks a minute, input tokens, per-task tokens and cost units. |
| Coordinator, worker and cache split per stage | for example s20: worker 1,006,148 input (671,350 cache read, 334,656 cache write), coordinator 386,649, coordinator share 0.276 | `stages.json` | Read. Reviewer tokens and retries are not recorded, so they are unknown. |
| Development waves, conflicts and rework | team: 20/20 joined, 0 conflicts; team2: 13/16 joined, 1 conflict, 2 failures, 3 lanes repaired later | `swarm/phase3/evidence/team.json`, `team2.json` | Read. Rework tokens are unknown. |
| Coordinator machinery | gate 0.0478 s per call; ledger build of 2,000 records in 0.724 s | `swarm/phase3/evidence/coordinator-scale.json` | Read. No agent ran. |
| 1,000-agent run | — | `swarm/phase3/evidence/stages.json`, `swarm/phase3/RESULTS-FINAL.md` | **Pending (owned by the swarm session).** Not read. |

Re-measurement of this integrated tree (`context_footprint`). The method is characters / 4
and approximate. No tokenizer module (`tiktoken`, `tokenizers`, `transformers`,
`anthropic`, `litellm`, `sentencepiece`) is installed, and no Claude tokenizer is
available offline. Only repository files are counted:

| Always loaded by a session | Characters | ≈ tokens |
|---|---:|---:|
| `CLAUDE.md` | 937 | 234 |
| `AGENTS.md` (through `@AGENTS.md`) | 2,135 | 533 |
| Skill listing: name and description of 6 `.claude/skills/*` | 2,041 | 510 |
| Agent listing: name and description of 12 `.claude/agents/*` | 1,929 | 482 |
| **Total** | **7,042** | **1,760** |

Loaded on demand (skill bodies and agent definitions): 21,703 characters, about 5,425
tokens. The lean worker definition `swarm-light` is 817 characters, about 204 tokens.

Comparison: the tree contributes about 1,760 tokens to every session. The 5,486-token and
222,067-token first requests were host-reported whole requests on earlier trees. The
difference is host-controlled context, unknown offline. So the reductions are cited, not
re-proven.

## 7. Engine contract

`engine(action, payload, ctx)` returns a dict. `health()` returns `{ok, detail}` without
side effects. All actions have side effect `none` and need permissions `read:repo` and
`secrets:none`. The repository root is never taken from the payload; it is this checkout
or `ctx["root"]`.

| Action | Summary |
|---|---|
| `summarize` | aggregate a schema 1 or 2 ledger |
| `assess` | typed metrics with units and unknowns |
| `recommend-concurrency` | next agent count and batch from measured waves |
| `estimate-scope` | ESTIMATE for a feature, an MVP or an enterprise system |
| `estimate-infrastructure` | ESTIMATE from supplied monthly ranges |
| `estimate-maintenance` | ESTIMATE from a build estimate |
| `estimate-rework` | ESTIMATE from a build estimate |
| `context-footprint` | re-measure the repository context a session loads |
| `measured-baseline` | measured inputs with their sources |

CLI: `python3 -m engineering_os.economics baseline --date YYYY-MM-DD --out
docs/evidence/gaie-20-layers/economics-baseline.json [--check]`. `--check` exits 1 when
the file is stale. `python3 -m engineering_os.economics footprint` prints the footprint.

## 8. Limits

- Ledger receipts, actor completeness, defects and the development period are caller assertions, not authenticated provider exports.
- No model price is built in. Money is unknown unless rates or billed receipts are supplied. Subscription quota is never observable here.
- Context tokens are characters / 4, which undercounts non-ASCII (Arabic) text. The host's own system prompt, tools and connector instructions are not measured.
- Whether a host loads `CLAUDE.md` into subagents is not established here, so the lean worker's repository share is reported only as its definition size.
- Estimates rest on generated stand-in tasks and a single run per configuration. The enterprise recipe (10 MVPs) and the maintenance rate are assumptions.
- Phase-2 stage waves record no conflicts, retries or reviewer usage, so those stay unknown. Team-document lane states are matched by fixed phrases, and an unrecognised state makes the counts unknown.
- `docs/specs/nextgen-intelligence/validation.json` holds an older SHA-256 of `economics.py` and `tests/test_economics.py`. That earlier receipt is historical, and no test reads it.
- The 1,000-agent phase-3 run is pending in the swarm session and is not cited.
