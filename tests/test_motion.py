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


if __name__ == "__main__":
    unittest.main()
