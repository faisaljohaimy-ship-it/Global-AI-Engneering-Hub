---
name: gaie-cinematic
description: GAIE Cinematic Intelligence — upgrade or produce a project's films, videos, voice-over, music, motion and 3D scenes. Use when the owner asks to upgrade or create videos, films, trailers, voice-over or cinematic motion («طور فيديوهات سديد», «أنتج فيلمًا», "upgrade Sadeed's videos"), or when the router returns engine CINEMATIC.
argument-hint: "[project] [media scope]"
---

1. If no router plan is in context, run `gaie-master-router` first; continue only
   when it returns `engine: CINEMATIC` with a resolved target. The operating rules of
   the master upgrade prompt apply (preserve, measure, verify, no added cost), with
   `scope: media`. Print it with the loader from the first location that exists, and
   stop if it reports drift, a missing file or a symlink:
   - hub checkout: `python3 engineering_os/master_docs.py show MASTER_UPGRADE`
   - plugin: `python3 "${CLAUDE_PLUGIN_ROOT}/engineering_os/master_docs.py" show MASTER_UPGRADE`
   - registered project: `python3 .engineering/gaie/master_docs.py show MASTER_UPGRADE`
   - user-level bootstrap: `python3 ../gaie-master-router/engine/master_docs.py show MASTER_UPGRADE`,
     relative to this file
   Only an install without a loader reads the file directly: `prompts/MASTER_UPGRADE.md`,
   `${CLAUDE_PLUGIN_ROOT}/prompts/MASTER_UPGRADE.md`, `.engineering/gaie/MASTER_UPGRADE.md`
   or `skills/gaie-upgrade/MASTER_UPGRADE.md` in the same `.claude` directory as this
   skill; then report that its bytes were not verified.
2. Inventory every existing media asset (`hub.py inventory <checkout>`): videos,
   audio, images, 3D, motion code; note weight, encoding, captions and where each is
   used. Existing media stays in place until its replacement is verified.
3. Plan each film: purpose, audience, script, storyboard, shot list with timing,
   typography, palette, Arabic and English versions. Use real screens of the system,
   not mock-ups that misrepresent it.
4. Choose engines by evidence, not by name: run `hub.py motions` and
   `hub.py capabilities --query <engine>`. The motion library and Universal Motion
   SDK (`universal-motion`, `digital-motion`) are verified in the hub; the
   deterministic renderer is `motion-library/render/render.mjs`
   (`cinematic-production`). Remotion, Blender, Three.js, WebGPU and similar engines
   need their own license review and a runtime proof in this environment before use.
   Choose only motions that are purposeful under `governance/policies/motion-purpose.json`
   (a stated digital meaning in English and Arabic, no unseeded randomness); a
   legacy-unclassified motion is used only by owner decision and labelled as such.
5. Produce the media for real: render the video, generate licensed voice-over,
   licensed or original music and effects, synchronize audio to picture, add
   captions, grade colour, encode efficiently, and test playback on mobile and
   desktop. A script or description is never delivered as a finished film. If an
   engine or permission is missing, deliver what was produced and name the blocker.
6. Never use a real person's voice or protected music without permission. Paid
   generation (voice, video, music credits) needs separate owner approval first.
7. Honour reduced motion, safe areas, RTL and LTR. Verify frame rate, clipping,
   contrast, loudness and file size; have an independent reviewer check the result.
8. Deliver the files outside Git unless the project stores media in Git, with a
   record of sources, licenses, render settings and what could not be verified.
