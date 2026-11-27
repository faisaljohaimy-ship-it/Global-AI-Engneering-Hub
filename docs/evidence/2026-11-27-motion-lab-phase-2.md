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
| Project links | 5 | 5 checksum-registered | 5 strict checks + CI | 5 post-merge hub-link checks | 5 discovery consumers |

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
  1,000 ms budget (38.75 ms in the recorded final local run; wall-clock results vary).
- Cinematic render: 1280×720, 30 fps, 126 H.264 frames, 4.2 seconds, all layout,
  repeatability, motion, RTL and contrast checks passed. Frame hash:
  `4a9838e6391a74461c0dce7b0c0b1f57789dd9a5a2b75c3f240900415063daf4`.
- Local integration probe: Blender 4.3.2 and FFmpeg 7.1.5 succeeded; Remotion,
  Three.js, Motion, GSAP, Rive and Lottie packages were not installed.
- `git diff --check` and JSON parsing passed.

Project registration checks also passed on the exact default-branch trees. Fresh
shallow clones of all five projects returned `verified`, `pin_on_main=true`, one
`skill:hub-capabilities` capability, two of two matching files and zero warnings.
The copied workflow in every project matched the central template byte-for-byte.
`python3 hub.py projects --audit` returned success for all three public projects;
the two private projects were checked from authenticated fresh clones without being
listed in the public registry.

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

The original declaration-only links were replaced after hub commit
`4f39e1d115e220629d73e56864813545022acc99` reached `main`. The default branches now
contain strict checksum registrations and successful post-merge `hub-link` runs:

- `max_-Alpha1` [PR #4](https://github.com/faisaljohaimy-ship-it/max_-Alpha1/pull/4),
  merge `e1e85c3e47fcb010023788569861b9e9a28db8d3`, run
  [46067307012](https://github.com/faisaljohaimy-ship-it/max_-Alpha1/actions/runs/46067307012).
- `n8n-docs` [PR #4](https://github.com/faisaljohaimy-ship-it/n8n-docs/pull/4),
  merge `75f586c9fc604de2c133e042c53d16d9fe7ac02e`, run
  [46067491762](https://github.com/faisaljohaimy-ship-it/n8n-docs/actions/runs/46067491762).
- `Wow-bus` [PR #23](https://github.com/faisaljohaimy-ship-it/Wow-bus/pull/23),
  merge `c608dcbd41e116dcd7678309e71396630a7859ac`, run
  [46067735859](https://github.com/faisaljohaimy-ship-it/Wow-bus/actions/runs/46067735859).
- `biltix-risk-ai-v2`
  [PR #4](https://github.com/faisaljohaimy-ship-it/biltix-risk-ai-v2/pull/4),
  merge `19299a1ad3ea210c42ed8cfbdbaa006ca5b4ba0f`, run
  [46067767079](https://github.com/faisaljohaimy-ship-it/biltix-risk-ai-v2/actions/runs/46067767079).
- `biz-pulse-ar` [PR #463](https://github.com/faisaljohaimy-ship-it/biz-pulse-ar/pull/463),
  merge `54d19a88371266334e721e1a5c8c1d0a10189e51`, run
  [46069752811](https://github.com/faisaljohaimy-ship-it/biz-pulse-ar/actions/runs/46069752811).

Project-specific evidence was also observed rather than inferred. `Wow-bus` passed
227 Node tests and browser QA; `biltix-risk-ai-v2` passed 227 MJS tests, two CJS
tests, Chromium and WebKit QA; `n8n-docs` passed hub-link, Vale, Lychee and
readability; and `max_-Alpha1` passed its JSON, Python syntax and CLI checks.
`biz-pulse-ar` passed 8,658 tests across 466 files with 30 skips, its build,
performance budget, contrast, secret scan over 3,667 tracked files and PR HTTP E2E.
Its production audit reported no high or critical issue and retained 16 existing
low/moderate findings. Real Postgres/PostgREST and RAG CI jobs were skipped by their
repository conditions and are not counted as successful tests.

Four optional Vercel preview contexts for `Wow-bus` and one for
`biltix-risk-ai-v2` could not run because of the free-plan build-rate limit. They
were not required checks, no upgrade was purchased and no deployment integration
was changed. The `biz-pulse-ar` PR preview succeeded automatically and was not
promoted to production.

The central implementation itself merged through
[hub PR #2](https://github.com/faisaljohaimy-ship-it/Global-AI-Engneering-Hub/pull/2)
as `4f39e1d115e220629d73e56864813545022acc99`; both jobs on the exact PR head and the
post-merge `main` run
[46066671041](https://github.com/faisaljohaimy-ship-it/Global-AI-Engneering-Hub/actions/runs/46066671041)
succeeded.
