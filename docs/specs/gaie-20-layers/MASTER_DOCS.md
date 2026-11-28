# GAIE OS — MASTER documents: adoption, pinning and owner updates (layers L06, L16)

Code: `engineering_os/master_docs.py` (loader and `pin`), `governance/policies/master-prompts.json`
(manifest). Test: `tests/test_master_docs.py`.

`prompts/MASTER_BUILD.md` and `prompts/MASTER_UPGRADE.md` are the agent instructions
behind the build engine (`gaie-build`) and the upgrade engine (`gaie-upgrade`; the
cinematic route also names `MASTER_UPGRADE`). Each exists once in the repository. The
manifest pins each one: canonical path, version, SHA-256, size, the places it is
installed to, and an append-only history of approved versions. Version 1.0.0 of both
was adopted in this integration (pull request #31). To see the current values, run
`python3 -m engineering_os.master_docs status`; this page does not copy the digests,
so it cannot go stale.

## 1. What the manifest records

| Field | Meaning |
|---|---|
| `documents.<NAME>.path` | canonical path in a hub checkout |
| `version`, `sha256`, `bytes` | the pinned bytes; equal to the last history entry |
| `installed_as.pack` | destination written by `pack:gaie-factory` (`catalog/packs.json`), relative to the project |
| `installed_as.claude` | destination written by `scripts/gaie_bootstrap.py`, relative to the `.claude` directory |
| `history[]` | `version`, `sha256`, `date`, `approved_by` (a label), `reference` (for example `PR #31`), `same_bytes` (only when a new version repeats the previous bytes), `chain` |

`chain` is the SHA-256 of the previous entry's chain (or the document name for the
first entry) and the entry itself. It makes an edited, reordered or removed entry
fail to load. It is not a signature: anyone who can edit the file can recompute it.
The test `test_committed_revisions_only_append` therefore also compares every
committed revision of the manifest with the next one and refuses any revision whose
history is not the earlier history plus new entries.

## 2. Where the loader finds the manifest

The loader uses only the Python standard library and imports nothing from the
repository, so it can be copied beside the router. Without a `root` argument it
finds the manifest relative to its own file:

| Layout | Root | Manifest | Loader | Documents |
|---|---|---|---|---|
| `hub` | hub checkout, or the plugin root (the plugin source is the repository, `.claude-plugin/marketplace.json`) | `governance/policies/master-prompts.json` | `engineering_os/master_docs.py` | `path` |
| `pack` | project registered with `pack:gaie-factory` | `.engineering/gaie/master-prompts.json` | `.engineering/gaie/master_docs.py` | `installed_as.pack` |
| `claude` | a `.claude` directory (`~/.claude` or `<project>/.claude`) | `skills/gaie-master-router/engine/master-prompts.json` | `skills/gaie-master-router/engine/master_docs.py` | `installed_as.claude` |

With `root`, it tries the hub, pack and claude layouts in that order, then
`<root>/.claude`. In the installed layouts the manifest and loader arrive only once
the pack and the bootstrap ship them (section 6).

## 3. Interface

```python
from engineering_os import master_docs
master_docs.load_manifest(root=None)   # validated manifest
master_docs.verify(root=None)          # {"ok", "layout", "root", "manifest", "policy_version", "documents": [...]}
master_docs.load(name, root=None)      # (text, record), or MasterDocsError
```

Each `documents` row has `name`, `path`, `version`, `sha256` and `status`:
`current` (bytes equal the pin), `drift` (different bytes; `actual_sha256` shows
them), `missing` (absent or not a regular file) or `link` (the file or a directory
on its path is a symlink). `load` raises `MasterDocsError` for anything but
`current`, and `verify` and `load` both raise it when the manifest itself is missing,
symlinked, not valid JSON, has a duplicate key, an unknown field, a version that does
not increase, or a history entry that does not match its chain. Names are accepted
as `MASTER_BUILD`, `master-build` or `build`.

```
python3 -m engineering_os.master_docs status [--root DIR] [--json]       # exit 0 only if every document is current
python3 -m engineering_os.master_docs show <name> [--root DIR] [--json]  # prints the exact pinned bytes
python3 -m engineering_os.master_docs pin [<name> ...] --version X.Y.Z --approved-by "<label>" --reference "<ref>" \
    [--date YYYY-MM-DD] [--allow-same-bytes] [--dry-run] [--json]
```

`pin` is the only command that changes a version, a digest or the history. It works
only in a hub checkout. Without names it pins every drifted document. It appends one
entry per document, refuses a version that is not greater than the pinned one,
refuses identical bytes under a new version unless `--allow-same-bytes`, refuses a
date earlier than the last entry, and refuses to run while a document is missing or
a symlink. With `--date` the result is byte-for-byte reproducible. Changing the
manifest's structure (adding a document, moving an install destination) is a
reviewed edit of the file itself; removing a document or an entry fails the test.

## 4. Owner procedure: change a MASTER document

Each command below was run once in a scratch clone of this branch, except where
marked.

1. Work on an isolated branch: `git switch -c claude/master-build-<topic>`.
2. Edit the canonical file only, for example `prompts/MASTER_BUILD.md`. Never edit an
   installed copy (`.engineering/gaie/…`, `.claude/skills/gaie-build/…`): the next
   install overwrites it, and until then it reports `drift`.
3. See the drift: `python3 -m engineering_os.master_docs status` (exit 1, the edited
   document shows `drift`).
4. Choose the version: patch for wording that changes no rule, minor for an added or
   changed rule, major for a removed rule or a changed phase order.
5. Pin, first as a dry run, then for real:

   ```
   python3 -m engineering_os.master_docs pin --version 1.1.0 --approved-by "owner" --reference "PR #<number>" --dry-run
   python3 -m engineering_os.master_docs pin --version 1.1.0 --approved-by "owner" --reference "PR #<number>"
   python3 -m engineering_os.master_docs status
   ```

   If the pull request number is not known yet, open the pull request as a draft
   first (step 8) and pin with its number.
6. Run the drift test and the tests of the consumers:

   ```
   python3 -m unittest tests.test_master_docs -v
   python3 -m unittest tests.test_gaie_factory tests.test_gaie_router tests.test_control_plane
   ```

7. Reinstall the `.claude` copies. In the hub checkout this keeps the skill mirrors
   identical (the hub reads the documents from `prompts/`):

   ```
   python3 scripts/gaie_bootstrap.py install --scope project --target . --apply
   ```

   On a workstation with a user-level install (not run here, because it writes to
   `~/.claude`): `python3 scripts/gaie_bootstrap.py install --scope user`, then the
   same with `--apply`, then `python3 scripts/gaie_bootstrap.py verify --scope user`.
   The project scope was run against a scratch project; its installed
   `MASTER_BUILD.md` had the newly pinned SHA-256 and `verify` reported `ok`.
8. Commit the document and the manifest together and open a pull request to `main`
   (not run here: no GitHub writes from this session). Merge only after the review
   that CODEOWNERS requires.
9. After the merge, re-pin each linked project to the reviewed `main` commit (not
   run here: these commands need a reviewed commit on `main`):

   ```
   python3 hub.py register <project-dir> --revision <main-sha>
   python3 hub.py register <project-dir> --revision <main-sha> --apply
   python3 hub.py verify --strict <project-dir>
   ```

When `hub.py` has the `master` subcommand, `python3 hub.py master status|show|pin`
passes its arguments to the same module.

## 5. What this proves and what it does not

- Proved by the manifest and the test: the bytes on disk equal a recorded digest;
  every MASTER path in the tree is the canonical path or a declared install
  destination; no other file in the checkout is a copy of either document; installed
  copies verify against the same manifest; each committed revision of the manifest
  only appends. This last check needs Git history: a checkout with one commit (the
  default depth of the CI checkout) compares only that commit with the working tree.
- Not proved: that the owner approved the bytes. `approved_by` is a label and one
  pull request can change a document and the manifest together. Real approval needs
  a CODEOWNERS entry for `prompts/` and `governance/policies/master-prompts.json`
  plus branch protection on `main` that requires code-owner review and allows no
  bypass. The owner sets branch protection on GitHub; its state is not readable from
  this environment.
- Editing a MASTER document changes agent instructions, not engine code. The
  deterministic engines (`engineering_os/build_engine.py`,
  `engineering_os/upgrade_engine.py`) keep their own stages and refusals and do not
  read the documents. Rules are also restated in the skills and in the gates of
  `governance/policies/gaie-routes.json`; a change to a rule must be made there too.

## 6. Consumers

The loader and the drift test are in this branch. Reading through the loader is
requested from the owners of the consuming files in this integration: the adapters
(`master-build` and `master-upgrade` spec and health fail closed on drift, and the
manifest joins their receipt sources), the router (the plan carries
`prompt_version` and `prompt_sha256` and is blocked on drift), the `gaie-build` and
`gaie-upgrade` skills (read the document through the loader; the fallback list gains
the plugin root), the bootstrap and the pack (ship the manifest and the loader),
`hub.py master`, the L16 layer entry, CODEOWNERS and the changelog. Until each lands,
drift is caught by this test and by `status`, not by that consumer.

## 7. PR #25 launch-time approval gate

Decision for this integration: not ported. PR #25 (`engineering_os/master_approval.py`,
`engineering_os/master_workflow.py`, on `codex/nextgen-intelligence`, not merged)
reads a private approval file outside Git at launch, checks that its revision is an
ancestor of `origin/main`, and compares its own list of six source paths with the Git
blobs at that revision. If the owner wants it later, it would pin this manifest
instead of its own path list: the private approval records the reviewed `main`
revision and the SHA-256 of `governance/policies/master-prompts.json` at that
revision; at launch the gate reads the manifest blob from Git at that revision,
compares its digest with the approval, then runs `master_docs.verify()` on the
working files and refuses anything not `current`. That would close the gap in
section 5, because the approval would sit outside the repository and a pull request
could not change it. Its source closure would also need
`engineering_os/workspace_policy.py`.
