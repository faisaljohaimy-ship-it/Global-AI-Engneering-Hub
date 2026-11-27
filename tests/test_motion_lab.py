import importlib.util
import json
import pathlib
import unittest
from html.parser import HTMLParser

ROOT = pathlib.Path(__file__).resolve().parents[1]
CATALOG = json.loads((ROOT / "motion-library/MOTION_CATALOG.json").read_text())
COMPONENTS = json.loads((ROOT / "motion-library/components.json").read_text())
MODULE_SPEC = importlib.util.spec_from_file_location("motion_compiler", ROOT / "motion-library/compiler.py")
COMPILER = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(COMPILER)


class LabParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.assets = []
        self.csp = ""

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if "id" in values:
            self.ids.add(values["id"])
        if tag == "script" and values.get("src"):
            self.assets.append(values["src"])
        if tag == "link" and values.get("href"):
            self.assets.append(values["href"])
        if tag == "meta" and values.get("http-equiv", "").lower() == "content-security-policy":
            self.csp = values.get("content", "")


class MotionLabTests(unittest.TestCase):
    def test_true_counts_and_engine_coverage(self):
        self.assertEqual(len(CATALOG["entries"]), 142)
        rows = COMPONENTS["components"]
        self.assertEqual(len(rows), 11)
        engines = [row["engine"] for row in rows]
        self.assertEqual(engines.count("css"), 6)
        self.assertEqual(engines.count("waapi"), 2)
        self.assertEqual(engines.count("glsl-webgl"), 1)
        self.assertEqual(engines.count("remotion-adapter"), 1)
        self.assertEqual(engines.count("three-adapter"), 1)

    def test_every_component_maps_to_catalog_and_valid_spec(self):
        catalog_ids = {row["id"] for row in CATALOG["entries"]}
        component_ids = [row["id"] for row in COMPONENTS["components"]]
        self.assertEqual(len(component_ids), len(set(component_ids)))
        for row in COMPONENTS["components"]:
            self.assertIn(row["id"], catalog_ids)
            self.assertEqual(row["implementation_status"], "implemented")
            self.assertEqual(row["test_status"], "automated")
            self.assertIn("motion-lab", row["used_by"])
            spec = json.loads((ROOT / "motion-library" / row["spec"]).read_text())
            self.assertEqual(spec["id"], row["id"])
            COMPILER.validate(spec)
            self.assertTrue(COMPILER.compile_css(spec).startswith("@keyframes"))

    def test_lab_is_local_accessible_and_non_autoplaying(self):
        parser = LabParser()
        html = (ROOT / "motion-lab/index.html").read_text()
        parser.feed(html)
        required = {"motionList", "direction", "motionMode", "play", "stop", "stage"}
        self.assertTrue(required <= parser.ids)
        self.assertTrue(parser.assets)
        self.assertTrue(all("://" not in asset and not asset.startswith("//") for asset in parser.assets))
        self.assertIn("object-src 'none'", parser.csp)
        self.assertIn("base-uri 'none'", parser.csp)
        app = (ROOT / "motion-lab/app.mjs").read_text()
        self.assertNotIn("innerHTML", app)
        self.assertNotIn("eval(", app)
        self.assertNotIn("autoplay=", html.lower())
        self.assertIn('refs.play.addEventListener("click"', app)

    def test_lab_static_budgets(self):
        budgets = {"index.html": 20_000, "styles.css": 40_000, "motions.css": 20_000, "app.mjs": 80_000}
        for name, limit in budgets.items():
            self.assertLessEqual((ROOT / "motion-lab" / name).stat().st_size, limit)

    def test_glsl_has_bounded_local_shader(self):
        shader = (ROOT / "motion-library/runtime/glsl/fresnel-rim.frag").read_text()
        self.assertIn("void main()", shader)
        self.assertIn("gl_FragColor", shader)
        self.assertNotIn("#include", shader)
        self.assertLess(len(shader.encode()), 4096)


if __name__ == "__main__":
    unittest.main()
