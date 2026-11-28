# Codex integration handoff

## Recovery checkpoint

| Item | State | Source |
|---|---|---|
| Central baseline | Integrated in `main` at `65c84fe784489f0b6dd77eaabbe11afd4bfaf13d` | [main](https://github.com/faisaljohaimy-ship-it/Global-AI-Engneering-Hub/commit/65c84fe784489f0b6dd77eaabbe11afd4bfaf13d) |
| Final integration | Active draft, synchronized through `d1d7e43da2b49035a35df1a2d64ac520204efe0c` | [PR #31](https://github.com/faisaljohaimy-ship-it/Global-AI-Engneering-Hub/pull/31) |
| Source PRs #27, #30 and #26 | Their observed heads are ancestors of the integration branch. Claude continues to own the cinematic edition and current core fixes. | [#27](https://github.com/faisaljohaimy-ship-it/Global-AI-Engneering-Hub/pull/27) · [#30](https://github.com/faisaljohaimy-ship-it/Global-AI-Engneering-Hub/pull/30) · [#26](https://github.com/faisaljohaimy-ship-it/Global-AI-Engneering-Hub/pull/26) |
| Source PR #25 | Next-generation baseline is present. The observed #25 tip diverges from #31. Review its remaining commits with the integration owner. | [#25](https://github.com/faisaljohaimy-ship-it/Global-AI-Engneering-Hub/pull/25) |
| Shared Context7 | In progress in #32. Its owner controls the policy, Claude configuration, shared prompts and registry. | [PR #32](https://github.com/faisaljohaimy-ship-it/Global-AI-Engneering-Hub/pull/32) |
| Codex Context7 | Scoped disabled profile already present on `codex/final-engineering-acceleration` at `98ba0616176509f01fe1ef904661384ab869bf05`. The native CLI dispatched both permitted tools to a local synthetic fixture and refused a third. | [Profile commit](https://github.com/faisaljohaimy-ship-it/Global-AI-Engneering-Hub/commit/98ba0616176509f01fe1ef904661384ab869bf05) |
| Hosted security | Verified exact integration SHA `5e6fc42` for the Governor isolation job. This job requires the full tier and fails on skipped isolation cases. | [Run 46144348367](https://github.com/faisaljohaimy-ship-it/Global-AI-Engneering-Hub/actions/runs/46144348367) |
| Release | Pending latest-head suite, remaining integration, independent review and owner's gates. | [Release checklist](RELEASE_CHECKLIST.md) |

## Ownership

Codex works on `codex/final-engineering-acceleration` and opens a handoff pull request
against `claude/eager-feynman-kztjo4`, the head branch of #31. Codex owns the project
skill adapters under `.agents/skills/gaie-*`, native agent adapters under
`.codex/agents/gaie-*.toml`, host compatibility tests under `tests/codex`, and the
new Codex verification scripts. The existing optional
`integrations/context7-codex` profile is the Codex native transport integration.

Use the central [resume record](RESUME.md) for Claude's lane ownership and the
[final report](FINAL_REPORT.md) for release integration. Keep edits to central
prompts, layer bindings, security fixes, shared Context7 and cinematic source in
their existing lanes. The private orchestration checkpoint tracks the Codex lane
leases and stays outside Git.

## Applicable acceptance

| Scenario | Acceptance for this handoff |
|---|---|
| I | A fresh Codex runtime discovers repo-scoped skills and loads the root instructions. Validate real model invocation separately. Claude Scenario I uses its existing installer and receipts. |
| J | Record capability evidence per engine and per host from actual invocation. Full model-backed parity remains open until both hosts have live results. |
| K | The Codex projection detects drift in canonical skills and versioned MASTER sources. Both engines follow the same MASTER policy. |
| L | The native Codex roster discovers the specialist and verifier adapters. Build and upgrade resolve the central twenty-role plan. Record actual staffing separately from the plan. |
| M | The disabled Codex client permits only the two Context7 documentation tools and agrees with the shared policy after #32 lands. Live service verification requires the approved Codex credential and existing free entitlement. |
| N | Existing central motion policy and tests continue to apply from both engines. Use the purposeful-motion validator and the native fixture suites. |
| O | A synthetic checkpoint survives both directions between the two engine-facing installations with digest and project checks. Fresh model-session recovery is separate. |

## Install and verify

Open the trusted GAIE hub checkout in Codex. The native six skills under
`.agents/skills` and two agent adapters under `.codex/agents` are project-scoped.
Use `gaie-master-router` for an owner's command. Its Codex entry point preserves
the canonical route, with Codex-owned write-branch suggestions.

```sh
python3 scripts/gaie_codex_bootstrap.py check
python3 -B -m scripts.gaie_codex_route -- 'ابنِ نظامًا جديدًا'
python3 -B -m scripts.gaie_codex_route -- 'طور سديد بالكامل'
python3 -m unittest discover -s tests -p '*codex*.py'
python3 scripts/verify_gaie_checkpoint_compatibility.py
```

On a host that blocks network access for the verifier process, run
`python3 -B scripts/verify_gaie_native_codex.py --reviewed-checkout <hub>`
against the reviewed checkout and trusted local Codex CLI. It creates temporary
state, disables MCP before opening a fresh thread, and reports source hashes
and discovery of the native roles. The verifier does no model turns.

On managed hosts with a mount marker below the default temporary root, pass
`--temp-dir` with an existing private root outside Git to the checkpoint check.
For shared skill updates, use `python3 scripts/gaie_codex_bootstrap.py render <skill>`
to generate the expected file, then review its diff before replacing the tracked
projection. MASTER version and digest checks remain in the central manifest and
test suite. The Codex adapters read the canonical policy at task time.

Build and upgrade use `gaie_specialist` with roles and grants from the central
staffing policy. Cap waves by both the roster plan and observed host capacity.
Use `gaie_verifier` only in an independently established read-only host session
with network and approval escalation disabled. These settings are inherited
from the parent Codex session. Use the canonical governed audit path when it
provides the required boundary, or report the review blocked.

## Verified results and open gates

| Item | Result |
|---|---|
| Native discovery | Fresh Codex CLI 0.172.0-alpha.2 discovered six repo skills and both custom roles. A fresh ephemeral read-only thread loaded `AGENTS.md`. The test made zero model calls. |
| Codex route | The synthetic worktree test accepts a verified `codex/` write plan and refuses a verified foreign write worktree. Read-only audit, unspecified targets, and gated release preserve the canonical decisions. The BILTIX and portfolio aliases need their exact private repository mappings. |
| Shared policy | Six skill projections match source digests. The 100-test MASTER, team and purposeful motion subset passed. The standing roster is still twenty central roles. |
| Context7 | Native CLI tests dispatched the two allowed tools to a synthetic loopback server and refused a third. The adapter matches the policy staged in #32. Hosted Codex credentials and tools are unverified. |
| Build and upgrade | At `5e6fc42`, Scenario A passed 4/4 with the pinned Playwright 1.65.1 browser and an independent bilingual Python/SQLite application. Scenario B passed 50/50 in the same network-isolated lab. |
| D–I and cross-cutting policy | At `5e6fc42`, 279 cases ran across memory, governor, healing, release, orchestration, install, layer, MASTER, motion and team suites. Four documented host-dependent cases were skipped. |
| Checkpoint | Two SHA-256-checked handoffs between the hub and installed Claude memory CLIs over synthetic data. Wrong digest and wrong project were refused. Each leg used a fresh Python process. |
| Motion | 35 Python and 70 JavaScript checks passed. Chromium rendered all 14 Digital Show scenes in Arabic and English with 392 frame hashes, zero page errors and zero external requests. No GPU host or real mobile-device result was recorded. |
| Cinematic | At `2e6dd11`, the offline pipeline rendered and decoded a 14-second bilingual 640×360 MP4 and a mobile derivative. The pipeline output passed 21/22 media checks. FFmpeg 7.1.5 omitted BT.709 transfer and primaries tags. A metadata-only remux passed 22/22 with identical decoded audio and video. Claude retains ownership of the pipeline fix and rerun. |
| Release | Readiness depends on shared lane closure, the latest exact-head suite, independent integration review and owner approval. The full isolation job now gates release at the integration base. [Codex handoff #33](https://github.com/faisaljohaimy-ship-it/Global-AI-Engneering-Hub/pull/33) targets the head of #31. |

The read-only merge check for `d1d7e43` plus Context7 head `4878539` found
one conflict in the source-bound Scenario I receipt. Regenerate the receipt
after the shared Context7 owner integrates that work. Keep the conflict
resolution in #31. [Context7 PR #32](https://github.com/faisaljohaimy-ship-it/Global-AI-Engneering-Hub/pull/32)

At `5e6fc42`, 22 registered engines passed `hub.py engine-health`, and the
twenty layers mapped 115 distinct test files. The activation receipt recorded
33 historical calls across 18 engines and five optional tools. The capability
registry listed 127 discovered, 22 reviewed, one approved and one tested.
It had no project-verified entries. These receipts describe their captured
hosts and source revisions.

The local source-bound L01 verifier reported 3/5 test files passing on the
managed host, with failures in the layer and governor suites. The positive
full-tier isolation receipt comes from GitHub, on the reported source revision.

Six distinct Codex subagents ran concurrently at peak, with a coordinator
separately. The central twenty-role plan did not determine the actual worker count.
This run added no paid services. Per-worker token and subscription credit totals
were unavailable. Full live cross-engine parity remains unmeasured.

## Resume

Fetch #31 and the Codex branch and compare both heads to the checkpoint before
editing. If #31 advanced, inspect concurrent paths before integrating it into the
Codex branch. Keep A–I results, J–O evidence, reviewer handoffs and the current
commit in the pull request. Keep private logs, agent output and credentials out of
Git. Take any final integration or production action only from its authorized release path.
