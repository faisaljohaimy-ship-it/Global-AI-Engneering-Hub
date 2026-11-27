# Global AI Engineering Hub
Global AI Engineering Hub for enterprise software, SaaS, agent skills, cybersecurity, cinematic production and reusable engineering tools.

Public, zero-additional-budget foundation. Core tooling uses the Python and Node standard libraries only. Contains a discovery registry, nine local skills, a progressive motion component library and a local Motion Lab. Listed external projects are not automatically installed, approved, or runtime-verified.

## Quick start
```sh
python3 hub.py audit
python3 hub.py search cinema
python3 hub.py recommend motion
python3 hub.py onboard /path/to/project --revision FULL_REVIEWED_SHA
python3 hub.py onboard /path/to/project --revision FULL_REVIEWED_SHA --apply
python3 hub.py register /path/to/project --revision FULL_REVIEWED_SHA \
  --capability skill:hub-capabilities --apply
python3 hub.py verify /path/to/project --strict
python3 -m unittest discover -s tests -v
node tests/test_motion_runtime.mjs
python3 -m http.server 8000  # open /motion-lab/
```

Onboarding defaults to dry-run and writes only absent `.engineering/` files plus the reviewed `hub-capabilities` discovery skill in the Codex and Claude skill locations. It never overwrites existing files. Review generated files in an isolated branch. No shared credentials or subscription quotas.

## Evidence snapshot

`hub.py audit` derives counts from manifests and browser evidence rather than
hard-coding them. The current phase indexes 142 motion specifications, exposes 30
executable Motion Lab components, and has 29 catalog entries with current Chromium
runtime evidence: CSS/WAAPI plus one dedicated WebGL shader check. Remotion-adapter
and Three-adapter evidence remains surface-specific instead of being promoted to an
engine-runtime claim. Integration probes
cover all 22 indexed programs and keep account metadata out of Git. See
[`integrations/EVIDENCE.json`](integrations/EVIDENCE.json) and the phase evidence under
[`docs/evidence`](docs/evidence/).

## Architecture
See [architecture](docs/ARCHITECTURE.md) and [onboarding](docs/ONBOARDING.md). One independent repository and deployment target per app. Shared capabilities use versioned references; no live production dependency on this hub. Keep client code, secrets, private business assets and sensitive data outside this public repository. Use services only within free-tier and commercial-use terms.

## Catalog expansion
Record canonical ID, license, commercial use, security review, and immutable revision before approval. Record runtime evidence separately. No third-party source copied here; upstream projects retain their own licenses. Public visibility does not grant a blanket license for this repository.

## Registering and verifying projects

The [Engineering SDK 1.0.0](docs/SDK.md) adds offline verification, a private
project registry validator, exact-target release guards and read-only MCP discovery.
Select `pack:engineering-sdk` during registration. Product CI runs the vendored
verifier without contacting this public repository. Dependency updates remain PRs
requiring review and tests; catalog candidates never execute automatically.

`python3 hub.py register` installs chosen skills, motion and packs from one reviewed,
pinned main commit and records a checksum for every file. `python3 hub.py verify`
compares a project with that commit and fails on differences. A manifest alone is
reported as `declared-only`. See [registration](docs/REGISTRATION.md). Public projects
are listed in `projects/registry.json`; private repositories stay private and verify
from their own CI.
