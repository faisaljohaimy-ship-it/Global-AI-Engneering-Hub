import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "motion-library" / "compiler.py"
SPEC = importlib.util.spec_from_file_location("motion_compiler", MODULE_PATH)
motion = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(motion)


class MotionCompilerTests(unittest.TestCase):
    def test_fade_in_compiles_with_reduced_motion(self):
        source = motion.load_spec(ROOT / "motion-library/specs/fade-in.json")
        css = motion.compile_css(source)
        self.assertIn("@keyframes hub-ui-fade-in", css)
        self.assertIn("prefers-reduced-motion: reduce", css)
        self.assertIn("opacity: 1;", css)

    def test_rejects_unordered_keyframes(self):
        source = motion.load_spec(ROOT / "motion-library/specs/fade-in.json")
        source["keyframes"][0]["offset"] = 1
        with self.assertRaises(ValueError):
            motion.compile_css(source)

    def test_rejects_css_injection(self):
        source = motion.load_spec(ROOT / "motion-library/specs/fade-in.json")
        source["keyframes"][0]["opacity"] = "0; color: red"
        with self.assertRaises(ValueError):
            motion.compile_css(source)

    def test_rejects_remote_css_fetch(self):
        source = motion.load_spec(ROOT / "motion-library/specs/fade-in.json")
        source["keyframes"][0] = {"offset": 0, "filter": "url(https://example.test/x)"}
        with self.assertRaises(ValueError):
            motion.compile_css(source)

    def test_rejects_boolean_duration_and_offset(self):
        source = motion.load_spec(ROOT / "motion-library/specs/fade-in.json")
        source["duration_ms"] = True
        with self.assertRaises(ValueError):
            motion.compile_css(source)
        source = motion.load_spec(ROOT / "motion-library/specs/fade-in.json")
        source["keyframes"][0]["offset"] = False
        with self.assertRaises(ValueError):
            motion.compile_css(source)

    def test_compilation_is_byte_deterministic(self):
        source = motion.load_spec(ROOT / "motion-library/specs/fade-in.json")
        self.assertEqual(motion.compile_css(source), motion.compile_css(source))

    def test_rtl_mirror_compiles_logical_keyframes(self):
        source = motion.load_spec(ROOT / "motion-library/specs/slide-inline-start.json")
        css = motion.compile_css(source)
        self.assertIn("@keyframes hub-ui-slide-inline-start-rtl", css)
        self.assertIn("transform: translateX(24px)", css)
        self.assertIn(":dir(rtl)", css)
        source["rtl_mirror"] = "yes"
        with self.assertRaisesRegex(ValueError, "rtl_mirror"):
            motion.compile_css(source)

    def test_duplicate_json_keys_are_rejected(self):
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "motion.json"
            path.write_text('{"schema_version": 1, "id": "a", "id": "b"}')
            with self.assertRaises(ValueError):
                motion.load_spec(path)


if __name__ == "__main__":
    unittest.main()
