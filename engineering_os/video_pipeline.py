"""Cinematic production pipeline (layers L08 cinematic intelligence / L18 media production).

storyboard (gaie.storyboard/1, bilingual ar/en) -> cinematic direction checks -> headless
frame rendering of real motion sources -> colour grade -> procedural music + sound design
(+ local voiceover where a local TTS exists) -> audio/picture sync on scene cuts ->
WebVTT/SRT sidecars -> H.264/AAC MP4 (main + mobile variant) -> media QA with ffprobe/ebur128.

Everything is deterministic and offline. Time is never read from a clock while drawing:
frame i is drawn from plan.timeline[i], so the same storyboard always yields the same
frames (checked by SHA-256 of every frame's RGBA pixels). Motion sources are the ones in
the repository: the native engines of packages/motion-engines (registry-bound), the 400
Canvas2D reference recipes of motion-library/expansion and the nextgen camera scenes.
No paid service, network request, model call or provider API is used: the browser page
may only load allowlisted repository modules, and every other request is refused and
counted. Media is written outside the repository; only a JSON manifest may be committed.

Python standard library only. External tools of the machine: ffmpeg/ffprobe, node with
Playwright and its Chromium. Their absence raises ToolMissing; it never fakes a result.
SPDX-License-Identifier: MIT
"""
import argparse
import array
import copy
import datetime as dt
import hashlib
import json
import math
import os
import pathlib
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import unicodedata
import wave

from . import cinematic
from .contracts import sha256 as canonical_sha256

ROOT = cinematic.ROOT
SCHEMA = "gaie.storyboard/1"
EVIDENCE_SCHEMA = "gaie.video-evidence/1"
DIRECTION_SCHEMA = "gaie.direction/1"
QA_SCHEMA = "gaie.media-qa/1"
VERSION = "1.0.0"

LANGUAGES = ("ar", "en")
FPS_ALLOWED = (24, 25, 30, 50, 60)
SAMPLE_RATE = 48000
REGISTRY = "packages/motion-engines/registry.json"
REFERENCE_DEFINITIONS = "motion-library/expansion/definitions.json"
REFERENCE_SOURCES = ("motion-library/expansion/catalog.mjs", "motion-library/expansion/families.mjs",
                     "motion-library/expansion/systems.mjs", "motion-library/expansion/geometry.mjs")
CAMERA_SOURCE = cinematic.CAMERA_SOURCE
SDK_SOURCE = "packages/motion-sdk/index.mjs"
ALLOWED_PREFIXES = ("motion-library/expansion/", "packages/motion-sdk/", "packages/motion-engines/core/",
                    "packages/motion-engines/engines/", "packages/motion-engines/shaders/",
                    "packages/motion-engines/motions/")
# Engines the compositor can read back from one canvas. DOM/SVG/layered compositions need
# screenshot capture and are refused rather than captured approximately.
RENDERABLE_ENGINES = frozenset({"canvas2d", "webgl2-glsl", "webgl2-points", "webgpu-wgsl"})
GPU_API_ENGINES = frozenset({"webgl2-glsl", "webgl2-points", "webgpu-wgsl"})

# Virtual camera moves reuse the reviewed CSS motion specifications of motion-library/specs.
CAMERA_MOVES = {
    "static": None,
    "cinema-dolly-in": "motion-library/specs/cinema-dolly-in.json",
    "cinema-dolly-out": "motion-library/specs/cinema-dolly-out.json",
    "cinema-truck-left": "motion-library/specs/cinema-truck-left.json",
    "cinema-truck-right": "motion-library/specs/cinema-truck-right.json",
    "cinema-crane-rise": "motion-library/specs/cinema-crane-rise.json",
    "cinema-rack-focus": "motion-library/specs/cinema-rack-focus.json",
}
NATIVE_TIMING_MOVES = frozenset({"cinema-rack-focus"})  # play at their spec duration, others fit the shot
MAX_OVERSCAN = 1.2
CSS_EASING = {"linear": (0.0, 0.0, 1.0, 1.0), "ease": (0.25, 0.1, 0.25, 1.0), "ease-in": (0.42, 0.0, 1.0, 1.0),
              "ease-out": (0.0, 0.0, 0.58, 1.0), "ease-in-out": (0.42, 0.0, 0.58, 1.0)}

# Typography: system fonts of the rendering machine, rasterised into frames, never shipped.
FONTS = {"ar": {"family": "DejaVu Sans", "css": '"DejaVu Sans"', "license": "Bitstream Vera / DejaVu (free)"},
         "en": {"family": "Inter", "css": '"Inter"', "license": "SIL Open Font License 1.1"}}
TEXT_COLORS = ("#f8fafc", "#e2e8f0")
TEXT_POSITIONS = {"center": 0.5, "lower-third": 0.74, "upper-third": 0.27}

# Direction thresholds. Reading speeds follow common subtitle practice (adult programmes):
# at most 17 characters/second for Arabic and 20 for English, combining marks not counted.
DIRECTION = {
    "title_safe": 0.90,           # graphics/title-safe area (EBU R95 / SMPTE ST 2046-1): 5 % margins
    "min_shot_ms": 1000, "max_shot_ms": 10000, "min_text_shot_ms": 1500,
    "min_reading_ms": 1000, "max_cps": {"ar": 17.0, "en": 20.0},
    "text_in_ms": 300, "text_fade_in_ms": 400, "text_fade_out_ms": 300, "text_out_ms": 150,
    "primary_size": 0.074, "secondary_size": 0.046, "min_text_size": 0.03,
    "min_contrast": 4.5,          # WCAG 2 AA, measured at the 95th-percentile background luminance
    "scrim_alpha": 0.72, "slide_px": 0.022,
    "vo_offset_ms": 300, "vo_tail_ms": 150,
    "subtitle_min_ms": 833, "subtitle_max_ms": 7000, "subtitle_line_chars": 42, "subtitle_lines": 2,
    "subtitle_gap_frames": 2,
}

# Media QA thresholds. Loudness: -16 LUFS integrated +-1 LU (common online/mobile delivery
# target), true peak <= -1 dBTP; ITU-R BS.1770 / EBU R128 measurement by ffmpeg ebur128.
QA = {"loudness_lufs": -16.0, "loudness_tolerance_lu": 1.0, "true_peak_max_dbtp": -1.0,
      "audio_rate": SAMPLE_RATE, "audio_channels": 2, "audio_duration_tolerance_s": 0.05,
      "sync_tolerance_frames": 1, "cut_strength": 3.0, "onset_ratio": 2.0,
      "max_video_kbps": {"1080": 16000, "720": 8000, "other": 8000}}

# Colour grades: ffmpeg filters, applied in RGB before the BT.709 YUV conversion.
GRADES = {
    "gaie-teal-amber": {
        "summary": "Filmic lift/roll-off curve, teal shadows + warm highlights, gentle vignette, +8 % saturation.",
        "rgb": ["curves=master='0/0.012 0.25/0.235 0.75/0.77 1/0.985'",
                "colorbalance=rs=-0.035:gs=-0.008:bs=0.045:rh=0.035:gh=0.008:bh=-0.03",
                "vignette=angle=0.38"],
        "yuv": ["eq=contrast=1.03:saturation=1.08"]},
    "neutral": {"summary": "No creative grade; BT.709 conversion only.", "rgb": [], "yuv": []},
}

# Music: a chord per shot so harmony changes exactly on the cut; the last shot resolves home.
PROGRESSION = (("Dm9", 38, (50, 57, 60, 64, 65)), ("Bbmaj9", 34, (46, 53, 57, 60, 62)),
               ("Fmaj9", 41, (53, 57, 60, 64, 67)), ("C6/9", 36, (48, 55, 57, 62, 64)),
               ("Gm9", 43, (55, 58, 62, 65, 69)))
HOME_CHORD = ("Dm(add9)", 38, (50, 57, 62, 64, 65))
AUDIO_LICENSE = ("Procedurally synthesised by engineering_os/video_pipeline.py (MIT, this repository): "
                 "additive wavetables, xorshift noise and closed-form envelopes. No samples, loops, "
                 "recordings or third-party audio are used.")
FLITE_LICENSE = ("CMU Flite via ffmpeg libflite (BSD-style permissive licence, voices from CMU ARCTIC "
                 "under the same terms); synthesised locally, no network or provider.")

_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_ARABIC = re.compile("[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]")
_LATIN = re.compile("[A-Za-z]")
_BIDI_CONTROLS = re.compile("[\u061C\u200E\u200F\u202A-\u202E\u2066-\u2069]")
_SAFE_PATH = re.compile(r"^[A-Za-z0-9/_.\-]+$")
RLM = "\u200F"


class VideoPipelineError(ValueError):
    """Base error of the media pipeline."""


class StoryboardError(VideoPipelineError):
    """The storyboard does not satisfy gaie.storyboard/1."""


class DirectionError(VideoPipelineError):
    """Cinematic direction checks failed; .report holds every check."""

    def __init__(self, message, report):
        super().__init__(message)
        self.report = report


class RenderError(VideoPipelineError):
    """Rendering, encoding or a tool failed."""


class ToolMissing(RenderError):
    """A required local tool (ffmpeg, ffprobe, node, Playwright/Chromium) is not available."""


# --------------------------------------------------------------------------- utilities

def _need(condition, message, error=StoryboardError):
    if not condition:
        raise error(message)


def _sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def _sha_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _repo_file(relative, root=ROOT):
    """A regular, non-symlinked file inside the repository (mirrors cinematic._file)."""
    path = pathlib.PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts or ".git" in path.parts or str(path) != relative:
        raise VideoPipelineError(f"unsafe repository path: {relative!r}")
    result = pathlib.Path(root)
    for part in path.parts:
        result = result / part
        if result.is_symlink():
            raise VideoPipelineError(f"symlinked source refused: {relative}")
    if not result.is_file():
        raise VideoPipelineError(f"missing source: {relative}")
    return result


def _tool(name):
    found = shutil.which(name)
    if not found:
        raise ToolMissing(f"{name} is required and was not found on PATH")
    return found


def _run(command, *, timeout=600, stdin=None, binary=False):
    try:
        done = subprocess.run(command, input=stdin, capture_output=True, timeout=timeout, check=False)
    except FileNotFoundError as error:
        raise ToolMissing(str(error)) from error
    except subprocess.TimeoutExpired as error:
        raise RenderError(f"{pathlib.Path(command[0]).name} timed out after {timeout}s") from error
    if done.returncode != 0:
        tail = done.stderr.decode("utf-8", "replace")[-1500:]
        raise RenderError(f"{pathlib.Path(command[0]).name} failed ({done.returncode}): {tail}")
    if binary:
        return done
    return subprocess.CompletedProcess(done.args, done.returncode, done.stdout.decode("utf-8", "replace"),
                                       done.stderr.decode("utf-8", "replace"))


def _member(value, allowed):
    return isinstance(value, str) and value in allowed


def _frames_of(ms, fps, what):
    frames = ms * fps / 1000
    _need(abs(frames - round(frames)) < 1e-9, f"{what}: {ms} ms is not a whole number of frames at {fps} fps")
    return int(round(frames))


def _visible_chars(text):
    return sum(1 for ch in text if not unicodedata.category(ch).startswith("M"))


def _outside_repository(directory, root=ROOT):
    path = pathlib.Path(directory).expanduser()
    _need(path.is_absolute(), "output directory must be an absolute path", RenderError)
    path.mkdir(parents=True, exist_ok=True)
    real, repo = path.resolve(), pathlib.Path(root).resolve()
    if real == repo or repo in real.parents:
        raise RenderError("media must be written outside the repository (only the manifest is committed)")
    return real


def tool_versions():
    versions = {}
    for name, command in (("ffmpeg", ["ffmpeg", "-hide_banner", "-version"]),
                          ("ffprobe", ["ffprobe", "-hide_banner", "-version"]), ("node", ["node", "--version"])):
        if shutil.which(name):
            out = _run(command, timeout=30).stdout.strip().splitlines()
            versions[name] = out[0] if out else "unknown"
        else:
            versions[name] = None
    return versions


# --------------------------------------------------------------------------- catalogs

def load_catalog(root=ROOT):
    """The three distinct motion namespaces a storyboard may name."""
    registry = json.loads(_repo_file(REGISTRY, root).read_text("utf-8"))
    definitions = json.loads(_repo_file(REFERENCE_DEFINITIONS, root).read_text("utf-8"))["definitions"]
    return {"engine": {m["id"]: m for m in registry["motions"]},
            "reference": {d["id"]: d for d in definitions},
            "camera": set(cinematic.CAMERA_IDS)}


def inventory():
    """Honest counts; delegated to the source-bound cinematic inventory."""
    return cinematic.motion_inventory()


def _camera_spec(move, root=ROOT):
    """Parse the reviewed CSS keyframes of a motion-library camera spec into numbers."""
    if move == "static":
        return {"id": "static", "duration_ms": 0, "easing": "linear",
                "keyframes": [{"offset": 0.0, "scale": 1.0, "tx": 0.0, "ty": 0.0, "blur": 0.0},
                              {"offset": 1.0, "scale": 1.0, "tx": 0.0, "ty": 0.0, "blur": 0.0}], "source": None}
    relative = CAMERA_MOVES[move]
    spec = json.loads(_repo_file(relative, root).read_text("utf-8"))
    frames = []
    for key in spec["keyframes"]:
        item = {"offset": float(key["offset"]), "scale": 1.0, "tx": 0.0, "ty": 0.0, "blur": 0.0}
        for function, value in re.findall(r"(scale|translateX|translateY)\(([-\d.]+)%?\)", key.get("transform", "")):
            number = float(value)
            if function == "scale":
                item["scale"] = number
            elif function == "translateX":
                item["tx"] = number / 100
            else:
                item["ty"] = number / 100
        blur = re.fullmatch(r"blur\(([\d.]+)px\)", key.get("filter", "blur(0px)"))
        _need(blur is not None, f"{move}: unsupported filter", VideoPipelineError)
        item["blur"] = float(blur.group(1))
        frames.append(item)
    _need(spec.get("easing") in CSS_EASING, f"{move}: unsupported easing", VideoPipelineError)
    return {"id": move, "duration_ms": spec["duration_ms"], "easing": spec["easing"], "keyframes": frames,
            "source": relative, "source_sha256": _sha_file(_repo_file(relative, root))}


def css_ease(name, x):
    """CSS cubic-bezier easing (the same curves the browser uses for the camera specs)."""
    x1, y1, x2, y2 = CSS_EASING[name]
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    if (x1, y1, x2, y2) == (0.0, 0.0, 1.0, 1.0):
        return float(x)
    bezier = lambda a, b, t: 3 * a * (1 - t) ** 2 * t + 3 * b * (1 - t) * t ** 2 + t ** 3
    low, high = 0.0, 1.0
    for _ in range(60):
        mid = (low + high) / 2
        if bezier(x1, x2, mid) < x:
            low = mid
        else:
            high = mid
    return bezier(y1, y2, (low + high) / 2)


# --------------------------------------------------------------------------- storyboard

_TOP = {"schema", "id", "title", "languages", "primary_language", "format", "scenes", "audio", "grade",
        "fade_in_ms", "fade_out_ms", "subtitles"}
_SCENE = {"id", "duration_ms", "motion", "camera", "transition_in", "dissolve_ms", "text", "text_position", "voiceover"}


def _text(value, lang, where):
    _need(isinstance(value, str) and value == value.strip() and 1 <= len(value) <= 90,
          f"{where}: text must be 1-90 characters without surrounding spaces")
    _need(not any(unicodedata.category(ch) in {"Cc", "Cf"} and ch not in "\u200C\u200D" for ch in value)
          and not _BIDI_CONTROLS.search(value),
          f"{where}: control and bidirectional override characters are refused")
    if lang == "ar":
        _need(_ARABIC.search(value), f"{where}: Arabic text must contain Arabic script")
    else:
        _need(not _ARABIC.search(value) and _LATIN.search(value), f"{where}: English text must be Latin script")
    return unicodedata.normalize("NFC", value)


def validate_storyboard(storyboard, root=ROOT):
    """Strict closed-schema validation; returns a normalised deep copy with defaults filled."""
    _need(isinstance(storyboard, dict), "storyboard: object required")
    unknown = set(storyboard) - _TOP
    _need(not unknown, f"storyboard: unknown fields {sorted(unknown)}")
    _need(storyboard.get("schema") == SCHEMA, f"storyboard.schema must be {SCHEMA!r}")
    sb = copy.deepcopy(storyboard)
    _need(isinstance(sb.get("id"), str) and _SLUG.match(sb["id"]), "storyboard.id: lowercase slug required")
    languages = sb.get("languages")
    _need(isinstance(languages, list) and 1 <= len(languages) <= 2 and all(_member(x, LANGUAGES) for x in languages)
          and len(set(languages)) == len(languages), "storyboard.languages: 1-2 of ['ar', 'en']")
    sb.setdefault("primary_language", languages[0])
    _need(_member(sb["primary_language"], languages), "storyboard.primary_language must be one of languages")
    title = sb.get("title")
    _need(isinstance(title, dict) and set(title) == set(languages), "storyboard.title: one entry per language")
    sb["title"] = {lang: _text(title[lang], lang, f"title.{lang}") for lang in languages}
    fmt = sb.get("format")
    _need(isinstance(fmt, dict) and set(fmt) == {"width", "height", "fps"}, "format: width, height, fps required")
    for key, low, high in (("width", 320, 3840), ("height", 180, 2160)):
        _need(type(fmt[key]) is int and low <= fmt[key] <= high and fmt[key] % 2 == 0, f"format.{key}: even integer {low}-{high}")
    _need(type(fmt["fps"]) is int and fmt["fps"] in FPS_ALLOWED, f"format.fps must be one of {FPS_ALLOWED}")
    fps = fmt["fps"]
    for key, default in (("fade_in_ms", 0), ("fade_out_ms", 0)):
        value = sb.setdefault(key, default)
        _need(type(value) is int and 0 <= value <= 2000, f"{key}: integer 0-2000")
        _frames_of(value, fps, key)
    sb.setdefault("grade", "gaie-teal-amber")
    _need(_member(sb["grade"], GRADES), f"grade must be one of {sorted(GRADES)}")
    subtitles = sb.setdefault("subtitles", {"burn_in": False, "embed": False})
    _need(isinstance(subtitles, dict) and set(subtitles) <= {"burn_in", "embed"}, "subtitles: burn_in, embed")
    subtitles.setdefault("burn_in", False)
    subtitles.setdefault("embed", False)
    _need(subtitles["burn_in"] is False and subtitles["embed"] is False,
          "subtitles: this pipeline delivers sidecar WebVTT/SRT only (burn_in/embed must be false)")
    audio = sb.setdefault("audio", {})
    _need(isinstance(audio, dict) and set(audio) <= {"bpm", "music", "sound_design", "voiceover"},
          "audio: bpm, music, sound_design, voiceover")
    audio.setdefault("bpm", 120)
    audio.setdefault("music", True)
    audio.setdefault("sound_design", True)
    audio.setdefault("voiceover", None)
    _need(type(audio["bpm"]) is int and 60 <= audio["bpm"] <= 180, "audio.bpm: integer 60-180")
    _need(type(audio["music"]) is bool and type(audio["sound_design"]) is bool, "audio.music/sound_design: booleans")
    voice = audio["voiceover"]
    if voice is not None:
        _need(isinstance(voice, dict) and set(voice) == {"language", "voice"}, "audio.voiceover: language and voice")
        _need(_member(voice["language"], languages), "audio.voiceover.language must be a storyboard language")
        _need(_member(voice["voice"], {"slt", "kal", "awb", "rms", "kal16"}), "audio.voiceover.voice: a local Flite voice")
    scenes = sb.get("scenes")
    _need(isinstance(scenes, list) and 1 <= len(scenes) <= 40, "scenes: 1-40 required")
    catalog = load_catalog(root)
    seen = set()
    for index, scene in enumerate(scenes):
        where = f"scenes[{index}]"
        _need(isinstance(scene, dict), f"{where}: object required")
        unknown = set(scene) - _SCENE
        _need(not unknown, f"{where}: unknown fields {sorted(unknown)}")
        _need(isinstance(scene.get("id"), str) and _SLUG.match(scene["id"]) and scene["id"] not in seen,
              f"{where}.id: unique lowercase slug required")
        seen.add(scene["id"])
        duration = scene.get("duration_ms")
        _need(type(duration) is int and DIRECTION["min_shot_ms"] <= duration <= DIRECTION["max_shot_ms"],
              f"{where}.duration_ms: integer {DIRECTION['min_shot_ms']}-{DIRECTION['max_shot_ms']}")
        _frames_of(duration, fps, f"{where}.duration_ms")
        scene["motion"] = _validate_motion(scene.get("motion"), catalog, f"{where}.motion", root)
        scene.setdefault("camera", "static")
        _need(_member(scene["camera"], CAMERA_MOVES), f"{where}.camera must be one of {sorted(CAMERA_MOVES)}")
        scene.setdefault("transition_in", "cut")
        _need(_member(scene["transition_in"], {"cut", "dissolve"}), f"{where}.transition_in: cut or dissolve")
        if scene["transition_in"] == "dissolve":
            _need(index > 0, f"{where}: the first shot cannot dissolve in")
            dissolve = scene.setdefault("dissolve_ms", 500)
            _need(type(dissolve) is int and 200 <= dissolve <= 1000, f"{where}.dissolve_ms: 200-1000")
            _need(dissolve * 2 <= min(duration, scenes[index - 1].get("duration_ms", 0)),
                  f"{where}.dissolve_ms: at most half of each adjacent shot")
        else:
            _need("dissolve_ms" not in scene, f"{where}.dissolve_ms only with transition_in dissolve")
        text = scene.get("text")
        _need(isinstance(text, dict) and set(text) == set(languages), f"{where}.text: one line per storyboard language")
        scene["text"] = {lang: _text(text[lang], lang, f"{where}.text.{lang}") for lang in languages}
        scene.setdefault("text_position", "center")
        _need(_member(scene["text_position"], TEXT_POSITIONS), f"{where}.text_position: {sorted(TEXT_POSITIONS)}")
        if "voiceover" in scene:
            _need(voice is not None, f"{where}.voiceover requires audio.voiceover")
            vo = scene["voiceover"]
            _need(vo is None or (isinstance(vo, dict) and set(vo) == {voice["language"]}),
                  f"{where}.voiceover: null or one line in the voiceover language")
            if vo is not None:
                scene["voiceover"] = {voice["language"]: _text(vo[voice["language"]], voice["language"], f"{where}.voiceover")}
    total = sum(scene["duration_ms"] for scene in scenes)
    _need(total <= 120000, "storyboard: at most 120 s")
    _need(sb["fade_in_ms"] <= scenes[0]["duration_ms"] // 2 and sb["fade_out_ms"] <= scenes[-1]["duration_ms"] // 2,
          "fades: at most half of the first/last shot")
    return sb


def _validate_motion(motion, catalog, where, root):
    _need(isinstance(motion, dict) and _member(motion.get("source"), {"engine", "reference", "camera"}),
          f"{where}: source engine | reference | camera")
    allowed = {"source", "id", "params", "render_scale"} if motion["source"] == "engine" else {"source", "id", "render_scale"}
    _need(set(motion) <= allowed and isinstance(motion.get("id"), str), f"{where}: fields {sorted(allowed)}")
    motion = dict(motion)
    identifier = motion["id"]
    _need(isinstance(identifier, str), f"{where}.id: string")
    if motion["source"] == "engine":
        entry = catalog["engine"].get(identifier)
        _need(entry is not None, f"{where}: unknown native engine motion {identifier!r}")
        _need(entry["engine"] in RENDERABLE_ENGINES,
              f"{where}: {identifier} uses the {entry['engine']} engine, which the frame compositor cannot read back")
        source = _repo_file(entry["source"], root)
        _need(_sha_file(source) == entry["source_sha256"],
              f"{where}: {identifier} source changed since its registry/browser evidence", VideoPipelineError)
        params = motion.setdefault("params", {})
        schema = entry["controls"]["parameters"]
        _need(isinstance(params, dict) and set(params) <= set(schema), f"{where}.params: only {sorted(schema)}")
        for name, value in params.items():
            spec = schema[name]
            _need(type(value) in {int, float} and math.isfinite(value) and spec["min"] <= value <= spec["max"],
                  f"{where}.params.{name}: {spec['min']}-{spec['max']}")
        motion.setdefault("render_scale", 0.75 if entry["engine"] in GPU_API_ENGINES else 1.0)
    elif motion["source"] == "reference":
        _need(identifier in catalog["reference"], f"{where}: unknown reference motion {identifier!r}")
        motion.setdefault("render_scale", 1.0)
    else:
        _need(identifier in catalog["camera"], f"{where}: unknown nextgen camera scene {identifier!r}")
        motion.setdefault("render_scale", 1.0)
    scale = motion["render_scale"]
    _need(type(scale) in {int, float} and 0.5 <= scale <= 1.0, f"{where}.render_scale: 0.5-1.0")
    return motion


def scene_times(sb):
    fps = sb["format"]["fps"]
    rows, start = [], 0
    for index, scene in enumerate(sb["scenes"]):
        frames = _frames_of(scene["duration_ms"], fps, scene["id"])
        rows.append({"index": index, "id": scene["id"], "start_frame": start, "frames": frames,
                     "start_ms": start * 1000 / fps, "end_ms": (start + frames) * 1000 / fps,
                     "transition_in": scene["transition_in"]})
        start += frames
    return rows


def text_window(sb, index):
    """Frame-aligned fade-in start, fade-out end and reading window of a shot's text (ms, shot-local)."""
    fps, scene, scenes = sb["format"]["fps"], sb["scenes"][index], sb["scenes"]
    frame_ms = 1000 / fps
    snap = lambda ms: round(ms / frame_ms) * frame_ms
    incoming = scene.get("dissolve_ms", 0) // 2 if scene["transition_in"] == "dissolve" else 0
    outgoing = scenes[index + 1].get("dissolve_ms", 0) // 2 if index + 1 < len(scenes) and scenes[index + 1]["transition_in"] == "dissolve" else 0
    fade_in, fade_out = DIRECTION["text_fade_in_ms"], DIRECTION["text_fade_out_ms"]
    start = snap(max(DIRECTION["text_in_ms"], incoming + 100))
    end = snap(scene["duration_ms"] - max(DIRECTION["text_out_ms"], outgoing + 100))
    return {"in_start": start, "in_end": start + fade_in, "out_start": end - fade_out, "out_end": end,
            "reading_ms": (end - fade_out / 2) - (start + fade_in / 2)}


# --------------------------------------------------------------------------- plan

def build_plan(sb, root=ROOT):
    """Per-frame timeline: layers (motion time/progress, camera transform, opacity), text and fades."""
    W, H, fps = sb["format"]["width"], sb["format"]["height"], sb["format"]["fps"]
    frame_ms = 1000 / fps
    times = scene_times(sb)
    total = times[-1]["start_frame"] + times[-1]["frames"]
    catalog = load_catalog(root)
    cameras, scenes_out, blocks = [], [], []
    for row, scene in zip(times, sb["scenes"]):
        spec = _camera_spec(scene["camera"], root)
        reach = max(max(abs(k["tx"]), abs(k["ty"])) for k in spec["keyframes"])
        cover = 1 + 2 * reach
        _need(cover * max(k["scale"] for k in spec["keyframes"]) <= MAX_OVERSCAN + 1e-9,
              f"{scene['id']}: camera move needs more than {MAX_OVERSCAN}x overscan", VideoPipelineError)
        cameras.append({**spec, "cover": cover})
        motion = scene["motion"]
        entry = {"source": motion["source"], "id": motion["id"], "render_scale": motion["render_scale"], "options": {}}
        if motion["source"] == "engine":
            registry = catalog["engine"][motion["id"]]
            entry["module"] = "/" + registry["source"]
            entry["kind"] = registry["kind"]
            entry["engine"] = registry["engine"]
            if motion.get("params"):
                entry["options"]["params"] = dict(motion["params"])
            if registry["kind"] == "oneshot":
                entry["options"]["duration"] = scene["duration_ms"]
            if registry["engine"] == "webgpu-wgsl":
                entry["options"]["gpu"] = "readback"
        scenes_out.append({"id": scene["id"], "motion": entry})
        lines = []
        order = [sb["primary_language"]] + [x for x in sb["languages"] if x != sb["primary_language"]]
        for rank, lang in enumerate(order):
            lines.append({"lang": lang, "dir": "rtl" if lang == "ar" else "ltr", "text": scene["text"][lang],
                          "size_px": round(H * (DIRECTION["primary_size"] if rank == 0 else DIRECTION["secondary_size"])),
                          "weight": 700 if rank == 0 else 600, "color": TEXT_COLORS[min(rank, 1)]})
        blocks.append({"scene": row["index"], "center_y": round(H * TEXT_POSITIONS[scene["text_position"]]), "lines": lines})
    timeline = []
    slide = round(H * DIRECTION["slide_px"])
    for frame in range(total):
        layers, texts = [], []
        for row, scene, camera in zip(times, sb["scenes"], cameras):
            local = (frame - row["start_frame"]) * frame_ms
            opacity = 0.0
            if 0 <= frame - row["start_frame"] < row["frames"]:
                opacity = 1.0
            following = row["index"] + 1 < len(times) and sb["scenes"][row["index"] + 1]["transition_in"] == "dissolve"
            if scene["transition_in"] == "dissolve":
                half = scene["dissolve_ms"] / 2
                if -half <= local < half:
                    opacity = css_ease("ease-in-out", (local + half) / (2 * half))
            if following:
                half = sb["scenes"][row["index"] + 1]["dissolve_ms"] / 2
                if row["end_ms"] - row["start_ms"] - half <= local < scene["duration_ms"] + half:
                    opacity = 1.0  # the incoming shot is blended on top
            if opacity <= 0:
                continue
            duration = scene["duration_ms"]
            if camera["id"] in NATIVE_TIMING_MOVES:
                progress = css_ease(camera["easing"], local / camera["duration_ms"])
            else:
                progress = css_ease(camera["easing"], local / duration)
            keys = camera["keyframes"]
            for a, b in zip(keys, keys[1:]):
                if progress <= b["offset"] or b is keys[-1]:
                    span = (b["offset"] - a["offset"]) or 1.0
                    u = min(1.0, max(0.0, (progress - a["offset"]) / span))
                    value = {k: a[k] + (b[k] - a[k]) * u for k in ("scale", "tx", "ty", "blur")}
                    break
            layers.append({"scene": row["index"], "time_ms": round(max(0.0, local), 4),
                           "progress": round(min(1.0, max(0.0, local / duration)), 6), "opacity": round(opacity, 6),
                           "camera": {"scale": round(value["scale"] * camera["cover"], 6), "tx": round(value["tx"], 6),
                                      "ty": round(value["ty"], 6), "blur": round(value["blur"] * H / 720, 3)}})
            window = text_window(sb, row["index"])
            if window["in_start"] <= local < window["out_end"]:
                if local < window["in_end"]:
                    u = css_ease("ease-out", (local - window["in_start"]) / (window["in_end"] - window["in_start"]))
                    alpha, dy = u, (1 - u) * slide
                elif local >= window["out_start"]:
                    alpha, dy = 1 - css_ease("ease-in", (local - window["out_start"]) / (window["out_end"] - window["out_start"])), 0.0
                else:
                    alpha, dy = 1.0, 0.0
                if alpha > 0:
                    texts.append({"scene": row["index"], "opacity": round(alpha, 6), "dy": round(dy, 3)})
        layers.sort(key=lambda layer: (layer["opacity"] < 1, layer["scene"]))
        t = frame * frame_ms
        end = total * frame_ms
        fade = 0.0
        if sb["fade_in_ms"] and t < sb["fade_in_ms"]:
            fade = 1 - t / sb["fade_in_ms"]
        if sb["fade_out_ms"] and t >= end - sb["fade_out_ms"]:
            fade = max(fade, (t + frame_ms - (end - sb["fade_out_ms"])) / sb["fade_out_ms"])
        timeline.append({"layers": layers, "texts": texts, "fade": round(min(1.0, fade), 6)})
    margin_x, margin_y = (1 - DIRECTION["title_safe"]) / 2 * W, (1 - DIRECTION["title_safe"]) / 2 * H
    return {"schema": "gaie.render-plan/1", "width": W, "height": H, "fps": fps, "frames": total,
            "duration_ms": total * frame_ms, "scenes": scenes_out, "text_blocks": blocks, "timeline": timeline,
            "cuts": [{"frame": r["start_frame"], "ms": r["start_ms"], "kind": r["transition_in"], "scene": r["id"]}
                     for r in times[1:]],
            "safe": {"x0": margin_x, "y0": margin_y, "x1": W - margin_x, "y1": H - margin_y},
            "scrim_alpha": DIRECTION["scrim_alpha"], "slide_px": slide,
            "fonts": {lang: FONTS[lang]["css"] for lang in LANGUAGES},
            "cameras": [{"id": c["id"], "source": c["source"], "source_sha256": c.get("source_sha256"), "cover": c["cover"]} for c in cameras]}


# --------------------------------------------------------------------------- direction

def _check(checks, identifier, passed, value=None, threshold=None, *, scene=None, severity="error", detail=None):
    status = "pass" if passed else ("fail" if severity == "error" else "warn")
    row = {"id": identifier, "status": status}
    if scene is not None:
        row["scene"] = scene
    if value is not None:
        row["value"] = value
    if threshold is not None:
        row["threshold"] = threshold
    if detail:
        row["detail"] = detail
    checks.append(row)
    return row


def _report(checks, extra=None):
    report = {"schema": DIRECTION_SCHEMA, "passed": not any(c["status"] == "fail" for c in checks),
              "errors": [c for c in checks if c["status"] == "fail"],
              "warnings": [c for c in checks if c["status"] == "warn"], "checks": checks}
    if extra:
        report.update(extra)
    return report


def direct(sb, plan=None):
    """Static cinematic direction checks: pacing, reading time, RTL hygiene, beat alignment, framing."""
    checks = []
    fps = sb["format"]["fps"]
    frame_ms = 1000 / fps
    times = scene_times(sb)
    durations = [s["duration_ms"] for s in sb["scenes"]]
    for scene in sb["scenes"]:
        d = scene["duration_ms"]
        _check(checks, "pacing.shot_length", DIRECTION["min_shot_ms"] <= d <= DIRECTION["max_shot_ms"], d,
               [DIRECTION["min_shot_ms"], DIRECTION["max_shot_ms"]], scene=scene["id"])
        _check(checks, "pacing.text_shot_length", d >= DIRECTION["min_text_shot_ms"], d, DIRECTION["min_text_shot_ms"],
               scene=scene["id"], severity="warn")
    for prev, scene in zip(sb["scenes"], sb["scenes"][1:]):
        _check(checks, "pacing.no_repeated_motion", prev["motion"]["id"] != scene["motion"]["id"], scene["motion"]["id"],
               scene=scene["id"], severity="warn")
    _check(checks, "pacing.average_shot_ms", True, round(statistics.mean(durations), 1))
    for index, scene in enumerate(sb["scenes"]):
        window = text_window(sb, index)
        for lang, text in scene["text"].items():
            chars = _visible_chars(text)
            cps = chars / (window["reading_ms"] / 1000)
            _check(checks, "reading.window_ms", window["reading_ms"] >= DIRECTION["min_reading_ms"],
                   round(window["reading_ms"], 1), DIRECTION["min_reading_ms"], scene=scene["id"])
            _check(checks, f"reading.cps.{lang}", cps <= DIRECTION["max_cps"][lang], round(cps, 2),
                   DIRECTION["max_cps"][lang], scene=scene["id"])
            if lang == "ar":
                _check(checks, "rtl.arabic_script", bool(_ARABIC.search(text)), scene=scene["id"])
                _check(checks, "rtl.no_bidi_overrides", not _BIDI_CONTROLS.search(text), scene=scene["id"])
    cuts = [r for r in times[1:] if r["transition_in"] == "cut"]
    if sb["audio"]["music"]:
        beat_ms = 60000 / sb["audio"]["bpm"]
        for row in cuts:
            offset = row["start_ms"] - round(row["start_ms"] / beat_ms) * beat_ms
            _check(checks, "music.cut_on_beat", abs(offset) <= frame_ms / 2, round(offset, 2), round(frame_ms / 2, 2),
                   scene=row["id"], severity="warn")
    plan = plan or build_plan(sb)
    for camera, scene in zip(plan["cameras"], sb["scenes"]):
        _check(checks, "framing.camera_overscan", camera["cover"] <= MAX_OVERSCAN, round(camera["cover"], 4),
               MAX_OVERSCAN, scene=scene["id"])
    _check(checks, "edit.cut_frames_exact", all(c["frame"] == round(c["ms"] * fps / 1000) for c in plan["cuts"]),
           [c["frame"] for c in plan["cuts"]])
    return _report(checks, {"storyboard": sb["id"], "duration_ms": plan["duration_ms"], "frames": plan["frames"]})


def browser_direction(sb, plan, preflight):
    """Checks that need the browser's own text layout and pixels: safe area, size, contrast, RTL, fonts."""
    checks = []
    W, H = plan["width"], plan["height"]
    safe = plan["safe"]
    setup = preflight["setup"]
    for key, block in setup["layout"].items():
        scene = sb["scenes"][int(key)]["id"]
        for line in block["lines"]:
            box = line["box"]
            inside = (box["x0"] >= safe["x0"] - 0.5 and box["x1"] <= safe["x1"] + 0.5 and box["y0"] >= safe["y0"] - 0.5
                      and box["y1"] + plan["slide_px"] <= safe["y1"] + 0.5)
            _check(checks, f"safe_area.title_safe.{line['lang']}", inside,
                   [round(box["x0"], 1), round(box["y0"], 1), round(box["x1"], 1), round(box["y1"] + plan["slide_px"], 1)],
                   [round(safe["x0"], 1), round(safe["y0"], 1), round(safe["x1"], 1), round(safe["y1"], 1)], scene=scene)
            _check(checks, f"typography.min_size.{line['lang']}", line["size"] >= DIRECTION["min_text_size"] * H,
                   line["size"], round(DIRECTION["min_text_size"] * H, 1), scene=scene)
            if line["lang"] == "ar":
                _check(checks, "rtl.canvas_direction", line["canvas_direction"] == "rtl", line["canvas_direction"], "rtl", scene=scene)
        lines = block["lines"]
        for upper, lower in zip(lines, lines[1:]):
            _check(checks, "typography.no_line_overlap", upper["box"]["y1"] <= lower["box"]["y0"],
                   [upper["box"]["y1"], lower["box"]["y0"]], scene=scene)
    for row in preflight["contrast"]:
        _check(checks, f"legibility.contrast.{row['lang']}", row["ratio"] >= DIRECTION["min_contrast"],
               round(row["ratio"], 2), DIRECTION["min_contrast"], scene=sb["scenes"][row["scene"]]["id"])
    rtl = preflight["rtl"]
    _check(checks, "rtl.arabic_glyphs_not_tofu", rtl["glyphs_distinct"] is True)
    for line in rtl["lines"]:
        _check(checks, "rtl.first_word_at_right_edge", line["first_word_at_right_edge"] is True,
               line["first_word_mismatch_pixels"], 0, detail=line["text"])
        _check(checks, "rtl.contextual_shaping", line["contextual_shaping"] is True, detail=line["text"])
    for lang, available in rtl.get("fonts", {}).items():
        _check(checks, f"typography.font_available.{lang}", available is True, FONTS[lang]["family"])
    for layer in setup["layers"]:
        _check(checks, "render.no_engine_fallback", layer["fallback"] is None, layer["fallback"], detail=layer["id"])
    _check(checks, "render.no_page_errors", not preflight["page_errors"], len(preflight["page_errors"]), 0)
    _check(checks, "render.no_external_requests", not preflight["external_requests"], len(preflight["external_requests"]), 0)
    _check(checks, "render.no_refused_requests", not preflight["refused"], preflight["refused"][:5] or None)
    return checks


def contrast_samples(sb, plan):
    """For every shot with text, the frame in the middle of its fully visible window."""
    samples = []
    fps = plan["fps"]
    for row in scene_times(sb):
        window = text_window(sb, row["index"])
        mid = (window["in_end"] + window["out_start"]) / 2
        samples.append({"scene": row["index"], "frame": row["start_frame"] + int(mid * fps / 1000), "dy": 0})
    return samples


# --------------------------------------------------------------------------- subtitles

def _clock(ms, separator):
    ms = int(round(ms))
    hours, rest = divmod(ms, 3600000)
    minutes, rest = divmod(rest, 60000)
    seconds, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{separator}{millis:03d}"


def _wrap(text, limit):
    if len(text) <= limit:
        return [text]
    words = text.split(" ")
    best = None
    for cut in range(1, len(words)):
        a, b = " ".join(words[:cut]), " ".join(words[cut:])
        if len(a) <= limit and len(b) <= limit:
            score = abs(len(a) - len(b))
            if best is None or score < best[0]:
                best = (score, [a, b])
    if best is None:
        raise StoryboardError(f"subtitle line cannot be wrapped into 2 lines of {limit}: {text!r}")
    return best[1]


def subtitle_cues(sb, lang):
    """Frame-aligned cues: from the first frame the text appears to its last frame."""
    cues = []
    for row in scene_times(sb):
        window = text_window(sb, row["index"])
        lines = _wrap(sb["scenes"][row["index"]]["text"][lang], DIRECTION["subtitle_line_chars"])
        if lang == "ar":
            lines = [RLM + line for line in lines]
        cues.append({"id": row["id"], "start_ms": round(row["start_ms"] + window["in_start"], 3),
                     "end_ms": round(row["start_ms"] + window["out_end"], 3), "lines": lines})
    return cues


def render_vtt(cues, lang):
    out = ["WEBVTT", f"Kind: subtitles", f"Language: {lang}", ""]
    for cue in cues:
        out += [cue["id"], f"{_clock(cue['start_ms'], '.')} --> {_clock(cue['end_ms'], '.')}", *cue["lines"], ""]
    return "\n".join(out)


def render_srt(cues):
    out = []
    for number, cue in enumerate(cues, 1):
        out += [str(number), f"{_clock(cue['start_ms'], ',')} --> {_clock(cue['end_ms'], ',')}", *cue["lines"], ""]
    return "\n".join(out)


_CUE_TIME = re.compile(r"^(\d{2}):(\d{2}):(\d{2})[.,](\d{3}) --> (\d{2}):(\d{2}):(\d{2})[.,](\d{3})(?:\s.*)?$")


def parse_subtitles(text):
    """Parse WebVTT or SRT produced here (or by others) into cues; raises on malformed timing."""
    blocks = [b for b in text.replace("\r\n", "\n").split("\n\n") if b.strip()]
    if blocks and blocks[0].startswith("WEBVTT"):
        blocks = blocks[1:]
    cues = []
    for block in blocks:
        lines = block.strip("\n").split("\n")
        index = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if index is None:
            raise VideoPipelineError(f"subtitle block without timing: {block[:40]!r}")
        match = _CUE_TIME.match(lines[index].strip())
        if not match:
            raise VideoPipelineError(f"malformed cue timing: {lines[index]!r}")
        g = [int(x) for x in match.groups()]
        start = ((g[0] * 60 + g[1]) * 60 + g[2]) * 1000 + g[3]
        end = ((g[4] * 60 + g[5]) * 60 + g[6]) * 1000 + g[7]
        cues.append({"id": lines[index - 1] if index else None, "start_ms": start, "end_ms": end, "lines": lines[index + 1:]})
    return cues


def check_subtitles(text, lang, *, fps, duration_ms, expected=None):
    checks = []
    try:
        cues = parse_subtitles(text)
    except VideoPipelineError as error:
        _check(checks, "subtitles.parse", False, detail=str(error))
        return _report(checks)
    _check(checks, "subtitles.parse", bool(cues), len(cues))
    gap = DIRECTION["subtitle_gap_frames"] * 1000 / fps
    for cue in cues:
        length = cue["end_ms"] - cue["start_ms"]
        _check(checks, "subtitles.duration", DIRECTION["subtitle_min_ms"] <= length <= DIRECTION["subtitle_max_ms"],
               length, [DIRECTION["subtitle_min_ms"], DIRECTION["subtitle_max_ms"]], scene=cue["id"])
        _check(checks, "subtitles.within_video", 0 <= cue["start_ms"] and cue["end_ms"] <= duration_ms + 0.5,
               [cue["start_ms"], cue["end_ms"]], duration_ms, scene=cue["id"])
        body = [line.lstrip(RLM) for line in cue["lines"]]
        _check(checks, "subtitles.lines", 1 <= len(body) <= DIRECTION["subtitle_lines"]
               and all(len(line) <= DIRECTION["subtitle_line_chars"] for line in body), [len(x) for x in body],
               DIRECTION["subtitle_line_chars"], scene=cue["id"])
        cps = _visible_chars(" ".join(body)) / (length / 1000)
        _check(checks, "subtitles.cps", cps <= DIRECTION["max_cps"][lang], round(cps, 2), DIRECTION["max_cps"][lang], scene=cue["id"])
        if lang == "ar":
            _check(checks, "subtitles.rtl_mark", all(line.startswith(RLM) for line in cue["lines"]), scene=cue["id"])
    for a, b in zip(cues, cues[1:]):
        _check(checks, "subtitles.order_and_gap", b["start_ms"] - a["end_ms"] >= gap - 0.5,
               round(b["start_ms"] - a["end_ms"], 1), round(gap, 1), scene=b["id"])
    if expected is not None:
        same = [(c["start_ms"], c["end_ms"]) for c in cues] == [(round(e["start_ms"]), round(e["end_ms"])) for e in expected]
        _check(checks, "subtitles.matches_storyboard", same)
    return _report(checks, {"language": lang, "cues": len(cues)})


# --------------------------------------------------------------------------- audio

_TABLE = 4096


def _table(harmonics):
    raw = [sum(a * math.sin(2 * math.pi * n * i / _TABLE) for n, a in harmonics) for i in range(_TABLE)]
    peak = max(abs(x) for x in raw)
    return [x / peak for x in raw]


def _midi(note):
    return 440.0 * 2 ** ((note - 69) / 12)


def _osc(table, freq, n, phase=0):
    inc = int(round(freq * _TABLE / SAMPLE_RATE * 65536))
    mask = _TABLE - 1
    return [table[((phase + i * inc) >> 16) & mask] for i in range(n)]


def _noise(n, seed):
    x = (seed * 2654435761) & 0xFFFFFFFF or 1
    out = [0.0] * n
    for i in range(n):
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= x >> 17
        x ^= (x << 5) & 0xFFFFFFFF
        out[i] = x / 2147483648.0 - 1.0
    return out


def _add(target, start, values, gain=1.0):
    end = min(len(target), start + len(values))
    offset = 0
    if start < 0:
        offset, start = -start, 0
    for i in range(start, end):
        target[i] += values[i - start + offset] * gain


def _impact(seed):
    """Sub thump (110 -> 42 Hz sweep, 1.5 ms attack) plus a short noise transient."""
    n = int(0.9 * SAMPLE_RATE)
    out, phase = [0.0] * n, 0.0
    noise = _noise(int(0.03 * SAMPLE_RATE), seed)
    for i in range(n):
        t = i / SAMPLE_RATE
        freq = 42 + 68 * math.exp(-t / 0.08)
        phase += 2 * math.pi * freq / SAMPLE_RATE
        attack = min(1.0, t / 0.0015)
        out[i] = math.sin(phase) * attack * math.exp(-t / 0.22) * 0.85
    prev = 0.0
    for i, value in enumerate(noise):
        t = i / SAMPLE_RATE
        high = value - prev
        prev = value
        out[i] += high * 0.45 * math.exp(-t / 0.006)
    return out


def _whoosh(length_s, seed):
    """Low-passed noise with a rising cutoff and swell, released just before the cut."""
    n = int(length_s * SAMPLE_RATE)
    noise = _noise(n, seed)
    out, state = [0.0] * n, 0.0
    for i in range(n):
        u = i / n
        cutoff = 300 * (5000 / 300) ** u
        k = 1 - math.exp(-2 * math.pi * cutoff / SAMPLE_RATE)
        state += k * (noise[i] - state)
        release = min(1.0, (n - i) / (0.04 * SAMPLE_RATE))
        out[i] = state * (u ** 2.2) * release * 0.9
    return out


def _envelope(n, attack, release):
    a, r = max(1, int(attack * SAMPLE_RATE)), max(1, int(release * SAMPLE_RATE))
    return [min(1.0, i / a, (n - i) / r) for i in range(n)]


def _read_wav_mono(path):
    with wave.open(str(path), "rb") as stream:
        if stream.getsampwidth() != 2 or stream.getframerate() != SAMPLE_RATE:
            raise RenderError("voiceover clip must be 16-bit 48 kHz")
        channels = stream.getnchannels()
        data = array.array("h")
        data.frombytes(stream.readframes(stream.getnframes()))
    if sys.byteorder == "big":
        data.byteswap()
    samples = [x / 32768.0 for x in data[::channels]]
    return samples


def _write_wav(path, left, right):
    interleaved = array.array("h", [0]) * (2 * len(left))
    for i, (l_value, r_value) in enumerate(zip(left, right)):
        interleaved[2 * i] = int(max(-1.0, min(1.0, l_value)) * 32767)
        interleaved[2 * i + 1] = int(max(-1.0, min(1.0, r_value)) * 32767)
    if sys.byteorder == "big":
        interleaved.byteswap()
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(2)
        stream.setsampwidth(2)
        stream.setframerate(SAMPLE_RATE)
        stream.writeframes(interleaved.tobytes())


def voiceover_capability():
    """Which local TTS exists. Never calls a network or paid provider."""
    binaries = {name: shutil.which(name) is not None for name in ("espeak", "espeak-ng", "pico2wave", "flite", "piper", "festival")}
    flite = False
    if shutil.which("ffmpeg"):
        filters = _run(["ffmpeg", "-hide_banner", "-filters"], timeout=30).stdout
        flite = re.search(r"\sflite\s", filters) is not None
    english = flite or binaries["flite"]
    arabic_binary = binaries["espeak"] or binaries["espeak-ng"]
    return {"binaries": binaries, "ffmpeg_libflite": flite,
            "en": {"available": english, "engine": "ffmpeg-libflite" if flite else ("flite" if english else None),
                   "license": FLITE_LICENSE if english else None},
            "ar": {"available": False,
                   "reason": ("espeak/espeak-ng present but not wired into this pipeline version" if arabic_binary else
                              "not available here: no local Arabic TTS (espeak, espeak-ng, pico2wave absent; Flite has no Arabic voice)")},
            "paid_or_network_tts_used": False}


def _voiceover_clips(sb, work):
    voice = sb["audio"]["voiceover"]
    if voice is None:
        return []
    capability = voiceover_capability()
    lang = voice["language"]
    if not capability[lang]["available"] or capability[lang]["engine"] != "ffmpeg-libflite":
        raise RenderError(f"voiceover in {lang!r} is not available here: {capability[lang].get('reason', 'no local engine')}")
    _need(_SAFE_PATH.match(str(work)) is not None, "work directory path has unsupported characters", RenderError)
    clips = []
    for index, scene in enumerate(sb["scenes"]):
        line = scene["voiceover"][lang] if scene.get("voiceover") else (None if "voiceover" in scene else scene["text"][lang])
        if not line:
            continue
        text_file, clip = work / f"vo-{index}.txt", work / f"vo-{index}.wav"
        text_file.write_text(line, "utf-8")
        _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
              f"flite=textfile={text_file}:voice={voice['voice']}", "-ar", str(SAMPLE_RATE), "-ac", "1",
              "-c:a", "pcm_s16le", str(clip)], timeout=120)
        samples = _read_wav_mono(clip)
        peak = max((abs(x) for x in samples), default=0.0)
        threshold = peak * 0.02
        active = [i for i, x in enumerate(samples) if abs(x) > threshold]
        if not active:
            raise RenderError(f"voiceover for {scene['id']} is silent")
        lo, hi = max(0, active[0] - 480), min(len(samples), active[-1] + 960)
        speech = [x / peak * 0.5 for x in samples[lo:hi]]
        clips.append({"scene": index, "id": scene["id"], "text": line, "samples": speech,
                      "duration_ms": round(len(speech) * 1000 / SAMPLE_RATE, 1), "sha256": _sha_file(clip)})
    return clips


def synthesize_audio(sb, path, *, clips=(), plan=None):
    """Procedural music bed + sound design (+ placed voiceover) as a 48 kHz stereo WAV.

    Returns facts: markers (cut sample positions), chords per shot and voiceover placement.
    """
    plan = plan or build_plan(sb)
    fps = sb["format"]["fps"]
    total = plan["frames"] * SAMPLE_RATE // fps
    times = scene_times(sb)
    music_l, music_r = [0.0] * total, [0.0] * total
    fx_l, fx_r = [0.0] * total, [0.0] * total
    beat = 60.0 / sb["audio"]["bpm"]
    chords = []
    if sb["audio"]["music"]:
        pad = _table([(1, 1.0), (2, 0.42), (3, 0.22), (4, 0.12), (5, 0.06)])
        pluck = _table([(1, 1.0), (2, 0.35), (3, 0.08)])
        bass_table = _table([(1, 1.0), (2, 0.28), (3, 0.08)])
        for row in times:
            last = row["index"] == len(times) - 1
            name, bass_note, notes = HOME_CHORD if last and len(times) > 1 else PROGRESSION[row["index"] % len(PROGRESSION)]
            chords.append({"scene": row["id"], "chord": name})
            start = row["start_frame"] * SAMPLE_RATE // fps
            end = (row["start_frame"] + row["frames"]) * SAMPLE_RATE // fps
            tail = int(0.06 * SAMPLE_RATE) if not last else 0
            n = end - start + tail
            env = _envelope(n, 0.35 if row["index"] == 0 else 0.012, 0.06 if not last else 0.4)
            for k, note in enumerate(notes):
                for detune, pan in ((-5, 0.3), (5, 0.7)):
                    shaped = [w * e for w, e in zip(_osc(pad, _midi(note + detune / 100), n, phase=(k * 977 + detune * 131) << 16), env)]
                    _add(music_l, start, shaped, 0.09 * (1 - pan))
                    _add(music_r, start, shaped, 0.09 * pan)
            # Bass enters on the first cut; it pulses on every beat of its shot.
            if row["index"] > 0:
                step = int(beat * SAMPLE_RATE)
                freq = _midi(bass_note)
                for b_start in range(start, end, step):
                    length = min(step, end - b_start)
                    tone = _osc(bass_table, freq, length)
                    shaped = [v * min(1.0, i / 190) * math.exp(-i / (0.22 * SAMPLE_RATE)) for i, v in enumerate(tone)]
                    _add(music_l, b_start, shaped, 0.2)
                    _add(music_r, b_start, shaped, 0.2)
            # Arpeggio on sixteenths over the chord tones, alternating sides.
            sixteenth = beat / 4
            pattern = (0, 2, 4, 1, 3, 2, 4, 1)
            count = int(math.floor((end - start) / (sixteenth * SAMPLE_RATE) + 1e-9))
            for j in range(count):
                at = start + int(round(j * sixteenth * SAMPLE_RATE))
                note = notes[pattern[j % len(pattern)] % len(notes)] + 12
                length = int(0.35 * SAMPLE_RATE)
                tone = _osc(pluck, _midi(note), length)
                shaped = [v * min(1.0, i / 96) * math.exp(-i / (0.11 * SAMPLE_RATE)) for i, v in enumerate(tone)]
                side = 0.35 if j % 2 else 0.65
                _add(music_l, at, shaped, 0.06 * (1 - side) * 2)
                _add(music_r, at, shaped, 0.06 * side * 2)
        # Ping-pong echo of the music bus at three sixteenths, 30 % feedback.
        delay = int(3 * beat / 4 * SAMPLE_RATE)
        echo_l, echo_r = [0.0] * total, [0.0] * total
        for i in range(delay, total):
            echo_l[i] = 0.18 * music_r[i - delay] + 0.3 * echo_r[i - delay]
            echo_r[i] = 0.18 * music_l[i - delay] + 0.3 * echo_l[i - delay]
        music_l = [a + b for a, b in zip(music_l, echo_l)]
        music_r = [a + b for a, b in zip(music_r, echo_r)]
    markers = []
    if sb["audio"]["sound_design"]:
        for row in times[1:]:
            at = row["start_frame"] * SAMPLE_RATE // fps
            if row["transition_in"] == "cut":
                hit = _impact(seed=row["index"] * 7919 + 17)
                _add(fx_l, at, hit, 0.5)
                _add(fx_r, at, hit, 0.5)
                markers.append({"scene": row["id"], "kind": "impact", "sample": at, "ms": round(at * 1000 / SAMPLE_RATE, 3)})
            whoosh = _whoosh(0.6, seed=row["index"] * 104729 + 3)
            begin = at - len(whoosh) - int(0.03 * SAMPLE_RATE)
            if row["transition_in"] == "dissolve":
                begin = at - len(whoosh) // 2
            _add(fx_l, begin, whoosh, 0.14)
            _add(fx_r, begin + 96, whoosh, 0.14)
        boom = _impact(seed=11)
        _add(fx_l, 0, boom, 0.25)
        _add(fx_r, 0, boom, 0.25)
    duck = [1.0] * total
    placed = []
    for clip in clips:
        row = times[clip["scene"]]
        at = row["start_frame"] * SAMPLE_RATE // fps + int(DIRECTION["vo_offset_ms"] * SAMPLE_RATE / 1000)
        _add(fx_l, at, clip["samples"], 0.9)
        _add(fx_r, at, clip["samples"], 0.9)
        n = len(clip["samples"])
        lo, hi = max(0, at - int(0.08 * SAMPLE_RATE)), min(total, at + n + int(0.2 * SAMPLE_RATE))
        floor = 10 ** (-7 / 20)
        for i in range(lo, hi):
            ramp = min(1.0, (i - lo) / (0.08 * SAMPLE_RATE), (hi - i) / (0.2 * SAMPLE_RATE))
            duck[i] = min(duck[i], 1 - (1 - floor) * ramp)
        placed.append({"scene": clip["id"], "start_ms": round(at * 1000 / SAMPLE_RATE, 1),
                       "end_ms": round((at + n) * 1000 / SAMPLE_RATE, 1), "text": clip["text"],
                       "clip_sha256": clip["sha256"]})
    fade_out = int(sb["fade_out_ms"] * SAMPLE_RATE / 1000)
    left = [m * d + f for m, d, f in zip(music_l, duck, fx_l)]
    right = [m * d + f for m, d, f in zip(music_r, duck, fx_r)]
    if fade_out:
        for i in range(total - fade_out, total):
            g = (total - 1 - i) / fade_out
            left[i] *= g
            right[i] *= g
    peak = max(max(abs(x) for x in left), max(abs(x) for x in right), 1e-9)
    scale = 0.7 / peak
    _write_wav(path, [x * scale for x in left], [x * scale for x in right])
    return {"samples": total, "sample_rate": SAMPLE_RATE, "duration_ms": total * 1000 / SAMPLE_RATE,
            "markers": markers, "chords": chords, "voiceover": placed, "bpm": sb["audio"]["bpm"]}


PEAK_LIMITER = "alimiter=limit=0.4:attack=3:release=60:level=0:latency=1"


def master_loudness(source, target, *, timeout=300):
    """Peak control, then two-pass EBU R128 normalisation to -16 LUFS / -2 dBTP.

    The delay-compensated look-ahead limiter lowers transient peaks so loudnorm can apply one
    linear gain (dynamics preserved); -2 dBTP leaves headroom for the AAC encoder.
    """
    base = f"{PEAK_LIMITER},loudnorm=I={QA['loudness_lufs']}:TP=-2.0:LRA=11"
    first = _run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(source), "-af", base + ":print_format=json",
                  "-f", "null", "-"], timeout=timeout).stderr
    measured = json.loads(first[first.rindex("{"):first.rindex("}") + 1])
    second_filter = (f"{base}:measured_I={measured['input_i']}:measured_TP={measured['input_tp']}"
                     f":measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}"
                     f":offset={measured['target_offset']}:linear=true:print_format=json")
    second = _run(["ffmpeg", "-hide_banner", "-nostats", "-y", "-i", str(source), "-af", second_filter,
                   "-ar", str(SAMPLE_RATE), "-c:a", "pcm_s16le", str(target)], timeout=timeout).stderr
    result = json.loads(second[second.rindex("{"):second.rindex("}") + 1])
    return {"input_i": float(measured["input_i"]), "input_tp": float(measured["input_tp"]),
            "output_i": float(result["output_i"]), "output_tp": float(result["output_tp"]),
            "normalization_type": result.get("normalization_type")}


# --------------------------------------------------------------------------- media QA

def mp4_atoms(path):
    """Top-level MP4 box order (to prove faststart: moov before mdat)."""
    order = []
    size_total = os.path.getsize(path)
    with open(path, "rb") as stream:
        offset = 0
        while offset < size_total and len(order) < 64:
            stream.seek(offset)
            header = stream.read(8)
            if len(header) < 8:
                break
            size = int.from_bytes(header[:4], "big")
            kind = header[4:8].decode("latin-1")
            if size == 1:
                size = int.from_bytes(stream.read(8), "big")
            elif size == 0:
                size = size_total - offset
            if size < 8:
                break
            order.append(kind)
            offset += size
    return order


def probe(path):
    out = _run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", "-count_frames",
                str(path)], timeout=300).stdout
    return json.loads(out)


def loudness(path, *, timeout=300):
    """Integrated loudness, loudness range and true peak of the first audio stream (ffmpeg ebur128)."""
    log = _run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-map", "0:a:0", "-af",
                "ebur128=peak=true:framelog=quiet", "-f", "null", "-"], timeout=timeout).stderr
    summary = log[log.rindex("Summary:"):]
    integrated = float(re.search(r"I:\s+(-?[\d.]+|-inf) LUFS", summary).group(1))
    lra = float(re.search(r"LRA:\s+(-?[\d.]+) LU", summary).group(1))
    peak = re.search(r"True peak:\s+Peak:\s+(-?[\d.]+|-inf) dBFS", summary)
    return {"integrated_lufs": integrated, "lra_lu": lra, "true_peak_dbtp": float(peak.group(1)) if peak else None}


def _decode_gray(path, width=64, height=36, *, timeout=300):
    data = _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path), "-map", "0:v:0", "-vf",
                 f"scale={width}:{height}:flags=area,format=gray", "-f", "rawvideo", "-"], timeout=timeout, binary=True).stdout
    size = width * height
    return [data[i:i + size] for i in range(0, len(data) - size + 1, size)]


def video_cuts(path, expected_frames, *, timeout=300):
    """Locate each expected hard cut as the strongest frame difference within +-2 frames."""
    frames = _decode_gray(path, timeout=timeout)
    diffs = [0.0] + [sum(abs(a - b) for a, b in zip(frames[i], frames[i - 1])) / len(frames[i]) for i in range(1, len(frames))]
    found = []
    for k in expected_frames:
        window = [i for i in range(k - 2, k + 3) if 0 < i < len(diffs)]
        if not window:
            found.append({"expected": k, "detected": None, "strength": 0.0})
            continue
        best = max(window, key=lambda i: diffs[i])
        neighbours = [diffs[i] for i in range(k - 8, k + 9) if 0 < i < len(diffs) and abs(i - best) > 1]
        strength = diffs[best] / (statistics.median(neighbours) + 0.5) if neighbours else 0.0
        found.append({"expected": k, "detected": best, "strength": round(strength, 2), "difference": round(diffs[best], 2)})
    return {"frames_decoded": len(frames), "cuts": found}


def _decode_audio(path, *, timeout=300):
    data = _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path), "-map", "0:a:0", "-ac", "1",
                 "-ar", str(SAMPLE_RATE), "-f", "s16le", "-"], timeout=timeout, binary=True).stdout
    samples = array.array("h")
    samples.frombytes(data[: len(data) // 2 * 2])
    if sys.byteorder == "big":
        samples.byteswap()
    return samples


def audio_onsets(samples, times_ms, *, search_ms=60):
    """The sharpest level rise (1 ms peak envelope vs. the preceding 20 ms) near each time."""
    block = SAMPLE_RATE // 1000
    env = [max(abs(x) for x in samples[i:i + block]) if samples[i:i + block] else 0 for i in range(0, len(samples), block)]
    found = []
    for t in times_ms:
        centre = int(round(t))
        best, ratio_best = None, 0.0
        for k in range(max(21, centre - search_ms), min(len(env), centre + search_ms + 1)):
            before = sum(env[k - 20:k]) / 20 + 1
            ratio = env[k] / before
            if ratio > ratio_best:
                best, ratio_best = k, ratio
        found.append({"expected_ms": round(t, 3), "onset_ms": best, "ratio": round(ratio_best, 2)})
    return found


def qa_media(path, expect, *, timeout=600):
    """Measure a delivered MP4 against the expected format; every check is a measurement."""
    path = pathlib.Path(path)
    checks = {}

    def check(name, passed, value, expected):
        checks[name] = {"passed": bool(passed), "value": value, "expected": expected}

    info = probe(path)
    streams = info.get("streams", [])
    video = [s for s in streams if s.get("codec_type") == "video"]
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    subtitle = [s for s in streams if s.get("codec_type") == "subtitle"]
    fmt = info.get("format", {})
    fps = expect["fps"]
    check("container.mp4", "mp4" in fmt.get("format_name", ""), fmt.get("format_name"), "mov,mp4,...")
    atoms = mp4_atoms(path)
    check("container.faststart", "moov" in atoms and "mdat" in atoms and atoms.index("moov") < atoms.index("mdat"), atoms[:6], "moov before mdat")
    check("video.present", len(video) == 1, len(video), 1)
    if video:
        v = video[0]
        check("video.codec", v.get("codec_name") == "h264", v.get("codec_name"), "h264")
        check("video.profile", v.get("profile") == expect.get("profile", v.get("profile")), v.get("profile"), expect.get("profile"))
        check("video.pix_fmt", v.get("pix_fmt") == "yuv420p", v.get("pix_fmt"), "yuv420p")
        check("video.dimensions", (v.get("width"), v.get("height")) == (expect["width"], expect["height"]),
              [v.get("width"), v.get("height")], [expect["width"], expect["height"]])
        check("video.fps", v.get("r_frame_rate") == f"{fps}/1" and v.get("avg_frame_rate") == f"{fps}/1",
              [v.get("r_frame_rate"), v.get("avg_frame_rate")], f"{fps}/1")
        frames = int(v.get("nb_read_frames") or 0)
        check("video.frame_count", frames == expect["frames"], frames, expect["frames"])
        duration = float(v.get("duration") or 0)
        check("video.duration", abs(duration - expect["frames"] / fps) <= 1 / fps + 1e-6, duration, round(expect["frames"] / fps, 4))
        check("video.color_bt709", all(v.get(k) == "bt709" for k in ("color_space", "color_transfer", "color_primaries")),
              [v.get("color_space"), v.get("color_transfer"), v.get("color_primaries")], "bt709")
        kbps = int(v.get("bit_rate") or 0) / 1000
        bucket = "1080" if expect["height"] >= 1080 else "720" if expect["height"] >= 720 else "other"
        check("video.bitrate", 0 < kbps <= QA["max_video_kbps"][bucket], round(kbps, 1), QA["max_video_kbps"][bucket])
    check("audio.present", len(audio) == 1, len(audio), 1)
    if audio:
        a = audio[0]
        check("audio.codec", a.get("codec_name") == "aac" and a.get("profile") == "LC", [a.get("codec_name"), a.get("profile")], ["aac", "LC"])
        check("audio.format", int(a.get("sample_rate", 0)) == QA["audio_rate"] and a.get("channels") == QA["audio_channels"],
              [a.get("sample_rate"), a.get("channels")], [QA["audio_rate"], QA["audio_channels"]])
        a_duration = float(a.get("duration") or 0)
        check("audio.duration", abs(a_duration - expect["frames"] / fps) <= QA["audio_duration_tolerance_s"],
              a_duration, round(expect["frames"] / fps, 4))
        level = loudness(path, timeout=timeout)
        check("audio.loudness", level["integrated_lufs"] is not None and abs(level["integrated_lufs"] - QA["loudness_lufs"]) <= QA["loudness_tolerance_lu"],
              level["integrated_lufs"], [QA["loudness_lufs"] - QA["loudness_tolerance_lu"], QA["loudness_lufs"] + QA["loudness_tolerance_lu"]])
        check("audio.true_peak", level["true_peak_dbtp"] is not None and level["true_peak_dbtp"] <= QA["true_peak_max_dbtp"],
              level["true_peak_dbtp"], QA["true_peak_max_dbtp"])
    check("subtitles.no_stream", len(subtitle) == expect.get("subtitle_streams", 0), len(subtitle), expect.get("subtitle_streams", 0))
    check("subtitles.not_burned", expect.get("burned_subtitles", False) is False, expect.get("burned_subtitles", False), False)
    cut_frames = expect.get("cut_frames") or []
    sync = None
    if cut_frames and video and audio:
        cuts = video_cuts(path, cut_frames, timeout=timeout)
        onsets = audio_onsets(_decode_audio(path, timeout=timeout), [k * 1000 / fps for k in cut_frames])
        rows = []
        for cut, onset in zip(cuts["cuts"], onsets):
            video_ms = cut["detected"] * 1000 / fps if cut["detected"] is not None else None
            offset = None if video_ms is None or onset["onset_ms"] is None else round(onset["onset_ms"] - video_ms, 3)
            rows.append({"expected_frame": cut["expected"], "video_frame": cut["detected"], "cut_strength": cut["strength"],
                         "audio_onset_ms": onset["onset_ms"], "onset_ratio": onset["ratio"], "offset_ms": offset})
        tolerance = QA["sync_tolerance_frames"] * 1000 / fps
        check("edit.cuts_at_planned_frames", all(r["video_frame"] == r["expected_frame"] and r["cut_strength"] >= QA["cut_strength"] for r in rows),
              [[r["video_frame"], r["cut_strength"]] for r in rows], [[k, f">={QA['cut_strength']}"] for k in cut_frames])
        check("sync.audio_on_cuts", all(r["offset_ms"] is not None and abs(r["offset_ms"]) <= tolerance and r["onset_ratio"] >= QA["onset_ratio"] for r in rows),
              [r["offset_ms"] for r in rows], f"|offset| <= {round(tolerance, 2)} ms")
        sync = rows
    return {"schema": QA_SCHEMA, "file": path.name, "sha256": _sha_file(path), "bytes": path.stat().st_size,
            "passed": all(c["passed"] for c in checks.values()), "checks": checks, "sync": sync,
            "duration_s": float(fmt.get("duration") or 0),
            "streams": [{k: s.get(k) for k in ("index", "codec_type", "codec_name", "profile", "width", "height", "pix_fmt",
                                                "r_frame_rate", "nb_read_frames", "sample_rate", "channels", "bit_rate", "duration")
                         if s.get(k) is not None} for s in streams],
            "atoms": atoms[:8]}


# --------------------------------------------------------------------------- browser

def _browser_files(work):
    html, js, renderer = work / "compositor.html", work / "compositor.mjs", work / "renderer.cjs"
    html.write_text(_COMPOSITOR_HTML, "utf-8")
    js.write_text(_COMPOSITOR_JS, "utf-8")
    renderer.write_text(_RENDERER_JS, "utf-8")
    return html, js, renderer


def renderer_digests():
    return {"compositor_html_sha256": _sha_bytes(_COMPOSITOR_HTML.encode()),
            "compositor_js_sha256": _sha_bytes(_COMPOSITOR_JS.encode()),
            "renderer_js_sha256": _sha_bytes(_RENDERER_JS.encode()),
            "pipeline_sha256": _sha_file(__file__)}


def _job(work, command, *, plan=None, viewport=None, rtl_lines=(), rtl_options=None, samples=(), root=ROOT):
    html, js, _ = _browser_files(work)
    if viewport is None:
        viewport = {"width": plan["width"], "height": plan["height"]} if plan else {"width": 1280, "height": 720}
    job = {"repo_root": str(pathlib.Path(root).resolve()), "compositor_html": str(html), "compositor_js": str(js),
           "allowed_prefixes": list(ALLOWED_PREFIXES), "viewport": viewport, "plan": plan,
           "rtl_lines": list(rtl_lines), "rtl_options": rtl_options or {"fonts": {k: v["css"] for k, v in FONTS.items()}},
           "contrast_samples": list(samples), "result_path": str(work / f"result-{command}.json")}
    path = work / f"job-{command}.json"
    path.write_text(json.dumps(job, ensure_ascii=False), "utf-8")
    return path, job


def _node(work, command, job_path, *, timeout=600):
    _tool("node")
    _, _, renderer = _browser_files(work)
    done = subprocess.run(["node", str(renderer), command, str(job_path)], cwd=str(work), capture_output=True, timeout=timeout)
    result_path = pathlib.Path(json.loads(pathlib.Path(job_path).read_text("utf-8"))["result_path"])
    if done.returncode != 0:
        message = done.stderr.decode("utf-8", "replace")[-1500:]
        if "Playwright is needed" in message or "Executable doesn't exist" in message:
            raise ToolMissing(message.strip().splitlines()[-1] if message.strip() else "Playwright/Chromium unavailable")
        raise RenderError(f"browser {command} failed: {message}")
    return json.loads(result_path.read_text("utf-8"))


def browser_probe(*, rtl_lines=("أمرٌ واحد.", "عشرون طبقة تخطّط وتبني وتختبر."), force_direction=None, timeout=300, root=ROOT):
    """Probe headless Chromium: WebGL2 draw + readback, WebGPU compute, Arabic RTL rendering, fonts."""
    with tempfile.TemporaryDirectory(prefix="gaie-probe-") as temp:
        work = pathlib.Path(temp)
        options = {"fonts": {k: v["css"] for k, v in FONTS.items()}}
        if force_direction:
            options["forceDirection"] = force_direction
        job_path, _ = _job(work, "probe", rtl_lines=rtl_lines, rtl_options=options, root=root)
        result = _node(work, "probe", job_path, timeout=timeout)
    gpu = result["gpu"]
    renderer = (gpu.get("webgl2", {}).get("renderer") or "")
    software = any(word in renderer.lower() for word in ("swiftshader", "llvmpipe", "software", "softpipe"))
    adapter = gpu.get("webgpu", {}).get("info", {})
    result["summary"] = {
        "webgl2_executed": gpu.get("webgl2", {}).get("executed") is True,
        "webgl2_renderer": renderer,
        "webgpu_compute_executed": gpu.get("webgpu", {}).get("compute_executed") is True,
        "webgpu_adapter": adapter,
        "hardware_gpu": bool(renderer) and not software and adapter.get("architecture") != "swiftshader",
        "note": ("GPU APIs executed on a CPU software rasteriser (SwiftShader); no hardware GPU was used."
                 if software else "Renderer string does not name a software rasteriser."),
    }
    return result


def hash_frames(storyboard, *, limit=None, timeout=600, root=ROOT):
    """Render frames headlessly without encoding; return the SHA-256 of each frame's RGBA pixels."""
    sb = validate_storyboard(storyboard, root=root)
    plan = build_plan(sb, root=root)
    if limit is not None:
        _need(type(limit) is int and 1 <= limit, "limit: positive integer", VideoPipelineError)
        plan = {**plan, "timeline": plan["timeline"][:limit]}
    with tempfile.TemporaryDirectory(prefix="gaie-frames-") as temp:
        work = pathlib.Path(temp)
        job_path, _ = _job(work, "render", plan=plan, root=root)
        result = _node(work, "render", job_path, timeout=timeout)
    if result["page_errors"] or result["external_requests"]:
        raise RenderError(f"browser errors {result['page_errors'][:2]} / external requests {result['external_requests'][:2]}")
    return result["frames"]


# --------------------------------------------------------------------------- render

def _variants(sb):
    W, H = sb["format"]["width"], sb["format"]["height"]
    if H >= 1080:
        mobile = (1280, 720)
    else:
        mobile = (max(160, W // 2 // 2 * 2), max(90, H // 2 // 2 * 2))
    return [{"name": "main", "width": W, "height": H, "crf": 18, "profile": "high", "audio_kbps": 192},
            {"name": "mobile", "width": mobile[0], "height": mobile[1], "crf": 21, "profile": "main", "audio_kbps": 128}]


def encode_command(sb, plan, audio_path, outputs, frames_input="pipe:0"):
    """One ffmpeg process: PNG frames on stdin -> RGB grade -> BT.709 -> main + mobile H.264/AAC MP4s."""
    fps = plan["fps"]
    grade = GRADES[sb["grade"]]
    rgb = ",".join(["format=gbrp", *grade["rgb"]])
    graph = [f"[0:v]{rgb},split={len(outputs)}" + "".join(f"[g{i}]" for i in range(len(outputs)))]
    for i, out in enumerate(outputs):
        yuv = "".join("," + f for f in grade["yuv"])
        graph.append(f"[g{i}]scale={out['width']}:{out['height']}:flags=lanczos:out_color_matrix=bt709:out_range=tv,"
                     f"format=yuv420p{yuv},setsar=1[v{i}]")
    keys = ",".join(f"{c['ms'] / 1000:.6f}" for c in plan["cuts"]) or "0"
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostats", "-y", "-f", "image2pipe", "-framerate", str(fps),
               "-c:v", "png", "-i", frames_input, "-i", str(audio_path), "-filter_complex", ";".join(graph)]
    language = {"en": "eng", "ar": "ara"}.get((sb["audio"]["voiceover"] or {}).get("language"), "zxx")
    for i, out in enumerate(outputs):
        command += ["-map", f"[v{i}]", "-map", "1:a:0", "-c:v", "libx264", "-preset", "medium", "-crf", str(out["crf"]),
                    "-profile:v", out["profile"], "-pix_fmt", "yuv420p", "-r", str(fps), "-g", str(fps * 2),
                    "-keyint_min", str(fps), "-sc_threshold", "0", "-force_key_frames", keys, "-bf", "2",
                    "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
                    "-c:a", "aac", "-b:a", f"{out['audio_kbps']}k", "-ar", str(SAMPLE_RATE), "-ac", "2",
                    "-metadata:s:a:0", f"language={language}", "-map_metadata", "-1", "-fflags", "+bitexact",
                    "-flags:v", "+bitexact", "-flags:a", "+bitexact", "-movflags", "+faststart", str(out["path"])]
    return command


def _render_frames(work, job_path, command, *, frames, timeout):
    """node (PNG frames on stdout) | ffmpeg (grade + encode); returns the renderer's result."""
    _tool("ffmpeg")
    _, _, renderer = _browser_files(work)
    with open(work / "node.log", "wb") as node_log, open(work / "ffmpeg.log", "wb") as ffmpeg_log:
        node = subprocess.Popen(["node", str(renderer), "render", str(job_path)], cwd=str(work), stdout=subprocess.PIPE, stderr=node_log)
        try:
            encoder = subprocess.Popen(command, cwd=str(work), stdin=node.stdout, stdout=subprocess.DEVNULL, stderr=ffmpeg_log)
        except FileNotFoundError as error:
            node.kill()
            raise ToolMissing(str(error)) from error
        node.stdout.close()
        try:
            encoder_code = encoder.wait(timeout=timeout)
            node_code = node.wait(timeout=60)
        except subprocess.TimeoutExpired as error:
            node.kill()
            encoder.kill()
            raise RenderError(f"render timed out after {timeout}s") from error
    if encoder_code != 0:
        raise RenderError("ffmpeg encode failed: " + (work / "ffmpeg.log").read_text("utf-8", "replace")[-1500:])
    if node_code != 0:
        raise RenderError("browser render failed: " + (work / "node.log").read_text("utf-8", "replace")[-1500:])
    result = json.loads((work / "result-render.json").read_text("utf-8"))
    if len(result.get("frames", [])) != frames:
        raise RenderError(f"renderer produced {len(result.get('frames', []))} of {frames} frames")
    return result


def render(storyboard, out_dir, *, name=None, keep_work=False, timeout=None, root=ROOT):
    """Render a storyboard to graded MP4s + subtitle sidecars outside the repository, then QA them.

    Raises DirectionError before any frame is drawn when the direction checks fail.
    """
    started = dt.datetime.now(dt.timezone.utc)
    sb = validate_storyboard(storyboard, root=root)
    out = _outside_repository(out_dir, root)
    name = name or sb["id"]
    _need(_SLUG.match(name) is not None, "output name: lowercase slug", RenderError)
    for tool in ("ffmpeg", "ffprobe", "node"):
        _tool(tool)
    plan = build_plan(sb, root=root)
    static = direct(sb, plan)
    if not static["passed"]:
        raise DirectionError("cinematic direction checks failed", static)
    work = out / f".work-{name}"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(mode=0o700)
    try:
        arabic = [scene["text"]["ar"] for scene in sb["scenes"]] if "ar" in sb["languages"] else []
        job_path, _ = _job(work, "preflight", plan=plan, rtl_lines=arabic, samples=contrast_samples(sb, plan), root=root)
        preflight = _node(work, "preflight", job_path, timeout=600)
        checks = static["checks"] + browser_direction(sb, plan, preflight)
        clips = _voiceover_clips(sb, work)
        for clip in clips:
            window = scene_times(sb)[clip["scene"]]["end_ms"] - scene_times(sb)[clip["scene"]]["start_ms"]
            room = window - DIRECTION["vo_offset_ms"] - DIRECTION["vo_tail_ms"]
            _check(checks, "voiceover.fits_shot", clip["duration_ms"] <= room, clip["duration_ms"], room, scene=clip["id"])
        direction = _report(checks, {"storyboard": sb["id"], "duration_ms": plan["duration_ms"], "frames": plan["frames"]})
        if not direction["passed"]:
            raise DirectionError("cinematic direction checks failed", direction)
        raw, mastered = work / "mix.wav", work / "master.wav"
        audio = synthesize_audio(sb, raw, clips=clips, plan=plan)
        audio["master"] = master_loudness(raw, mastered)
        subtitles = []
        for lang in sb["languages"]:
            cues = subtitle_cues(sb, lang)
            for kind, text in (("vtt", render_vtt(cues, lang)), ("srt", render_srt(cues))):
                target = out / f"{name}.{lang}.{kind}"
                target.write_text(text, "utf-8")
                report = check_subtitles(text, lang, fps=plan["fps"], duration_ms=plan["duration_ms"], expected=cues)
                subtitles.append({"language": lang, "format": kind, "file": target.name, "sha256": _sha_file(target),
                                  "cues": len(cues), "qa": report})
        outputs = []
        for variant in _variants(sb):
            suffix = "" if variant["name"] == "main" else f"-{variant['height']}p"
            outputs.append({**variant, "path": out / f"{name}{suffix}.mp4"})
        job_path, _ = _job(work, "render", plan=plan, root=root)
        command = encode_command(sb, plan, mastered, outputs)
        frames = _render_frames(work, job_path, command, frames=plan["frames"],
                                timeout=timeout or 300 + plan["frames"] * 3)
        qa = []
        for output in outputs:
            report = qa_media(output["path"], {"width": output["width"], "height": output["height"], "fps": plan["fps"],
                                               "frames": plan["frames"], "profile": output["profile"].capitalize(),
                                               "cut_frames": [c["frame"] for c in plan["cuts"] if c["kind"] == "cut"],
                                               "subtitle_streams": 0, "burned_subtitles": False})
            report["variant"] = output["name"]
            qa.append(report)
        result = {"storyboard": sb, "plan_summary": {k: plan[k] for k in ("width", "height", "fps", "frames", "duration_ms", "cuts")},
                  "direction": direction, "preflight": {k: preflight[k] for k in ("gpu", "rtl", "browser_version", "playwright_version",
                                                                                   "chromium_args", "page_errors", "external_requests", "refused")},
                  "layout": preflight["setup"]["layout"], "layers": preflight["setup"]["layers"],
                  "contrast": preflight["contrast"], "audio": audio, "subtitles": subtitles, "frames": frames, "qa": qa,
                  "outputs": [{"variant": o["name"], "path": str(o["path"]), "width": o["width"], "height": o["height"]} for o in outputs],
                  "served_sources": frames.get("served", {}), "plan_cameras": plan["cameras"],
                  "started_at_utc": started.isoformat().replace("+00:00", "Z"),
                  "finished_at_utc": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")}
        return result
    finally:
        if not keep_work:
            shutil.rmtree(work, ignore_errors=True)


# --------------------------------------------------------------------------- manifest

def build_manifest(result, *, gpu=None, voice=None, root=ROOT):
    """The committed evidence: hashes, streams, QA, motions with source ids — never the media."""
    sb = result["storyboard"]
    served = result["served_sources"]
    catalog = load_catalog(root)
    motions = []
    for scene, layer in zip(sb["scenes"], result["layers"]):
        motion = scene["motion"]
        if motion["source"] == "engine":
            entry = catalog["engine"][motion["id"]]
            files = [entry["source"]]
            kind = f"native motion engine ({entry['engine']})"
        elif motion["source"] == "reference":
            entry = catalog["reference"][motion["id"]]
            files = list(REFERENCE_SOURCES)
            kind = "Canvas2D reference recipe (motion-library/expansion, 400-recipe set)"
        else:
            files = [CAMERA_SOURCE]
            kind = "nextgen camera scene (CPU perspective projection drawn with Canvas2D)"
        motions.append({"scene": scene["id"], "source": motion["source"], "id": motion["id"], "kind": kind,
                        "engine": layer["engine"], "render_size": [layer["width"], layer["height"]],
                        "fallback_used": layer["fallback"],
                        "source_files": {f: served.get(f) or _sha_file(_repo_file(f, root)) for f in files},
                        "loaded_by_browser": all(f in served for f in files)})
    frames = result["frames"]["frames"]
    chain = hashlib.sha256("".join(frames).encode()).hexdigest()
    outputs = []
    for report, output in zip(result["qa"], result["outputs"]):
        outputs.append({"variant": output["variant"], "file": report["file"], "stored_outside_git": True,
                        "sha256": report["sha256"], "bytes": report["bytes"], "duration_s": report["duration_s"],
                        "streams": report["streams"], "atoms": report["atoms"], "qa_passed": report["passed"],
                        "qa": report["checks"], "sync": report["sync"]})
    probe_summary = (gpu or {}).get("summary")
    sample = canonical_sha256(sb) == canonical_sha256(validate_storyboard(SAMPLE_STORYBOARD, root=root))
    manifest = {
        "schema": EVIDENCE_SCHEMA, "pipeline_version": VERSION, "scenario": "C" if sample else None,
        "generated_at_utc": result["finished_at_utc"],
        "storyboard": {"id": sb["id"], "sha256": canonical_sha256(sb), "title": sb["title"], "languages": sb["languages"],
                       "format": sb["format"], "duration_ms": result["plan_summary"]["duration_ms"],
                       "frames": result["plan_summary"]["frames"], "document": sb},
        "outputs": outputs,
        "qa_passed": all(o["qa_passed"] for o in outputs) and all(s["qa"]["passed"] for s in result["subtitles"]),
        "subtitles": [{k: s[k] for k in ("language", "format", "file", "sha256", "cues")} | {"qa_passed": s["qa"]["passed"]}
                      for s in result["subtitles"]],
        "frames": {"count": len(frames), "hash": "sha256 of RGBA pixels per frame (in-browser crypto.subtle)",
                   "chain_sha256": chain, "first": frames[0], "last": frames[-1], "distinct": len(set(frames))},
        "motions": motions,
        "camera_moves": [{"scene": s["id"], **c} for s, c in zip(sb["scenes"], result["plan_cameras"])],
        "direction": {"passed": result["direction"]["passed"], "warnings": result["direction"]["warnings"],
                      "checks": len(result["direction"]["checks"]),
                      "failed": [c for c in result["direction"]["checks"] if c["status"] == "fail"],
                      "contrast_min": round(min(r["ratio"] for r in result["contrast"]), 2) if result["contrast"] else None,
                      "thresholds": DIRECTION},
        "grade": {"name": sb["grade"], **GRADES[sb["grade"]], "colour_pipeline": "RGB grade -> BT.709 limited-range YUV 4:2:0"},
        "audio": {"music": "procedural" if sb["audio"]["music"] else None, "sound_design": sb["audio"]["sound_design"],
                  "license": AUDIO_LICENSE, "bpm": result["audio"]["bpm"], "chords": result["audio"]["chords"],
                  "cut_markers": result["audio"]["markers"], "master": result["audio"]["master"],
                  "voiceover": {"placed": result["audio"]["voiceover"], "capability": voice,
                                "license": FLITE_LICENSE if result["audio"]["voiceover"] else None}},
        "renderer": {"browser": "chromium", "browser_version": result["preflight"]["browser_version"],
                     "playwright": result["preflight"]["playwright_version"], "chromium_args": result["preflight"]["chromium_args"],
                     "tools": tool_versions(), **renderer_digests(),
                     "page_errors": len(result["frames"]["page_errors"]) + len(result["preflight"]["page_errors"]),
                     "external_requests": len(result["frames"]["external_requests"]) + len(result["preflight"]["external_requests"]),
                     "time_source": "plan.timeline frame index (no wall clock)"},
        "fonts": FONTS,
        "gpu_probe": probe_summary,
        "inventory": inventory(),
        "proven": [
            "Frames rendered headlessly in Chromium from repository motion sources by stepping plan time (no wall clock).",
            "Same storyboard -> same frame hashes (tests/test_video_pipeline.py renders twice and compares).",
            "MP4 outputs measured with ffprobe/ebur128: codec, dimensions, fps, frame count, duration, faststart, AAC audio, "
            "loudness, true peak, no subtitle stream, cuts at planned frames, audio transients on cuts.",
            "Arabic text: shaped glyphs, RTL paragraph order and canvas direction checked in the browser.",
        ],
        "not_proven": [
            "Hardware GPU rendering: WebGL2/WebGPU executed on SwiftShader (CPU) in this environment."
            if probe_summary and not probe_summary.get("hardware_gpu") else "Hardware GPU rendering beyond the probe result.",
            "Arabic voiceover: no local Arabic TTS here; English voiceover is CMU Flite (robotic, not broadcast quality)."
            if result["audio"]["voiceover"] else "Voiceover: not used in this render.",
            "Licensed/commercial music: none used; the bed is procedural and only as good as its synthesis.",
            "Real-device playback, HDR, broadcast (EBU R128 -23 LUFS) delivery, burned-in or embedded subtitles.",
            "Byte-identical MP4 across machines (frames and QA are deterministic here; encoder builds differ).",
        ],
    }
    return manifest


# --------------------------------------------------------------------------- sample (Scenario C)

SAMPLE_STORYBOARD = {
    "schema": SCHEMA,
    "id": "gaie-os-one-command",
    "title": {"en": "GAIE OS: one command, a working system", "ar": "GAIE OS: أمرٌ واحد، ونظامٌ يعمل"},
    "languages": ["ar", "en"],
    "primary_language": "ar",
    "format": {"width": 1920, "height": 1080, "fps": 30},
    "grade": "gaie-teal-amber",
    "fade_in_ms": 500,
    "fade_out_ms": 700,
    "audio": {"bpm": 120, "music": True, "sound_design": True, "voiceover": {"language": "en", "voice": "slt"}},
    "subtitles": {"burn_in": False, "embed": False},
    "scenes": [
        {"id": "one-command", "duration_ms": 2500, "camera": "cinema-dolly-in", "text_position": "center",
         "motion": {"source": "engine", "id": "quantum-light-tunnel", "params": {"speed": 1.2}},
         "text": {"ar": "أمرٌ واحد.", "en": "One command."}},
        {"id": "twenty-layers", "duration_ms": 3500, "camera": "cinema-truck-left", "text_position": "lower-third",
         "motion": {"source": "reference", "id": "os-networks-b01"},
         "text": {"ar": "عشرون طبقة تخطّط وتبني وتختبر.", "en": "Twenty layers plan, build and test."}},
        {"id": "verified", "duration_ms": 2500, "camera": "cinema-crane-rise", "text_position": "lower-third",
         "motion": {"source": "reference", "id": "os-storytelling-b09"},
         "text": {"ar": "كل خطوة مُتحقَّق منها.", "en": "Every step verified."}},
        {"id": "working-system", "duration_ms": 2500, "camera": "static", "text_position": "upper-third",
         "motion": {"source": "camera", "id": "camera-drone-approach"},
         "text": {"ar": "نظامٌ يعمل.", "en": "A working system."}},
        {"id": "gaie-os", "duration_ms": 3000, "camera": "cinema-dolly-out", "text_position": "center",
         "motion": {"source": "engine", "id": "atmosphere-core-ignition"},
         "text": {"ar": "GAIE OS — أمرٌ واحد، ونظامٌ يعمل.", "en": "GAIE OS — one command, a working system."},
         "voiceover": {"en": "One command, a working system."}},
    ],
}


def preview_storyboard(sb=None, width=640, height=360):
    """The same storyboard at a preview size (used by the fast end-to-end test)."""
    preview = copy.deepcopy(sb or SAMPLE_STORYBOARD)
    preview["format"] = {**preview["format"], "width": width, "height": height}
    return preview


def render_sample(out_dir, manifest_path=None, *, name="gaie-sample", storyboard=None, keep_work=False, root=ROOT):
    gpu = browser_probe(root=root)
    voice = voiceover_capability()
    result = render(storyboard or SAMPLE_STORYBOARD, out_dir, name=name, keep_work=keep_work, root=root)
    manifest = build_manifest(result, gpu=gpu, voice=voice, root=root)
    if manifest_path:
        target = pathlib.Path(manifest_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True) + "\n", "utf-8")
    return manifest


# --------------------------------------------------------------------------- engine contract

ENGINE_RECORD = {
    "id": "cinematic-production",
    "layer": "L18",
    "title": {"en": "Cinematic production pipeline", "ar": "خط الإنتاج السينمائي"},
    "entrypoint": "engineering_os.video_pipeline:engine",
    "health": "engineering_os.video_pipeline:health",
    "actions": {
        "inventory": {"side_effect": "none", "permissions": ["read:repo", "secrets:none"], "summary": "Count native engine motions vs Canvas2D reference motions."},
        "validate": {"side_effect": "none", "permissions": ["read:repo", "secrets:none"], "summary": "Validate a gaie.storyboard/1 document."},
        "direct": {"side_effect": "none", "permissions": ["read:repo", "secrets:none"], "summary": "Static cinematic direction checks."},
        "subtitles": {"side_effect": "none", "permissions": ["read:repo", "secrets:none"], "summary": "WebVTT and SRT text for each language."},
        "probe": {"side_effect": "none", "permissions": ["read:repo", "exec:sandbox", "secrets:none"], "summary": "Probe headless Chromium GPU APIs, Arabic rendering and local TTS."},
        "render": {"side_effect": "state-write", "permissions": ["read:repo", "write:state", "exec:sandbox", "secrets:none"], "summary": "Render, encode and QA media into a state directory outside Git."},
        "qa": {"side_effect": "none", "permissions": ["read:state", "exec:sandbox", "secrets:none"], "summary": "Measure an MP4 against an expected delivery format."},
    },
    "supersedes": [],
}


def health():
    missing = [name for name in ("ffmpeg", "ffprobe", "node") if not shutil.which(name)]
    return {"ok": not missing, "detail": "tools present" if not missing else f"missing: {', '.join(missing)}"}


def engine(action, payload, ctx=None):
    """Control-plane entrypoint `(action, payload, ctx) -> dict`. Payloads are data, never instructions."""
    payload = payload or {}
    _need(isinstance(payload, dict), "payload must be an object", VideoPipelineError)
    if action == "inventory":
        return inventory()
    if action == "validate":
        sb = validate_storyboard(payload.get("storyboard"))
        return {"valid": True, "storyboard_sha256": canonical_sha256(sb), "frames": build_plan(sb)["frames"]}
    if action == "direct":
        return direct(validate_storyboard(payload.get("storyboard")))
    if action == "subtitles":
        sb = validate_storyboard(payload.get("storyboard"))
        return {lang: {"vtt": render_vtt(subtitle_cues(sb, lang), lang), "srt": render_srt(subtitle_cues(sb, lang))} for lang in sb["languages"]}
    if action == "probe":
        return {"browser": browser_probe()["summary"], "voiceover": voiceover_capability()}
    if action == "render":
        out_dir = payload.get("out_dir") or (ctx or {}).get("state_dir")
        _need(isinstance(out_dir, str), "render needs out_dir (a state directory outside Git)", VideoPipelineError)
        result = render(payload.get("storyboard"), out_dir, name=payload.get("name"))
        return {"qa_passed": all(r["passed"] for r in result["qa"]), "outputs": result["outputs"],
                "qa": result["qa"], "direction_passed": result["direction"]["passed"]}
    if action == "qa":
        expect = payload.get("expect")
        _need(isinstance(expect, dict), "qa needs expect", VideoPipelineError)
        return qa_media(payload.get("path"), expect)
    raise VideoPipelineError(f"unknown action {action!r}")


# --------------------------------------------------------------------------- CLI

def _load(path):
    if path == "sample":
        return copy.deepcopy(SAMPLE_STORYBOARD)
    return json.loads(pathlib.Path(path).read_text("utf-8"))


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python3 -m engineering_os.video_pipeline", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "direct", "plan"):
        sub.add_parser(name).add_argument("storyboard", help="JSON file, or 'sample'")
    subtitles = sub.add_parser("subtitles")
    subtitles.add_argument("storyboard")
    subtitles.add_argument("--out", required=True)
    sub.add_parser("probe")
    sub.add_parser("inventory")
    run = sub.add_parser("render")
    run.add_argument("storyboard")
    run.add_argument("--out", required=True, help="directory outside the repository")
    run.add_argument("--name")
    run.add_argument("--manifest", help="write the evidence manifest here")
    run.add_argument("--keep-work", action="store_true")
    check = sub.add_parser("qa")
    check.add_argument("file")
    check.add_argument("--width", type=int, required=True)
    check.add_argument("--height", type=int, required=True)
    check.add_argument("--fps", type=int, required=True)
    check.add_argument("--frames", type=int, required=True)
    check.add_argument("--cut-frames", default="")
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            sb = validate_storyboard(_load(args.storyboard))
            output = {"valid": True, "storyboard_sha256": canonical_sha256(sb), "frames": build_plan(sb)["frames"]}
        elif args.command == "direct":
            output = direct(validate_storyboard(_load(args.storyboard)))
        elif args.command == "plan":
            plan = build_plan(validate_storyboard(_load(args.storyboard)))
            output = {k: v for k, v in plan.items() if k != "timeline"}
        elif args.command == "subtitles":
            sb = validate_storyboard(_load(args.storyboard))
            out = _outside_repository(args.out)
            output = []
            for lang in sb["languages"]:
                cues = subtitle_cues(sb, lang)
                for kind, text in (("vtt", render_vtt(cues, lang)), ("srt", render_srt(cues))):
                    target = out / f"{sb['id']}.{lang}.{kind}"
                    target.write_text(text, "utf-8")
                    output.append(str(target))
        elif args.command == "probe":
            output = {"browser": browser_probe()["summary"], "voiceover": voiceover_capability()}
        elif args.command == "inventory":
            output = inventory()
        elif args.command == "render":
            sb = _load(args.storyboard)
            if args.manifest:
                manifest = render_sample(args.out, args.manifest, name=args.name or "gaie-sample", storyboard=sb, keep_work=args.keep_work)
                output = {"qa_passed": manifest["qa_passed"], "outputs": [{k: o[k] for k in ("file", "sha256", "bytes", "qa_passed")} for o in manifest["outputs"]],
                          "manifest": args.manifest}
            else:
                result = render(sb, args.out, name=args.name, keep_work=args.keep_work)
                output = {"qa_passed": all(r["passed"] for r in result["qa"]), "outputs": result["outputs"]}
        else:
            cuts = [int(x) for x in args.cut_frames.split(",") if x]
            output = qa_media(args.file, {"width": args.width, "height": args.height, "fps": args.fps,
                                          "frames": args.frames, "cut_frames": cuts})
    except DirectionError as error:
        print(json.dumps({"error": str(error), "direction": error.report}, ensure_ascii=False, indent=1))
        return 2
    except VideoPipelineError as error:
        print(json.dumps({"error": f"{type(error).__name__}: {error}"}, ensure_ascii=False))
        return 2
    print(json.dumps(output, ensure_ascii=False, indent=1))
    return 0 if not isinstance(output, dict) or output.get("qa_passed", output.get("passed", True)) else 1


# --------------------------------------------------------------------------- browser assets
# The compositor and the Node driver are generated into the private work directory at run
# time (they are part of this reviewed source file and hashed into every manifest).

_COMPOSITOR_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>GAIE compositor</title>
<style>html,body{margin:0;background:#000;overflow:hidden}</style></head>
<body><script type="module" src="/__gaie/compositor.mjs"></script></body></html>
"""

_COMPOSITOR_JS = r"""// GAIE cinematic compositor (generated by engineering_os/video_pipeline.py; MIT).
// Executes a frame plan computed in Python. Time never comes from a clock: frame i is
// drawn from plan.timeline[i] only, so the same plan always yields the same pixels.
import { sampleMotion as sampleReference } from '/motion-library/expansion/catalog.mjs';
import { sampleMotion as sampleCamera } from '/motion-library/expansion/nextgen-camera.mjs';
import { drawScene } from '/packages/motion-sdk/index.mjs';
import { createMotion } from '/packages/motion-engines/core/api.mjs';
import { createVirtualClock } from '/packages/motion-engines/core/clock.mjs';
import { isArabic } from '/packages/motion-engines/core/text.mjs';

const S = { plan: null, comp: null, g: null, layers: [], layout: null, host: null, fonts: { ar: '"DejaVu Sans"', en: '"Inter"' } };
const hex = async (data) => Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', data)), (b) => b.toString(16).padStart(2, '0')).join('');
const fontFor = (lang, size, weight) => `${weight} ${size}px ${S.fonts[lang] || S.fonts.en},sans-serif`;
const luminance = (r, g, b) => {
  const c = (v) => { v /= 255; return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
  return 0.2126 * c(r) + 0.7152 * c(g) + 0.0722 * c(b);
};

function host() {
  if (!S.host) {
    S.host = document.createElement('div');
    S.host.style.cssText = 'position:fixed;left:0;top:0;width:0;height:0;overflow:hidden;';
    document.body.append(S.host);
  }
  return S.host;
}

async function makeLayer(plan, m) {
  const pw = Math.max(2, Math.round(plan.width * m.render_scale));
  const ph = Math.max(2, Math.round(plan.height * m.render_scale));
  if (m.source === 'engine') {
    const definition = (await import(m.module)).default;
    if (!definition || definition.id !== m.id) throw new Error(`motion module does not define ${m.id}`);
    const stage = document.createElement('div');
    host().append(stage);
    const instance = await createMotion(definition, {
      container: stage, width: pw, height: ph, pixelRatio: 1, quality: 'high', clock: createVirtualClock(),
      reducedMotion: false, direction: 'ltr', locale: 'en', ...(m.options || {}),
    });
    if (!instance.canvas) throw new Error(`${m.id}: the compositor needs a motion drawn on one canvas`);
    const info = instance.info();
    return {
      id: m.id, source: 'engine', engine: definition.engine, width: pw, height: ph, fallback: info.fallback ?? null,
      async draw(at) {
        instance.render({ time: at.time_ms });
        if (definition.engine === 'webgpu-wgsl') await instance.settled();
        return instance.canvas;
      },
      dispose() { instance.destroy(); stage.remove(); },
    };
  }
  const canvas = document.createElement('canvas');
  canvas.width = pw; canvas.height = ph;
  const pg = canvas.getContext('2d', { alpha: false });
  const sample = m.source === 'reference' ? sampleReference : sampleCamera;
  return {
    id: m.id, source: m.source, engine: 'canvas2d', width: pw, height: ph, fallback: null,
    async draw(at) {
      drawScene(pg, sample(m.id, at.progress, { width: pw, height: ph, ...(m.options || {}) }), { pixelRatio: 1 });
      return canvas;
    },
    dispose() { canvas.width = 1; },
  };
}

function layoutTexts(plan) {
  const g = S.g;
  const blocks = {};
  for (const block of plan.text_blocks) {
    const lines = block.lines.map((line) => {
      let size = line.size_px;
      g.font = fontFor(line.lang, size, line.weight);
      g.direction = line.dir; g.textAlign = 'center'; g.textBaseline = 'alphabetic';
      let m = g.measureText(line.text);
      const room = plan.safe.x1 - plan.safe.x0;
      let fitted = false;
      if (m.actualBoundingBoxLeft + m.actualBoundingBoxRight > room) {
        size = Math.floor(size * room / (m.actualBoundingBoxLeft + m.actualBoundingBoxRight));
        g.font = fontFor(line.lang, size, line.weight);
        m = g.measureText(line.text);
        fitted = true;
      }
      return { lang: line.lang, dir: line.dir, text: line.text, color: line.color, weight: line.weight, font: g.font,
        canvas_direction: g.direction, size, requested_size: line.size_px, fitted, advance: m.width,
        left: m.actualBoundingBoxLeft, right: m.actualBoundingBoxRight, ascent: m.actualBoundingBoxAscent, descent: m.actualBoundingBoxDescent };
    });
    const gap = Math.round(lines[0].size * 0.32);
    const heights = lines.map((l) => l.ascent + l.descent);
    const total = heights.reduce((a, b) => a + b, 0) + gap * (lines.length - 1);
    let top = block.center_y - total / 2;
    const x = plan.width / 2;
    lines.forEach((l, i) => {
      l.x = x; l.baseline = top + l.ascent;
      l.box = { x0: x - l.left, x1: x + l.right, y0: l.baseline - l.ascent, y1: l.baseline + l.descent };
      top += heights[i] + gap;
    });
    const box = { x0: Math.min(...lines.map((l) => l.box.x0)), x1: Math.max(...lines.map((l) => l.box.x1)),
      y0: Math.min(...lines.map((l) => l.box.y0)), y1: Math.max(...lines.map((l) => l.box.y1)) };
    blocks[block.scene] = { scene: block.scene, lines, box, pad: Math.round(lines[0].size * 0.9) };
  }
  return blocks;
}

function drawBlock(T, glyphs) {
  const { g, plan } = S;
  const block = S.layout[T.scene];
  if (!block || T.opacity <= 0) return;
  const { box, pad } = block;
  g.save();
  g.globalAlpha = T.opacity * plan.scrim_alpha;
  const y0 = box.y0 - pad + T.dy, y1 = box.y1 + pad + T.dy;
  const gradient = g.createLinearGradient(0, y0, 0, y1);
  gradient.addColorStop(0, 'rgba(3,6,14,0)');
  gradient.addColorStop(0.3, 'rgba(3,6,14,1)');
  gradient.addColorStop(0.7, 'rgba(3,6,14,1)');
  gradient.addColorStop(1, 'rgba(3,6,14,0)');
  g.fillStyle = gradient;
  g.fillRect(0, y0, plan.width, y1 - y0);
  g.restore();
  if (!glyphs) return;
  for (const l of block.lines) {
    g.save();
    g.globalAlpha = T.opacity;
    g.font = l.font; g.direction = l.dir; g.textAlign = 'center'; g.textBaseline = 'alphabetic';
    g.shadowColor = 'rgba(0,0,0,0.5)'; g.shadowBlur = Math.round(l.size * 0.16); g.shadowOffsetY = Math.round(l.size * 0.03);
    g.fillStyle = l.color;
    g.fillText(l.text, l.x, l.baseline + T.dy);
    g.restore();
  }
}

async function compose(index, { glyphs = true } = {}) {
  const { g, plan } = S;
  const f = plan.timeline[index];
  if (!f) throw new Error(`no frame ${index}`);
  const W = plan.width, H = plan.height;
  g.save();
  g.setTransform(1, 0, 0, 1, 0, 0);
  g.globalAlpha = 1; g.filter = 'none'; g.globalCompositeOperation = 'source-over';
  g.fillStyle = '#000'; g.fillRect(0, 0, W, H);
  for (const L of f.layers) {
    const source = await S.layers[L.scene].draw(L);
    g.save();
    g.globalAlpha = L.opacity;
    g.filter = L.camera.blur > 0 ? `blur(${L.camera.blur}px)` : 'none';
    g.imageSmoothingEnabled = true; g.imageSmoothingQuality = 'high';
    g.translate(W / 2 + L.camera.tx * W, H / 2 + L.camera.ty * H);
    g.scale(L.camera.scale, L.camera.scale);
    g.drawImage(source, -W / 2, -H / 2, W, H);
    g.restore();
  }
  for (const T of f.texts) drawBlock(T, glyphs);
  if (f.fade > 0) { g.globalAlpha = f.fade; g.fillStyle = '#000'; g.fillRect(0, 0, W, H); }
  g.restore();
}

const pixels = () => S.g.getImageData(0, 0, S.plan.width, S.plan.height).data;

async function setup(plan) {
  for (const layer of S.layers) layer.dispose();
  S.plan = plan; S.layers = [];
  if (plan.fonts) S.fonts = plan.fonts;
  if (!S.comp) { S.comp = document.createElement('canvas'); document.body.append(S.comp); }
  S.comp.width = plan.width; S.comp.height = plan.height;
  S.g = S.comp.getContext('2d', { alpha: false, willReadFrequently: true });
  for (const scene of plan.scenes) S.layers.push(await makeLayer(plan, scene.motion));
  S.layout = layoutTexts(plan);
  return { layout: S.layout, layers: S.layers.map((l) => ({ id: l.id, source: l.source, engine: l.engine, width: l.width, height: l.height, fallback: l.fallback })) };
}

async function frame(index) {
  await compose(index);
  const sha256 = await hex(pixels());
  return { index, sha256, png: S.comp.toDataURL('image/png') };
}

// Worst-case (95th percentile) background luminance under each text line, with the scrim
// but without glyphs, at the frame where the block is fully visible.
async function contrast(samples) {
  const out = [];
  for (const sample of samples) {
    await compose(sample.frame, { glyphs: false });
    const block = S.layout[sample.scene];
    if (!block) continue;
    const data = pixels();
    for (const l of block.lines) {
      const x0 = Math.max(0, Math.floor(l.box.x0)), x1 = Math.min(S.plan.width, Math.ceil(l.box.x1));
      const y0 = Math.max(0, Math.floor(l.box.y0 + sample.dy)), y1 = Math.min(S.plan.height, Math.ceil(l.box.y1 + sample.dy));
      const values = [];
      for (let y = y0; y < y1; y += 2) for (let x = x0; x < x1; x += 2) {
        const i = (y * S.plan.width + x) * 4;
        values.push(luminance(data[i], data[i + 1], data[i + 2]));
      }
      values.sort((a, b) => a - b);
      const background = values.length ? values[Math.min(values.length - 1, Math.floor(values.length * 0.95))] : 0;
      const [r, gg, b] = [1, 3, 5].map((k) => parseInt(l.color.slice(k, k + 2), 16));
      const text = luminance(r, gg, b);
      const ratio = (Math.max(text, background) + 0.05) / (Math.min(text, background) + 0.05);
      out.push({ scene: sample.scene, frame: sample.frame, lang: l.lang, background_p95_luminance: background, text_luminance: text, ratio });
    }
  }
  return out;
}

function inkBox(data, w, h) {
  let x0 = w, x1 = -1;
  for (let y = 0; y < h; y += 1) for (let x = 0; x < w; x += 1) if (data[(y * w + x) * 4 + 3] > 0) { if (x < x0) x0 = x; if (x > x1) x1 = x; }
  return x1 < 0 ? null : { x0, x1 };
}

// Facts about Arabic rendering: real glyphs (not .notdef boxes), contextual joining,
// and right-to-left paragraph order (the first logical word sits at the right edge).
function rtlProbe(lines, options = {}) {
  if (options.fonts) S.fonts = options.fonts;
  const size = options.size || 72;
  const forced = options.forceDirection || null;
  const w = 1800, h = Math.round(size * 2.2);
  const canvas = document.createElement('canvas'); canvas.width = w; canvas.height = h;
  const g = canvas.getContext('2d', { willReadFrequently: true });
  const draw = (text, direction) => {
    g.setTransform(1, 0, 0, 1, 0, 0); g.clearRect(0, 0, w, h);
    g.font = fontFor('ar', size, 700); g.direction = direction; g.textAlign = 'right'; g.textBaseline = 'middle';
    g.fillStyle = '#ffffff'; g.fillText(text, w - 40, h / 2);
    return g.getImageData(0, 0, w, h).data.slice();
  };
  const differ = (a, b) => { let n = 0; for (let i = 3; i < a.length; i += 4) if (Math.abs(a[i] - b[i]) > 16) n += 1; return n; };
  const glyphsDistinct = differ(draw('\u0628', 'rtl'), draw('\u062A', 'rtl')) > 20;
  const results = [];
  for (const text of lines) {
    const direction = forced || 'rtl';
    const words = text.split(/\s+/u).filter(Boolean);
    const full = draw(text, direction);
    const fullBox = inkBox(full, w, h);
    const longest = [...words].sort((a, b) => b.length - a.length)[0] || text;
    const shaping = differ(draw(longest, direction), draw(Array.from(longest).join('\u200C'), direction)) > 20;
    // The first logical run: a leading Latin run (e.g. a brand name) stays one LTR run.
    let lead = words[0] || text;
    if (/[A-Za-z]/.test(lead) && !isArabic(lead)) {
      const run = [];
      for (const word of words) { if (/[A-Za-z]/.test(word) && !isArabic(word)) run.push(word); else break; }
      lead = run.join(' ');
    }
    const first = draw(lead, direction);
    const firstBox = inkBox(first, w, h);
    let mismatch = null;
    if (firstBox && fullBox) {
      mismatch = 0;
      for (let y = 0; y < h; y += 1) for (let x = firstBox.x0 + 2; x <= firstBox.x1; x += 1) {
        const i = (y * w + x) * 4 + 3;
        if (Math.abs(first[i] - full[i]) > 16) mismatch += 1;
      }
    }
    results.push({ text, direction, arabic: isArabic(text), words: words.length, ink: fullBox, first_run: lead,
      first_word_at_right_edge: mismatch === 0, first_word_mismatch_pixels: mismatch, contextual_shaping: shaping });
  }
  // A family is available when it changes the advance of its own script against monospace.
  const width = (font, text) => { g.font = font; return g.measureText(text).width; };
  const probes = { ar: '\u0627\u0644\u0639\u0631\u0628\u064A\u0629 \u0646\u0638\u0627\u0645', en: 'Working system 0123' };
  const fonts = {};
  for (const lang of Object.keys(probes)) {
    fonts[lang] = Math.abs(width(`700 ${size}px ${S.fonts[lang]},monospace`, probes[lang]) - width(`700 ${size}px monospace`, probes[lang])) > 0.5;
  }
  return { glyphs_distinct: glyphsDistinct, lines: results, fonts, font_css: { ...S.fonts } };
}

async function gpuProbe() {
  const out = { webgl2: { context: false }, webgpu: { api: Boolean(navigator.gpu) } };
  const c = document.createElement('canvas'); c.width = 4; c.height = 4;
  const gl = c.getContext('webgl2');
  if (gl) {
    gl.clearColor(0.25, 0.5, 0.75, 1); gl.clear(gl.COLOR_BUFFER_BIT);
    const px = new Uint8Array(4); gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px);
    const ext = gl.getExtension('WEBGL_debug_renderer_info');
    out.webgl2 = { context: true, executed: Math.abs(px[0] - 64) <= 1 && Math.abs(px[1] - 128) <= 1 && Math.abs(px[2] - 191) <= 1,
      readback: Array.from(px), renderer: ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER),
      vendor: ext ? gl.getParameter(ext.UNMASKED_VENDOR_WEBGL) : gl.getParameter(gl.VENDOR) };
    gl.getExtension('WEBGL_lose_context')?.loseContext();
  }
  if (navigator.gpu) {
    try {
      const adapter = await navigator.gpu.requestAdapter();
      out.webgpu.adapter = Boolean(adapter);
      if (adapter) {
        const info = adapter.info || {};
        out.webgpu.info = { vendor: info.vendor || '', architecture: info.architecture || '', device: info.device || '',
          description: info.description || '', fallback: Boolean(info.isFallbackAdapter ?? adapter.isFallbackAdapter) };
        const device = await adapter.requestDevice();
        const n = 64;
        const input = new Uint32Array(n).map((_, i) => i + 1);
        const buffer = device.createBuffer({ size: n * 4, usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_SRC | GPUBufferUsage.COPY_DST });
        device.queue.writeBuffer(buffer, 0, input);
        const read = device.createBuffer({ size: n * 4, usage: GPUBufferUsage.COPY_DST | GPUBufferUsage.MAP_READ });
        const module = device.createShaderModule({ code: '@group(0) @binding(0) var<storage, read_write> v: array<u32>;\n@compute @workgroup_size(64) fn main(@builtin(global_invocation_id) id: vec3<u32>) { v[id.x] = v[id.x] * 2u + 1u; }' });
        const pipeline = device.createComputePipeline({ layout: 'auto', compute: { module, entryPoint: 'main' } });
        const bind = device.createBindGroup({ layout: pipeline.getBindGroupLayout(0), entries: [{ binding: 0, resource: { buffer } }] });
        const encoder = device.createCommandEncoder();
        const pass = encoder.beginComputePass(); pass.setPipeline(pipeline); pass.setBindGroup(0, bind); pass.dispatchWorkgroups(1); pass.end();
        encoder.copyBufferToBuffer(buffer, 0, read, 0, n * 4);
        device.queue.submit([encoder.finish()]);
        await read.mapAsync(GPUMapMode.READ);
        const result = new Uint32Array(read.getMappedRange().slice(0));
        read.unmap();
        out.webgpu.compute_executed = result.every((v, i) => v === (i + 1) * 2 + 1);
        device.destroy();
      }
    } catch (error) {
      out.webgpu.error = String((error && error.message) || error);
    }
  }
  return out;
}

window.gaie = { ready: true, setup, frame, contrast, rtlProbe, gpuProbe };
"""

_RENDERER_JS = r"""'use strict';
// GAIE headless renderer (generated by engineering_os/video_pipeline.py; MIT).
// Drives the compositor in Chromium through Playwright. Every request is answered from
// the reviewed repository allowlist or refused: nothing leaves the machine.
//   node renderer.cjs <probe|preflight|render> job.json   (render writes PNG frames to stdout)
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { pathToFileURL } = require('url');

const ORIGIN = 'http://localhost';
const TYPES = { '.mjs': 'text/javascript', '.js': 'text/javascript', '.json': 'application/json' };

async function main() {
  const [command, jobPath] = process.argv.slice(2);
  if (!['probe', 'preflight', 'render'].includes(command)) throw new Error('command must be probe, preflight or render');
  const job = JSON.parse(fs.readFileSync(jobPath, 'utf8'));
  const root = fs.realpathSync(job.repo_root);
  const tools = await import(pathToFileURL(path.join(root, 'packages/motion-engines/tools/playwright.mjs')).href);
  const { playwright, version } = tools.loadPlaywright();
  const result = { command, playwright_version: version, chromium_args: tools.CHROMIUM_ARGS, external_requests: [], refused: [], page_errors: [], served: {} };
  const own = { '/__gaie/compositor.html': [job.compositor_html, 'text/html'], '/__gaie/compositor.mjs': [job.compositor_js, 'text/javascript'] };
  const serve = async (route) => {
    const url = new URL(route.request().url());
    if (url.origin !== ORIGIN) { result.external_requests.push(url.origin); return route.abort(); }
    const name = decodeURIComponent(url.pathname);
    if (own[name]) return route.fulfill({ status: 200, contentType: own[name][1], body: fs.readFileSync(own[name][0]) });
    const relative = name.replace(/^\/+/, '');
    const allowed = job.allowed_prefixes.some((prefix) => relative.startsWith(prefix)) && TYPES[path.extname(relative)]
      && !relative.split('/').some((part) => part === '..' || part === '' || part.startsWith('.'));
    let file = null;
    if (allowed) {
      const candidate = path.join(root, relative);
      try {
        if (!fs.lstatSync(candidate).isSymbolicLink() && fs.realpathSync(candidate) === candidate && candidate.startsWith(root + path.sep)) file = candidate;
      } catch { file = null; }
    }
    if (!file) { result.refused.push(relative.slice(0, 200)); return route.fulfill({ status: 404, body: '' }); }
    const body = fs.readFileSync(file);
    result.served[relative] = crypto.createHash('sha256').update(body).digest('hex');
    return route.fulfill({ status: 200, contentType: TYPES[path.extname(file)], body });
  };
  const browser = await playwright.chromium.launch({ args: tools.CHROMIUM_ARGS });
  result.browser_version = browser.version();
  try {
    const page = await browser.newPage({ viewport: { width: job.viewport.width, height: job.viewport.height }, deviceScaleFactor: 1 });
    page.on('pageerror', (error) => result.page_errors.push(String(error.message).slice(0, 500)));
    page.on('console', (message) => { if (message.type() === 'error') result.page_errors.push(('console: ' + message.text()).slice(0, 500)); });
    await page.route('**/*', serve);
    await page.goto(ORIGIN + '/__gaie/compositor.html');
    await page.waitForFunction(() => window.gaie && window.gaie.ready === true, null, { timeout: 30000 });
    if (command === 'probe' || command === 'preflight') {
      result.gpu = await page.evaluate(() => window.gaie.gpuProbe());
      result.rtl = await page.evaluate(([lines, options]) => window.gaie.rtlProbe(lines, options), [job.rtl_lines || [], job.rtl_options || {}]);
    }
    if (command === 'preflight' || command === 'render') {
      result.setup = await page.evaluate((plan) => window.gaie.setup(plan), job.plan);
    }
    if (command === 'preflight') {
      result.contrast = await page.evaluate((samples) => window.gaie.contrast(samples), job.contrast_samples || []);
    }
    if (command === 'render') {
      const frames = [];
      const out = process.stdout;
      for (let index = 0; index < job.plan.timeline.length; index += 1) {
        const shot = await page.evaluate((i) => window.gaie.frame(i), index);
        const png = Buffer.from(shot.png.slice(shot.png.indexOf(',') + 1), 'base64');
        frames.push(shot.sha256);
        if (!out.write(png)) await new Promise((drained) => out.once('drain', drained));
      }
      result.frames = frames;
      await new Promise((done) => out.end(done));
    }
  } finally {
    await browser.close();
    fs.writeFileSync(job.result_path, JSON.stringify(result));
  }
}

main().catch((error) => {
  process.stderr.write(String((error && error.stack) || error) + '\n');
  process.exit(1);
});
"""


if __name__ == "__main__":
    sys.exit(main())
