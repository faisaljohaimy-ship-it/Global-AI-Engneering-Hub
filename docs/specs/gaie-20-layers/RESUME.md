# GAIE OS — resume page for the final integration

This page is the pick-up point for the last stretch of the twenty-layer work. It is
hand-written and updated at the end of every stage, then pushed. A new session resumes
from this page and the branch, not from any conversation.

Last updated: 2026-11-28, stage 2 (team at work).

## Where the work lives

| Item | Value |
|---|---|
| Single final integration branch | `claude/eager-feynman-kztjo4` |
| Pull request | #31 (draft), base `main` |
| Supersedes | #27 (`claude/gaie-20-layer-integration`) and #30 (`codex/master-security-hardening-20261128`) |
| Base | `main` at `65c84fe` |

#27 and #30 stay open only as sources. Nothing is merged into `main` from them directly:
their commits reach `main` through #31.

## Lineage of the branch

| Commit | What it is | Evidence |
|---|---|---|
| `0986919` | #27 at `b7097df` merged onto `main` `65c84fe`. Two Motion Lab test conflicts took `main`'s stricter ID-level checks, byte-identical to the reconciliation reviewed in #30 (`8a1bb60`). | 9 of 9 GitHub checks green on `0986919` |
| `7aedd71` | #27 at `7f77665` merged in: digital shows scene kit, cinematic edition 2, SEC-08 fix. Clean merge. | CI on this commit: see #31 |

Pending merge: the security hardening of #30 (`df35563`). Four files conflict with the
later wave-2 work (`engineering_os/control_plane.py`, `engineering_os/governor.py`,
`prompts/MASTER_BUILD.md`, `sdk/engineering_sdk.py`). Resolution keeps both sides; where
they disagree the stricter, fail-closed behaviour wins.

## Coordination with the earlier session

The session that built #27 was told on 2026-11-28 that #31 is the only integration
branch. Split of work:

- It keeps only what it already had in flight: the cinematic and digital-shows edition 2
  work (`engineering_os/video_pipeline.py`, `packages/digital-shows/`,
  `tests/test_digital_show*`, `tests/test_video_pipeline.py`), pushed to its own branch.
- Everything else listed under "Open items" is done here.
- Each new head of `claude/gaie-20-layer-integration` is merged into this branch. Check
  with `git fetch origin claude/gaie-20-layer-integration && git log --oneline HEAD..FETCH_HEAD`.

## Team at work (stage 2)

Each lane is one specialist role from `governance/agent-roles.json`, working in its own
git worktree on a local branch `gaie/r-<lane>` cut from the working base (this branch
plus the resolved #30 merge). A lane edits only the paths it owns; anything else goes
through a written request to the owner of that file. Lanes are merged here one at a
time after the gate (owned paths, secret scan, tests, `hub.py audit`), then pushed.
Local lane branches are not on GitHub until they are merged, so a lane that is not
listed as `done` below must be re-run from its brief if the machine is lost.

| Lane | Role | Scope |
|---|---|---|
| reg-engines | control-plane-integration-engineer | wave-2 engines reachable through `control_plane.invoke`, path fields, role grants |
| reg-layers | twenty-layer-architecture-engineer | wave-2 interfaces and tests appended to the layer registry, scenarios bound |
| assurance | independent-assurance-engineer | `engineering_os/assurance.py`, review receipts, the gate |
| scenario-g | github-integration-release-engineer | release engine, Scenario G test and evidence, the hub's own release record |
| release-prep | github-integration-release-engineer | changelog backfill, release gate list, SDK label, release checklist |
| sec-isolation | agent-isolation-security-engineer | SEC-07, SEC-12, measured isolation evidence |
| sec-findings | enterprise-security-privacy-engineer | SEC-10, private-mode finding, behavioural audit probes |
| agents-20 | adaptive-agent-orchestration-engineer | standing team policy, loader, specialist agent definition |
| master-docs | master-build-engine-engineer | manifest, loader and drift test for the two MASTER documents |
| motion-policy | motion-sdk-animation-engineer | purposeful-motion policy, validator, registry build rule |
| install | claude-code-integration-engineer | vendored pack, Scenario I test and evidence |
| ci | testing-self-healing-engineer | time limits, node tests in no workflow, positive isolation job, coverage guard |
| activation | knowledge-intelligence-integration-engineer | approved tools installed from their locks and run, regenerable receipt |

Independent reviewers (read-only, never the producer of what they review): three on the
#30 merge (authorization, isolation, merge quality) and two on the wave-2 engines
(build, upgrade, requirements; memory, healing, orchestration, reasoning).

Still to start: the port of motions from earlier branches (waits for the motion-policy
lane), the wiring pass (router, skills, prompts, `hub.py`), status documents, the final
review and the report.

Host limits that shape the run: 4 CPUs. The workflow runner allows two agents at once
on this host, so lanes run as direct background agents; each runs only its own targeted
tests, and the full suite runs once at the gate.

## What the mapping stage established

- No central team policy, MASTER manifest or motion-purpose policy exists on any branch.
- The wave-2 engines run for real through their own entry points but are not registered
  in the control plane, so those runs carry no grant, audit row or receipt.
- In GitHub CI the sandbox tier is `plain`: the sandbox, cage and wall tests are skipped
  there. Positive enforcement has been measured only on a host with user namespaces.
- `detectors.Sandbox` (SEC-07) was measured reading and writing outside its copy; only
  its environment scrub holds. `layers.verify` (SEC-12) runs tests with the caller's
  environment.
- None of the six priority tools is installed on a fresh machine; their dated receipts
  describe an earlier host.
- A release tag is created only when the owner publishes a GitHub Release whose target
  is the merge commit. Until then the truthful wording is "recorded, tag pending".

## Acceptance scenarios

Verified by running each test file alone on `0986919`.

| Scenario | Subject | State | Test |
|---|---|---|---|
| A | Master build | Passing | `tests/test_build_engine_e2e.py` (4), `tests/test_build_engine.py` (31) |
| B | Master upgrade | Passing | `tests/test_upgrade_engine.py` (45) |
| C | Video pipeline | Passing, 1 skip (sample media is kept outside Git) | `tests/test_video_pipeline.py` |
| D | Memory resume | Passing | `tests/test_memory_unified.py` (25) |
| E | Security governor | Passing | `tests/test_governor.py` (49) |
| F | Self-healing | Passing | `tests/test_self_healing_loop.py` (20) |
| G | Release engine | **Partial**: read-only pieces only, no acceptance test, spec or evidence | — |
| H | Adaptive orchestration | Passing, 1 skip (live metrics file is outside the repository) | `tests/test_orchestrator.py` (38) |
| I | Permanent Claude Code install | **Partial**: bootstrap mechanics pass, no acceptance test or proof at this head | `tests/test_gaie_factory.py` (20) |

The registry reports 20 of 20 layers `VERIFIED`, but it runs 35 of 99 test files and binds
no scenario. That figure is not yet a statement about scenarios A–I.

## Open items

Status values: `open`, `in progress`, `done` (with the commit).

| Id | Item | Status |
|---|---|---|
| pr30 | Review and merge the security hardening of #30 | in progress |
| motion-policy | Purposeful digital motion policy: one central policy file, validator, tests, registry build refuses a motion with no stated meaning | in progress |
| motion-port | Bring over motions that exist only on earlier branches (`claude/native-motion-engines-wip`, `feat/chromium-motion-stack`), as they are | open |
| agents-20 | Standing policy: a team of up to twenty specialist roles for every build and upgrade, bound to `governance/agent-roles.json` | open |
| master-central | `MASTER_BUILD` and `MASTER_UPGRADE` adopted, one canonical source with version and digest, drift test | open |
| registry | Register the wave-2 engines in `governance/engines.json` and `engineering_os/adapters.py`; append their interfaces and tests to `governance/layers.json`; bind scenarios A–I | open |
| assurance | L20 independent assurance module (`engineering_os/assurance.py`): the reviewer is never the producer | open |
| scenario-g | Release engine acceptance: spec, test on a synthetic repository, evidence | open |
| scenario-i | Install proof in a new Claude Code session and in an independent project | open |
| security | Remaining findings in `docs/evidence/gaie-20-layers/security-findings.json`; measured isolation | open |
| activation | Run the approved tools, skills and engines for real and record what ran on this host | open |
| status-docs | `docs/OPERATING_SYSTEM_STATUS.md`, `CHANGELOG.md`, `docs/GAIE_FACTORY.md` are stale | open |
| review | Independent engineering review of the whole branch | open |
| release | Version, changelog and release record; merge to `main` | open |
| report | Final report in Arabic and English with a scenario matrix checked by a test | open |

## How to pick up

```
git fetch origin claude/eager-feynman-kztjo4 && git checkout claude/eager-feynman-kztjo4
export GAIE_HOME=/tmp/gaie-home          # private state, never inside Git
export TMPDIR=/tmp                       # tests bind AF_UNIX sockets; long paths fail
python3 -m unittest discover -s tests    # the CI gate
python3 hub.py audit
python3 scripts/security_scan.py scan
python3 hub.py layers --verify           # writes receipts under $GAIE_HOME/layers
```

Receipts, memory checkpoints and ledgers are private state outside Git. They are not on a
fresh machine; run `hub.py layers --verify` again in each new environment.

## Boundaries that hold for this work

- The swarm stack is frozen: everything under `swarm/`, `.claude/agents/swarm-*.md`,
  `.claude/settings.json` and `tests/test_p3_*.py` (162 files, `swarm/phase3/FREEZE.json`).
  Do not edit, re-run or re-freeze it. The 1,000-agent experiment is cited, not repeated.
- `governance/layers.json` changes only additively.
- No deploys, no paid services, no skipped or weakened checks.
- A host limitation is recorded as a limitation, never as a pass.
