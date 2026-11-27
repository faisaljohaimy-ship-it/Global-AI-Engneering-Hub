# Motion Lab phase 2 verification — 2026-11-27

No credentials, connector payloads, customer data, account identifiers or private
media are included in this record.

## Capability states

| Area | Indexed | Implemented/available | Automated-tested | Runtime-verified | Used here |
|---|---:|---:|---:|---:|---:|
| Motion specifications | 142 | 11 | 11 | 0 | 11 (Motion Lab only) |
| Program integrations | 22 | 12 available | 22 probed | 10 authenticated reads + 2 local executables | 1 (GitHub delivery) |
| Recovered package groups | 3 | 0 imported | 3 source/integrity reviewed | 0 | 0 |
| Local hub skills | 9 | 9 | discovery checks | n/a | task-selected |

The 11 motion components are six CSS, two WAAPI, one WebGL/GLSL, one deterministic
Remotion adapter and one deterministic Three.js camera adapter. The two adapters do
not prove the optional packages are installed. `runtime-verified` remains zero because
the shared browser surface was unavailable and local Chromium timed out after GPU/DBus
sandbox failures. Static HTTP asset requests succeeded, but that is not animation
runtime evidence.

## Tests that passed

- Python: 28 tests covering catalogs, evidence, onboarding, compare-and-swap updates,
  JSON duplicate rejection, CSS grammar/injection, Motion Lab accessibility/security,
  manifest reconciliation, byte budgets, action pinning and secret-pattern scanning.
- Node: 4 deterministic adapter/runtime tests.
- Performance: 100,000 combined Three/Remotion adapter samples completed below the
  1,000 ms budget (observed runs varied by host; the final pre-commit run is reported
  in the pull request).
- Local integration probe: Blender 4.3.2 and FFmpeg 7.1.5 succeeded; Remotion,
  Three.js, Motion, GSAP, Rive and Lottie packages were not installed.
- `git diff --check` and JSON parsing passed.

## Integration probe outcomes

- Successful official MCP authenticated reads (10): GitHub, Vercel, Supabase,
  Google Drive, Canva, Figma, Runway, Higgsfield, HeyGen and Lovable.
- Successful local executable probes (2): Blender and FFmpeg.
- Unavailable/uninstalled (10): Render, ElevenLabs, n8n, OpenRouter, Remotion,
  Three.js, Motion, GSAP, Rive and Lottie.
- Mutating, generation and paid probes: 0.

These results prove only the operation named in `integrations/EVIDENCE.json`.

## Security changes

- GitHub Actions are pinned to immutable SHAs with read-only contents permission,
  concurrency cancellation and a ten-minute timeout.
- JSON duplicate keys/non-finite values are rejected.
- CSS property-specific grammars reject URLs, custom variables, control characters,
  injection delimiters and invalid opacity/transform/filter/color values.
- Motion Lab has a CSP, local assets only, no dynamic HTML/eval and no autoplay.
- Central updates require full current/target SHAs and dry-run by default; they refuse
  symlinks, budget changes, production runtime coupling and stale expected revisions.

## Recovery boundary

Eight locked MIT video skill wrappers, a 144-skill MIT pack, and a 72-agent/180-tool
MIT pack were verified at their existing public source and indexed as
`verified-source`. They were not copied or installed. Branded/private Remotion assets
and materials without a repository-level public license were explicitly excluded.

## Repository linkage

- Already merged before this phase: `max_-Alpha1`, `biltix-risk-ai-v2`.
- Merged in this phase: `n8n-docs` PR #3.
- Pending exact-head CI at evidence-writing time: `Wow-bus` PR #21 and
  `biz-pulse-ar` PR #462. They must not merge unless their required checks succeed.
