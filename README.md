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
python3 -m unittest discover -s tests -v
node tests/test_motion_runtime.mjs
python3 -m http.server 8000  # open /motion-lab/
```

Onboarding defaults to dry-run and writes only absent `.engineering/` files plus the reviewed `hub-capabilities` discovery skill in the Codex and Claude skill locations. It never overwrites existing files. Review generated files in an isolated branch. No shared credentials or subscription quotas.

## Evidence snapshot

`hub.py audit` derives counts from manifests rather than hard-coding them. The current
phase indexes 142 motion specifications and implements/tests 11 components used by the
Motion Lab. Browser-runtime verification remains a separate state. Integration probes
cover all 22 indexed programs and keep account metadata out of Git. See
[`integrations/EVIDENCE.json`](integrations/EVIDENCE.json) and the phase evidence under
[`docs/evidence`](docs/evidence/).

## Architecture
See [architecture](docs/ARCHITECTURE.md) and [onboarding](docs/ONBOARDING.md). One independent repository and deployment target per app. Shared capabilities use versioned references; no live production dependency on this hub. Keep client code, secrets, private business assets and sensitive data outside this public repository. Use services only within free-tier and commercial-use terms.

## Catalog expansion
Record canonical ID, license, commercial use, security review, and immutable revision before approval. Record runtime evidence separately. No third-party source copied here; upstream projects retain their own licenses. Public visibility does not grant a blanket license for this repository.
