import copy
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


compiler, springs, status = load("compiler"), load("springs"), load("component_status")


class MotionComponentTests(unittest.TestCase):
    def test_every_specification_is_exactly_one_component(self):
        rows = json.loads((LIBRARY / "components.json").read_text(encoding="utf-8"))["components"]
        listed = sorted(row["spec"] for row in rows)
        on_disk = sorted(f"specs/{path.name}" for path in (LIBRARY / "specs").glob("*.json"))
        self.assertEqual(listed, on_disk)
        for row in rows:
            self.assertEqual(compiler.load_spec(LIBRARY / row["spec"])["id"], row["id"])

    def test_manifest_and_lab_claim_only_what_browser_evidence_supports(self):
        document, evidence = status.load()
        self.assertEqual(status.dump(status.synced(document, evidence)), (LIBRARY / "components.json").read_text(encoding="utf-8"))
        current = status.LAB_CSS.read_text(encoding="utf-8")
        self.assertEqual(status.lab_css(document, current), current)
        for row in document["components"]:
            self.assertEqual("evidence" in row, row["runtime_status"] == "browser-verified", row["id"])
            if row["engine"] == "css":
                self.assertIn(f".run-{row['id']} ", current)
        self.assertTrue(any(row["runtime_status"] == "browser-verified" for row in document["components"]))

    def test_stale_evidence_withdraws_the_claim(self):
        document, evidence = status.load()

        def state(changed, component):
            row = next(item for item in status.synced(document, changed)["components"] if item["id"] == component)
            return row["runtime_status"], "evidence" in row

        stale = copy.deepcopy(evidence)
        next(row for row in stale["results"] if row["id"] == "ui-fade-in")["css_sha256"] = "0" * 64
        self.assertEqual(state(stale, "ui-fade-in"), ("pending-browser", False))
        self.assertEqual(state(stale, "ui-slide-up"), ("browser-verified", True))
        failed = copy.deepcopy(evidence)
        next(row for row in failed["results"] if row["id"] == "ui-slide-up")["pass"] = False
        self.assertEqual(state(failed, "ui-slide-up"), ("pending-browser", False))
        runtime = copy.deepcopy(evidence)
        runtime["inputs"]["runtime_sha256"] = "0" * 64
        self.assertEqual(state(runtime, "ui-slide-up"), ("pending-browser", False))
        self.assertEqual(state(runtime, "spatial-fresnel-rim"), ("browser-verified", True))
        lab = copy.deepcopy(evidence)
        lab["inputs"]["lab_sha256"] = "0" * 64
        self.assertEqual(state(lab, "spatial-fresnel-rim"), ("pending-browser", False))
        self.assertEqual(state(lab, "ui-slide-up"), ("browser-verified", True))
        self.assertEqual(state(lab, "cinema-orbit-camera"), ("adapter-tested", False))

    def test_mirrored_specifications_compile_for_both_directions(self):
        mirrored = [path for path in sorted((LIBRARY / "specs").glob("*.json")) if compiler.load_spec(path).get("rtl_mirror")]
        self.assertGreaterEqual(len(mirrored), 3)
        for path in mirrored:
            spec = compiler.load_spec(path)
            css = compiler.compile_css(spec)
            selector = f".hub-motion-{spec['id']}"
            self.assertIn(f"@keyframes hub-{spec['id']}-rtl", css)
            self.assertIn(f"{selector}:dir(rtl) {{\n  animation-name: hub-{spec['id']}-rtl;", css)
            self.assertIn(f"  {selector}, {selector}:dir(rtl) {{\n    animation: none;", css)
        self.assertEqual(compiler.mirrored("translateX(-24px) scale(0.9)"), "translateX(24px) scale(0.9)")
        self.assertEqual(compiler.mirrored("translateX(1.5rem)"), "translateX(-1.5rem)")
        self.assertEqual(compiler.mirrored("translateY(-24px)"), "translateY(-24px)")
        plain = compiler.compile_css(compiler.load_spec(LIBRARY / "specs/fade-in.json"))
        self.assertNotIn(":dir(rtl)", plain)

    def test_shared_rejection_cases_are_refused(self):
        cases = json.loads((LIBRARY / "verify/rejections.json").read_text(encoding="utf-8"))["cases"]
        self.assertGreaterEqual(len(cases), 15)
        for case in cases:
            spec = compiler.load_spec(LIBRARY / "specs/fade-in.json")
            target = spec
            for key in case["path"][:-1]:
                target = target[key]
            target[case["path"][-1]] = case["value"]
            with self.assertRaises(ValueError, msg=case["case"]):
                compiler.compile_css(spec)

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
        self.assertEqual(springs.number(-0.0001), "0")


class ClaudeCodeEvidenceTests(unittest.TestCase):
    def test_probe_rows_cover_the_index_and_stay_sanitized(self):
        indexed = {item["name"] for item in json.loads((ROOT / "integrations/PROGRAMS.json").read_text(encoding="utf-8"))["programs"]}
        evidence = json.loads((ROOT / "integrations/EVIDENCE.claude-code.json").read_text(encoding="utf-8"))
        self.assertEqual({item["program"] for item in evidence["programs"]}, indexed)
        rows = evidence["programs"] + evidence["other_connected_programs"]
        self.assertTrue(all(item["mutation"] is False and item["budget_impact"] == 0 for item in rows))
        self.assertTrue(all(item["result"] in {"success", "failed", "unavailable", "metadata-only", "not-exercised"} for item in rows))
        self.assertTrue(all(item["authenticated_read"] is False for item in rows if item["result"] != "success"))
        serialized = json.dumps(evidence).casefold()
        for forbidden in ("email", "account_id", "team_id", "balance", "access_token", "@gmail"):
            self.assertNotIn(forbidden, serialized)

    def test_index_summarises_the_evidence(self):
        programs = json.loads((ROOT / "integrations/PROGRAMS.json").read_text(encoding="utf-8"))["programs"]
        evidence = {item["program"]: item for item in json.loads((ROOT / "integrations/EVIDENCE.claude-code.json").read_text(encoding="utf-8"))["programs"]}
        for item in programs:
            connected = item["claude_code_connection"].startswith(("verified", "local-binary-verified"))
            self.assertEqual(connected, evidence[item["name"]]["result"] == "success", item["name"])

    def test_recovered_additions_do_not_repeat_the_package_index(self):
        packages = {item["id"] for item in json.loads((ROOT / "catalog/recovered-packages.json").read_text(encoding="utf-8"))["packages"]}
        additions = json.loads((ROOT / "catalog/recovered-additions.json").read_text(encoding="utf-8"))["items"]
        self.assertFalse(packages & {item["id"] for item in additions})
        self.assertTrue(all(item["status"] in {"imported", "referenced", "not-found"} for item in additions))
        imported = [item for item in additions if item["status"] == "imported"]
        packs = json.loads((ROOT / "catalog/packs.json").read_text(encoding="utf-8"))["packs"]
        self.assertTrue(all(item["hub_capability"].split(":")[1] in packs for item in imported))


if __name__ == "__main__":
    unittest.main()
