# Codex integration handoff for PR #31

Base for the handoff is the final-integration branch. Keep its existing
twenty-layer registry, security controls, role policy and MASTER prompt pins.
The Codex branch adds an installation layout, a disabled Context7 profile and
cross-layout acceptance. The existing release and cinema lanes retain their
source ownership.

The upstream [ownership handoff](CODEX_HANDOFF.md) also identifies the native
Codex agent adapters and the shared Context7 work in PR #32.

## Install and verify

A clone of the Hub has six Codex skills in `.agents/skills`. These are small
entry points to the canonical skill and policy sources. For a separate project
or user installation, the bootstrap supplies the required public runtime files
and pinned policy bytes locally. It lists planned changes by default, preserves
foreign or modified files and verifies the resulting bytes before use.

```sh
python3 scripts/gaie_codex_bootstrap.py check
python3 scripts/gaie_codex_portable.py install --scope project --target /path/to/project
python3 scripts/gaie_codex_portable.py install --scope project --target /path/to/project --apply
python3 scripts/gaie_codex_portable.py verify --scope project --target /path/to/project
python3 scripts/gaie_codex_portable.py uninstall --scope project --target /path/to/project
```

User installation uses `--scope user`. Review an update before applying it.
Whenever a canonical skill or pinned policy changes, use the Hub check and
render commands to review and refresh its projections, then run the parity checks. Read and validate
the existing MASTER pin before using it. Routes describe intent and target.
All write operations still need separately approved, isolated execution.

## Acceptance checks and their scope

| Item | Check | Evidence boundary |
| --- | --- | --- |
| J | Standalone route calls from both installed layouts agree in Arabic and English, preserve audit-only grants and leave ambiguous repositories unresolved. | CLI policy behavior. |
| K | Both layouts contain the same pinned MASTER documents. The Codex loader and generated Hub skill verifier enforce the pin and detect copy drift. | Installed text and verification, separate from model behavior. |
| L | Both layouts resolve build and upgrade through the existing twenty-role policy. | Team discovery, separate from actual staffing and concurrency. |
| M | A native Codex client lists and calls the two permitted tools on a credential-free loopback fixture. | Streamable HTTP and tool filtering. The hosted profile stays disabled. |
| N | The portable Codex layout copies the central motion policy. The existing validator requires every current motion to have a defined classification. | Shared policy, with runtime rendering evidenced separately. |
| O | Fresh CLI processes restore checkpoints into separate stores in both directions and accept each handover under the new engine label. | Private state integrity and recovery, separate from interactive host-to-host model transfer. |

```sh
python3 -m unittest tests.codex.test_codex_portable tests.codex.test_dual_engine_acceptance tests.codex.test_codex_context7
GAIE_CHECK_CODEX_CONTEXT7=1 python3 -m unittest tests.codex.test_codex_context7
```

The native Context7 proof uses a local fixture and needs a local Codex binary
and loopback sockets. See [Context7 profile](../../../integrations/context7-codex/README.md).
Use the existing full-tier GitHub isolation check on the exact integration
tree before release. The integration release gate now requires that job. Verify the
final combined SHA before publishing.
