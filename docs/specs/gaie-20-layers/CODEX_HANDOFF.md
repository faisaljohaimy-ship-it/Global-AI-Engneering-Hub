# Codex integration handoff

## Recovery checkpoint

| Item | State | Source |
|---|---|---|
| Central baseline | Integrated in `main` at `65c84fe784489f0b6dd77eaabbe11afd4bfaf13d` | [main](https://github.com/faisaljohaimy-ship-it/Global-AI-Engneering-Hub/commit/65c84fe784489f0b6dd77eaabbe11afd4bfaf13d) |
| Final integration | Active draft, checked through `5e6fc42c39d45634501fb8164d495d7e3a05c4c6` | [PR #31](https://github.com/faisaljohaimy-ship-it/Global-AI-Engneering-Hub/pull/31) |
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

## Resume

Fetch #31 and the Codex branch and compare both heads to the checkpoint before
editing. If #31 advanced, inspect concurrent paths before integrating it into the
Codex branch. Keep A–I results, J–O evidence, reviewer handoffs and the current
commit in the pull request. Keep private logs, agent output and credentials out of
Git. Take any final integration or production action only from its authorized release path.
