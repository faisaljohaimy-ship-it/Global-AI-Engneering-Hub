"""Cinematic production pipeline (L08/L18): storyboard -> direction -> frames -> audio ->
subtitles -> encode -> media QA. Browser and ffmpeg tests run real tools and are skipped
(never faked) only where those tools are absent."""
import array
import copy
import functools
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest
import wave

from engineering_os import cinematic, contracts
from engineering_os import video_pipeline as vp

ROOT = pathlib.Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/evidence/gaie-20-layers/video-sample.json"
HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


@functools.lru_cache(maxsize=1)
def browser_available():
    if not shutil.which("node"):
        return False
    try:
        vp.browser_probe(rtl_lines=())
        return True
    except vp.ToolMissing:
        return False


def small_storyboard(**changes):
    """Three 1 s shots (native GLSL engine, Canvas2D reference, nextgen camera) at 320x180."""
    sb = {
        "schema": vp.SCHEMA, "id": "det-clip", "title": {"ar": "مقطع اختبار", "en": "Test clip"},
        "languages": ["ar", "en"], "primary_language": "ar", "format": {"width": 320, "height": 180, "fps": 30},
        "audio": {"bpm": 120, "music": True, "sound_design": True, "voiceover": None},
        "scenes": [
            {"id": "glsl", "duration_ms": 1000, "camera": "cinema-dolly-in",
             "motion": {"source": "engine", "id": "quantum-light-tunnel"}, "text": {"ar": "أمرٌ واحد.", "en": "One command."}},
            {"id": "reference", "duration_ms": 1000, "camera": "cinema-truck-left",
             "motion": {"source": "reference", "id": "os-networks-b01"}, "text": {"ar": "نظامٌ يعمل.", "en": "It works."}},
            {"id": "camera", "duration_ms": 1000, "motion": {"source": "camera", "id": "camera-drone-approach"},
             "text": {"ar": "تحقّق.", "en": "Verified."}},
        ],
    }
    sb.update(changes)
    return sb


class StoryboardValidationTests(unittest.TestCase):
    def setUp(self):
        self.sb = copy.deepcopy(vp.SAMPLE_STORYBOARD)

    def test_sample_is_a_valid_bilingual_10_to_15_second_storyboard(self):
        sb = vp.validate_storyboard(self.sb)
        self.assertEqual(sb["languages"], ["ar", "en"])
        plan = vp.build_plan(sb)
        self.assertEqual((plan["frames"], plan["fps"], plan["width"], plan["height"]), (420, 30, 1920, 1080))
        self.assertTrue(10000 <= plan["duration_ms"] <= 15000)
        self.assertEqual({s["motion"]["source"] for s in sb["scenes"]}, {"engine", "reference", "camera"})
        self.assertEqual(self.sb, vp.SAMPLE_STORYBOARD, "validation must not mutate its input")

    def test_negative_storyboards_are_refused(self):
        def scene(mutate):
            return lambda sb: mutate(sb["scenes"][0])
        cases = {
            "wrong schema": lambda sb: sb.update(schema="gaie.storyboard/2"),
            "unknown top field": lambda sb: sb.update(script="rm -rf /"),
            "unknown scene field": scene(lambda s: s.update(html="<script>")),
            "missing english line": scene(lambda s: s["text"].pop("en")),
            "arabic without arabic script": scene(lambda s: s["text"].update(ar="One command.")),
            "english with arabic script": scene(lambda s: s["text"].update(en="أمر")),
            "bidi override": scene(lambda s: s["text"].update(en="One ‮command")),
            "control character": scene(lambda s: s["text"].update(en="One\x07command")),
            "text too long": scene(lambda s: s["text"].update(en="x" * 91)),
            "unknown engine motion": scene(lambda s: s["motion"].update(id="quantum-made-up")),
            "path as motion id": scene(lambda s: s["motion"].update(id="../../etc/passwd")),
            "dom engine not readable": scene(lambda s: s["motion"].update(id="micro-magnetic-button")),
            "composition engine not readable": scene(lambda s: s["motion"].update(id="compositions-quantum-master-sequence")),
            "unknown engine parameter": scene(lambda s: s["motion"].update(params={"warp": 2})),
            "engine parameter out of range": scene(lambda s: s["motion"].update(params={"speed": 9})),
            "render scale out of range": scene(lambda s: s["motion"].update(render_scale=2)),
            "unknown reference motion": lambda sb: sb["scenes"][1]["motion"].update(id="os-networks-b99"),
            "unknown camera scene": lambda sb: sb["scenes"][3]["motion"].update(id="camera-orbit"),
            "unknown source": scene(lambda s: s.update(motion={"source": "url", "id": "https://example.com/x.mjs"})),
            "unknown camera move": scene(lambda s: s.update(camera="cinema-whip-pan")),
            "not whole frames": scene(lambda s: s.update(duration_ms=2510)),
            "shot too short": scene(lambda s: s.update(duration_ms=900)),
            "fps not allowed": lambda sb: sb["format"].update(fps=29),
            "odd width": lambda sb: sb["format"].update(width=1919),
            "duplicate scene id": lambda sb: sb["scenes"][1].update(id=sb["scenes"][0]["id"]),
            "dissolve into first shot": scene(lambda s: s.update(transition_in="dissolve")),
            "dissolve_ms without dissolve": lambda sb: sb["scenes"][1].update(dissolve_ms=500),
            "burned subtitles": lambda sb: sb.update(subtitles={"burn_in": True}),
            "unknown voice": lambda sb: sb["audio"].update(voiceover={"language": "en", "voice": "cloud-neural"}),
            "voiceover override without voiceover": lambda sb: (sb["audio"].update(voiceover=None),
                                                                 sb["scenes"][0].update(voiceover={"en": "Hi."})),
            "fade longer than half shot": lambda sb: sb.update(fade_in_ms=1500),
            "longer than 120 s": lambda sb: sb.update(scenes=[dict(sb["scenes"][1], id=f"s{i}", duration_ms=10000) for i in range(13)]),
            "language missing from title": lambda sb: sb["title"].pop("ar"),
            "unsupported language": lambda sb: sb.update(languages=["ar", "fr"]),
            "not an object": lambda sb: sb["scenes"].__setitem__(0, "scene"),
            "unhashable camera": scene(lambda s: s.update(camera=["static"])),
            "unhashable language": lambda sb: sb.update(languages=[["ar"]]),
            "unhashable source": scene(lambda s: s["motion"].update(source={"engine": 1})),
            "unhashable transition": lambda sb: sb["scenes"][1].update(transition_in=["cut"]),
            "unhashable voice": lambda sb: sb["audio"].update(voiceover={"language": "en", "voice": ["slt"]}),
            "dissolve longer than half a shot": lambda sb: sb["scenes"][1].update(transition_in="dissolve", dissolve_ms=1000,
                                                                                  duration_ms=1500),
        }
        for name, mutate in cases.items():
            sb = copy.deepcopy(vp.SAMPLE_STORYBOARD)
            mutate(sb)
            with self.subTest(name), self.assertRaises(vp.StoryboardError):
                vp.validate_storyboard(sb)

    def test_changed_engine_source_is_refused_until_its_evidence_is_rebuilt(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            for relative in [vp.REGISTRY, vp.REFERENCE_DEFINITIONS, "packages/motion-engines/motions/quantum/light-tunnel.mjs",
                             "packages/motion-engines/motions/atmosphere/core-ignition.mjs"]:
                (root / relative).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / relative, root / relative)
            vp.validate_storyboard(self.sb, root=root)
            source = root / "packages/motion-engines/motions/quantum/light-tunnel.mjs"
            source.write_bytes(source.read_bytes() + b"\n// changed\n")
            with self.assertRaisesRegex(vp.VideoPipelineError, "changed since its registry"):
                vp.validate_storyboard(self.sb, root=root)


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.sb = vp.validate_storyboard(vp.SAMPLE_STORYBOARD)
        self.plan = vp.build_plan(self.sb)

    def test_frames_and_cuts_are_exact(self):
        self.assertEqual([c["frame"] for c in self.plan["cuts"]], [75, 180, 255, 330])
        self.assertEqual(len(self.plan["timeline"]), 420)
        for frame in self.plan["timeline"]:
            self.assertEqual(len(frame["layers"]), 1)  # hard cuts only: one shot per frame

    def test_camera_moves_follow_the_reviewed_specs(self):
        dolly = [f["layers"][0]["camera"]["scale"] for f in self.plan["timeline"][:75]]
        self.assertAlmostEqual(dolly[0], 1.0)
        self.assertAlmostEqual(vp.css_ease("ease-in-out", 74 / 75) * 0.12 + 1, dolly[-1], places=5)
        self.assertEqual(dolly, sorted(dolly))
        for frame in self.plan["timeline"][75:180]:  # truck-left: +-4 % travel inside 1.08x overscan
            camera = frame["layers"][0]["camera"]
            self.assertGreaterEqual(camera["scale"] + 1e-9, 1 + 2 * abs(camera["tx"]))
        self.assertAlmostEqual(self.plan["timeline"][75]["layers"][0]["camera"]["tx"], 0.04)

    def test_text_fades_in_after_the_cut_and_out_before_the_next(self):
        texts = [f["texts"] for f in self.plan["timeline"]]
        self.assertEqual(texts[75 + 8], [])  # 266 ms into the shot: not yet
        self.assertEqual(texts[75 + 9], [])  # 300 ms: the fade starts at opacity 0, nothing drawn yet
        self.assertGreater(texts[75 + 10][0]["opacity"], 0)
        self.assertGreater(texts[75 + 10][0]["dy"], 0)  # still sliding up
        middle = texts[120][0]
        self.assertEqual((middle["opacity"], middle["dy"]), (1.0, 0.0))
        self.assertEqual(texts[179], [])  # the last frame of the shot is clean

    def test_film_fades_and_is_deterministic(self):
        self.assertEqual(self.plan["timeline"][0]["fade"], 1.0)
        self.assertEqual(self.plan["timeline"][-1]["fade"], 1.0)
        self.assertEqual(self.plan["timeline"][200]["fade"], 0.0)
        self.assertEqual(contracts.sha256(self.plan), contracts.sha256(vp.build_plan(self.sb)))

    def test_dissolve_blends_two_shots_around_the_cut(self):
        sb = copy.deepcopy(vp.SAMPLE_STORYBOARD)
        default = copy.deepcopy(sb)
        default["scenes"][1]["transition_in"] = "dissolve"
        self.assertEqual(vp.validate_storyboard(default)["scenes"][1]["dissolve_ms"], 500)  # 7.5 frames each side is fine
        sb["scenes"][1].update(transition_in="dissolve", dissolve_ms=600)
        plan = vp.build_plan(vp.validate_storyboard(sb))
        around = plan["timeline"][75 - 8:75 + 9]  # 600 ms centred on the cut; the frame at opacity 0 is skipped
        self.assertTrue(all(len(f["layers"]) == 2 for f in around))
        self.assertEqual((len(plan["timeline"][66]["layers"]), len(plan["timeline"][84]["layers"])), (1, 1))
        incoming = [next(l["opacity"] for l in f["layers"] if l["scene"] == 1) for f in around]
        self.assertEqual(incoming, sorted(incoming))
        self.assertLess(incoming[0], 0.05)
        self.assertGreater(incoming[-1], 0.95)
        self.assertEqual([c["kind"] for c in plan["cuts"]][0], "dissolve")

    def test_css_easing_matches_reference_curves(self):
        self.assertEqual(vp.css_ease("linear", 0.3), 0.3)
        self.assertAlmostEqual(vp.css_ease("ease-in-out", 0.5), 0.5, places=6)
        self.assertGreater(vp.css_ease("ease-out", 0.5), 0.5)
        self.assertLess(vp.css_ease("ease-in", 0.5), 0.5)
        self.assertEqual((vp.css_ease("ease", 0), vp.css_ease("ease", 1)), (0.0, 1.0))


class DirectionTests(unittest.TestCase):
    def test_sample_passes_static_direction(self):
        report = vp.direct(vp.validate_storyboard(vp.SAMPLE_STORYBOARD))
        self.assertTrue(report["passed"], report["errors"])
        self.assertEqual(report["warnings"], [])
        ids = {c["id"] for c in report["checks"]}
        self.assertTrue({"pacing.shot_length", "reading.cps.ar", "reading.cps.en", "rtl.arabic_script",
                         "music.cut_on_beat", "framing.camera_overscan", "edit.cut_frames_exact"} <= ids)

    def test_reading_speed_violation_is_an_error(self):
        sb = copy.deepcopy(vp.SAMPLE_STORYBOARD)
        sb["scenes"][0].update(duration_ms=2000, text={"ar": "عشرون طبقة تخطّط وتبني وتختبر وتنشر وتراقب.",
                                                       "en": "Twenty layers plan, build, test, ship and watch."})
        report = vp.direct(vp.validate_storyboard(sb))
        self.assertFalse(report["passed"])
        self.assertEqual({c["id"] for c in report["errors"]}, {"reading.cps.ar", "reading.cps.en"})
        sb["scenes"][0]["duration_ms"] = 1500  # 700 ms of readable time is too short in any language
        self.assertIn("reading.window_ms", {c["id"] for c in vp.direct(vp.validate_storyboard(sb))["errors"]})

    def test_off_beat_cut_and_repeated_motion_are_warnings(self):
        sb = copy.deepcopy(vp.SAMPLE_STORYBOARD)
        sb["audio"]["bpm"] = 100
        sb["scenes"][2]["motion"] = dict(sb["scenes"][1]["motion"])
        report = vp.direct(vp.validate_storyboard(sb))
        self.assertTrue(report["passed"])
        self.assertIn("music.cut_on_beat", {c["id"] for c in report["warnings"]})
        self.assertIn("pacing.no_repeated_motion", {c["id"] for c in report["warnings"]})

    def test_browser_direction_flags_unsafe_layout_contrast_and_rtl(self):
        sb = vp.validate_storyboard(vp.SAMPLE_STORYBOARD)
        plan = vp.build_plan(sb)
        line = lambda lang, box, size=80, direction="rtl": {"lang": lang, "box": box, "size": size, "canvas_direction": direction}
        preflight = {
            "setup": {"layout": {"0": {"lines": [line("ar", {"x0": 10, "x1": 900, "y0": 400, "y1": 480}),
                                                 line("en", {"x0": 500, "x1": 1400, "y0": 470, "y1": 520}, size=20)]}},
                      "layers": [{"id": "quantum-light-tunnel", "fallback": "webgl2"}]},
            "contrast": [{"scene": 0, "lang": "ar", "ratio": 2.1}],
            "rtl": {"glyphs_distinct": False, "fonts": {"ar": False, "en": True},
                    "lines": [{"text": "أمرٌ واحد.", "first_word_at_right_edge": False, "first_word_mismatch_pixels": 900,
                               "contextual_shaping": False}]},
            "page_errors": ["boom"], "external_requests": ["https://cdn.example"], "refused": ["../secret"]}
        failed = {c["id"] for c in vp.browser_direction(sb, plan, preflight) if c["status"] == "fail"}
        self.assertEqual(failed, {"safe_area.title_safe.ar", "typography.min_size.en", "typography.no_line_overlap",
                                  "legibility.contrast.ar", "rtl.arabic_glyphs_not_tofu", "rtl.first_word_at_right_edge",
                                  "rtl.contextual_shaping", "typography.font_available.ar", "render.no_engine_fallback",
                                  "render.no_page_errors", "render.no_external_requests", "render.no_refused_requests"})


class SubtitleTests(unittest.TestCase):
    def setUp(self):
        self.sb = vp.validate_storyboard(vp.SAMPLE_STORYBOARD)
        self.frame = 1000 / 30

    def test_cues_are_frame_aligned_and_follow_the_on_screen_text(self):
        for lang in ("ar", "en"):
            cues = vp.subtitle_cues(self.sb, lang)
            self.assertEqual([c["id"] for c in cues], [s["id"] for s in self.sb["scenes"]])
            for cue, row in zip(cues, vp.scene_times(self.sb)):
                window = vp.text_window(self.sb, row["index"])
                self.assertAlmostEqual(cue["start_ms"], row["start_ms"] + 300, places=2)
                self.assertAlmostEqual(cue["end_ms"], row["start_ms"] + window["out_end"], places=2)
                for value in (cue["start_ms"], cue["end_ms"]):
                    self.assertAlmostEqual(value / self.frame, round(value / self.frame), places=4)
            for a, b in zip(cues, cues[1:]):
                self.assertGreaterEqual(b["start_ms"] - a["end_ms"], 2 * self.frame)
        self.assertEqual(vp.subtitle_cues(self.sb, "en")[0]["start_ms"], 300.0)
        self.assertAlmostEqual(vp.subtitle_cues(self.sb, "en")[0]["end_ms"], 2333.333, places=2)

    def test_vtt_and_srt_round_trip_and_pass_their_own_qa(self):
        for lang in ("ar", "en"):
            cues = vp.subtitle_cues(self.sb, lang)
            vtt, srt = vp.render_vtt(cues, lang), vp.render_srt(cues)
            self.assertTrue(vtt.startswith("WEBVTT\n"))
            self.assertIn("00:00:00.300 --> 00:00:02.333", vtt)
            self.assertIn("1\n00:00:00,300 --> 00:00:02,333\n", srt)
            for text in (vtt, srt):
                parsed = vp.parse_subtitles(text)
                self.assertEqual([(c["start_ms"], c["end_ms"]) for c in parsed], [(round(c["start_ms"]), round(c["end_ms"])) for c in cues])
                report = vp.check_subtitles(text, lang, fps=30, duration_ms=14000, expected=cues)
                self.assertTrue(report["passed"], report["errors"])

    def test_arabic_lines_carry_a_right_to_left_mark(self):
        arabic = vp.subtitle_cues(self.sb, "ar")
        self.assertTrue(all(line.startswith(vp.RLM) for cue in arabic for line in cue["lines"]))
        self.assertFalse(any(vp.RLM in line for cue in vp.subtitle_cues(self.sb, "en") for line in cue["lines"]))
        # A Latin-first Arabic line (brand name) still reads right to left.
        self.assertTrue(arabic[-1]["lines"][0].startswith(vp.RLM + "GAIE OS"))
        stripped = vp.render_vtt(arabic, "ar").replace(vp.RLM, "")
        self.assertIn("subtitles.rtl_mark", {c["id"] for c in vp.check_subtitles(stripped, "ar", fps=30, duration_ms=14000)["errors"]})

    def test_bad_subtitles_are_detected(self):
        bad = "1\n00:00:01,000 --> 00:00:01,400\nTwenty layers plan, build and test right now.\n\n2\n00:00:01,300 --> 00:00:03,000\nNext.\n"
        failed = {c["id"] for c in vp.check_subtitles(bad, "en", fps=30, duration_ms=2000)["errors"]}
        self.assertEqual(failed, {"subtitles.duration", "subtitles.cps", "subtitles.lines", "subtitles.order_and_gap", "subtitles.within_video"})
        self.assertFalse(vp.check_subtitles("WEBVTT\n\n00:00:01.000 -> 00:00:02.000\nx\n", "en", fps=30, duration_ms=2000)["passed"])

    def test_long_lines_wrap_into_two_balanced_lines(self):
        lines = vp._wrap("GAIE OS — one command, a working system, tested and verified.", 42)
        self.assertEqual(len(lines), 2)
        self.assertTrue(all(len(line) <= 42 for line in lines))
        with self.assertRaises(vp.StoryboardError):
            vp._wrap("x" * 90, 42)


class AudioTests(unittest.TestCase):
    def test_synthesis_is_deterministic_exact_and_hits_the_cuts(self):
        sb = vp.validate_storyboard(small_storyboard())
        with tempfile.TemporaryDirectory() as temp:
            a, b = pathlib.Path(temp) / "a.wav", pathlib.Path(temp) / "b.wav"
            facts = vp.synthesize_audio(sb, a)
            vp.synthesize_audio(sb, b)
            self.assertEqual(hashlib.sha256(a.read_bytes()).digest(), hashlib.sha256(b.read_bytes()).digest())
            self.assertEqual(facts["samples"], 3 * vp.SAMPLE_RATE)
            self.assertEqual([m["ms"] for m in facts["markers"]], [1000.0, 2000.0])
            with wave.open(str(a)) as stream:
                self.assertEqual((stream.getnchannels(), stream.getframerate(), stream.getnframes()), (2, 48000, 144000))
                data = array.array("h", stream.readframes(stream.getnframes()))
            mono = array.array("h", data[::2])
            for onset in vp.audio_onsets(mono, [1000, 2000]):
                self.assertLessEqual(abs(onset["onset_ms"] - onset["expected_ms"]), 3)
                self.assertGreaterEqual(onset["ratio"], vp.QA["onset_ratio"])
            self.assertLessEqual(max(abs(x) for x in data), int(0.7 * 32767) + 1)
            self.assertEqual([c["chord"] for c in facts["chords"]], ["Dm9", "Bbmaj9", "Dm(add9)"])

    def test_voiceover_capability_is_reported_honestly(self):
        capability = vp.voiceover_capability()
        self.assertFalse(capability["ar"]["available"])
        self.assertIn("not", capability["ar"]["reason"])
        self.assertFalse(capability["paid_or_network_tts_used"])
        if HAVE_FFMPEG and capability["ffmpeg_libflite"]:
            self.assertEqual(capability["en"]["engine"], "ffmpeg-libflite")

    @unittest.skipUnless(HAVE_FFMPEG, "ffmpeg not installed")
    def test_mastering_reaches_the_loudness_target(self):
        sb = vp.validate_storyboard(small_storyboard())
        with tempfile.TemporaryDirectory() as temp:
            raw, master = pathlib.Path(temp) / "raw.wav", pathlib.Path(temp) / "master.wav"
            vp.synthesize_audio(sb, raw)
            facts = vp.master_loudness(raw, master)
            level = vp.loudness(master)
        self.assertLessEqual(abs(level["integrated_lufs"] + 16), 1.0)
        self.assertLessEqual(level["true_peak_dbtp"], -1.0)
        self.assertEqual(facts["normalization_type"], "linear")


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg/ffprobe not installed")
class MediaQATests(unittest.TestCase):
    """QA must catch real defects in real files (generated with ffmpeg test sources)."""

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.dir = pathlib.Path(cls.temp.name)
        srt = cls.dir / "cue.srt"
        srt.write_text("1\n00:00:00,100 --> 00:00:00,900\nHello\n", "utf-8")
        cls.files = {}

        def make(name, *, fps=30, size="320x180", audio=True, faststart=True, subtitle=False, gain=0.0, seconds=2):
            path = cls.dir / f"{name}.mp4"
            command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                       f"testsrc2=size={size}:rate={fps}:duration={seconds}"]
            if audio:
                command += ["-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={seconds}"]
            if subtitle:
                command += ["-i", str(srt)]
            command += ["-map", "0:v"]
            if audio:
                command += ["-map", "1:a", "-af", f"aformat=channel_layouts=stereo,loudnorm=I={-16 + gain}:TP=-2:LRA=7",
                            "-ar", "48000", "-c:a", "aac", "-b:a", "128k"]
            if subtitle:
                command += ["-map", "2:s", "-c:s", "mov_text"]
            command += ["-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p", "-colorspace", "bt709",
                        "-color_primaries", "bt709", "-color_trc", "bt709"]
            if faststart:
                command += ["-movflags", "+faststart"]
            subprocess.run(command + [str(path)], check=True, timeout=120)
            cls.files[name] = path

        make("good")
        make("fps25", fps=25)
        make("wide", size="352x180")
        make("silent", audio=False)
        make("slow-start", faststart=False)
        make("subtitled", subtitle=True)
        make("quiet", gain=-14)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def qa(self, name, **changes):
        expect = {"width": 320, "height": 180, "fps": 30, "frames": 60, "profile": "High"}
        expect.update(changes)
        report = vp.qa_media(self.files[name], expect)
        return report, {k for k, v in report["checks"].items() if not v["passed"]}

    def test_conforming_file_passes(self):
        report, failed = self.qa("good")
        self.assertEqual(failed, set())
        self.assertTrue(report["passed"])
        self.assertEqual(report["atoms"][:2], ["ftyp", "moov"])

    def test_wrong_fps_is_detected(self):
        report, failed = self.qa("fps25", frames=50)
        self.assertIn("video.fps", failed)
        self.assertFalse(report["passed"])
        self.assertEqual(report["checks"]["video.fps"]["value"], ["25/1", "25/1"])

    def test_wrong_frame_count_and_dimensions_are_detected(self):
        self.assertIn("video.frame_count", self.qa("good", frames=61)[1])
        self.assertIn("video.dimensions", self.qa("wide")[1])

    def test_missing_audio_missing_faststart_and_subtitle_stream_are_detected(self):
        self.assertIn("audio.present", self.qa("silent")[1])
        self.assertEqual(self.qa("slow-start")[1], {"container.faststart"})
        self.assertEqual(self.qa("subtitled")[1], {"subtitles.no_stream"})

    def test_loudness_outside_target_is_detected(self):
        report, failed = self.qa("quiet")
        self.assertEqual(failed, {"audio.loudness"})
        self.assertLess(report["checks"]["audio.loudness"]["value"], -25)

    def test_missing_cut_and_unsynced_audio_are_detected(self):
        report, failed = self.qa("good", cut_frames=[30])  # testsrc2 has no hard cut and no transient there
        self.assertIn("edit.cuts_at_planned_frames", failed)
        self.assertIn("sync.audio_on_cuts", failed)


@unittest.skipUnless(shutil.which("node") and HAVE_FFMPEG, "node/ffmpeg not installed")
class BrowserTests(unittest.TestCase):
    def setUp(self):
        if not browser_available():
            self.skipTest("Playwright/Chromium not available")

    def test_gpu_probe_records_what_actually_ran(self):
        summary = vp.browser_probe(rtl_lines=())["summary"]
        self.assertTrue(summary["webgl2_executed"])
        if "swiftshader" in summary["webgl2_renderer"].lower():
            self.assertFalse(summary["hardware_gpu"])
            self.assertIn("SwiftShader", summary["note"])

    def test_arabic_rtl_rendering_is_shaped_and_right_to_left(self):
        lines = ["أمرٌ واحد.", "GAIE OS — أمرٌ واحد، ونظامٌ يعمل."]
        result = vp.browser_probe(rtl_lines=lines)["rtl"]
        self.assertTrue(result["glyphs_distinct"])
        self.assertEqual(result["fonts"], {"ar": True, "en": True})
        for line in result["lines"]:
            self.assertTrue(line["contextual_shaping"], line)
            self.assertTrue(line["first_word_at_right_edge"], line)
        self.assertEqual(result["lines"][1]["first_run"], "GAIE OS")
        # Negative: a left-to-right paragraph puts the full stop at the right edge.
        forced = vp.browser_probe(rtl_lines=lines[:1], force_direction="ltr")["rtl"]["lines"][0]
        self.assertFalse(forced["first_word_at_right_edge"])
        self.assertGreater(forced["first_word_mismatch_pixels"], 100)

    def test_same_storyboard_renders_identical_frames(self):
        first = vp.hash_frames(small_storyboard(), limit=40)
        second = vp.hash_frames(small_storyboard(), limit=40)
        self.assertEqual(len(first), 40)
        self.assertEqual(first, second)
        self.assertGreater(len(set(first)), 30)  # the picture moves
        changed = small_storyboard()
        changed["scenes"][0]["text"] = {"ar": "أمرٌ آخر.", "en": "Another command."}
        third = vp.hash_frames(changed, limit=40)
        window = vp.text_window(vp.validate_storyboard(changed), 0)
        shown = range(round(window["in_start"] * 30 / 1000) + 1, round(window["out_end"] * 30 / 1000))
        self.assertEqual((shown.start, shown.stop), (10, 25))
        self.assertEqual(first[:shown.start], third[:shown.start])  # before the text shows: identical
        self.assertTrue(all(first[i] != third[i] for i in shown))  # while it shows: different
        self.assertEqual(first[shown.stop:], third[shown.stop:])  # after it, and the next shot: identical


@unittest.skipUnless(shutil.which("node") and HAVE_FFMPEG, "node/ffmpeg not installed")
class ScenarioCTests(unittest.TestCase):
    """Acceptance Scenario C: the bilingual sample storyboard rendered to playable MP4s, all QA passing."""

    def setUp(self):
        if not browser_available():
            self.skipTest("Playwright/Chromium not available")

    def test_sample_storyboard_end_to_end_at_preview_size(self):
        with tempfile.TemporaryDirectory(prefix="gaie-scenario-c-") as temp:
            result = vp.render(vp.preview_storyboard(), temp, name="scenario-c")
            for report in result["qa"]:
                self.assertTrue(report["passed"], {k: v for k, v in report["checks"].items() if not v["passed"]})
                self.assertTrue(all(abs(row["offset_ms"]) <= 1000 / 30 for row in report["sync"]))
            self.assertEqual([(r["checks"]["video.dimensions"]["value"]) for r in result["qa"]], [[640, 360], [320, 180]])
            self.assertTrue(all(s["qa"]["passed"] for s in result["subtitles"]))
            self.assertEqual(len(result["subtitles"]), 4)
            self.assertTrue(result["direction"]["passed"])
            self.assertEqual(len(result["frames"]["frames"]), 420)
            self.assertEqual((result["frames"]["page_errors"], result["frames"]["external_requests"]), ([], []))
            self.assertEqual(result["audio"]["master"]["normalization_type"], "linear")
            self.assertEqual(len(result["audio"]["voiceover"]), 5)
            files = sorted(p.name for p in pathlib.Path(temp).iterdir())
            self.assertEqual(files, ["scenario-c-180p.mp4", "scenario-c.ar.srt", "scenario-c.ar.vtt", "scenario-c.en.srt",
                                     "scenario-c.en.vtt", "scenario-c.mp4"])  # work directory removed
            manifest = vp.build_manifest(result, voice=vp.voiceover_capability())
            self.assertTrue(manifest["qa_passed"])
            self.assertEqual([m["source"] for m in manifest["motions"]], ["engine", "reference", "reference", "camera", "engine"])
            self.assertTrue(all(m["loaded_by_browser"] for m in manifest["motions"]))
            json.dumps(manifest, allow_nan=False)

    def test_media_is_never_written_into_the_repository(self):
        with self.assertRaisesRegex(vp.RenderError, "outside the repository"):
            vp.render(vp.preview_storyboard(), str(ROOT / "docs"), name="nope")

    def test_direction_failure_stops_before_any_frame_is_drawn(self):
        sb = vp.preview_storyboard()
        sb["scenes"][0].update(duration_ms=1500, text={"ar": "عشرون طبقة تخطّط وتبني وتختبر وتنشر وتراقب.",
                                                       "en": "Twenty layers plan, build, test, ship and watch."})
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(vp.DirectionError) as raised:
                vp.render(sb, temp, name="refused")
            self.assertEqual(list(pathlib.Path(temp).iterdir()), [])
        self.assertFalse(raised.exception.report["passed"])


class EngineContractTests(unittest.TestCase):
    def test_engine_record_satisfies_the_shared_contract(self):
        contracts.validate_engine(vp.ENGINE_RECORD, check_imports=True)
        self.assertEqual(vp.ENGINE_RECORD["actions"]["render"]["side_effect"], "state-write")

    def test_engine_actions(self):
        self.assertEqual(vp.engine("inventory", {})["reference_canvas2d_motions"]["count"], 400)
        self.assertEqual(vp.engine("validate", {"storyboard": vp.SAMPLE_STORYBOARD})["frames"], 420)
        self.assertTrue(vp.engine("direct", {"storyboard": vp.SAMPLE_STORYBOARD})["passed"])
        subtitles = vp.engine("subtitles", {"storyboard": vp.SAMPLE_STORYBOARD})
        self.assertEqual(set(subtitles), {"ar", "en"})
        with self.assertRaises(vp.VideoPipelineError):
            vp.engine("deploy", {})
        with self.assertRaises(vp.VideoPipelineError):
            vp.engine("render", {"storyboard": vp.SAMPLE_STORYBOARD})
        self.assertIn("ok", vp.health())


class EvidenceManifestTests(unittest.TestCase):
    """The committed Scenario C manifest must describe the current sources and a passing render."""

    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(EVIDENCE.read_text("utf-8"))

    def test_manifest_records_a_passing_1080p_and_720p_render(self):
        m = self.manifest
        self.assertEqual((m["schema"], m["scenario"]), (vp.EVIDENCE_SCHEMA, "C"))
        self.assertTrue(m["qa_passed"])
        main, mobile = m["outputs"]
        for output, size, profile in ((main, [1920, 1080], "High"), (mobile, [1280, 720], "Main")):
            self.assertTrue(output["stored_outside_git"])
            self.assertTrue(output["qa_passed"])
            self.assertTrue(all(c["passed"] for c in output["qa"].values()))
            qa = output["qa"]
            self.assertEqual(qa["video.dimensions"]["value"], size)
            self.assertEqual(qa["video.profile"]["value"], profile)
            self.assertEqual(qa["video.fps"]["value"], ["30/1", "30/1"])
            self.assertEqual(qa["video.frame_count"]["value"], 420)
            self.assertLessEqual(abs(qa["audio.loudness"]["value"] + 16), 1.0)
            self.assertLessEqual(qa["audio.true_peak"]["value"], -1.0)
            self.assertEqual(output["atoms"][:2], ["ftyp", "moov"])
            self.assertTrue(all(abs(row["offset_ms"]) <= 1000 / 30 for row in output["sync"]))
            self.assertRegex(output["sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(len(m["subtitles"]), 4)
        self.assertTrue(all(s["qa_passed"] for s in m["subtitles"]))
        self.assertTrue(m["direction"]["passed"])
        self.assertEqual(m["frames"]["count"], 420)

    def test_manifest_is_bound_to_current_sources(self):
        m = self.manifest
        sb = vp.validate_storyboard(vp.SAMPLE_STORYBOARD)
        self.assertEqual(m["storyboard"]["document"], sb)
        self.assertEqual(m["storyboard"]["sha256"], contracts.sha256(sb))
        for motion in m["motions"]:
            self.assertTrue(motion["loaded_by_browser"])
            for relative, digest in motion["source_files"].items():
                self.assertEqual(hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(), digest, relative)
        digests = vp.renderer_digests()
        for key in ("compositor_html_sha256", "compositor_js_sha256", "renderer_js_sha256"):
            self.assertEqual(m["renderer"][key], digests[key], key)
        for camera in m["camera_moves"]:
            if camera["source"]:
                self.assertEqual(hashlib.sha256((ROOT / camera["source"]).read_bytes()).hexdigest(), camera["source_sha256"])
        self.assertEqual(m["inventory"], cinematic.motion_inventory())
        self.assertEqual((m["renderer"]["page_errors"], m["renderer"]["external_requests"]), (0, 0))

    def test_manifest_is_honest_about_gpu_voiceover_and_music(self):
        m = self.manifest
        self.assertFalse(m["inventory"]["gpu_hardware_claimed"])
        if "swiftshader" in m["gpu_probe"]["webgl2_renderer"].lower():
            self.assertFalse(m["gpu_probe"]["hardware_gpu"])
        self.assertFalse(m["audio"]["voiceover"]["capability"]["ar"]["available"])
        self.assertFalse(m["audio"]["voiceover"]["capability"]["paid_or_network_tts_used"])
        self.assertIn("No samples", m["audio"]["license"])
        self.assertTrue(any("Arabic voiceover" in item for item in m["not_proven"]))

    def test_manifest_holds_no_media(self):
        raw = EVIDENCE.read_bytes()
        self.assertLess(len(raw), 256 * 1024)
        self.assertNotIn(b"data:image", raw)
        self.assertNotIn(b"/home/", raw)
        tracked = subprocess.run(["git", "-C", str(ROOT), "ls-files", "*.mp4", "*.webm", "*.wav", "*.vtt", "*.srt"],
                                 capture_output=True, text=True, check=False).stdout.split()
        self.assertEqual(tracked, [])

    @unittest.skipUnless(HAVE_FFMPEG, "ffprobe not installed")
    def test_delivered_sample_matches_manifest_when_present(self):
        media = pathlib.Path(os.environ.get("GAIE_STATE_DIR", "/home/user/gaie-state")) / "media"
        for output in self.manifest["outputs"]:
            path = media / output["file"]
            if not path.is_file():
                self.skipTest("sample media is kept outside Git and is not on this machine")
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), output["sha256"])
            expect = {"width": output["qa"]["video.dimensions"]["expected"][0],
                      "height": output["qa"]["video.dimensions"]["expected"][1], "fps": 30, "frames": 420,
                      "profile": output["qa"]["video.profile"]["expected"], "cut_frames": [75, 180, 255, 330]}
            self.assertTrue(vp.qa_media(path, expect)["passed"])


if __name__ == "__main__":
    unittest.main()
