# L11 — Release Engine (acceptance Scenario G)

Status: implemented and tested on a synthetic repository (`engineering_os/release_engine.py`,
`tests/test_release_engine.py`, fixture `tests/fixtures/release/scenario_g.py`, evidence
`docs/evidence/gaie-20-layers/scenario-g.json`). Deterministic code only: no model, no network,
no provider call. The engine **never deploys, pushes, tags or publishes**. Its output is a
source-bound release record and the exact commands the owner would run.

It sits beside the existing read-only L11 pieces and does not replace them:
`scripts/verify_release.py` (run by `.github/workflows/release.yml` after the owner publishes),
the `master-release` adapter (`spec`, `provenance`, `eligibility` of a product's deployment
evidence through `sdk/engineering_sdk.py release`) and `skills/gaie-release`.

## 1. Acceptance criteria

A release of commit `C` as version `V` is **ELIGIBLE** only when every criterion holds.
Otherwise the decision is **REFUSED** with one refusal `{code, detail}` per failed check (all
checks run; the codes are stable).

| Id | Criterion | Refusal codes | Test (`tests/test_release_engine.py`) |
|---|---|---|---|
| G1 | The checkout is its own Git work tree root, is no partial clone (no promisor remote, `extensions.partialClone` or `partialCloneFilter`, checked before the index is read), defines no filter program, has no nested submodule, hides no index entry (`sdk.engineering_sdk.checkout_guard`; every Git call offline: no transport or lazy fetch, no global config, stdin closed) and has no uncommitted or untracked file. | `checkout-unsafe`, `dirty-tree` | `ScenarioG.test_g1_refused_for_a_dirty_or_unsafe_checkout` |
| G2 | `C` is a full 40-character lowercase SHA and equals `HEAD`. A given base is a proper ancestor of `C`; by default the base is the first parent. | `commit-invalid`, `commit-not-head`, `base-invalid`, `base-not-ancestor` | `test_g2_refused_unless_the_exact_full_sha_is_head` |
| G3 | Every required `(workflow, job)` of the profile has exactly one receipt for `C`, and it is `completed` / `success`. Receipts for other SHAs never count. | `receipts-missing`, `receipts-invalid`, `receipts-commit`, `job-receipt-missing`, `job-receipt-other-commit`, `job-receipt-ambiguous`, `job-failed` | `test_g3_refused_for_another_sha_a_missing_failed_or_ambiguous_job` |
| G4 | An owner authorization record names `C`, `V` and the planned tag, with `authorized_by: "owner"`. | `authorization-missing`, `authorization-invalid`, `authorization-commit`, `authorization-version`, `authorization-tag` | `test_g4_refused_without_owner_authorization_for_this_sha_and_version` |
| G5 | `V` is `MAJOR.MINOR.PATCH` (no pre-release or build suffix), greater than every recorded version (tags `<tag_prefix>X.Y.Z`, older changelog headings, an explicit `previous_version`), equal to the top `## <changelog_heading>V` heading and to the version file. | `version-invalid`, `version-not-increasing`, `version-changelog-mismatch`, `version-source-mismatch`, `previous-version-invalid`, `changelog-unreadable`, `version-source-unreadable`, `component-unreadable` | `test_g5_refused_for_a_version_that_is_invalid_not_greater_or_not_in_the_changelog` |
| G6 | An independent review gate result (§3.3) is bound to `C` (or its Git tree), every pass/fail signal in it passes, and its reviewer is not its producer. | `review-gate-missing`, `review-gate-invalid`, `review-gate-unbound`, `review-gate-commit`, `review-gate-failed`, `review-gate-self-review` | `test_g6_refused_unless_an_independent_review_gate_passed_for_this_commit` |
| G7 | A record is written only for an ELIGIBLE release, outside every Git work tree, never through a symbolic link (the file or any parent), never over an existing file, mode 0600. | `record-path-symlink`, `record-path-in-repository`, `record-exists` | `test_g7_record_never_written_through_a_link_inside_git_or_over_a_file`, `test_g7_record_is_private_exclusive_and_defaults_to_the_state_directory` |
| G8 | No push, tag, fetch, remote, network or non-Git process is ever started. Git runs only `rev-parse`, `status`, `ls-tree`, `merge-base`, `tag --list`, `cat-file` (plus `config --list` / `ls-files` inside `checkout_guard`), through the SDK's hardened runner. | (`ReleaseError` for any other Git subcommand) | `test_g8_no_push_tag_or_network_command_is_ever_executed` |
| G9 | `verify-record` is VERIFIED only while the record matches its own digest and everything it binds is unchanged; otherwise UNVERIFIED with reasons. | `record-unreadable`, `record-invalid`, `record-digest`, `record-claims-action`, `profile-changed`, `required-jobs-changed`, `checkout-unsafe`, `commit-not-head`, `dirty-tree`, `tree-changed`, `commit-unknown`, `base-changed`, `changelog-changed`, `version-source-changed`, `component-changed`, `receipts-changed`, `authorization-changed`, `review-gate-changed`, `tag-on-other-commit` | `test_g9_verify_record_goes_unverified_after_one_byte_and_back_after_restoring`, `test_g9_verify_record_after_head_moves_or_the_profile_changes` |

`test_g1_g8_eligible_with_complete_exact_sha_evidence` is the positive case. Each refusal case
changes one thing in a fresh copy of the synthetic repository; the expected code list is exact.

## 2. Actions

`engine(action, payload, ctx)`; payload fields are data, never commands. `profile` is `"hub"`
or a `gaie.release-profile/1` object.

| Action | Side effect | Payload |
|---|---|---|
| `eligibility` | none | `root, profile, version, commit` + optional `receipts, authorization, review_gate, base, previous_version, repository` |
| `plan` | none | as `eligibility` + `now`; returns the record body and the owner commands when ELIGIBLE |
| `record` | state-write | as `plan` + `out` (default `ctx.state_dir/releases/release-<V>-<sha12>.json`) |
| `verify-record` | none | `root, profile, record_path` + optional `receipts, authorization, review_gate` (their digests must match the record) |

Every action is at or below `workspace-write` (`EngineContract` test). `ENGINE_RECORD` has id
`release-engine`, layer `L11`; it is not yet in `governance/engines.json` (request
`scenario-g.json` to the registry owner).

Command line (from the repository root; exit 0 ELIGIBLE/VERIFIED, 1 REFUSED/UNVERIFIED, 2 input error):

```
python3 -m engineering_os.release_engine version
python3 -m engineering_os.release_engine eligibility|plan --version V --commit SHA \
    --receipts ci.json --authorization auth.json --review-gate gate.json [--profile hub|profile.json] [--root DIR]
python3 -m engineering_os.release_engine record ... --out FILE [--now YYYY-MM-DDTHH:MM:SSZ]
python3 -m engineering_os.release_engine hub-record --version V --commit MERGE_SHA --receipts ci.json \
    --authorization auth.json --review-gate gate.json --out FILE
python3 -m engineering_os.release_engine verify-record FILE [--profile hub] [--root DIR]
```

JSON input files are read without following a link, at most 1 MiB, duplicate keys refused.

## 3. Inputs

### 3.1 CI receipts (`gaie.ci-receipts/1`)

```json
{"schema": "gaie.ci-receipts/1", "commit": "<sha40>", "repository": "<owner>/<name>",
 "jobs": [{"workflow": ".github/workflows/verify.yml", "job": "test", "commit": "<sha40>",
           "status": "completed", "conclusion": "success", "run_id": 1, "job_id": 2, "url": "https://..."}]}
```

`commit` and `repository` at the top are optional; `url` and `run_attempt` per job are optional.
The values come from `gh api repos/<repo>/actions/runs?head_sha=<sha>&branch=main` and
`.../runs/<id>/jobs`. They are caller data: the engine checks completeness and consistency,
not that GitHub produced them. `scripts/verify_release.py` re-checks the real runs after the
owner publishes.

### 3.2 Owner authorization (`gaie.release-authorization/1`)

```json
{"schema": "gaie.release-authorization/1", "commit": "<sha40>", "version": "X.Y.Z",
 "tag": "<tag_prefix>X.Y.Z", "authorized_by": "owner",
 "reference": "where the owner's instruction is recorded (PR comment URL or quote id)",
 "at": "YYYY-MM-DDTHH:MM:SSZ"}
```

Exactly these fields. The record keeps `reference`, `at` and the SHA-256 of the whole record.
The record does not authenticate the owner: anyone can write this file. The authorization that
counts on GitHub is the owner publishing the Release.

### 3.3 Independent review gate result

Any JSON object, for example the L20 assurance gate output. The engine does not import the
assurance module; it reads the result as data:

- binding: one of `commit`, `subject_commit`, `subject`, `head` equal to `C`, or `tree` /
  `subject_tree` equal to the Git tree of `C`. None present: `review-gate-unbound`.
- signals: `passed` / `ok` (booleans), `gate` / `status` / `verdict` (`pass`, `passed`,
  `approve`, `approved` pass; `fail`, `failed`, `block`, `blocked`, `unverified`, `refused`
  fail), `failed` / `blocked` / `unverified` (must be empty lists). At least one signal; any
  unknown value is `review-gate-invalid`; any failing signal is `review-gate-failed`.
- `reviewer` equal to `producer`: `review-gate-self-review`.

The record keeps the SHA-256 of the result and the reviewer.

### 3.4 Release profile (`gaie.release-profile/1`)

`product`, `title`, `tag_prefix` (`v` or `<kebab-id>-v`), `changelog`, `changelog_heading`,
`version_file` (or null), `components` (`{id, path, key}`; `key` null for a one-line text file,
else a JSON key path) and `required_jobs` (`{workflow path: [job names]}`). All paths are plain
relative paths; files are read without following links. `hub_profile()` is the hub's own.

## 4. The record (`gaie.release-record/1`)

`version`, `planned_tag`, `status: "recorded, tag pending"`, `tag_created: false`,
`pushed: false`, `published: false`, `deployed: false`, `network_requests: 0`, `repository`,
`base_commit`, `tested_commit`, `tree` (`object_format`, `git_tree`, SHA-256 of
`git ls-tree -r -z --full-tree`), `changelog` (path, SHA-256, heading, version, notes SHA-256),
`release_notes`, `version_source`, `previous_version` (with its sources), `components`
(version and SHA-256 of each declaring file), `required_jobs` with their receipts,
`receipts_sha256`, `authorization`, `review_gate`, `profile_sha256`, `owner_commands`,
`rollback`, `recorded_at`, `claims_not_made` and `record_sha256` — the SHA-256 of the canonical
JSON of every other field (`engineering_os.contracts.sha256`).

`owner_commands` are argument vectors the engine never runs: save `release_notes` as
`RELEASE_NOTES.md`; `gh release create <tag> [--repo R] --target <C> --title "<title> <V>"
--notes-file RELEASE_NOTES.md --latest`; `gh release view <tag> --json
tagName,targetCommitish,isDraft,isPrerelease`; `git ls-remote --tags origin refs/tags/<tag>`.
`rollback` names the previous version, tag and (when the tag is present locally) commit, with
`gh release edit <previous tag> --latest` and `gh release delete <tag> --cleanup-tag --yes`.
Rolling back a release label does not revert commits on main or product pins.

## 5. This repository's own release

- Version source: `engineering_os/VERSION`, one line. Before this file the OS version was
  declared only in CHANGELOG headings. It holds `0.2.0` because the top heading already says
  `Engineering OS0.2.0`; **the number is the owner's choice (0.2.0 or 1.0.0)**. Change the file
  and the heading together: `HubRelease.test_os_version_source_matches_the_changelog_and_the_tag_shape`
  fails otherwise, and `python3 -m engineering_os.release_engine version` prints both.
- Profile `hub`: tag `engineering-os-v<V>` (the only shape `scripts/verify_release.py`
  accepts), changelog heading `Engineering OS`, required jobs = `verify_release.WORKFLOWS` of
  the running tree, components = `engineering_os/VERSION`, `sdk/VERSION`,
  `sdk/capabilities.json`, `.claude-plugin/plugin.json`, `templates/app-stdlib/manifest.json`,
  `packages/motion-engines/package.json`, `packages/digital-shows/package.json`,
  `governance/policies/gaie-routes.json`, `governance/policies/orchestration.json` and every
  versioned pack in `catalog/packs.json`.
- Sequence: merge PR #31 with a merge commit; wait until main CI for that merge commit is
  green; save the job results as `gaie.ci-receipts/1`; then, with HEAD at the merge commit,
  run `hub-record` with the owner's authorization and the review gate result, writing to
  private state outside Git. The record says "recorded, tag pending". The tag is created only
  when the owner publishes the GitHub Release (`owner_commands`), which starts `release.yml`.
- A record committed into the repository cannot contain its own commit SHA or the future merge
  SHA, so the hub record lives outside Git; a later backfill belongs to the next release.

## 6. Limits

- Receipts, authorizations and gate results are caller-supplied. Digests detect change and
  inconsistency; they do not prove who produced the data.
- The record proves content and intent, not publication. GitHub state (tags, Releases, runs)
  is never read by the engine.
- Required jobs for the hub are taken from the running tree's `scripts/verify_release.py`; run
  the engine from the commit being released.
- Evidence `scenario-g.json` is synthetic: produced by
  `python3 tests/fixtures/release/scenario_g.py --out docs/evidence/gaie-20-layers/scenario-g.json`,
  reproduced exactly by `ScenarioGEvidence`, bound to the SHA-256 of the engine and the fixture.
  It does not represent a release of this repository.
