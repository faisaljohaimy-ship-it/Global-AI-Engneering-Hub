---
name: gaie-release
description: GAIE Release Engine — safely release or deploy a specific project after identity, permission and quality checks. Use when the owner asks to release, deploy, publish or ship a project («انشر سديد», «أطلق», "deploy Sadeed", "release"), or when the router returns engine RELEASE.
argument-hint: "[project]"
---

Production changes need the owner's explicit authorization in this conversation for
this project and this commit. A general instruction to upgrade is not authorization
to deploy. If the router lists `release` under `prohibited`, stop.

1. If no router plan is in context, run `gaie-master-router` first; continue only
   when it returns `engine: RELEASE` with exactly one resolved target.
2. Verify identity: the repository, team, deployment project and tested commit match
   the project's own record. For hub-linked projects run
   `python3 .engineering/sdk/engineering_sdk.py target` with the exact values. Never
   deploy a project because its name resembles another.
3. Verify quality on the exact head commit: all mandatory checks green, independent
   review done, no skipped or weakened tests. Never bypass CI or a security check.
4. Build a preview, confirm it is the intended project and commit, and smoke-test
   the core journeys, permissions and both languages.
5. Capture the rollback target before promoting. Do not run destructive migrations
   or change sensitive external settings without separate authorization.
6. Promote the same tested artifact, smoke-test the production domain, and roll back
   immediately on a critical failure. With the engineering SDK, validate the captured
   provider receipts with its `release` command.
7. Report the commit, deployment identity, checks, smoke results, rollback target
   and anything not verified. Save a `release` entry to project memory.
8. For a release of this hub (Engineering OS) or of any repository with a release profile, the
   release engine decides eligibility and never tags: in a hub checkout run
   `python3 -m engineering_os.release_engine plan --version <X.Y.Z> --commit <exact SHA>
   --receipts <ci.json> --authorization <auth.json> --review-gate <gate.json>` (another
   repository adds `--profile <profile.json> --root <checkout>`) and continue only on
   `ELIGIBLE`. For the hub, run `hub-record ... --out <private path outside Git>` with HEAD at the
   merge commit. The record's status stays "recorded, tag pending" until the owner publishes the
   GitHub Release with the `gh release create` command listed in it. Never run that command,
   never create or push a tag. Formats: docs/specs/gaie-20-layers/RELEASE_ENGINE.md.

Follow `release-engineering` and `engineering-sdk` for the detailed guards.
