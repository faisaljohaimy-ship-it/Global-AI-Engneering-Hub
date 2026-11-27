# Onboarding
1. Inspect repository and current production mapping.
2. Create an isolated branch.
3. Checkout a reviewed immutable hub commit.
4. Run dry-run onboarding; review file changes.
5. Apply and choose relevant skills; integrate existing AGENTS.md and CLAUDE.md deliberately, never overwrite.
6. Verify agent skill discovery, build and security checks.
7. Submit PR. Only deploy a verified intended target after mandatory gates.
For new projects use a private template or the same onboarding flow.

## Safe updates

Pin changes are compare-and-swap guarded and dry-run by default:

```sh
python3 hub.py update-pin /path/to/project \
  --expected CURRENT_FULL_SHA --revision REVIEWED_TARGET_FULL_SHA
python3 hub.py update-pin /path/to/project \
  --expected CURRENT_FULL_SHA --revision REVIEWED_TARGET_FULL_SHA --apply
```

The updater changes only `.engineering/capabilities.json`, refuses symlinks,
non-zero additional budgets, unexpected current revisions and production runtime
dependencies. It does not pull code, install packages, merge, or deploy.

## Verified links

`onboard` creates a manifest that declares no capability. `hub.py register` goes
further: it installs chosen skills, motions and packs from the pinned commit and records
a checksum per file, and `hub.py verify` then proves the project matches that commit.
A manifest that lists capabilities must be re-pinned with `register`, which reinstalls
the files; `update-pin` changes only the SHA, so `verify` fails afterwards if any listed
file differs at the new commit. See [registration](REGISTRATION.md).
