# Motion Lab phase 2 verification — 2026-11-27

No credentials, connector payloads, customer data, account identifiers or private
media are included in this record.

## Capability states

| Area | Indexed | Implemented/available | Automated-tested | Runtime-verified | Used here |
|---|---:|---:|---:|---:|---:|
| Motion specifications | 142 | 30 | 30 | 29 | 30 (Motion Lab) |
| Program integrations | 22 | 12 available | 22 probed | 10 authenticated reads + 2 local executables | 1 (GitHub delivery) |
| Recovered package groups | 3 | 0 imported | 3 source/integrity reviewed | 0 | 0 |
| Local hub skills | 9 | 9 | discovery checks | n/a | task-selected |

The 30 Motion Lab components are six CSS, eighteen WAAPI specifications, three WAAPI
runtime behaviours, one WebGL/GLSL component, one deterministic Remotion adapter and
one deterministic Three.js camera adapter. Chromium produced 30 passing raw results
(26 CSS/WAAPI specifications, three behaviours and one dedicated GLSL/WebGL check).
The catalog reports 29 runtime-verified entries. The Three component remains excluded
because generic CSS proof and a camera adapter unit test do not prove Three.js ran.
Likewise, the Remotion adapter test does not prove the optional package is installed.

## Tests that passed

- Python: 56 tests covering catalogs, evidence, registration, onboarding, safe pin updates,
  JSON duplicate rejection, CSS grammar/injection, Motion Lab accessibility/security,
  manifest reconciliation, byte budgets, action pinning and secret-pattern scanning.
- Node: 17 deterministic runtime, adapter and render-option tests.
- Chromium: 30/30 verifier results passed with Playwright 1.63.0; the Motion Lab
  listed all 142 entries and Play/Stop completed for all 30 executable controls with
  no page errors or external requests.
- Performance: 100,000 combined Three/Remotion adapter samples completed below the
  1,000 ms budget (41.36 ms in the recorded final local run; wall-clock results vary).
- Cinematic render: 1280×720, 30 fps, 126 H.264 frames, 4.2 seconds, all layout,
  repeatability, motion, RTL and contrast checks passed. Frame hash:
  `4a9838e6391a74461c0dce7b0c0b1f57789dd9a5a2b75c3f240900415063daf4`.
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

- Merged onboarding manifests and dual discovery skill copies exist in five projects:
  `max_-Alpha1` PR #2, `biltix-risk-ai-v2` PR #1, `n8n-docs` PR #3,
  `Wow-bus` PR #21 and `biz-pulse-ar` PR #462.
- The stronger checksum model correctly reports those original manifests as
  `declared-only` because they contain no registered capability file list. They must be
  re-registered against this change after it is merged to hub `main`; no strict-link
  claim is made here.
