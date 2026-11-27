import importlib.util
import json
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "motion-library"


def load(name):
    spec = importlib.util.spec_from_file_location(name, LIBRARY / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


compiler, springs, status = load("compiler"), load("springs"), load("catalog_status")


class MotionCatalogTests(unittest.TestCase):
    def test_every_specification_compiles_and_is_catalogued(self):
        catalog = {entry["id"] for entry in json.loads((LIBRARY / "MOTION_CATALOG.json").read_text(encoding="utf-8"))["entries"]}
        ids = []
        for path in sorted((LIBRARY / "specs").glob("*.json")):
            spec = compiler.load_spec(path)
            css = compiler.compile_css(spec)
            self.assertIn(f".hub-motion-{spec['id']}", css)
            self.assertIn("prefers-reduced-motion: reduce", css)
            self.assertIn(spec["id"], catalog, path.name)
            ids.append(spec["id"])
        self.assertEqual(len(ids), len(set(ids)))

    def test_catalog_claims_only_what_browser_evidence_supports(self):
        catalog, evidence = status.load()
        self.assertEqual(status.synced(catalog, evidence), catalog)
        implemented = [entry for entry in catalog["entries"] if entry["status"] == "implemented"]
        self.assertTrue(implemented)
        for entry in catalog["entries"]:
            self.assertEqual(entry["runtime_verified"], entry["status"] == "implemented")
            self.assertEqual("evidence" in entry, entry["runtime_verified"])

    def test_generic_browser_proof_does_not_claim_glsl_or_three_runtime(self):
        catalog, evidence = status.load()
        evidence = json.loads(json.dumps(evidence))
        evidence["inputs"] = {
            "runtime_sha256": status._sha256((LIBRARY / "runtime/hub-motion.mjs").read_bytes()),
            "base_css_sha256": status._sha256((LIBRARY / "runtime/hub-motion-base.css").read_bytes()),
        }
        compiler_module = compiler
        for motion_id, name in (
            ("spatial-fresnel-rim", "fresnel-rim.json"),
            ("cinema-orbit-camera", "orbit-camera.json"),
        ):
            path = LIBRARY / "specs" / name
            css = compiler_module.compile_css(json.loads(path.read_text(encoding="utf-8")))
            evidence["results"].append(
                {
                    "id": motion_id,
                    "kind": "spec",
                    "source": str(path.relative_to(ROOT)),
                    "css_sha256": status._sha256(css.encode("utf-8")),
                    "pass": True,
                }
            )
        proof = status.verified(evidence)
        self.assertNotIn("spatial-fresnel-rim", proof)
        self.assertNotIn("cinema-orbit-camera", proof)

    def test_stale_evidence_withdraws_the_claim(self):
        catalog, evidence = status.load()
        stale = json.loads(json.dumps(evidence))
        target = next(row for row in stale["results"] if row["id"] == "ui-fade-in")
        target["css_sha256"] = "0" * 64
        entry = next(row for row in status.synced(catalog, stale)["entries"] if row["id"] == "ui-fade-in")
        self.assertEqual((entry["status"], entry["runtime_verified"]), ("specification", False))
        self.assertNotIn("evidence", entry)
        stale["inputs"]["runtime_sha256"] = "0" * 64
        self.assertFalse(any(row["runtime_verified"] for row in status.synced(catalog, stale)["entries"]))
        failed = json.loads(json.dumps(evidence))
        next(row for row in failed["results"] if row["id"] == "ui-slide-up")["pass"] = False
        self.assertNotIn("ui-slide-up", status.verified(failed))

    def test_generated_spring_specifications_are_current(self):
        for name, build in springs.GENERATED.items():
            self.assertEqual((LIBRARY / "specs" / name).read_text(encoding="utf-8"), springs.dump(build()), name)

    def test_spring_response(self):
        self.assertEqual(springs.spring(0, 180, 12), 0)
        for stiffness, damping in ((180, 12), (100, 20), (100, 40)):
            self.assertAlmostEqual(springs.spring(10, stiffness, damping), 1, places=6)
        under = [value for _, value in springs.samples(700, 180, 12, steps=200)]
        self.assertGreater(max(under), 1.01)
        for damping in (20, 40):
            self.assertLessEqual(max(value for _, value in springs.samples(2000, 100, damping, steps=200)), 1)
        rows = springs.samples(700, 180, 12)
        self.assertEqual((rows[0], rows[-1]), ((0.0, 0.0), (1.0, 1.0)))


if __name__ == "__main__":
    unittest.main()
