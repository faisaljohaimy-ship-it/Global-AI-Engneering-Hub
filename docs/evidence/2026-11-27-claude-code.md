# Claude Code verification — 2026-11-27

Recorded by the Claude Code session that worked alongside the Codex session of the same
day, after merging that session's Motion Lab (#3). It contains no credentials, account
identifiers, customer data, private repository names or private assets. Each line says
what was run; "verified read" means one harmless authenticated read succeeded, no more.

## Verified

**Hub**
- `python3 -m unittest discover -s tests` passes on this branch, including the suites
  merged from #1 and #3. Those suites also pass unmodified on `main` at `dcb95d1`.
- `node --test motion-library/runtime/hub-motion.test.mjs`, `node tests/test_motion_runtime.mjs`
  and `node tests/test_motion_performance.mjs` pass.
- `python3 hub.py register` then `verify` on a scratch project: files install from the
  pinned commit, an edited or missing file fails verification, and a file the hub does
  not manage is not overwritten.

**Motion in a real browser** (`motion-library/evidence/chromium.json`)
- `node motion-library/verify/browser.mjs`: 28 of 28 results pass in Chromium 158 here
  and Chromium 153 in CI (Playwright 1.63.0). That is the first browser run for the
  eleven components of #3, which were merged as `pending-browser`.
- 24 of 26 components are now `browser-verified`: 21 CSS, 2 WAAPI and the WebGL shader.
  The Remotion and Three.js adapters stay `adapter-tested`; their demos run in the lab
  but neither package is installed.
- The Motion Lab was driven through its own controls: it loads without page errors, its
  counts match the manifest, every component starts, each CSS component's lab rule
  matches its specification at five moments, Reduced mode applies the end state without
  animating, and inline travel mirrors under RTL.
- Three behaviours of the runtime (stagger, typewriter by grapheme and by word, counter)
  pass in the page. They are helpers, not catalog components: the manifest admits only
  rows with a compilable specification.
- The compiler and the runtime refuse the same 18 cases in `verify/rejections.json`.

**Defects the browser run caught**
- The runtime eased a three-keyframe motion across its whole length where CSS eases each
  interval. Fixed; reintroducing it makes the three-keyframe components fail.
- The compiled CSS ignored `rtl_mirror`, so an inline-start slide entered from the wrong
  side on right-to-left pages. The compiler now emits mirrored keyframes for `:dir(rtl)`.
- `scripts/browser_smoke.sh` crashed Chromium with `--single-process --no-zygote`.
  Without those flags it passes.
- A frame captured straight after a seek could be unsettled; the renderer now repeats a
  capture until two in a row are identical.

**Cinematic sample** (`motion-library/evidence/sample-render.json`)
- `node motion-library/render/render.mjs`: a 4.2 s bilingual sample (1280x720, 30 fps,
  126 frames, H.264) passed every measured playbook check; separate runs produce
  identical frame hashes. No audio, and only the system fallback typeface for Arabic.

**Connections from this environment** (`integrations/EVIDENCE.claude-code.json`)
- Read and write: GitHub.
- Verified read: Vercel, Supabase, Google Drive, Gmail, Notion, Slack, Figma, Canva,
  Lovable, HeyGen HyperFrames, Picsart, Base44.
- Local tools: ffmpeg and ffprobe 6.1.1; Playwright with Chromium.

**Earlier packs and skills** (`catalog/recovered-additions.json`)
- `catalog-media-tools` is now a hub pack. Its copies in four project repositories are
  byte-identical to it; its catalog search downloaded and checksum-verified 178,964
  discovery rows.

**Onboarding pull requests**
- The four earlier pull requests carried byte-identical files, their skill copies match
  the hub at the pinned commit, and the pin is on the hub's main history. With `verify`
  they report `declared-only`: valid, with no capability declared.
- Claude Code discovered and loaded `hub-capabilities` from a project's `.claude/skills/`
  in a live session.

## Open finding

- `interactive-waapi-keyframes`: the Motion Lab eases the whole animation, while the
  compiled CSS and the runtime ease each keyframe interval. Opacity differs by up to 0.157
  between them. The specification should mean one motion; the lab's WAAPI path was left
  as merged for its author to decide.

## Failed

- ElevenLabs: both connectors answered that they must be reconnected with additional
  permissions, and the API answered 401. No audio was generated.
- OCR in `catalog-media-tools`: `tesseract` is not installed here.

## Not verified

- Render, Runway, Higgsfield and OpenRouter: no connector in this environment.
- n8n: documentation only; no instance is connected. Composio: attached, not exercised.
- Remotion, Three.js, Motion, GSAP, Rive and Lottie: version and licence metadata were
  read from the npm registry. None was installed, reviewed or approved. Remotion and
  GSAP use non-standard licences that need review before commercial use.
- Blender is not installed here.
- Motion in engines other than Chromium, on phones, and with assistive technology.
- Skill discovery inside Codex.
- No deployment was created, promoted or changed, and nothing was purchased.

## Not found

- The earlier Q-infinity pack (120-variant catalogue and Remotion sample).

## Reproduction

```sh
python3 -m unittest discover -s tests -v
node --test motion-library/runtime/hub-motion.test.mjs
node motion-library/verify/browser.mjs                 # needs Playwright with Chromium
python3 motion-library/component_status.py
node motion-library/render/render.mjs --out /tmp/hub-sample   # needs ffmpeg as well
python3 hub.py projects --audit                        # needs network access
```
