# Claude Code evidence reconciliation — 2026-11-27

This is a sanitized reconciliation of the earlier Claude Code session with the
current hub evidence. It contains no credentials, account identifiers, private
repository names, customer data or private media.

## Accepted evidence

- Claude Code and Codex discover the same capability contract through
  `skills/hub-capabilities/SKILL.md`. Registration installs byte-identical copies in
  both `.claude/skills/` and `.agents/skills/`, pins a reviewed hub `main` commit, and
  records a checksum for every managed file.
- The locked Playwright 1.63.0 verifier produced 30 passing Chromium results: 26
  CSS/WAAPI specifications, stagger/typewriter/counter behaviours, and one dedicated
  WebGL shader run. The catalog claims 29 runtime-verified entries; generic CSS proof
  is still not treated as proof that Three.js or Remotion ran.
- The bounded cinematic sample rendered at 1280×720, 30 fps and 126 frames with
  FFmpeg. `motion-library/evidence/sample-render.json` records the tool versions,
  input hashes, frame hash and measured checks; the video itself stays outside Git.
- `integrations/EVIDENCE.json` is the authoritative snapshot for the 22 program
  integrations in scope: 12 successful harmless probes and 10 unavailable probes,
  with no mutation or budget impact.
- `catalog/recovered-packages.json` is the authoritative recovery index. Three
  licensed public sources are recorded as `verified-source` and not imported.
  `catalog-media-tools` remains deferred and is not exposed as a hub capability.

## Superseded claims

Earlier branch notes reported 26 browser results, 29 programs and an activated
`catalog-media-tools` pack. Those statements described an intermediate branch and
must not be used as current evidence. The checked manifests and generated evidence in
this commit take precedence.

## Limits

- Engine-runtime execution is still pending for Remotion and Three.js; adapter/unit
  evidence is labelled separately. GLSL has a dedicated Chromium WebGL result.
- Browser evidence covers Chromium, not all browsers, phones or assistive technology.
- Agent discovery files and checksum verification prove availability, not that every
  future Claude Code or Codex environment will automatically select the right skill.
- No deployment, purchase, paid generation or production configuration change was
  made.

## Reproduction

```sh
python3 -m unittest discover -s tests -v
node --test motion-library/runtime/hub-motion.test.mjs
npm ci --prefix motion-library/verify --ignore-scripts --no-audit --no-fund
node motion-library/verify/browser.mjs
python3 motion-library/catalog_status.py
node tests/test_motion_lab_browser.mjs
node motion-library/render/render.mjs --out /tmp/hub-sample
python3 hub.py projects --audit
```
