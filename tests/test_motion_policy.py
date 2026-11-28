"""Purposeful-motion policy: the real tree complies, and every violation is produced on a copy.

Negative cases either pass a changed policy to the validator (the tree is only read) or copy the
policy, the registries and the motion sources into a short temporary directory and change the
copy. No repository file is edited, nothing is fetched and no browser is run.
"""
import copy
import hashlib
import io
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

from engineering_os import cinematic, motion_policy as mp

ROOT = pathlib.Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
COPIED = ("governance/policies/motion-purpose.json", "packages/motion-engines", "packages/digital-shows/kit.mjs",
          "packages/digital-shows/registry.json", "packages/motion-sdk", "motion-library/expansion", "motion-library/runtime",
          "motion-library/MOTION_CATALOG.json", "motion-library/components.json", "engineering_os/motion_policy.py",
          "tests/test_motion_policy.py", "tests/test_native_motions_digital.mjs")
REGISTRY = "packages/motion-engines/registry.json"
SHOWS = "packages/digital-shows/registry.json"
KIT = "packages/digital-shows/kit.mjs"
RECIPES = "motion-library/expansion/definitions.json"
CATALOG = "motion-library/MOTION_CATALOG.json"
CAMERA = "motion-library/expansion/nextgen-camera.mjs"
PURPOSEFUL = "micro-success-feedback"
LEGACY = "glass-card-elevation"
MEANING = {"en": "A completed request issues a receipt with a reference code.", "ar": "الطلب المكتمل يُصدر إيصالًا برقم مرجعي."}


def codes(violations):
    return [(row["code"], row["registry"], row["id"]) for row in violations]


class Tree:
    """A copy of everything the policy covers, in a short temporary directory."""

    def __init__(self, case):
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="mp-"))
        case.addCleanup(shutil.rmtree, self.root, True)
        for relative in COPIED:
            source, target = ROOT / relative, self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", "node_modules"))
            else:
                shutil.copy2(source, target)

    def text(self, relative):
        return (self.root / relative).read_text("utf-8")

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, "utf-8")

    def json(self, relative):
        return json.loads(self.text(relative))

    def edit(self, relative, change):
        value = self.json(relative)
        change(value)
        self.write(relative, json.dumps(value, ensure_ascii=False, indent=1) + "\n")
        return value

    def row(self, identifier):
        return next(row for row in self.json(REGISTRY)["motions"] if row["id"] == identifier)

    def edit_row(self, identifier, change):
        self.edit(REGISTRY, lambda value: change(next(row for row in value["motions"] if row["id"] == identifier)))

    def resync(self, identifier):
        """Rebuild what the registry builder would: the row's hash of its source."""
        digest = hashlib.sha256((self.root / self.row(identifier)["source"]).read_bytes()).hexdigest()
        self.edit_row(identifier, lambda row: row.update(source_sha256=digest))

    def add_motion(self, identifier, meaning, text="export default {};\n"):
        module, _, slug = identifier.partition("-")
        source = f"packages/motion-engines/motions/{module}/{slug}.mjs"
        self.write(source, text)
        row = copy.deepcopy(self.row(PURPOSEFUL))
        row.update(id=identifier, meaning=meaning, source=source, source_sha256=hashlib.sha256(text.encode()).hexdigest())
        self.edit(REGISTRY, lambda value: value["motions"].append(row))

    def remove_motion(self, identifier):
        (self.root / self.row(identifier)["source"]).unlink()
        self.edit(REGISTRY, lambda value: value["motions"].remove(next(row for row in value["motions"] if row["id"] == identifier)))

    def policy(self, change):
        return self.edit(mp.POLICY, change)

    def validate(self):
        return mp.validate(self.root)


def changed(change):
    """The real policy with one change, for cases that need no changed tree."""
    policy = json.loads((ROOT / mp.POLICY).read_text("utf-8"))
    change(policy)
    return policy


class RealTree(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = mp.load_policy()
        cls.registry = json.loads((ROOT / REGISTRY).read_text("utf-8"))

    def test_the_tree_complies_and_the_report_counts_every_class(self):
        self.assertEqual(mp.validate(), [])
        report = mp.report()
        self.assertTrue(report["ok"])
        self.assertEqual(report["violations"], [])
        self.assertEqual(report["classes"], {"purposeful": 47, "legacy-unclassified": 37, "reference-illustrative": 400,
                                             "specification-index": 156, "withdrawn": 5})
        self.assertEqual(report["unclassified"], 0)
        self.assertEqual(report["registries"], {
            "native-engine": {"total": 67, "purposeful": 33, "legacy-unclassified": 34, "withdrawn": 5},
            "nextgen-camera": {"total": 3, "legacy-unclassified": 3},
            "digital-shows": {"total": 14, "purposeful": 14},
            "reference-recipes": {"total": 400, "reference-illustrative": 400},
            "catalog": {"total": 156, "specification-index": 156}})
        self.assertEqual(report["legacy_unclassified_ids"], {name: sorted(ids) for name, ids in mp.BASELINE_LEGACY.items()})
        self.assertEqual((report["policy"], report["policy_version"], report["effective_from"]), (mp.POLICY, "1.0.0", "2026-11-28"))
        self.assertEqual(report["policy_sha256"], hashlib.sha256((ROOT / mp.POLICY).read_bytes()).hexdigest())
        self.assertGreaterEqual(report["sources_scanned"]["pure"], 67 + 7 + 1)
        self.assertGreaterEqual(report["sources_scanned"]["runtime"], 20)
        self.assertEqual(report, mp.report())
        json.dumps(report)

    def test_the_policy_is_one_central_file_with_the_shape_the_classes_and_the_pinned_lists(self):
        policy = self.policy
        self.assertEqual((policy["schema_version"], policy["implementation"]), (1, "engineering_os/motion_policy.py"))
        self.assertEqual(policy["meaning"]["keys"], ["ar", "en"])
        self.assertEqual((policy["meaning"]["min_chars"], policy["meaning"]["max_chars"], policy["meaning"]["arabic_script_in"]), (12, 240, "ar"))
        self.assertEqual(tuple(policy["classes"]), mp.CLASSES)
        for text in (policy["rule"], policy["sources"]["seeded_randomness"], *policy["classes"].values()):
            self.assertRegex(text["ar"], "[\u0600-\u06ff]")
            self.assertTrue(text["en"])
        native = policy["registries"]["native-engine"]
        without = [row["id"] for row in self.registry["motions"] if row["meaning"] is None]
        self.assertEqual(sorted(native["legacy_ids"]), sorted(without))
        self.assertEqual(len(native["legacy_ids"]), 34)
        self.assertEqual(self.registry["counts"]["with_digital_meaning"], 67 - 34)
        self.assertEqual(set(native["legacy_ids"]), mp.BASELINE_LEGACY["native-engine"])
        self.assertEqual(set(native["withdrawn_ids"]), mp.BASELINE_WITHDRAWN["native-engine"])
        for identifier in native["withdrawn_ids"]:
            module, _, slug = identifier.partition("-")
            self.assertFalse((ROOT / native["sources"] / module / f"{slug}.mjs").exists(), identifier)
        self.assertEqual(set(policy["registries"]["nextgen-camera"]["legacy_ids"]), set(cinematic.CAMERA_IDS))
        self.assertEqual(policy["owner_decisions"]["records"], [])
        self.assertIn("seeded", policy["sources"]["seeded_randomness"]["en"])
        self.assertTrue(any("only shrink" in line for line in policy["invariants"]))
        for row in policy["enforcement"]:
            self.assertTrue((ROOT / row["path"]).is_file(), row["path"])

    def test_the_fixed_lists_in_code_are_the_ones_the_motion_tools_state(self):
        inventory = (ROOT / "packages/motion-engines/tools/native_inventory.mjs").read_text("utf-8")
        self.assertIn("export const BASELINE_ENGINE_MOTIONS = 34;", inventory)
        withdrawn = re.search(r"export const WITHDRAWN = Object\.freeze\(\[(.*?)\]\);", inventory, re.S)
        self.assertEqual(set(re.findall(r"'([a-z0-9-]+)'", withdrawn.group(1))), mp.BASELINE_WITHDRAWN["native-engine"])
        self.assertEqual(len(mp.BASELINE_LEGACY["native-engine"]), 34)
        self.assertEqual(mp.BASELINE_LEGACY["nextgen-camera"], cinematic.CAMERA_IDS)
        self.assertEqual(mp.camera_ids((ROOT / CAMERA).read_text("utf-8")),
                         ["camera-infinite-flythrough", "camera-drone-approach", "camera-macro-to-micro"])
        self.assertEqual(mp.PIN_CEILING, {"reference-recipes": 400, "catalog": 156})

    def test_a_motion_without_a_meaning_is_never_classed_purposeful(self):
        policy, purposeful = self.policy, 0
        for row in self.registry["motions"]:
            cls = mp.classify("native-engine", row, policy)
            self.assertEqual(cls, "purposeful" if row["meaning"] else "legacy-unclassified", row["id"])
            purposeful += cls == "purposeful"
        self.assertEqual(purposeful, self.registry["counts"]["with_digital_meaning"])
        for identifier in mp.BASELINE_LEGACY["native-engine"]:
            self.assertEqual(mp.classify("native-engine", {"id": identifier, "meaning": None}, policy), "legacy-unclassified")
        for entry in ({"id": "icons-new-thing"}, {"id": "icons-new-thing", "meaning": None}, {"id": "icons-new-thing", "meaning": {"en": MEANING["en"]}},
                      {"id": "icons-new-thing", "meaning": "a sentence that is long enough"}, {"id": LEGACY, "meaning": MEANING}):
            with self.subTest(entry=entry), self.assertRaises(mp.MotionPolicyError):
                mp.classify("native-engine", entry, policy)

    def test_classify_answers_one_class_per_registry(self):
        policy = self.policy
        self.assertEqual(mp.classify("native-engine", {"id": "icons-new-thing", "meaning": MEANING}, policy), "purposeful")
        self.assertEqual(mp.classify("native-engine", {"id": "lighting-lens-flare", "meaning": MEANING}, policy), "withdrawn")
        self.assertEqual(mp.classify("nextgen-camera", {"id": "camera-drone-approach"}, policy), "legacy-unclassified")
        self.assertEqual(mp.classify("digital-shows", {"id": "approval-gate", "meaning": MEANING}, policy), "purposeful")
        self.assertEqual(mp.classify("reference-recipes", {"id": "os-quantum-b01"}, policy), "reference-illustrative")
        self.assertEqual(mp.classify("catalog", {"id": "legacy-1"}, policy), "specification-index")
        self.assertEqual(mp.classify("catalog", {"id": "legacy-1", "meaning": MEANING}, policy), "specification-index")
        self.assertEqual(mp.classify("digital-shows", {"id": "approval-gate", "meaning": MEANING}), "purposeful")
        for registry, entry in (("nextgen-camera", {"id": "camera-new-scene", "meaning": MEANING}), ("digital-shows", {"id": "new-scene"}),
                                ("digital-shows", {"id": "new-scene", "meaning": {"ar": "", "en": "Something long enough."}}),
                                ("no-such-registry", {"id": "x"}), ("native-engine", {}), ("native-engine", "quantum-light-tunnel")):
            with self.subTest(registry=registry, entry=entry), self.assertRaises(mp.MotionPolicyError):
                mp.classify(registry, entry, policy)

    def test_a_meaning_is_one_english_and_one_arabic_sentence_and_nothing_else(self):
        good = {"en": "Records from many systems merge into one.", "ar": "سجلاتٌ من أنظمةٍ كثيرة تندمج في سجلٍّ واحد."}
        bad = [None, "text", {}, [], {"en": good["en"]}, {"ar": good["ar"]}, {"en": good["en"], "ar": "English only here, no Arabic"},
               {"en": "short", "ar": good["ar"]}, {**good, "fr": "en plus"}, {"en": good["en"], "ar": "ق" * 300},
               {"en": 7, "ar": good["ar"]}, {"en": " " * 40, "ar": good["ar"]}]
        self.assertTrue(mp.valid_meaning(good, self.policy))
        for value in bad:
            self.assertFalse(mp.valid_meaning(value, self.policy), value)
        tighter = changed(lambda policy: policy["meaning"].update(min_chars=60))
        self.assertFalse(mp.valid_meaning(good, tighter))
        looser = changed(lambda policy: policy["meaning"].update(min_chars=1, max_chars=5000))
        self.assertFalse(mp.valid_meaning({"en": "short", "ar": good["ar"]}, looser), "the fixed limits still apply")
        self.assertFalse(mp.valid_meaning({"en": good["en"], "ar": "ق" * 300}, looser))

    @unittest.skipUnless(NODE, "node not installed")
    def test_the_registry_builder_applies_the_same_meaning_check(self):
        good = {"en": "Records from many systems merge into one.", "ar": "سجلاتٌ من أنظمةٍ كثيرة تندمج في سجلٍّ واحد."}
        cases = [good, None, {}, {"en": good["en"]}, {"en": good["en"], "ar": "English only here, no Arabic"}, {"en": "short", "ar": good["ar"]},
                 {**good, "fr": "en plus"}, {"en": good["en"], "ar": "ق" * 300}, {"en": "x" * 12, "ar": "ق" * 12}, {"en": "x" * 240, "ar": "ق" * 240},
                 {"en": "x" * 241, "ar": "ق" * 12}, {"en": "x" * 11, "ar": "ق" * 12}]
        script = ("import { validMeaning, purposePolicy } from './packages/motion-engines/tools/build_registry.mjs';"
                  "const cases = JSON.parse(process.argv[1]);"
                  "console.log(JSON.stringify({ valid: cases.map(validMeaning), legacy: [...purposePolicy().legacy].sort(), withdrawn: [...purposePolicy().withdrawn].sort() }));")
        done = subprocess.run([NODE, "--input-type=module", "-e", script, json.dumps(cases)], cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)
        answer = json.loads(done.stdout)
        self.assertEqual(answer["valid"], [mp.valid_meaning(case, self.policy) for case in cases])
        self.assertEqual(answer["valid"][0], True)
        native = self.policy["registries"]["native-engine"]
        self.assertEqual((answer["legacy"], answer["withdrawn"]), (sorted(native["legacy_ids"]), sorted(native["withdrawn_ids"])))

    def test_the_command_prints_the_report_and_exits_zero(self):
        done = subprocess.run([sys.executable, "-m", "engineering_os.motion_policy"], cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout), mp.report())


class PolicyFile(unittest.TestCase):
    def test_a_duplicate_key_in_the_policy_is_refused(self):
        tree = Tree(self)
        text = tree.text(mp.POLICY)
        for old, new in (('"policy_version": "1.0.0",', '"policy_version": "1.0.0",\n  "policy_version": "1.0.0",'),
                         ('"withdrawn_ids": [\n        "lighting-lens-flare",', '"legacy_ids": [],\n      "withdrawn_ids": [\n        "lighting-lens-flare",'),
                         ('"min_chars": 12,', '"min_chars": 12,\n    "min_chars": 1,')):
            with self.subTest(new=new):
                self.assertEqual(text.count(old), 1)
                tree.write(mp.POLICY, text.replace(old, new))
                json.loads(tree.text(mp.POLICY))  # an ordinary parser accepts it and silently keeps the last value
                with self.assertRaisesRegex(mp.MotionPolicyError, "duplicate JSON key"):
                    mp.load_policy(tree.root)
                with self.assertRaisesRegex(mp.MotionPolicyError, "duplicate JSON key"):
                    mp.validate(tree.root)
                report = mp.report(tree.root)
                self.assertFalse(report["ok"])
                self.assertEqual(codes(report["violations"]), [("policy-invalid", None, None)])
                self.assertIn("duplicate JSON key", report["violations"][0]["detail"])
                self.assertEqual(sum(report["classes"].values()), 0)
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(mp.main([str(tree.root)]), 1)
        tree.write(mp.POLICY, text)
        self.assertEqual(mp.validate(tree.root), [])

    def test_a_missing_unreadable_or_non_finite_policy_is_refused(self):
        tree = Tree(self)
        text = tree.text(mp.POLICY)
        for broken in ("", "{", "[]", text.replace('"schema_version": 1', '"schema_version": NaN'), text.replace('"schema_version": 1', '"schema_version": 2'),
                       text.encode("utf-8")[:-40].decode("utf-8", "ignore"), "[" * 100000 + "]" * 100000):
            with self.subTest(broken=broken[:30]):
                tree.write(mp.POLICY, broken)
                with self.assertRaises(mp.MotionPolicyError):
                    mp.load_policy(tree.root)
                self.assertEqual(codes(mp.report(tree.root)["violations"]), [("policy-invalid", None, None)])
        (tree.root / mp.POLICY).unlink()
        with self.assertRaisesRegex(mp.MotionPolicyError, "missing"):
            mp.load_policy(tree.root)
        (tree.root / mp.POLICY).symlink_to(ROOT / mp.POLICY)
        with self.assertRaisesRegex(mp.MotionPolicyError, "symlink refused"):
            mp.load_policy(tree.root)
        self.assertFalse(mp.report(tree.root)["ok"])

    def test_a_policy_of_the_wrong_shape_is_refused(self):
        def drop(key):
            return lambda policy: policy.pop(key)
        cases = {
            "unknown top-level key": lambda policy: policy.update(exceptions=["icons-new-thing"]),
            "missing rule": drop("rule"),
            "rule without Arabic": lambda policy: policy["rule"].update(ar="English only"),
            "a third language as a required key": lambda policy: policy["meaning"].update(keys=["ar", "en", "fr"]),
            "meaning without Arabic": lambda policy: policy["meaning"].update(keys=["en"]),
            "min above max": lambda policy: policy["meaning"].update(min_chars=300),
            "a missing class": lambda policy: policy["classes"].pop("legacy-unclassified"),
            "an invented class": lambda policy: policy["classes"].update(decorative=policy["classes"]["purposeful"]),
            "a missing registry": lambda policy: policy["registries"].pop("digital-shows"),
            "a legacy allowance for show scenes": lambda policy: policy["registries"]["digital-shows"].update(legacy_ids=["title-card"]),
            "a repeated id": lambda policy: policy["registries"]["native-engine"]["legacy_ids"].append(LEGACY),
            "an id both legacy and withdrawn": lambda policy: policy["registries"]["native-engine"]["withdrawn_ids"].append(LEGACY),
            "an id that is not an id": lambda policy: policy["registries"]["native-engine"]["legacy_ids"].append("../x"),
            "a record outside the tree": lambda policy: policy["registries"]["native-engine"].update(record="../registry.json"),
            "an absolute record": lambda policy: policy["registries"]["catalog"].update(record="/etc/passwd"),
            "another class for the recipes": lambda policy: policy["registries"]["reference-recipes"].update({"class": "purposeful"}),
            "a negative pin": lambda policy: policy["registries"]["catalog"].update(pinned_count=-1),
            "a pattern that does not compile": lambda policy: policy["sources"]["patterns"]["timer"].append("("),
            "an unknown forbidden group": lambda policy: policy["sources"]["sets"]["pure"]["forbidden"].append("no-such-group"),
            "a source root outside the tree": lambda policy: policy["sources"]["sets"]["pure"]["roots"].append({"path": "../x", "recursive": False}),
            "a missing source set": lambda policy: policy["sources"]["sets"].pop("runtime"),
            "a decision of an unknown kind": lambda policy: policy["owner_decisions"]["records"].append(
                {"registry": "native-engine", "id": LEGACY, "decision": "approved", "date": "2026-12-01", "note": "x"}),
            "a decision without a date": lambda policy: policy["owner_decisions"]["records"].append(
                {"registry": "native-engine", "id": LEGACY, "decision": "promoted", "note": "x"}),
            "another implementation": lambda policy: policy.update(implementation="engineering_os/other.py"),
            "no enforcement": lambda policy: policy.update(enforcement=[]),
        }
        for name, change in cases.items():
            with self.subTest(name=name), self.assertRaises(mp.MotionPolicyError):
                mp.validate(ROOT, changed(change))
        with self.assertRaises(mp.MotionPolicyError):
            mp.validate(ROOT, [])

    def test_the_policy_cannot_relax_what_is_fixed_in_code(self):
        def drop_pattern(policy):
            policy["sources"]["patterns"]["unseeded-randomness"].remove("Math\\s*\\.\\s*random")
        def weaken_seed(policy):
            policy["sources"]["patterns"]["clock-as-seed"] = ["never-matches"]
        def drop_root(policy):
            policy["sources"]["sets"]["pure"]["roots"] = [row for row in policy["sources"]["sets"]["pure"]["roots"] if row["path"] != "packages/digital-shows/kit.mjs"]
        def shallow(policy):
            policy["sources"]["sets"]["pure"]["roots"][0]["recursive"] = False
        cases = {
            "shorter meanings": (lambda policy: policy["meaning"].update(min_chars=3), ("rule-relaxed", None, "meaning")),
            "longer meanings": (lambda policy: policy["meaning"].update(max_chars=2000), ("rule-relaxed", None, "meaning")),
            "Math.random allowed": (drop_pattern, ("rule-relaxed", None, "unseeded-randomness")),
            "clock seeds allowed": (weaken_seed, ("rule-relaxed", None, "clock-as-seed")),
            "the kit no longer scanned": (drop_root, ("rule-relaxed", None, "pure")),
            "motions scanned one level deep": (shallow, ("rule-relaxed", None, "pure")),
            "clocks allowed in motions": (lambda policy: policy["sources"]["sets"]["pure"]["forbidden"].remove("wall-clock"), ("rule-relaxed", None, "pure")),
            "randomness allowed in playback": (lambda policy: policy["sources"]["sets"]["runtime"]["forbidden"].remove("unseeded-randomness"), ("rule-relaxed", None, "runtime")),
            "a larger recipe pin": (lambda policy: policy["registries"]["reference-recipes"].update(pinned_count=401), ("pin-raised", "reference-recipes", None)),
            "a larger catalogue pin": (lambda policy: policy["registries"]["catalog"].update(pinned_count=200), ("pin-raised", "catalog", None)),
            "a withdrawn id forgotten": (lambda policy: policy["registries"]["native-engine"]["withdrawn_ids"].remove("shaders-sdf-morph"),
                                         ("withdrawn-list-shrank", "native-engine", "shaders-sdf-morph")),
        }
        for name, (change, expected) in cases.items():
            with self.subTest(name=name):
                self.assertIn(expected, codes(mp.validate(ROOT, changed(change))))
        # Tightening is the owner's to do in the file: nothing in the tree breaks a stricter limit of 40 characters.
        self.assertEqual(mp.validate(ROOT, changed(lambda policy: policy["meaning"].update(min_chars=40))), [])
        extra = changed(lambda policy: policy["sources"]["sets"]["runtime"]["roots"].append({"path": "motion-library/adapters", "recursive": False}))
        self.assertEqual(mp.validate(ROOT, extra), [])


class Violations(unittest.TestCase):
    def test_an_untouched_copy_complies_so_each_violation_below_is_caused_by_its_change(self):
        tree = Tree(self)
        self.assertEqual(tree.validate(), [])
        self.assertEqual(mp.report(tree.root)["classes"], mp.report()["classes"])

    def test_a_new_motion_with_no_meaning_is_a_violation(self):
        tree = Tree(self)
        tree.add_motion("micro-input-focus", None)
        self.assertEqual(codes(tree.validate()), [("missing-meaning", "native-engine", "micro-input-focus")])
        report = mp.report(tree.root)
        self.assertFalse(report["ok"])
        self.assertEqual((report["classes"]["purposeful"], report["classes"]["legacy-unclassified"], report["unclassified"]), (47, 37, 1))
        self.assertEqual(report["registries"]["native-engine"], {"total": 68, "purposeful": 33, "legacy-unclassified": 34, "unclassified": 1, "withdrawn": 5})
        self.assertNotIn("micro-input-focus", report["legacy_unclassified_ids"]["native-engine"])
        # The same motion with a meaning is purposeful and the tree is clean again.
        tree.edit_row("micro-input-focus", lambda row: row.update(meaning=MEANING))
        self.assertEqual(tree.validate(), [])
        self.assertEqual(mp.report(tree.root)["registries"]["native-engine"]["purposeful"], 34)

    def test_a_source_that_was_never_registered_is_a_violation(self):
        tree = Tree(self)
        tree.write("packages/motion-engines/motions/icons/animated-set.mjs", "export default {};\n")
        self.assertEqual(codes(tree.validate()), [("unregistered-source", "native-engine", "icons-animated-set")])
        # A helper below motions/<module>/lib is not a motion, but it is scanned like one.
        tree = Tree(self)
        tree.write("packages/motion-engines/motions/icons/lib/draw.mjs", "export const jitter = () => Math.random();\n")
        self.assertEqual(codes(tree.validate()), [("forbidden-source", None, "packages/motion-engines/motions/icons/lib/draw.mjs:1")])

    def test_a_thirty_fifth_legacy_id_is_a_violation(self):
        tree = Tree(self)
        tree.add_motion("micro-input-focus", None)
        tree.policy(lambda policy: policy["registries"]["native-engine"]["legacy_ids"].append("micro-input-focus"))
        self.assertEqual(codes(tree.validate()), [("legacy-list-grew", "native-engine", "micro-input-focus")])
        self.assertFalse(mp.report(tree.root)["ok"])
        # Swapping one id for another keeps the count at 34 and is refused all the same.
        tree.policy(lambda policy: policy["registries"]["native-engine"]["legacy_ids"].remove(LEGACY))
        found = codes(tree.validate())
        self.assertIn(("legacy-list-grew", "native-engine", "micro-input-focus"), found)
        self.assertIn(("missing-meaning", "native-engine", LEGACY), found)
        self.assertIn(("undecided-removal", "native-engine", LEGACY), found)
        # The camera list is fixed the same way.
        camera = changed(lambda policy: policy["registries"]["nextgen-camera"]["legacy_ids"].append("camera-crane-reveal"))
        self.assertIn(("legacy-list-grew", "nextgen-camera", "camera-crane-reveal"), codes(mp.validate(ROOT, camera)))

    def test_a_pinned_id_that_now_has_a_meaning_is_a_violation_until_the_promotion_is_recorded(self):
        tree = Tree(self)
        tree.edit_row(LEGACY, lambda row: row.update(meaning=MEANING))
        self.assertEqual(codes(tree.validate()), [("legacy-stale", "native-engine", LEGACY)])
        report = mp.report(tree.root)
        self.assertEqual((report["registries"]["native-engine"]["purposeful"], report["registries"]["native-engine"]["unclassified"]), (33, 1))
        # Removing the pin without a decision record is not a promotion.
        tree.policy(lambda policy: policy["registries"]["native-engine"]["legacy_ids"].remove(LEGACY))
        self.assertEqual(codes(tree.validate()), [("undecided-removal", "native-engine", LEGACY)])
        record = {"registry": "native-engine", "id": LEGACY, "decision": "promoted", "date": "2026-12-01", "note": "Owner stated the meaning; proven again in Chromium."}
        tree.policy(lambda policy: policy["owner_decisions"]["records"].append(record))
        self.assertEqual(tree.validate(), [])
        report = mp.report(tree.root)
        self.assertEqual(report["registries"]["native-engine"], {"total": 67, "purposeful": 34, "legacy-unclassified": 33, "withdrawn": 5})
        self.assertNotIn(LEGACY, report["legacy_unclassified_ids"]["native-engine"])
        # A promotion counts only while the motion is proven: an unverified row is not a promoted motion.
        tree.edit_row(LEGACY, lambda row: row.update(status="implemented-unverified"))
        self.assertEqual(codes(tree.validate()), [("promotion-unproven", "native-engine", LEGACY)])
        tree.edit_row(LEGACY, lambda row: row.update(status="operational", meaning=None))
        self.assertEqual(sorted(codes(tree.validate())), [("missing-meaning", "native-engine", LEGACY), ("promotion-unproven", "native-engine", LEGACY)])

    def test_a_decision_must_match_what_the_lists_and_the_tree_say(self):
        def record(identifier, decision, registry="native-engine"):
            return {"registry": registry, "id": identifier, "decision": decision, "date": "2026-12-01", "note": "test"}
        still_pinned = changed(lambda policy: policy["owner_decisions"]["records"].append(record(LEGACY, "promoted")))
        self.assertEqual(codes(mp.validate(ROOT, still_pinned)), [("decision-mismatch", "native-engine", LEGACY)])
        never_legacy = changed(lambda policy: policy["owner_decisions"]["records"].append(record(PURPOSEFUL, "withdrawn")))
        self.assertEqual(codes(mp.validate(ROOT, never_legacy)), [("decision-mismatch", "native-engine", PURPOSEFUL)])
        def promote_camera(policy):
            policy["registries"]["nextgen-camera"]["legacy_ids"].remove("camera-drone-approach")
            policy["owner_decisions"]["records"].append(record("camera-drone-approach", "promoted", "nextgen-camera"))
        found = codes(mp.validate(ROOT, changed(promote_camera)))
        self.assertIn(("decision-mismatch", "nextgen-camera", "camera-drone-approach"), found)
        self.assertIn(("missing-meaning", "nextgen-camera", "camera-drone-approach"), found)

    def test_a_withdrawn_id_present_on_disk_is_a_violation(self):
        tree = Tree(self)
        tree.write("packages/motion-engines/motions/lighting/lens-flare.mjs", "export default {};\n")
        self.assertEqual(codes(tree.validate()), [("withdrawn-present", "native-engine", "lighting-lens-flare")])
        self.assertIn("motions/lighting/lens-flare.mjs", tree.validate()[0]["detail"])
        # Registering it does not help, whatever meaning it states.
        tree = Tree(self)
        tree.add_motion("shaders-sdf-morph", MEANING)
        self.assertEqual(codes(tree.validate()), [("withdrawn-present", "native-engine", "shaders-sdf-morph")] * 2)
        report = mp.report(tree.root)
        self.assertEqual((report["registries"]["native-engine"]["purposeful"], report["classes"]["withdrawn"]), (33, 5))

    def test_withdrawing_a_legacy_motion_needs_the_source_gone_the_list_moved_and_a_record(self):
        tree = Tree(self)
        tree.remove_motion(LEGACY)
        self.assertEqual(codes(tree.validate()), [("legacy-stale", "native-engine", LEGACY)])
        def withdraw(policy):
            policy["registries"]["native-engine"]["legacy_ids"].remove(LEGACY)
            policy["registries"]["native-engine"]["withdrawn_ids"].append(LEGACY)
        tree.policy(withdraw)
        self.assertEqual(codes(tree.validate()), [("undecided-removal", "native-engine", LEGACY)])
        record = {"registry": "native-engine", "id": LEGACY, "decision": "withdrawn", "date": "2026-12-01", "note": "Decorative only."}
        tree.policy(lambda policy: policy["owner_decisions"]["records"].append(record))
        self.assertEqual(tree.validate(), [])
        report = mp.report(tree.root)
        self.assertEqual(report["registries"]["native-engine"], {"total": 66, "purposeful": 33, "legacy-unclassified": 33, "withdrawn": 6})
        self.assertEqual(report["classes"]["withdrawn"], 6)
        # Recorded as withdrawn but not moved to withdrawn_ids: the id could be rebuilt unnoticed.
        tree.policy(lambda policy: policy["registries"]["native-engine"]["withdrawn_ids"].remove(LEGACY))
        self.assertEqual(codes(tree.validate()), [("decision-mismatch", "native-engine", LEGACY)])

    def test_a_meaning_missing_arabic_is_a_violation(self):
        tree = Tree(self)
        english_only = {"en": MEANING["en"], "ar": "A completed request issues a receipt."}
        tree.edit_row(PURPOSEFUL, lambda row: row.update(meaning=english_only))
        self.assertEqual(codes(tree.validate()), [("invalid-meaning", "native-engine", PURPOSEFUL)])
        report = mp.report(tree.root)
        self.assertEqual((report["registries"]["native-engine"]["purposeful"], report["unclassified"]), (32, 1))
        for meaning in ({"en": MEANING["en"]}, {"ar": MEANING["ar"]}, {**MEANING, "fr": "Une phrase assez longue."}, {"en": "short", "ar": MEANING["ar"]},
                        {"en": MEANING["en"], "ar": "ق" * 241}, "A plain sentence instead of an object.", [], 7):
            with self.subTest(meaning=meaning):
                tree.edit_row(PURPOSEFUL, lambda row: row.update(meaning=meaning))
                self.assertEqual(codes(tree.validate()), [("invalid-meaning", "native-engine", PURPOSEFUL)])

    def test_a_show_scene_must_state_a_valid_meaning_and_has_no_legacy_allowance(self):
        tree = Tree(self)
        def scene(change):
            tree.edit(SHOWS, lambda value: change(next(row for row in value["scenes"] if row["id"] == "approval-gate")))
        scene(lambda row: row.update(meaning={"en": MEANING["en"], "ar": "English only, long enough."}))
        self.assertEqual(codes(tree.validate()), [("invalid-meaning", "digital-shows", "approval-gate")])
        scene(lambda row: row.pop("meaning"))
        self.assertEqual(codes(tree.validate()), [("missing-meaning", "digital-shows", "approval-gate")])
        self.assertEqual(mp.report(tree.root)["registries"]["digital-shows"], {"total": 14, "purposeful": 13, "unclassified": 1})
        scene(lambda row: row.update(meaning=MEANING))
        tree.edit(SHOWS, lambda value: value["scenes"].append({"id": "new-scene", "meaning": None}))
        self.assertEqual(codes(tree.validate()), [("missing-meaning", "digital-shows", "new-scene")])
        tree.edit(SHOWS, lambda value: value["scenes"][-1].update(meaning=MEANING))
        self.assertEqual(tree.validate(), [])
        self.assertEqual(mp.report(tree.root)["registries"]["digital-shows"], {"total": 15, "purposeful": 15})

    def test_randomness_in_a_motion_source_is_a_violation(self):
        tree = Tree(self)
        source = tree.row(PURPOSEFUL)["source"]
        lines = tree.text(source).count("\n")
        tree.write(source, tree.text(source) + "const jitter = Math.random();\n")
        tree.resync(PURPOSEFUL)
        violations = tree.validate()
        self.assertEqual(codes(violations), [("forbidden-source", None, f"{source}:{lines + 1}")])
        self.assertIn("unseeded-randomness", violations[0]["detail"])
        self.assertFalse(mp.report(tree.root)["ok"])
        # Without the rebuilt registry the changed source is also reported as unproven.
        tree = Tree(self)
        tree.write(source, tree.text(source) + "const jitter = Math\n  .random();\n")
        self.assertEqual(sorted(codes(tree.validate())), [("forbidden-source", None, f"{source}:{lines + 1}"), ("registry-stale", "native-engine", PURPOSEFUL)])

    def test_every_covered_source_set_refuses_its_forbidden_names(self):
        cases = (
            ("packages/motion-engines/motions/quantum/light-tunnel.mjs", "const start = Date.now();", "wall-clock"),
            ("packages/motion-engines/motions/quantum/light-tunnel.mjs", "setTimeout(() => {}, 16);", "timer"),
            ("motion-library/expansion/families.mjs", "const pick = crypto.getRandomValues(new Uint32Array(1))[0];", "unseeded-randomness"),
            ("motion-library/expansion/nextgen-camera.mjs", "const t0 = performance.now();", "wall-clock"),
            (KIT, "const id = crypto.randomUUID();", "unseeded-randomness"),
            (KIT, "/* Math.random() would make a show unrepeatable */", "unseeded-randomness"),
            ("packages/motion-engines/core/api.mjs", "const seed = Date.now();", "clock-as-seed"),
            ("packages/motion-engines/core/util.mjs", "export const unseeded = () => Math.random();", "unseeded-randomness"),
            ("packages/motion-engines/engines/canvas2d.mjs", "const next = mulberry32(performance.now());", "clock-as-seed"),
            ("packages/motion-engines/orchestrator.mjs", "const tie = Math.random();", "unseeded-randomness"),
            ("packages/motion-sdk/index.mjs", "const seed = new Date().getTime();", "clock-as-seed"),
            ("motion-library/runtime/hub-motion.mjs", "const shuffle = Math.random() - 0.5;", "unseeded-randomness"),
        )
        for relative, line, group in cases:
            with self.subTest(relative=relative, line=line):
                tree = Tree(self)
                tree.write(relative, tree.text(relative) + line + "\n")
                found = [row for row in tree.validate() if row["code"] == "forbidden-source"]
                self.assertEqual(len(found), 1, found)
                self.assertTrue(found[0]["id"].startswith(relative + ":"), found[0])
                self.assertIn(group, found[0]["detail"])

    def test_a_seeded_generator_a_playback_clock_and_a_comment_are_not_violations(self):
        allowed = (
            (KIT, "const extra = seeded(4242 + 7);"),
            (KIT, "  // no Math.random, no Date.now and no setTimeout in this kit"),
            ("packages/motion-engines/motions/quantum/light-tunnel.mjs", "// ctx.random(salt) is seeded: Math.random() is never used"),
            ("packages/motion-engines/core/api.mjs", "const again = mulberry32((7 + Math.imul(3, 0x9e3779b1)) >>> 0);"),
            ("packages/motion-engines/core/clock.mjs", "const now = () => performance.now();"),
            ("packages/motion-sdk/index.mjs", "const started = Date.now();"),
            ("motion-library/expansion/geometry.mjs", "export const jitter = (i, seed = 1) => noise(i, seed) - 0.5;"),
        )
        tree = Tree(self)
        for relative, line in allowed:
            tree.write(relative, tree.text(relative) + line + "\n")
        self.assertEqual([row for row in tree.validate() if row["code"] == "forbidden-source"], [])
        policy = mp.load_policy()
        patterns = [re.compile(pattern) for group in policy["sources"]["patterns"].values() for pattern in group]
        for line in ("const next = mulberry32((settings.seed + Math.imul(salt + 1, 0x9e3779b1)) >>> 0);", "const rand = ctx.random(7);",
                     "const next = seeded(977 + c.seed);", "const n = noise(i, seed);"):
            self.assertEqual(mp.scan_source(line, patterns), [], line)
        self.assertEqual(mp.scan_source("a\n// Math.random()\nMath.random()\n", [re.compile(r"Math\s*\.\s*random")]), [(3, r"Math\s*\.\s*random")])

    def test_a_four_hundred_and_first_recipe_or_a_new_catalogue_row_is_a_violation(self):
        tree = Tree(self)
        tree.edit(RECIPES, lambda value: value["definitions"].append({**value["definitions"][0], "id": "os-quantum-b99"}))
        self.assertEqual(codes(tree.validate()), [("count-above-pin", "reference-recipes", None)])
        self.assertEqual(mp.report(tree.root)["registries"]["reference-recipes"], {"total": 401, "reference-illustrative": 401})
        # Raising the pin to fit is refused: the ceiling is fixed in code.
        tree.policy(lambda policy: policy["registries"]["reference-recipes"].update(pinned_count=401))
        self.assertEqual(codes(tree.validate()), [("pin-raised", "reference-recipes", None)])
        tree = Tree(self)
        tree.edit(CATALOG, lambda value: value["entries"].append({**value["entries"][0], "id": "legacy-999"}))
        self.assertEqual(codes(tree.validate()), [("count-above-pin", "catalog", None)])
        tree = Tree(self)
        tree.edit(RECIPES, lambda value: value["definitions"].append(dict(value["definitions"][0])))
        self.assertEqual(codes(tree.validate()), [("duplicate-id", "reference-recipes", "os-quantum-b01")])
        tree = Tree(self)
        tree.edit("motion-library/components.json", lambda value: value["components"].append({**value["components"][0], "id": "unlisted-fade"}))
        self.assertEqual(codes(tree.validate()), [("unindexed-component", "catalog", "unlisted-fade")])

    def test_a_pinned_count_follows_the_set_down_and_never_back_up(self):
        tree = Tree(self)
        tree.edit(RECIPES, lambda value: value["definitions"].pop())
        self.assertEqual(codes(tree.validate()), [("pin-stale", "reference-recipes", None)])
        tree.policy(lambda policy: policy["registries"]["reference-recipes"].update(pinned_count=399))
        self.assertEqual(tree.validate(), [])
        tree.edit(RECIPES, lambda value: value["definitions"].append({**value["definitions"][0], "id": "os-quantum-b99"}))
        self.assertEqual(codes(tree.validate()), [("count-above-pin", "reference-recipes", None)])

    def test_a_new_camera_scene_is_a_violation_and_an_unreadable_table_is_not_a_pass(self):
        tree = Tree(self)
        text = tree.text(CAMERA)
        anchor = "  ['camera-macro-to-micro',"
        self.assertEqual(text.count(anchor), 1)
        tree.write(CAMERA, text.replace(anchor, "  ['camera-crane-reveal','Crane','رافعة','A crane rises.'],\n" + anchor))
        self.assertEqual(codes(tree.validate()), [("missing-meaning", "nextgen-camera", "camera-crane-reveal")])
        self.assertEqual(mp.report(tree.root)["registries"]["nextgen-camera"], {"total": 4, "legacy-unclassified": 3, "unclassified": 1})
        tree.write(CAMERA, text.replace(anchor, '  ["camera-crane-reveal","Crane","رافعة","A crane rises."],\n' + anchor))
        self.assertEqual(codes(tree.validate()), [("missing-meaning", "nextgen-camera", "camera-crane-reveal")])
        row = re.search(r"^  \['camera-drone-approach'.*\n", text, re.M).group(0)
        tree.write(CAMERA, text.replace(row, ""))
        self.assertEqual(codes(tree.validate()), [("legacy-stale", "nextgen-camera", "camera-drone-approach")])
        for unreadable in (text.replace("const specs = [", "const rows = ["), text.replace(anchor, "  [`camera-macro-to-micro`,")):
            tree.write(CAMERA, unreadable)
            found = codes(tree.validate())
            self.assertIn(("unreadable-record", "nextgen-camera", None), found)
            report = mp.report(tree.root)
            self.assertFalse(report["ok"])
            self.assertNotIn("legacy-unclassified", report["registries"]["nextgen-camera"])
        for bad in ("", "const specs = [\n];", "const specs = [\n  [1,'x'],\n];"):
            with self.assertRaises(mp.MotionPolicyError):
                mp.camera_ids(bad)

    def test_a_registry_that_no_longer_matches_its_source_is_not_trusted(self):
        tree = Tree(self)
        source = tree.row(LEGACY)["source"]
        tree.write(source, tree.text(source) + "\n")
        self.assertEqual(codes(tree.validate()), [("registry-stale", "native-engine", LEGACY)])
        tree = Tree(self)
        tree.edit_row(PURPOSEFUL, lambda row: row.update(source="packages/motion-engines/motions/micro/magnetic-button.mjs"))
        self.assertEqual(codes(tree.validate()), [("registry-stale", "native-engine", PURPOSEFUL)])
        tree = Tree(self)
        (tree.root / tree.row(PURPOSEFUL)["source"]).unlink()
        self.assertEqual(codes(tree.validate()), [("registry-stale", "native-engine", PURPOSEFUL)])
        tree = Tree(self)
        tree.write(KIT, tree.text(KIT) + "\n")
        self.assertEqual(codes(tree.validate()), [("registry-stale", "digital-shows", None)])
        tree = Tree(self)
        tree.edit(REGISTRY, lambda value: value["motions"].append(dict(value["motions"][0])))
        self.assertEqual(codes(tree.validate()), [("duplicate-id", "native-engine", tree.json(REGISTRY)["motions"][0]["id"])])

    def test_a_record_that_cannot_be_read_is_a_violation_never_a_pass(self):
        for relative, registry in ((REGISTRY, "native-engine"), (SHOWS, "digital-shows"), (RECIPES, "reference-recipes"), (CATALOG, "catalog"), (CAMERA, "nextgen-camera")):
            with self.subTest(relative=relative):
                tree = Tree(self)
                (tree.root / relative).unlink()
                self.assertIn(("unreadable-record", registry, None), codes(tree.validate()))
                report = mp.report(tree.root)
                self.assertFalse(report["ok"])
                self.assertEqual(report["registries"][registry], {"total": 0, **({"withdrawn": 5} if registry == "native-engine" else {})})
                (tree.root / relative).symlink_to(ROOT / relative)
                self.assertIn(("unreadable-record", registry, None), codes(tree.validate()))
        tree = Tree(self)
        tree.write(REGISTRY, '{"motions": [], "motions": []}')
        self.assertIn(("unreadable-record", "native-engine", None), codes(tree.validate()))
        tree.write(REGISTRY, '{"motions": [{"meaning": null}]}')
        self.assertIn(("unreadable-record", "native-engine", None), codes(tree.validate()))
        tree = Tree(self)
        shutil.rmtree(tree.root / "motion-library/runtime")
        self.assertEqual(codes(tree.validate()), [("unreadable-record", None, "motion-library/runtime")])
        tree = Tree(self)
        (tree.root / "packages/motion-sdk/extra.mjs").symlink_to(ROOT / "packages/motion-sdk/index.mjs")
        self.assertEqual(codes(tree.validate()), [("unreadable-record", None, "packages/motion-sdk/extra.mjs")])

    def test_an_enforcement_point_named_by_the_policy_must_exist(self):
        tree = Tree(self)
        (tree.root / "tests/test_native_motions_digital.mjs").unlink()
        self.assertEqual(codes(tree.validate()), [("enforcement-missing", None, "tests/test_native_motions_digital.mjs")])

    def test_the_command_exits_one_on_a_violation(self):
        tree = Tree(self)
        tree.add_motion("micro-input-focus", None)
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(mp.main([str(tree.root)]), 1)
        report = json.loads(output.getvalue())
        self.assertEqual((report["ok"], codes(report["violations"])), (False, [("missing-meaning", "native-engine", "micro-input-focus")]))

    @unittest.skipUnless(NODE, "node not installed")
    def test_the_registry_builder_refuses_what_the_validator_reports(self):
        tree = Tree(self)
        builder = [NODE, str(tree.root / "packages/motion-engines/tools/build_registry.mjs"), "--check"]
        done = subprocess.run(builder, capture_output=True, text=True, timeout=120)
        self.assertEqual((done.returncode, done.stderr), (0, ""))
        source = tree.row(PURPOSEFUL)["source"]
        stripped, count = re.subn(r"  meaning: \{\n.*\n.*\n  \},\n", "", tree.text(source))
        self.assertEqual(count, 1)
        tree.write(source, stripped)
        done = subprocess.run(builder, capture_output=True, text=True, timeout=120)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn(f"{PURPOSEFUL}: a motion must state its digital meaning", done.stderr)
        # The validator sees the same tree as unproven until a registry can be built from it again.
        self.assertEqual(codes(tree.validate()), [("registry-stale", "native-engine", PURPOSEFUL)])


if __name__ == "__main__":
    unittest.main()
