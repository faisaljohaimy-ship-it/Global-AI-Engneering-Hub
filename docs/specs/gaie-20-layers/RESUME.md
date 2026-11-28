# GAIE OS — resume page for the final integration

This page is the pick-up point for the last stretch of the twenty-layer work. It is
hand-written and updated at the end of every stage, then pushed. A new session resumes
from this page and the branch, not from any conversation.

Last updated: 2026-11-28, stage 4 (lanes landing, all five reviews in).

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

Merged at `ff3368e`: the security hardening of #30 (`df35563`), resolved locally as `077a934`, `79a5e8d`, `30c7bfd`, `e3f4c8d`. Four files conflict with the
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
| assurance | L20 independent assurance module (`engineering_os/assurance.py`): the reviewer is never the producer | done (`121bab9`): assign/record/verify/gate with source-bound receipts; control-plane registration in wave 2 |
| scenario-g | Release engine acceptance: spec, test on a synthetic repository, evidence | done (`347bd86`): 22 tests, never tags or pushes, evidence reproducible; registration in wave 2 |
| release-prep | github-integration-release-engineer | changelog backfill, release gate list, SDK label, release checklist |
| sec-isolation | agent-isolation-security-engineer | SEC-07, SEC-12, measured isolation evidence |
| sec-findings | enterprise-security-privacy-engineer | SEC-10, private-mode finding, behavioural audit probes |
| agents-20 | Standing policy: a team of up to twenty specialist roles for every build and upgrade, bound to `governance/agent-roles.json` | done (`823e6b5`): policy file, standalone loader, orchestrator reads its limits from it, specialist agent definition; router/skills wiring in wave 1 |
| master-docs | master-build-engine-engineer | manifest, loader and drift test for the two MASTER documents |
| motion-policy | Purposeful digital motion policy: one central policy file, validator, tests, registry build refuses a motion with no stated meaning | done (`f95b85e`): 47 purposeful, 37 legacy-unclassified pinned, 400 reference, 156 index, 0 violations |
| install | claude-code-integration-engineer | vendored pack, Scenario I test and evidence |
| ci | testing-self-healing-engineer | time limits, node tests in no workflow, positive isolation job, coverage guard |
| activation | Run the approved tools, skills and engines for real and record what ran on this host | done (`867aebf`): 5 of 6 tools ran from their locks, Headroom 71% lossless reduction, 33/33 engine calls; receipt regenerated at the final commit |

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

## Restart record

- 08:36Z: every lane of the first launch stopped on a model usage limit, nearly all before
  writing anything. Only the motion-policy lane left files (uncommitted, unreviewed).
- Lane briefs are kept outside Git in the session scratchpad (`briefs/lanes/<lane>.md`),
  so a relaunch does not depend on the conversation. If the machine is lost, the briefs
  are lost too: the scopes in the "Team at work" table above are the source to rewrite them.
- Relaunched with 18 agents at once: the 13 engineering lanes and the 5 independent
  reviews. Motion port and status documents start as lanes finish.
- Each lane is merged here and pushed as soon as it passes the gate; no lane waits for
  the others.

## Independent review register

Reviewer findings JSON is kept in the session scratchpad (`reviews/<key>.json`) with the
proofs of concept. Each finding is fixed by a lane that did not review it, then re-checked.

| Review | Verdict | Findings | Fixed by |
|---|---|---|---|
| pr30-authz | approve-with-fixes | F1 medium (SDK `checkout_guard` bypass via submodule config runs a planted filter during `master-release.eligibility`), F2 low (read-only memory actions create a lock or migrate), F3 low (registered-project rule depends on wording) | review-fixes; F2 journal half: sec-findings |
| pr30-merge-quality | approve-with-fixes | nothing lost or weakened by the merge; F1/F2 low (SEC-09 and SEC-11 probes do not exercise the real path), F3/F4 low (stale docs) | sec-findings, sec-isolation, reg-engines, review-fixes |
| w2-memory-heal-orch | approve-with-fixes | **H1 high** (self-healing reports "repaired" while its patch adds a new defect), 5 medium (journal has no lock; secret filter misses keys next to Arabic letters; reviewer-is-producer check ignores history; unbounded test log; zero-evidence root cause reported as supported), 7 low | w2-fixes (H1, L2, M3, M5, L6, L3, L5), sec-findings (M1), review-fixes (M2, L7), sec-isolation (M4, L1, L4) |
| pr30-isolation | approve-with-fixes | strict sandbox held against every direct escape tried (sockets, files, env, /proc, fds, setuid, Git pointer); 4 medium: lazy-fetch config runs a program during the hardened Git check (SEC-09 status was wrong), a strict child can plant a Git config that runs later on the host, workspace-run blocks peers, the upgrade path runs hostile tests unsandboxed (same cause as SEC-07); 3 low | isolation-fixes (F1-F4, F6, F7, build part of F5), sec-isolation (upgrade part of F5), sec-findings (SEC-09 probe) |
| w2-build-upgrade | **block** | injection through spec fields, CSRF, session and password storage held; **3 high**: generated app's link routes ignore ownership/delete permission (a member locked out a manager), read-only upgrade audit executes target SQL so `ATTACH` writes files anywhere, WAL-mode databases are corrupted by the upgrade; 8 medium (sub-resource read bypass, two-hop scoping, mutable principal, acceptance criteria and NFRs reported passed without being exercised, detectors touch the original target, breaking requests reported met, negated locales ignored); 4 low | build-fixes (W2-BU-*, W2-RQ-*), upgrade-fixes (W2-UP-*) |

All findings predate the security merge; none was introduced by it. The release is blocked
until the 4 high findings (H1, W2-BU-01, W2-UP-01, W2-UP-02) are fixed and re-checked by
their reviewers.

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
| pr30 | Review and merge the security hardening of #30 | merged into this branch (`ff3368e`); independent review in progress |
| motion-policy | Purposeful digital motion policy: one central policy file, validator, tests, registry build refuses a motion with no stated meaning | done (`f95b85e`) |
| motion-port | Bring over motions that exist only on earlier branches (`claude/native-motion-engines-wip`, `feat/chromium-motion-stack`), as they are, each with a stated meaning and a fresh browser proof | in progress |
| agents-20 | Standing policy: a team of up to twenty specialist roles for every build and upgrade, bound to `governance/agent-roles.json` | done (`823e6b5`): policy file, standalone loader, orchestrator reads its limits from it, specialist agent definition; router/skills wiring in wave 1 |
| master-central | `MASTER_BUILD` and `MASTER_UPGRADE` adopted, one canonical source with version and digest, drift test | done (`157d8d1`; pinned 1.1.0 in `daacfa6`, merged with wiring-1 in `8800176`) |
| registry | Register the wave-2 engines in `governance/engines.json` and `engineering_os/adapters.py`; append their interfaces and tests to `governance/layers.json`; bind scenarios A–I | open |
| assurance | L20 independent assurance module (`engineering_os/assurance.py`): the reviewer is never the producer | done (`121bab9`): assign/record/verify/gate with source-bound receipts; control-plane registration in wave 2 |
| scenario-g | Release engine acceptance: spec, test on a synthetic repository, evidence | done (`347bd86`): 22 tests, never tags or pushes, evidence reproducible; registration in wave 2 |
| scenario-i | Install proof in a new Claude Code session and in an independent project | open |
| security | Remaining findings in `docs/evidence/gaie-20-layers/security-findings.json`; measured isolation | in progress: regenerated after the sec-isolation, sec-findings and isolation-fixes merges (`d9c84ef`): open 2 (SEC-16, SEC-17, low), fixed 10 including SEC-07, SEC-09 and SEC-12 |
| activation | Run the approved tools, skills and engines for real and record what ran on this host | done (`867aebf`): 5 of 6 tools ran from their locks, Headroom 71% lossless reduction, 33/33 engine calls; receipt regenerated at the final commit |
| status-docs | `docs/OPERATING_SYSTEM_STATUS.md`, `CHANGELOG.md`, `docs/GAIE_FACTORY.md` are stale | done for the status documents, README and the final report skeleton (merge `2c0667f`); `CHANGELOG.md` untouched |
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
