# Global AI Engineering Hub
Global AI Engineering Hub for enterprise software, SaaS, agent skills, cybersecurity, cinematic production and reusable engineering tools.

Public, zero-additional-budget foundation. Core tooling uses the Python and Node standard libraries only. Contains a discovery registry, ten local skills, a progressive motion component library and a local Motion Lab. Listed external projects are not automatically installed, approved, or runtime-verified.

## Quick start
```sh
python3 hub.py audit
python3 hub.py search cinema
python3 hub.py recommend motion
python3 hub.py onboard /path/to/project --revision FULL_REVIEWED_SHA
python3 hub.py onboard /path/to/project --revision FULL_REVIEWED_SHA --apply
python3 hub.py register /path/to/project --revision FULL_REVIEWED_SHA --capability skill:hub-capabilities
python3 hub.py verify /path/to/project
python3 -m unittest discover -s tests -v
node tests/test_motion_runtime.mjs
node motion-library/verify/browser.mjs   # needs Playwright with Chromium
python3 -m http.server 8000  # open /motion-lab/
```

Onboarding defaults to dry-run and writes only absent `.engineering/` files plus the reviewed `hub-capabilities` discovery skill in the Codex and Claude skill locations. It never overwrites existing files. Review generated files in an isolated branch. No shared credentials or subscription quotas.

## Evidence snapshot

`hub.py audit` derives counts from manifests rather than hard-coding them. The current
phase indexes 142 motion specifications and implements/tests 26 components used by the
Motion Lab. Browser-runtime verification is a separate state, set only by
`motion-library/component_status.py` from `motion-library/evidence/chromium.json`: 24 of
the 26 are browser-verified in Chromium and the two optional-package adapters stay
adapter-tested. Integration probes cover all 22 indexed programs and keep account
metadata out of Git. See [`integrations/EVIDENCE.json`](integrations/EVIDENCE.json),
[`integrations/EVIDENCE.claude-code.json`](integrations/EVIDENCE.claude-code.json) and the
phase evidence under [`docs/evidence`](docs/evidence/).

## Registering and verifying projects

`hub.py register` installs chosen skills, motions and packs from one pinned commit and
records a checksum for each file; `hub.py verify` compares a project with that commit and
fails on any difference. A manifest with no capability is reported as declared-only, not
linked. See [registration](docs/REGISTRATION.md). Public projects are listed in
`projects/registry.json`; `python3 hub.py projects --audit` clones and checks them all.

## Architecture
See [architecture](docs/ARCHITECTURE.md) and [onboarding](docs/ONBOARDING.md). One independent repository and deployment target per app. Shared capabilities use versioned references; no live production dependency on this hub. Keep client code, secrets, private business assets and sensitive data outside this public repository. Use services only within free-tier and commercial-use terms.

## Catalog expansion
Record canonical ID, license, commercial use, security review, and immutable revision before approval. Record runtime evidence separately. No third-party source copied here; upstream projects retain their own licenses. Public visibility does not grant a blanket license for this repository.
