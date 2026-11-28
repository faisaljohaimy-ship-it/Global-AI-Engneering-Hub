"""Motions ported from earlier branches: the manifest, the sources and the browser receipt agree.

docs/evidence/ported-motions.json lists each ported module, the branch and commit it came from and
the motions it left out; docs/evidence/ported-motions-chromium.json is the browser proof, bound to the
SHA-256 of every module and of the files that drew it. This test reads them with the policy's
duplicate-key-refusing loader and fails when a ported motion has no valid meaning, duplicates a native,
withdrawn or camera id, uses a forbidden source pattern, or has no passing, current browser proof.
Negative cases change a copy in a short temporary directory; no browser runs here (the proof is
`node tests/test_ported_motions_browser.mjs`), and tests/test_ported_motions.mjs is run with Node.
"""
import hashlib
import json
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest

from engineering_os import motion_policy as mp

ROOT = pathlib.Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
MANIFEST = "docs/evidence/ported-motions.json"
RECEIPT = "docs/evidence/ported-motions-chromium.json"
REGISTRY = "packages/motion-engines/registry.json"
BRIEF = "packages/motion-engines/tools/brief.json"
INPUTS = ("packages/motion-sdk/index.mjs", "tests/test_ported_motions_browser.mjs", "motion-library/verify/serve.mjs")
CHECKS = {"drawn", "changes", "deterministic", "reduced_motion", "rtl", "exports", "pause", "stop", "cleanup", "cpu_budget"}
VIEWPORTS = ({"width": 390, "height": 844}, {"width": 1280, "height": 720})
CLAIMS = ("production_fps_verified", "real_devices_verified", "gpu_runtime_verified")


def _load(root, relative):
    return mp.load_json((root / relative).read_bytes())


def _sha(root, relative):
    return hashlib.sha256((root / relative).read_bytes()).hexdigest()


def problems(root=ROOT):
    """Everything that is wrong with the ported motions of a tree; empty when they comply."""
    root = pathlib.Path(root)
    out = []
    policy = mp.load_policy(root)
    manifest, receipt = _load(root, MANIFEST), _load(root, RECEIPT)
    native = {row["id"] for row in _load(root, REGISTRY)["motions"]}
    asked = {row["id"] for row in _load(root, BRIEF)["motions"]}
    withdrawn = set(policy["registries"]["native-engine"]["withdrawn_ids"])
    camera = set(policy["registries"]["nextgen-camera"]["legacy_ids"])
    pure = policy["sources"]["sets"]["pure"]
    patterns = [re.compile(p) for group in pure["forbidden"] for p in policy["sources"]["patterns"][group]]
    seen = set()
    for group in manifest["groups"]:
        source = group["source"]
        if not source.startswith("motion-library/expansion/") or "/" in source[len("motion-library/expansion/"):]:
            out.append(f"{source}: a ported module must sit directly in motion-library/expansion, where the pure source scan reads it")
        if not (root / source).is_file():
            out.append(f"{source}: missing")
            continue
        for line, pattern in mp.scan_source((root / source).read_text("utf-8"), patterns):
            out.append(f"{source}:{line}: forbidden source pattern {pattern}")
        for key in ("from_branch", "from_commit", "from_blob"):
            if not isinstance(group.get(key), str) or not group[key]:
                out.append(f"{source}: provenance {key} missing")
        for identifier in group["ids"]:
            if identifier in seen:
                out.append(f"{identifier}: ported twice")
            seen.add(identifier)
            if identifier not in asked:
                out.append(f"{identifier}: not a brief name")
            for name, ids in (("native engine motion", native), ("withdrawn id", withdrawn), ("camera scene", camera)):
                if identifier in ids:
                    out.append(f"{identifier}: is a {name}")
        for identifier, reason in group["left_out"].items():
            if identifier in group["ids"]:
                out.append(f"{identifier}: left out and ported")
            if reason.startswith("superseded") and identifier not in native:
                out.append(f"{identifier}: said to be superseded by a native motion that does not exist")
        proof = receipt["groups"].get(source)
        if proof is None:
            out.append(f"{source}: no browser proof")
            continue
        if proof.get("status") != "passed" or proof.get("failures") != [] or proof.get("page_errors") != 0 or proof.get("external_requests") != 0:
            out.append(f"{source}: browser proof did not pass")
        if proof.get("source_sha256") != _sha(root, source):
            out.append(f"{source}: changed since its browser proof")
        if set(proof.get("inputs", {})) != set(INPUTS) or any(_sha(root, path) != digest for path, digest in proof["inputs"].items()):
            out.append(f"{source}: the SDK, the proof script or the server changed since the proof")
        if any(proof.get(claim) is not False for claim in CLAIMS):
            out.append(f"{source}: unsupported device, frame-rate or GPU claim")
        motions = proof.get("motions", [])
        if [row["id"] for row in motions] != group["ids"]:
            out.append(f"{source}: the proof covers other motions than the manifest")
        for row in motions:
            if not mp.valid_meaning(row.get("meaning"), policy):
                out.append(f"{row['id']}: no valid digital meaning")
        cases = {(row["id"], row["viewport"]["width"]): row for row in proof.get("cases", [])}
        for identifier in group["ids"]:
            for viewport in VIEWPORTS:
                row = cases.get((identifier, viewport["width"]))
                if row is None or row["viewport"] != viewport or set(row["checks"]) != CHECKS or not all(v is True for v in row["checks"].values()):
                    out.append(f"{identifier}: no passing proof at {viewport['width']}x{viewport['height']}")
    for identifier in manifest["not_ported"]:
        if identifier in seen:
            out.append(f"{identifier}: listed as not ported and ported")
    for source in set(receipt["groups"]) - {group["source"] for group in manifest["groups"]}:
        out.append(f"{source}: proof for a module the manifest does not list")
    return out


class Copy:
    """The files the check reads, copied into a short temporary directory."""

    def __init__(self, case):
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="pm-"))
        case.addCleanup(shutil.rmtree, self.root, True)
        sources = [group["source"] for group in _load(ROOT, MANIFEST)["groups"]]
        for relative in (MANIFEST, RECEIPT, REGISTRY, BRIEF, mp.POLICY, *INPUTS, *sources):
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, target)

    def edit(self, relative, change):
        path = self.root / relative
        value = json.loads(path.read_text("utf-8"))
        change(value)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=1) + "\n", "utf-8")


class PortedMotionsTest(unittest.TestCase):
    def test_the_real_tree_complies(self):
        self.assertEqual(problems(), [])
        manifest = _load(ROOT, MANIFEST)
        self.assertGreater(sum(len(group["ids"]) for group in manifest["groups"]), 0)

    def test_the_policy_report_stays_clean(self):
        report = mp.report(ROOT)
        self.assertTrue(report["ok"], report["violations"])
        self.assertEqual((report["unclassified"], len(report["violations"])), (0, 0))

    def test_a_meaning_without_arabic_is_refused(self):
        tree = Copy(self)
        source = _load(ROOT, MANIFEST)["groups"][0]["source"]
        tree.edit(RECEIPT, lambda r: r["groups"][source]["motions"][0].update(meaning={"en": "A packet finds its route.", "ar": "A packet finds its route."}))
        self.assertTrue(any("no valid digital meaning" in p for p in problems(tree.root)))

    def test_a_changed_source_voids_its_proof(self):
        tree = Copy(self)
        source = _load(ROOT, MANIFEST)["groups"][0]["source"]
        path = tree.root / source
        path.write_text(path.read_text("utf-8") + "\n// changed\n", "utf-8")
        self.assertIn(f"{source}: changed since its browser proof", problems(tree.root))

    def test_a_native_withdrawn_or_unknown_id_is_refused(self):
        tree = Copy(self)
        tree.edit(MANIFEST, lambda m: m["groups"][0]["ids"].extend(["neural-inference-pipeline", "lighting-lens-flare", "not-in-the-brief"]))
        found = problems(tree.root)
        self.assertIn("neural-inference-pipeline: is a native engine motion", found)
        self.assertIn("lighting-lens-flare: is a withdrawn id", found)
        self.assertIn("not-in-the-brief: not a brief name", found)

    def test_unseeded_randomness_and_a_clock_are_refused(self):
        tree = Copy(self)
        source = _load(ROOT, MANIFEST)["groups"][0]["source"]
        path = tree.root / source
        path.write_text(path.read_text("utf-8") + "\nconst jitter = Math.random();\nconst now = performance.now();\n", "utf-8")
        found = problems(tree.root)
        self.assertTrue(any("Math" in p and "forbidden" in p for p in found), found)
        self.assertTrue(any("performance" in p and "forbidden" in p for p in found), found)

    def test_a_failed_check_or_a_missing_case_is_refused(self):
        tree = Copy(self)
        source = _load(ROOT, MANIFEST)["groups"][0]["source"]
        def change(receipt):
            group = receipt["groups"][source]
            group["cases"][0]["checks"]["deterministic"] = False
            group["cases"].pop()
            group["gpu_runtime_verified"] = True
        tree.edit(RECEIPT, change)
        found = problems(tree.root)
        self.assertEqual(sum("no passing proof" in p for p in found), 2, found)
        self.assertIn(f"{source}: unsupported device, frame-rate or GPU claim", found)

    def test_a_duplicate_json_key_is_refused(self):
        tree = Copy(self)
        path = tree.root / MANIFEST
        path.write_text(path.read_text("utf-8").replace('"schema_version": 1,', '"schema_version": 1, "schema_version": 1,', 1), "utf-8")
        with self.assertRaises(mp.MotionPolicyError):
            problems(tree.root)

    @unittest.skipIf(NODE is None, "Node.js is required to sample the ported modules")
    def test_the_modules_sample_as_the_manifest_and_receipt_say(self):
        result = subprocess.run([NODE, "--test", "tests/test_ported_motions.mjs"], cwd=ROOT, capture_output=True,
                                text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout[-4000:] + result.stderr[-2000:])


if __name__ == "__main__":
    unittest.main()
