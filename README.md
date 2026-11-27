# Global AI Engineering Hub
Global AI Engineering Hub for enterprise software, SaaS, agent skills, cybersecurity, cinematic production and reusable engineering tools.

Public engineering control plane with independent product runtimes. Core tooling uses the Python and Node standard libraries; opt-in browser/quality test environments have separate exact dependency locks. Catalog candidates are reviewed before installation. No paid provider or continuous agent service is enabled by this repository.

## Quick start
```sh
python3 hub.py audit
python3 hub.py architecture
python3 hub.py capabilities --query playwright
python3 hub.py health --project /path/to/project
python3 hub.py motions
python3 hub.py integrations
python3 hub.py search cinema
python3 hub.py recommend motion
python3 hub.py onboard /path/to/project --revision FULL_REVIEWED_SHA
python3 hub.py onboard /path/to/project --revision FULL_REVIEWED_SHA --apply
python3 hub.py register /path/to/project --revision FULL_REVIEWED_SHA \
  --capability skill:hub-capabilities --apply
python3 hub.py verify /path/to/project --strict
python3 -m unittest discover -s tests -v
node tests/test_motion_runtime.mjs
python3 -m http.server 8000 --bind 127.0.0.1 # open /motion-lab/ or /motion-studio/
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

The additive expansion implements **400 new Canvas2D reference motions**:
200 authored mechanisms and 200 distinct coupled compositions across twenty
categories. The [Universal Motion SDK](packages/motion-sdk/README.md) supports
creation, playback/lifecycle, deterministic previews, frame export, optimization
and scoped CPU benchmarks. [Motion Studio](motion-studio/index.html) provides
Arabic/English, RTL/LTR, reduced-motion posters and mobile layouts. Read the
[expansion scope](motion-library/expansion/README.md) and source-bound browser
receipt before treating a category label as an actual GPU/3D/physics integration.
The original 142 catalog entries and 30 Motion Lab components remain preserved.

Private task leases, branch ownership, handovers and recovery use the
[orchestration CLI](agents/orchestrator/README.md). The model router validates
project-specific authorization, privacy, usage and cost evidence; its five
provider candidates contain **zero operational model versions** and make no API
calls. [Technology discovery](scripts/discover_technology.py) collects bounded
public metadata into review artifacts, never installs what it discovers.

## Architecture
See the [twelve-layer architecture](ARCHITECTURE.md), [existing reference](docs/ARCHITECTURE.md) and [onboarding](docs/ONBOARDING.md). One independent repository and deployment target per app. Shared capabilities use versioned references; no live production dependency on this hub. Keep client code, secrets, private business assets and sensitive data outside this public repository. Use services only within approved budget and commercial-use terms.

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
