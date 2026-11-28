# GAIE factory evidence — 2026-11-28

Scope: the router, memory, inventory, bootstrap, skills and plugin manifest added in
this change. Environment: Claude Code 2.1.332 cloud container, Python 3.13, Linux.

## Automated tests

`python3 -m unittest discover -s tests` — see the pull request checks for the run on
the exact head. Added: `tests/test_gaie_router.py` (22 tests) and
`tests/test_gaie_factory.py` (20 tests) covering the eight owner acceptance phrases,
English equivalents, Arabic normalization, negation, unknown and near-miss projects,
conflicting registries, the workspace-origin guard, memory isolation, credential
refusal, tamper detection, inventory classification, bootstrap dry-run, idempotence,
preservation, update, uninstall, symlink refusal, source/installed drift, and real
registration of `pack:gaie-factory` into a temporary project followed by running the
vendored router and inventory as subprocesses.

## Clean-session discovery (real host)

Nine separate headless sessions (`claude -p "<phrase>" --max-turns 6`) were started
in this checkout with no prior context, one per phrase: the eight owner acceptance
phrases and "upgrade Biltix".

- 9 of 9 sessions listed the six `gaie-*` skills and the `gaie-verifier` agent.
- 9 of 9 invoked a GAIE skill from the bare sentence (8 `gaie-master-router`,
  1 went straight to `gaie-cinematic` after attempting the router command).
- In all nine the `hub.py route` command was refused by the headless permission
  system because no approver is present in that mode. Sessions then read the skill
  and registry files; none edited the hub. One finished by asking the owner for the
  missing approval and details.

One further session with the route command pre-approved for that invocation
(`--allowedTools "Bash(python3 hub.py route:*)"`, phrase «طور فيديوهات سديد») ran the
full chain: `gaie-master-router` → `hub.py route` returned `CINEMATIC` for
`biz-pulse-ar` with `write_allowed: false` for this checkout → `gaie-cinematic`
loaded → the session tried to verify the target repository and stopped at
permissions, leaving the hub unmodified.

`claude plugin validate .` passed (one advisory about a README install line, since
added).

## Independent review

A separate read-only reviewer agent probed the first version and reproduced
defects: negations more than two words away or outside a short list routed to
release; statements and questions were taken as commands; a negated project stayed
a target; build skipped the near-miss rule; overlay aliases could collide through
prefixes; the workspace guard accepted non-GitHub hosts and partial matches; a
poisoned install manifest could delete files outside `.claude`; installs wrote
through symlinked temporary files; an identical pre-existing file could later be
uninstalled; memory integrity missed removal and reordering; the credential filter
and inventory had gaps. Each was fixed and has a regression test in the two files
above. The clean-session runs below were made before these fixes; skill files did
not change, the router did.

Known residual limits: the router is a rule set, so unusual phrasing is refused
rather than understood; the credential filter is best-effort; the memory hash
chain does not stop a deliberate rewrite of the whole file; whoever can edit the
install manifest can mark GAIE's own paths as installed.

## What this does not show

- Interactive approval flow, plugin installation from the marketplace, user-level
  install persistence on a workstation, and discovery inside a product repository
  after `register` were not exercised on a real host.
- No build, upgrade, audit, film or release was carried out through the engines.
  Routing and skill invocation are not evidence that an engine completes its work.
- Session cost for the ten runs was about 3.5 USD-equivalent of plan usage as
  reported by the CLI; no token-saving comparison was made.
