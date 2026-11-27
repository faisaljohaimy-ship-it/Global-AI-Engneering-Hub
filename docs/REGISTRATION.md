# Project registration and link verification

One mechanism links every project, new or existing, to the hub. It replaces "the
project has a manifest" with "the project's files were compared with the hub".

## What a link is

A project is linked when `.engineering/capabilities.json` pins a full hub commit and
every capability it declares can be reproduced byte for byte from that commit. A
manifest with an empty capability list is a declaration only; `verify` says so.

## Capabilities

| Id | Installs |
|---|---|
| `skill:<name>` | `skills/<name>/` into `.claude/skills/<name>/` and `.agents/skills/<name>/` |
| `motion:<id>` | the specification and the CSS the pinned compiler emits, into `.engineering/vendor/hub-motion/` |
| `pack:<name>` | the skills and companion files listed in `catalog/packs.json` |

## Register

```sh
git -C /path/to/hub rev-parse HEAD            # the commit to pin; use a merged one
python3 hub.py register /path/to/project --revision SHA --id my-project \
  --repository https://github.com/owner/my-project \
  --capability skill:hub-capabilities --capability motion:ui-fade-in
python3 hub.py register /path/to/project --revision SHA --id my-project \
  --capability skill:hub-capabilities --capability motion:ui-fade-in --apply
```

The first command is a dry run and prints the plan. Rules it keeps:

- A project file the hub does not manage is never overwritten. Identical content is
  adopted; different content stops the run and names the file.
- Running it again with a newer `--revision` re-pins: every declared capability is
  reinstalled from the new commit.
- `--remove skill:<name>` drops a capability and deletes its files, but only those that
  still match their recorded checksum; a file edited in the project is kept and named.
- Paths that leave the project, `.git/`, and symlinks are refused.
- Nothing is installed from the network and nothing is enabled or deployed.

Then copy `templates/hub-link.yml` to `.github/workflows/hub-link.yml` and open a pull
request in the project. To list a public project in the hub, add a row to
`projects/registry.json`. Private repositories are not listed in this public file;
their manifest and their own workflow are the registration.

## Verify

```sh
python3 hub.py verify /path/to/project            # integrity
python3 hub.py verify /path/to/project --strict   # also: a capability is installed and the pin is on main
python3 hub.py projects --audit                   # clone and verify every listed public project
```

`verify` exits 1 when a declared file is missing, edited, or differs from the hub at
the pin, when the pin is not a commit in the hub, or when the manifest breaks a rule
(non-zero budget, a production runtime dependency, another hub URL). It reports one of
three levels: `verified`, `declared-only`, `broken`.

The project workflow fetches hub `main`, proves the pin is its ancestor before running
any code from it, and uses strict verification so a declaration-only manifest fails.
It triggers only when link files change, so ordinary application builds and deployments
do not depend on the hub.
