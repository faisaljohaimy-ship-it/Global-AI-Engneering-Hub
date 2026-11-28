# Advanced Cinematic Intelligence — production pipeline (L08 / L18)

Status: implemented and tested in `engineering_os/video_pipeline.py` (pipeline) and
`engineering_os/cinematic.py` (`motion_inventory`, source-bound receipts). Tests:
`tests/test_video_pipeline.py`, `tests/test_cinematic_intelligence.py`. Evidence of
acceptance Scenario C: `docs/evidence/gaie-20-layers/video-sample.json` (manifest only —
the MP4s stay outside Git).

The pipeline is deterministic and offline. No paid service, provider API, model call or
network request is made: the browser page may load only allowlisted repository modules
and every other request is refused and counted (the evidence records `0`).

```
storyboard (gaie.storyboard/1, ar + en)
  -> validate          closed schema, motion ids resolved in three namespaces, source digests
  -> direct            pacing, reading time, RTL hygiene, beat alignment, camera overscan
  -> preflight         (Chromium) text layout in title-safe area, size, contrast, Arabic shaping/RTL, fonts
  -> voiceover         local TTS only (ffmpeg libflite, English); Arabic: not available here
  -> audio             procedural music bed + sound design, ducking, peak limiter, EBU R128 two-pass
  -> subtitles         WebVTT + SRT per language, frame-aligned, RLM-marked Arabic, sidecar files
  -> render            Chromium/Playwright steps plan time frame by frame -> PNG pipe
  -> grade + encode    one ffmpeg: RGB grade -> BT.709 -> H.264/AAC MP4 main + mobile, faststart
  -> media QA          ffprobe + ebur128 + cut/onset detection on the delivered files
  -> manifest          hashes, streams, QA, motions with source ids (committed); media is not
```

## 1. Storyboard — `gaie.storyboard/1`

```json
{"schema": "gaie.storyboard/1", "id": "gaie-os-one-command",
 "title": {"ar": "…", "en": "…"}, "languages": ["ar", "en"], "primary_language": "ar",
 "format": {"width": 1920, "height": 1080, "fps": 30}, "grade": "gaie-teal-amber",
 "fade_in_ms": 500, "fade_out_ms": 700,
 "audio": {"bpm": 120, "music": true, "sound_design": true, "voiceover": {"language": "en", "voice": "slt"}},
 "subtitles": {"burn_in": false, "embed": false},
 "scenes": [{"id": "one-command", "duration_ms": 2500, "camera": "cinema-dolly-in",
             "transition_in": "cut", "text_position": "center",
             "motion": {"source": "engine", "id": "quantum-light-tunnel", "params": {"speed": 1.2}},
             "text": {"ar": "أمرٌ واحد.", "en": "One command."}}]}
```

Rules (violations raise `StoryboardError`; the schema is closed — unknown fields are refused):

| Field | Rule |
|---|---|
| `format` | even width 320–3840, height 180–2160; fps ∈ {24, 25, 30, 50, 60} |
| `scenes` | 1–40 shots, unique slugs, 1 000–10 000 ms, a whole number of frames; total ≤ 120 s |
| `motion.source` | `engine` (packages/motion-engines registry id), `reference` (one of the 400 recipes), `camera` (nextgen camera scene). Ids are looked up, never used as paths |
| engine motions | only engines the compositor can read back from one canvas: `canvas2d`, `webgl2-glsl`, `webgl2-points`, `webgpu-wgsl` (readback). `dom`, `svg`, `composition` are refused. The motion file must still match its registry `source_sha256` |
| `params` | only the motion's declared parameters, within their ranges |
| `camera` | `static` or a reviewed spec of `motion-library/specs/`: `cinema-dolly-in`, `-dolly-out`, `-truck-left`, `-truck-right`, `-crane-rise`, `-rack-focus` |
| `transition_in` | `cut` or `dissolve` (`dissolve_ms` 200–1000, ≤ half of each adjacent shot) |
| `text` | one line per language, 1–90 characters; Arabic must contain Arabic script, English must be Latin; control and bidi override/isolate characters (U+202A–202E, U+2066–2069, LRM/RLM/ALM) are refused (the pipeline adds RLM itself) |
| `subtitles` | sidecar only in this version (`burn_in`/`embed` must be `false`) |
| `audio.voiceover` | `null` or a local Flite voice; per-shot override `voiceover: {"en": "…"}` or `null` |

## 2. Cinematic direction checks

Static (`direct`) and browser-measured (`browser_direction`) checks; any `fail` raises
`DirectionError` **before a frame is drawn** (the work directory is removed).

| Check | Threshold | Severity |
|---|---|---|
| `pacing.shot_length` | 1 000–10 000 ms | error |
| `pacing.text_shot_length` | ≥ 1 500 ms for a shot carrying text | warning |
| `pacing.no_repeated_motion` | consecutive shots use different motions | warning |
| `reading.window_ms` | fully readable time ≥ 1 000 ms (half of each fade counted) | error |
| `reading.cps.ar` / `.en` | ≤ 17 / ≤ 20 characters per second (combining marks not counted) | error |
| `rtl.arabic_script`, `rtl.no_bidi_overrides` | as named | error |
| `music.cut_on_beat` | every hard cut within ½ frame of a beat of `audio.bpm` | warning |
| `framing.camera_overscan` | plate overscan (1 + 2·max translation) × max scale ≤ 1.2 — no edge is ever revealed | error |
| `safe_area.title_safe.*` | every text box (incl. its slide-in) inside the 90 % title-safe area (EBU R95 / SMPTE ST 2046-1) | error |
| `typography.min_size.*` | ≥ 3 % of frame height after auto-fit | error |
| `typography.no_line_overlap` | stacked lines do not overlap | error |
| `legibility.contrast.*` | WCAG AA ≥ 4.5 : 1 against the 95th-percentile background luminance under the line (scrim included, glyphs excluded) at mid-shot | error |
| `rtl.arabic_glyphs_not_tofu` | ب and ت render differently (no .notdef boxes) | error |
| `rtl.contextual_shaping` | a word differs from the same letters split by ZWNJ (joining applied) | error |
| `rtl.first_word_at_right_edge` | the first logical run (an Arabic word, or a leading Latin brand run) occupies the right edge pixel-for-pixel | error |
| `rtl.canvas_direction` | Arabic lines drawn with `direction = 'rtl'` | error |
| `typography.font_available.*` | DejaVu Sans (ar) and Inter (en) change the advance vs. monospace | error |
| `render.no_engine_fallback`, `render.no_page_errors`, `render.no_external_requests`, `render.no_refused_requests` | zero | error |
| `voiceover.fits_shot` | trimmed speech ≤ shot − 300 ms offset − 150 ms tail | error |

The direction stage is not decorative: on its first real run it refused the sample
because the English line over the bright ignition shot measured 3.57 : 1; the scrim
and the secondary text colour were raised until it measured ≥ 4.5 : 1 (5.95 : 1 now).

## 3. Rendering engines

The compositor is generated from `video_pipeline.py` into a private work directory and
hashed into every manifest. It runs in headless Chromium through Playwright
(`require('playwright')`, browsers in `PLAYWRIGHT_BROWSERS_PATH`), reusing
`packages/motion-engines/tools/playwright.mjs` for loading and Chromium flags.

- **Native engine motions** — `packages/motion-engines/core/api.mjs#createMotion` with a
  virtual clock; each frame calls `instance.render({time})`, then the engine canvas is
  composited. One-shot motions get the shot duration; loops keep their own cycle.
- **Reference recipes (Canvas2D)** — `motion-library/expansion/catalog.mjs#sampleMotion`
  drawn by the Universal Motion SDK `packages/motion-sdk/index.mjs#drawScene`.
- **Nextgen camera scenes** — `motion-library/expansion/nextgen-camera.mjs#sampleMotion`
  (CPU perspective projection), drawn by the same SDK.
- **Virtual camera** — keyframes parsed from the reviewed CSS specs, eased with the same
  cubic-bezier curves as CSS, applied as a plate transform with constant overscan.
- **Text** — Canvas2D `fillText` (never HTML), per-language font and direction, auto-fit
  to the title-safe width, scrim band and soft shadow; slide-up + fade in, fade out.

Time never comes from a clock: Python computes `plan.timeline[i]` (layer time/progress,
camera transform, opacity, text opacity and offset, film fade) and the page only executes
it. Each frame's RGBA pixels are hashed in the page (`crypto.subtle`, SHA-256) and the PNG
is piped to ffmpeg. The test renders the same clip twice and compares every hash, and
checks that changing one line changes exactly the frames that show it.

### Inventory (honest, from `cinematic.motion_inventory()`)

| Namespace | Count | Engine |
|---|---|---|
| Native engine motions, `packages/motion-engines` (PR #16) | **34** (all source-bound to the registry) | 23 `webgl2-glsl`, 2 `webgl2-points`, 1 `webgpu-wgsl`, 5 `canvas2d`, 1 `svg`, 1 `dom`, 1 `composition` → 26 GPU-API, 8 CPU |
| Nextgen camera scenes (PR #25) | **3** | Canvas2D, CPU perspective projection |
| **Native total** | **37** | |
| Canvas2D reference recipes, `motion-library/expansion` | **400** (200 basic + 200 advanced) | Canvas2D only — 2D reference scenes, not native engines |
| motion-library CSS/WAAPI components | 30 of 142 indexed | CSS/WAAPI/… |

Reference recipes are never added to the native count. No Three.js/Babylon-class 3D scene
engine is installed (`native_3d_scene_engines: []`).

### GPU — what is and is not proven

`browser_probe()` draws with WebGL2 and reads the pixel back, and runs a WebGPU compute
shader and checks its output. In this environment both **executed on SwiftShader**, a CPU
software rasteriser (`ANGLE … SwiftShader Device (Subzero)`, WebGPU adapter architecture
`swiftshader`, fallback). So: GPU **APIs** ran; **no hardware GPU** was used and none is
claimed (`hardware_gpu: false`). The sample's GLSL motions were rendered the same way.

## 4. Colour grade

Applied by ffmpeg in RGB (`format=gbrp`) before a single BT.709 limited-range 4:2:0
conversion (`scale=…:out_color_matrix=bt709:out_range=tv`), tagged bt709/bt709/bt709:

| Grade | Filters |
|---|---|
| `gaie-teal-amber` | `curves=master='0/0.012 0.25/0.235 0.75/0.77 1/0.985'` (lifted blacks, rolled-off highlights), `colorbalance=rs=-0.035:gs=-0.008:bs=0.045:rh=0.035:gh=0.008:bh=-0.03` (teal shadows, warm highlights), `vignette=angle=0.38`; then `eq=contrast=1.03:saturation=1.08` |
| `neutral` | BT.709 conversion only |

Contrast is measured before the grade (the grade lowers the edges slightly through the
vignette; text is kept inside the title-safe area).

## 5. Audio

All audio is generated in code (`synthesize_audio`, Python standard library: additive
wavetables, xorshift noise, closed-form envelopes, 48 kHz stereo). No samples, loops,
recordings or third-party audio are used, so the licence is this repository's MIT.

- **Music bed**: one chord per shot (Dm9 → B♭maj9 → Fmaj9 → C6/9 → Gm9, resolving to
  Dm(add9) on the last shot), so harmony changes exactly on the cut; detuned pad, bass
  entering on the first cut and pulsing on the beat, sixteenth-note arpeggio, ping-pong echo.
- **Sound design**: an impact (110 → 42 Hz sub sweep, 1.5 ms attack, noise transient)
  starting on the exact sample of every hard cut; a filtered-noise whoosh rising into it;
  a soft boom at frame 0.
- **Voiceover**: `voiceover_capability()` looks for espeak, espeak-ng, pico2wave, flite,
  piper, festival and for ffmpeg's `flite` filter. Here only **ffmpeg libflite (CMU Flite,
  English voices)** exists, so English voiceover is synthesised locally (BSD-style licence)
  and placed 300 ms into each shot with −7 dB music ducking. **Arabic voiceover: not
  available here** (no local Arabic TTS). No paid or network TTS is ever called.
- **Mastering**: delay-compensated look-ahead limiter (`alimiter … latency=1`), then
  two-pass `loudnorm` (I −16 LUFS, TP −2 dBTP, linear when achievable — it is for the
  sample) for AAC headroom.

## 6. Audio/picture sync

Cuts are integer frames; impacts start at `cut_frame × 48000 / fps`, so the plan is exact
by construction. QA then **measures the delivered file**: hard cuts are located as the
strongest frame difference (decoded at 64×36 grey) within ±2 frames and must be at the
planned frame with ≥ 3× the local median difference; audio onsets are the sharpest
1 ms-peak rise over the preceding 20 ms within ±60 ms. `|onset − cut| ≤ 1 frame`
(33.3 ms at 30 fps; stricter than EBU R37's +40/−60 ms). The sample measures 0–2 ms.

## 7. Subtitles

`subtitle_cues` derives one cue per shot and language from the storyboard text: start =
first frame the text appears, end = its last frame (frame-aligned), ≥ 2 frames between
cues, ≤ 2 lines × 42 characters (balanced wrap), ≥ 833 ms, ≤ 7 s, reading speed ≤ 17 (ar)
/ 20 (en) cps. Arabic lines start with U+200F RLM so a Latin-first line (e.g. “GAIE OS —
…”) still reads right to left in any player. Files: `<name>.<lang>.vtt` (WebVTT with
`Kind`/`Language` header) and `<name>.<lang>.srt`, sidecar only; `check_subtitles` parses
them back and verifies all of the above.

## 8. Encoding

One ffmpeg process reads the PNG frames from the renderer's stdout and writes both
variants: libx264 `preset medium`, `yuv420p`, BT.709 tags, keyframes forced on every cut,
GOP 2 s, `+faststart`, `-map_metadata -1`, bitexact flags; AAC-LC 48 kHz stereo.

| Variant | Size | Video | Audio |
|---|---|---|---|
| main | storyboard size (sample 1920×1080) | High profile, CRF 18 | 192 kb/s |
| mobile | 1280×720 for 1080p sources (else half size) | Main profile, CRF 21 | 128 kb/s |

Media is written only outside the repository (`render` refuses a directory inside it).

## 9. Media QA (`qa_media`) — every value is measured on the file

| Check | Expectation |
|---|---|
| `container.mp4`, `container.faststart` | MP4; top-level `moov` before `mdat` (parsed from the box headers) |
| `video.codec`, `.profile`, `.pix_fmt` | h264, High (main) / Main (mobile), yuv420p |
| `video.dimensions`, `video.fps` | exact; `r_frame_rate` and `avg_frame_rate` = fps/1 |
| `video.frame_count`, `video.duration` | decoded frame count exact (`-count_frames`); duration within 1 frame |
| `video.color_bt709`, `video.bitrate` | bt709 matrix/transfer/primaries; ≤ 16 Mb/s (1080) / 8 Mb/s (720) |
| `audio.present`, `.codec`, `.format`, `.duration` | one AAC-LC stream, 48 kHz stereo, within 50 ms of the video |
| `audio.loudness`, `audio.true_peak` | −16 LUFS ± 1 LU integrated; true peak ≤ −1 dBTP (ffmpeg `ebur128=peak=true`, ITU-R BS.1770) |
| `subtitles.no_stream`, `subtitles.not_burned` | no subtitle stream; nothing burned in unless requested |
| `edit.cuts_at_planned_frames`, `sync.audio_on_cuts` | see §6 |

Tests prove the checks fail on real defective files (25 fps, wrong size or frame count,
no audio, no faststart, a mov_text stream, −30 LUFS audio, no cut/transient where planned).

## 10. Acceptance Scenario C

`python3 -m engineering_os.video_pipeline render sample --out <state>/media --name gaie-sample --manifest docs/evidence/gaie-20-layers/video-sample.json`

The built-in storyboard “GAIE OS: one command, a working system” (14 s, 5 shots,
Arabic primary + English, 120 bpm) uses two native GLSL engine motions
(`quantum-light-tunnel`, `atmosphere-core-ignition`), two Canvas2D reference recipes
(`os-networks-b01`, `os-storytelling-b09`) and one nextgen camera scene
(`camera-drone-approach`). Outputs: `gaie-sample.mp4` (1920×1080), `gaie-sample-720p.mp4`
(1280×720) and four subtitle sidecars, outside Git. The committed manifest records their
SHA-256, size, duration, streams, every QA result, the sync table, the frame-hash chain,
every motion with the SHA-256 of the source files the browser actually loaded, the camera
specs, renderer/compositor digests, tool versions, the GPU probe and the inventory.

Measured on this machine: 1080p MP4 7 168 115 bytes, 720p 2 707 392 bytes, 14.000 s,
420 frames, −15.9 / −16.0 LUFS, true peak −4.0 / −4.3 dBTP, A/V offsets on the four cuts
2, 1, 0, 1 ms (main) and 2, 1, 2, 1 ms (mobile), minimum text contrast 5.95 : 1, loudnorm
in linear mode. Two independent full renders (a trial and the evidence run) produced
byte-identical MP4s (SHA-256 `90614bd2…` / `c2325592…`) — reproducibility on one machine,
not a cross-machine claim.

`tests/test_video_pipeline.py` runs the same storyboard end to end at preview size
(640×360 + 320×180, all 420 frames, audio, voiceover, subtitles, both encodes, full QA) in
the default suite (~25 s), checks that the committed manifest is bound to the current
sources, and re-hashes and re-measures the delivered 1080p/720p files when they are present
(`GAIE_STATE_DIR`, default `/home/user/gaie-state`). The full 1080p render takes ~2 min on
4 shared CPUs and is run through the CLI above.

## 11. Proven vs not proven

Proven here (by tests and the manifest): deterministic headless frame rendering of real
repository motions; same input → same frame hashes; real playable H.264/AAC MP4s at the
stated formats with faststart; loudness and true peak; cuts at planned frames and audio
transients within 1 frame of them; bilingual WebVTT/SRT with correct RTL marking; Arabic
shaping, RTL order and fonts in the renderer; no network requests from the page.

Not proven / not claimed:

- **Hardware GPU** rendering — WebGL2/WebGPU ran on SwiftShader (CPU) here.
- **Arabic voiceover** — no local Arabic TTS; English is CMU Flite (intelligible, robotic,
  not broadcast quality).
- **Licensed music** — none; the bed is procedural and only as good as its synthesis.
- Real-device playback, HDR, broadcast loudness (EBU R128 −23 LUFS), burned-in or embedded
  subtitles, DOM/SVG/composition engine motions in the compositor, byte-identical MP4s
  across machines (frames and QA are deterministic here; encoder builds differ).

## 12. Interfaces

- Python: `validate_storyboard`, `build_plan`, `direct`, `browser_direction`,
  `subtitle_cues`, `render_vtt`, `render_srt`, `parse_subtitles`, `check_subtitles`,
  `synthesize_audio`, `master_loudness`, `voiceover_capability`, `browser_probe`,
  `hash_frames`, `render`, `qa_media`, `loudness`, `mp4_atoms`, `build_manifest`,
  `render_sample`, `inventory`; errors `StoryboardError`, `DirectionError` (`.report`),
  `RenderError`, `ToolMissing` (all `VideoPipelineError`).
- Engine contract: `video_pipeline.ENGINE_RECORD` (`cinematic-production`, layer L18;
  validates with `contracts.validate_engine(check_imports=True)`), entrypoint
  `engineering_os.video_pipeline:engine(action, payload, ctx)` with actions `inventory`,
  `validate`, `direct`, `subtitles`, `probe` (side effect none) and `render`
  (`state-write`, writes only outside Git), `qa`; health `engineering_os.video_pipeline:health`.
- CLI: `python3 -m engineering_os.video_pipeline {validate|direct|plan|subtitles|probe|inventory|render|qa} …`
  (`sample` names the built-in storyboard).
