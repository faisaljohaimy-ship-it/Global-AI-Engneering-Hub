"""Verify source-bound Codex checkout skills and the read-only bootstrap CLI."""

import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

from scripts import gaie_codex_bootstrap as bootstrap


ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = pathlib.Path("scripts/gaie_codex_bootstrap.py")


def run(root, *args):
    return subprocess.run(
        [sys.executable, str(root / SCRIPT), *args], cwd=root, capture_output=True, timeout=10,
    )


class CheckoutSkillsTests(unittest.TestCase):
    def test_all_factory_skills_are_current(self):
        result = run(ROOT, "check")
        self.assertEqual(result.returncode, 0, result.stdout.decode("utf-8"))
        report = json.loads(result.stdout)
        self.assertTrue(report["ok"])
        self.assertEqual(set(report["skills"]), set(bootstrap.skill_names(ROOT)))
        for name, skill in report["skills"].items():
            with self.subTest(name=name):
                source = ROOT / "skills" / name / "SKILL.md"
                self.assertEqual(skill, {"status": "current", "source_sha256":
                                         hashlib.sha256(source.read_bytes()).hexdigest()})

    def test_audit_projection_has_codex_metadata_and_loads_central_policy(self):
        rendered = run(ROOT, "render", "gaie-audit")
        self.assertEqual(rendered.returncode, 0, rendered.stderr.decode("utf-8"))
        frontmatter, body = rendered.stdout.decode("utf-8").split("\n---\n", 1)
        self.assertEqual([line.split(":", 1)[0] for line in frontmatter.splitlines()[1:]],
                         ["name", "description"])
        self.assertIn("skills/gaie-audit/SKILL.md", body)
        self.assertIn("required grants and\nexecution boundaries", body)
        self.assertIn("`gaie_verifier` only if", body)
        for name in ("gaie-master-router", "gaie-build", "gaie-upgrade"):
            with self.subTest(name=name):
                rendered = run(ROOT, "render", name)
                self.assertEqual(rendered.returncode, 0, rendered.stderr.decode("utf-8"))
                self.assertIn(b"`gaie_specialist` agent", rendered.stdout)
                if name == "gaie-master-router":
                    self.assertIn(b"python3 -B -m scripts.gaie_codex_route --", rendered.stdout)
                else:
                    self.assertIn(b"create or re-check a Codex routing plan", rendered.stdout)


class BootstrapSafetyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = pathlib.Path(temporary.name) / "hub"
        self.root.mkdir()
        names = bootstrap.skill_names(ROOT)
        files = [SCRIPT, bootstrap.PACK]
        for name in names:
            files.extend(path / name / "SKILL.md" for path in (pathlib.Path("skills"), bootstrap.CODEX_SKILLS))
        for file in files:
            target = self.root / file
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / file, target)
        self.source = self.root / "skills/gaie-audit/SKILL.md"
        self.target = self.root / bootstrap.CODEX_SKILLS / "gaie-audit/SKILL.md"

    def check_fails(self):
        result = run(self.root, "check")
        self.assertEqual(result.returncode, 1, result.stdout.decode("utf-8"))
        report = json.loads(result.stdout)
        self.assertFalse(report["ok"])
        return report

    def test_source_changes_invalidate_projection_and_render_keeps_local_edits(self):
        self.source.write_bytes(self.source.read_bytes() + b"\nNew source instruction.\n")
        local = self.target.read_bytes() + b"\nLocal change.\n"
        self.target.write_bytes(local)
        report = self.check_fails()
        self.assertEqual(report["skills"]["gaie-audit"]["status"], "drifted")
        rendered = run(self.root, "render", "gaie-audit")
        self.assertEqual(rendered.returncode, 0)
        self.assertIn(report["skills"]["gaie-audit"]["source_sha256"].encode(), rendered.stdout)
        self.assertEqual(self.target.read_bytes(), local)

    def test_missing_and_unknown_projections_are_reported(self):
        self.target.unlink()
        (self.target.parent.parent / "gaie-unknown").mkdir()
        report = self.check_fails()
        self.assertEqual(report["skills"]["gaie-audit"]["status"], "missing")
        self.assertEqual(report["unexpected"], ["gaie-unknown"])
        self.assertFalse(self.target.exists())

    def test_symlink_is_rejected(self):
        self.target.unlink()
        self.target.symlink_to(self.source)
        report = self.check_fails()
        self.assertIn("non-regular path", report["error"])
        self.assertTrue(self.target.is_symlink())

    def test_render_refuses_names_outside_the_pack(self):
        result = run(self.root, "render", "../../outside")
        self.assertEqual(result.returncode, 1)
        self.assertIn("outside the GAIE factory pack", json.loads(result.stdout)["error"])


if __name__ == "__main__":
    unittest.main()
