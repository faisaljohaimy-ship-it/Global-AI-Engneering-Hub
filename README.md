# Global AI Engineering Hub
Global AI Engineering Hub for enterprise software, SaaS, agent skills, cybersecurity, cinematic production and reusable engineering tools.

Public, zero-additional-budget foundation. Python standard library only. Contains a discovery registry and seven original reusable skills; listed external projects are not automatically installed, approved, or runtime-verified.

## Quick start
```sh
python3 hub.py audit
python3 hub.py search cinema
python3 hub.py onboard /path/to/project --revision FULL_REVIEWED_SHA
python3 hub.py onboard /path/to/project --revision FULL_REVIEWED_SHA --apply
python3 -m unittest discover -s tests -v
```

Onboarding defaults to dry-run and writes only absent files under .engineering/. Review generated files in an isolated branch. Select reviewed SKILL.md directories for the agent-specific skills installer. No shared credentials or subscription quotas.

## Architecture
See [architecture](docs/ARCHITECTURE.md) and [onboarding](docs/ONBOARDING.md). One independent repository and deployment target per app. Shared capabilities use versioned references; no live production dependency on this hub. Keep client code, secrets, private business assets and sensitive data outside this public repository. Use services only within free-tier and commercial-use terms.

## Catalog expansion
Record canonical ID, license, commercial use, security review, and immutable revision before approval. Record runtime evidence separately. No third-party source copied here; upstream projects retain their own licenses. Public visibility does not grant a blanket license for this repository.
