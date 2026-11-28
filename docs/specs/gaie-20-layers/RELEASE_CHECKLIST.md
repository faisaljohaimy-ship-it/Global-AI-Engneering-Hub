# GAIE OS — post-merge release checklist

The steps after PR #31 is approved, in order. A hub release is two things: the merge
of PR #31 into `main`, and a published GitHub Release whose new tag sits on that exact
merge commit. `.github/workflows/release.yml` only verifies; it creates no tag, Release
or asset.

Status until the owner publishes the Release: **recorded, tag pending**. Do not write
"released" anywhere before step 8 shows a successful provenance run.

```sh
REPO=faisaljohaimy-ship-it/Global-AI-Engneering-Hub
VERSION=X.Y.Z            # the owner's choice, e.g. 0.2.0 or 1.0.0
TAG=engineering-os-v$VERSION
```

## The tag shape

Exactly `engineering-os-v` followed by three dot-separated numbers
(`scripts/verify_release.py` checks `engineering-os-v[0-9]+\.[0-9]+\.[0-9]+`).
Rejected, and leaving a failed "Release provenance" run behind if published:
`engineering-os-v1.0.0-rc.1`, `v1.0.0`, `engineering-sdk-v1.0.1`. The Engineering SDK
(label 1.0.1) ships inside the OS release and gets no tag of its own.

```sh
python3 -c "import re,sys;sys.exit(not re.fullmatch(r'engineering-os-v[0-9]+\.[0-9]+\.[0-9]+',sys.argv[1]))" "$TAG" && echo ok
grep -m1 '^## Engineering OS' CHANGELOG.md   # must name the same $VERSION
```

## Merge sequence

1. **Mark PR #31 ready.** GitHub does not merge a draft.
   `gh pr ready 31 --repo "$REPO"` (or "Ready for review" on the PR page).
2. **Merge with a merge commit, never squash or rebase.** Evidence files cite commit
   SHAs of the branch; a squash or rebase leaves them out of `main`'s history. Every
   tagged release commit so far is a two-parent merge. Pin the exact reviewed head:
   ```sh
   HEAD_SHA=<final reviewed head of PR #31>
   gh api -X PUT "repos/$REPO/pulls/31/merge" -f merge_method=merge -f sha="$HEAD_SHA"
   ```
3. **Record the merge SHA** and check it has two parents:
   ```sh
   MERGE_SHA=$(gh api "repos/$REPO/pulls/31" --jq .merge_commit_sha)
   gh api "repos/$REPO/commits/$MERGE_SHA" --jq '[.sha, (.parents | length)]'
   ```
4. **Push nothing else to `main` until every run at `$MERGE_SHA` has finished.** The
   required workflows cancel in-progress runs per ref; a second push cancels the merge
   commit's runs, and that commit can then never pass the release check.
5. **Check the main-push runs** at the merge commit:
   ```sh
   gh api "repos/$REPO/actions/runs?head_sha=$MERGE_SHA&branch=main&per_page=100" \
     --jq '.workflow_runs[] | [.path, .event, .status, .conclusion, .updated_at] | @tsv'
   ```
   Required: `verify.yml`, `operating-system.yml`, `security.yml`,
   `dependency-audit.yml`, `motion-cross-browser.yml` and `nextgen-intelligence.yml`,
   each `push`, `completed`, `success`.

## The step left for the owner

6. **Publish a GitHub Release with a new tag `$TAG` targeted at `$MERGE_SHA`.**
   Publishing creates the tag and starts `release.yml`. A pushed tag alone or a draft
   Release does not start it.
   - Web: Releases, Draft a new release, Choose a tag, type `$TAG`, "Create new tag on
     publish"; Target: the commit `$MERGE_SHA` from "Recent commits" (not the branch
     `main`, not the PR head); title `Engineering OS v$VERSION — <summary>`; notes
     from the CHANGELOG entry; "Set as a pre-release" unchecked; "Set as the latest
     release" checked; Publish.
   - Or on the owner's machine:
     ```sh
     gh release create "$TAG" --repo "$REPO" --target "$MERGE_SHA" \
       --title "Engineering OS v$VERSION — <summary>" --notes-file <notes.md> --latest
     ```
7. **Publish within 24 hours of the dependency-audit run** at `$MERGE_SHA` (its
   `updated_at` in step 5). If that window has passed and `main` still points at
   `$MERGE_SHA`, run it again, wait for success, then publish:
   `gh workflow run dependency-audit.yml --repo "$REPO" --ref main`.
   Once `main` has moved, the merge commit cannot get a fresh run.

Do not tag the PR head: it is only an ancestor of `main` after the merge and has no
main-push runs, so the check fails with "Missing required main push workflow".

Optional pre-check, as done for v0.1.0 and v0.1.1: create the tag on `$MERGE_SHA`,
run "Release provenance" by hand, then publish the Release from the existing tag.

```sh
git fetch origin && git tag -a "$TAG" "$MERGE_SHA" -m "Engineering OS v$VERSION"
git push origin "refs/tags/$TAG"
gh workflow run release.yml --repo "$REPO" -f tag="$TAG"
```

## What release.yml then verifies

One job, "Verify published engineering release provenance", 5-minute limit,
permissions `contents: read` and `actions: read`. `scripts/verify_release.py`:

- the tag matches the shape above;
- the tag resolves to a commit, and that commit is an ancestor of `origin/main`;
- for each required workflow, the latest run at that commit on `main` in this
   repository (event `push`; for `dependency-audit.yml` also `schedule` or
   `workflow_dispatch`) is `completed` with `success`, and the dependency audit is at
   most 24 hours old;
- in each of those runs, every required job is present exactly once and succeeded:

   | Workflow | Required jobs |
   |---|---|
   | `.github/workflows/verify.yml` | `test`, `motion in Chromium` |
   | `.github/workflows/operating-system.yml` | `operating system and motion unit tests`, `fresh Chromium and Motion Studio runtime evidence` |
   | `.github/workflows/security.yml` | `Tracked secrets and Python execution hazards` |
   | `.github/workflows/dependency-audit.yml` | `Audit exact tracked npm locks` |
   | `.github/workflows/motion-cross-browser.yml` | `Motion Studio in firefox`, `Motion Studio in webkit` |
   | `.github/workflows/nextgen-intelligence.yml` | `Original camera motions in Chromium` |

It uploads the Actions artifact `engineering-release-provenance-<run_id>` (30-day
retention) holding `schema_version`, `tag`, `commit`, `main_ancestor`,
`verified_at_utc`, `workflows` (workflow, run_id, url, jobs) and
`product_deployment_performed: false`.

8. **Check the result:**
   ```sh
   gh api "repos/$REPO/actions/workflows/release.yml/runs?per_page=5" \
     --jq '.workflow_runs[] | [.id, .event, .head_branch, .head_sha, .conclusion, .html_url] | @tsv'
   gh api "repos/$REPO/releases/latest" --jq '[.tag_name, .target_commitish, .prerelease]'
   ```
   Expected: event `release`, head_branch `$TAG`, head_sha `$MERGE_SHA`, conclusion
   `success`; the latest Release is `$TAG`, not a pre-release.

## Post-release backfill

9. **Save the provenance JSON within 30 days.** It is only an Actions artifact; it is
   never attached to the Release. Keep it in private state outside Git:
   ```sh
   RUN_ID=<release.yml run id from step 8>
   DEST="${GAIE_HOME:-$HOME/.gaie}/releases/$TAG"
   mkdir -p "$DEST" && gh run download "$RUN_ID" --repo "$REPO" \
     --name "engineering-release-provenance-$RUN_ID" --dir "$DEST"
   ```
10. **Write the tag, `$MERGE_SHA` and the release.yml run URL** into the PR #31 thread
    and the `release` row of `docs/specs/gaie-20-layers/RESUME.md`. Any in-repo
    backfill is a later commit, so it belongs to the next release, as was done for
    v0.1.3. Only then change "recorded, tag pending" to "released as `$TAG` at
    `$MERGE_SHA`".
