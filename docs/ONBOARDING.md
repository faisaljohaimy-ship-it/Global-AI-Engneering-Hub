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

The updater changes only a declaration-only `.engineering/capabilities.json` and
refuses symlinks, non-zero additional budgets, unexpected current revisions,
production runtime dependencies, and manifests with registered capabilities. Re-pin
registered capabilities with `hub.py register`, which regenerates their files and
checksums from the reviewed commit. Neither path merges or deploys.
