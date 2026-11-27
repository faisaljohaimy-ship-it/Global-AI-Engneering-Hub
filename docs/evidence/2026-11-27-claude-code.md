# Claude Code verification — 2026-11-27

Recorded by the Claude Code session that worked alongside the Codex session of the same
day. It contains no credentials, account identifiers, customer data, private repository
names or private assets. Each line says what was run; "verified read" means one harmless
authenticated read succeeded, nothing more.

## Verified

**Hub**
- `python3 -m unittest discover -s tests` passes 25 tests on this branch. The hub's
  earlier suite also passes at both commits the onboarding pull requests pinned
  (5 tests at `7c586a7`, 8 at `53e620f`).
- `node --test motion-library/runtime/hub-motion.test.mjs` passes 7 tests.
- `python3 hub.py register` then `verify` on a scratch project: files install from the
  pinned commit, an edited or missing file fails verification, and a file the hub does
  not manage is not overwritten.

**Motion**
- `node motion-library/verify/browser.mjs`: 26 of 26 pass in Chromium 158 (Playwright
  1.63.0). 23 specifications are played from compiled CSS and through the runtime; 3
  behaviours (stagger, typewriter, counter) run in the page. Result: 26 of 142 catalog
  entries are implemented; 116 remain specifications.
- The verification caught two real defects before they were committed: the runtime
  eased a three-keyframe motion across its whole length where CSS eases each interval,
  and a transparent shadow colour that the engine reports differently. Reintroducing
  the first defect makes `ui-press-feedback` fail again.
- `node motion-library/render/render.mjs`: a 4.2 s bilingual sample (1280x720, 30 fps,
  126 frames, H.264, about 195 kB) passed every measured playbook check, and three
  separate runs produced identical frame hashes. One earlier run captured an unsettled
  frame; captures now repeat until two in a row are identical.

**Connections from this environment** (`integrations/PROGRAMS.json` has the per-program line)
- Read and write: GitHub.
- Verified read: Vercel, Supabase, Google Drive, Gmail, Notion, Slack, Figma, Canva,
  Lovable, HeyGen HyperFrames, Picsart, Base44.
- Local tools: ffmpeg and ffprobe 6.1.1; Playwright with Chromium.

**Earlier packs and skills** (`catalog/recovered.json`)
- `catalog-media-tools` is now a hub pack. Its copies in four project repositories are
  byte-identical to it; its catalog search downloaded and checksum-verified 178,964
  discovery rows.
- Three earlier packs and the pinned video skills are referenced at a commit in their
  public source repository. Nothing was copied.

**Onboarding pull requests**
- The four earlier pull requests carried byte-identical files, their skill copies match
  the hub at the pinned commit, and the pin is on the hub's main history.
- With this branch's `verify`, those projects report `declared-only`: valid, with no
  capability declared.

## Failed

- ElevenLabs: both connectors answered that they must be reconnected with additional
  permissions, and the API answered 401. No audio was generated; the sample has no sound.
- OCR in `catalog-media-tools`: `tesseract` is not installed here.

## Not verified

- Render, Runway, Higgsfield and OpenRouter: no connector in this environment.
- n8n: documentation only; no instance is connected.
- Composio: attached, not exercised.
- Remotion, Three.js, Motion, GSAP, Rive and Lottie: version and licence metadata were
  read from the npm registry. None was installed, reviewed or approved. Remotion and
  GSAP use non-standard licences that need review before commercial use.
- Blender is not installed.
- Motion in browsers other than Chromium, on phones, and with real assistive technology.
- Skill discovery inside Codex.
- No deployment was created, promoted or changed, and nothing was purchased.

## Not found

- The earlier Q-infinity pack (120-variant catalogue and Remotion sample).

## Reproduction

```sh
python3 -m unittest discover -s tests -v
node --test motion-library/runtime/hub-motion.test.mjs
node motion-library/verify/browser.mjs                 # needs Playwright with Chromium
python3 motion-library/catalog_status.py
node motion-library/render/render.mjs --out /tmp/hub-sample   # needs ffmpeg as well
python3 hub.py projects --audit                        # needs network access
```
