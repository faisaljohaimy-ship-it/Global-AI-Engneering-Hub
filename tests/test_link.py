import json
import pathlib
import tempfile
import unittest
from unittest import mock

import hublink

LEGACY = {"schema_version": 1, "hub_revision": "0" * 40, "capabilities": [], "budget_additional_sar": 0}


class LinkTests(unittest.TestCase):
    """Registration and verification against the commit under test."""

    @classmethod
    def setUpClass(cls):
        cls.revision = hublink.head()

    def setUp(self):
        # The suite exercises the unmerged commit under test. Production callers do
        # not receive this patch: register/verify still require main ancestry.
        patcher = mock.patch("hublink.on_main", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def project(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return pathlib.Path(directory.name)

    def register(self, target, *capabilities, **options):
        return hublink.register(target, self.revision, capabilities=capabilities, **options)

    def test_tampered_manifest_cannot_claim_and_delete_project_file(self):
        target = self.project()
        readme = target / "README.md"
        readme.write_text("project owned\n")
        (target / ".engineering").mkdir()
        manifest = {
            "schema_version": 1,
            "hub_url": hublink.HUB_URL,
            "hub_revision": self.revision,
            "capabilities": [
                {
                    "id": "skill:hub-capabilities",
                    "files": [
                        {
                            "path": "README.md",
                            "source": "skills/hub-capabilities/SKILL.md",
                            "mode": "copy",
                            "sha256": hublink.sha256(readme.read_bytes()),
                        }
                    ],
                }
            ],
            "budget_additional_sar": 0,
            "production_runtime_dependency": False,
        }
        (target / hublink.MANIFEST).write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "does not match"):
            hublink.register(
                target,
                self.revision,
                remove=("skill:hub-capabilities",),
                apply=True,
            )
        self.assertEqual(readme.read_text(), "project owned\n")

    def test_dry_run_writes_nothing(self):
        target = self.project()
        result = self.register(target, "skill:hub-capabilities")
        self.assertFalse(result["applied"])
        self.assertEqual(result["files"][hublink.MANIFEST], "create")
        self.assertEqual(list(target.iterdir()), [])

    def test_stale_manifest_temporary_file_fails_before_mutation(self):
        target = self.project()
        engineering = target / ".engineering"
        engineering.mkdir()
        temporary = engineering / "capabilities.json.tmp"
        temporary.write_text("occupied", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Temporary manifest path already exists"):
            self.register(target, "skill:hub-capabilities", apply=True)
        self.assertEqual(temporary.read_text(encoding="utf-8"), "occupied")
        self.assertFalse((target / ".claude").exists())
        self.assertFalse((target / ".agents").exists())
        self.assertFalse((engineering / "capabilities.json").exists())

    def test_registered_project_verifies(self):
        target = self.project()
        self.register(target, "skill:digital-motion", "motion:ui-fade-in", "pack:motion-runtime", project_id="sample",
                      repository="https://github.com/example/sample", apply=True)
        css = (target / hublink.MOTION_DIR / "ui-fade-in.css").read_text(encoding="utf-8")
        self.assertIn("@keyframes hub-ui-fade-in", css)
        self.assertTrue((target / ".claude/skills/digital-motion/SKILL.md").is_file())
        self.assertTrue((target / ".agents/skills/digital-motion/SKILL.md").is_file())
        self.assertTrue((target / hublink.MOTION_DIR / "hub-motion.mjs").is_file())
        report = hublink.verify(target)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["level"], "verified")
        self.assertEqual(report["verified_files"], 6)
        self.assertEqual(report["project"], {"id": "sample", "repository": "https://github.com/example/sample"})
        self.assertEqual(self.register(target)["files"][hublink.MANIFEST], "unchanged")

    def test_tampered_file_fails(self):
        target = self.project()
        self.register(target, "skill:hub-capabilities", apply=True)
        (target / ".claude/skills/hub-capabilities/SKILL.md").write_text("edited", encoding="utf-8")
        report = hublink.verify(target)
        self.assertFalse(report["ok"])
        self.assertEqual(report["level"], "broken")
        self.assertIn(".claude/skills/hub-capabilities/SKILL.md", report["checks"][-1]["detail"])

    def test_tampered_manifest_metadata_fails(self):
        target = self.project()
        self.register(target, "skill:hub-capabilities", apply=True)
        path = target / hublink.MANIFEST
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["capabilities"][0]["files"][0]["source"] = "skills/digital-motion/SKILL.md"
        manifest["capabilities"][0]["files"][0]["mode"] = "css"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        report = hublink.verify(target, strict=True)
        self.assertFalse(report["ok"])
        self.assertEqual(report["level"], "broken")

    def test_missing_file_and_edited_manifest_fail(self):
        target = self.project()
        self.register(target, "motion:ui-fade-in", apply=True)
        (target / hublink.MOTION_DIR / "ui-fade-in.css").unlink()
        self.assertFalse(hublink.verify(target)["ok"])
        self.register(target, apply=True)
        self.assertTrue(hublink.verify(target)["ok"])
        path = target / hublink.MANIFEST
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["capabilities"][0]["files"][0]["sha256"] = "f" * 64
        path.write_text(json.dumps(manifest), encoding="utf-8")
        self.assertFalse(hublink.verify(target)["ok"])

    def test_unmanaged_file_is_never_overwritten(self):
        target = self.project()
        skill = target / ".claude/skills/hub-capabilities/SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("project's own text", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Refusing to overwrite"):
            self.register(target, "skill:hub-capabilities", apply=True)
        self.assertEqual(skill.read_text(encoding="utf-8"), "project's own text")
        self.assertFalse((target / hublink.MANIFEST).exists())

    def test_earlier_onboarding_is_adopted_not_replaced(self):
        target = self.project()
        content = hublink.read(self.revision, "skills/hub-capabilities/SKILL.md")
        for root in hublink.SKILL_ROOTS:
            path = target / root / "hub-capabilities/SKILL.md"
            path.parent.mkdir(parents=True)
            path.write_bytes(content)
        manifest = dict(LEGACY, hub_revision=self.revision, hub_url=hublink.HUB_URL, discovery_skill="hub-capabilities",
                        production_runtime_dependency=False)
        (target / ".engineering").mkdir()
        (target / hublink.MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
        before = hublink.verify(target)
        self.assertTrue(before["ok"])
        self.assertEqual(before["level"], "declared-only")
        self.assertTrue(any("not declared" in warning for warning in before["warnings"]))
        self.assertFalse(hublink.verify(target, strict=True)["ok"])
        result = self.register(target, "skill:hub-capabilities", apply=True)
        self.assertEqual(result["files"][".claude/skills/hub-capabilities/SKILL.md"], "unchanged")
        saved = json.loads((target / hublink.MANIFEST).read_text(encoding="utf-8"))
        self.assertEqual(saved["discovery_skill"], "hub-capabilities")
        after = hublink.verify(target)
        self.assertEqual((after["level"], after["verified_files"]), ("verified", 2))

    def test_removing_a_capability_deletes_only_unedited_files(self):
        target = self.project()
        self.register(target, "skill:hub-capabilities", "skill:digital-motion", "motion:ui-fade-in", apply=True)
        edited = target / ".agents/skills/digital-motion/SKILL.md"
        edited.write_text("local note", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "not registered"):
            self.register(target, remove=["skill:never-installed"], apply=True)
        result = self.register(target, remove=["skill:digital-motion"], apply=True)
        self.assertEqual(result["files"][".claude/skills/digital-motion/SKILL.md"], "delete")
        self.assertTrue(result["files"][".agents/skills/digital-motion/SKILL.md"].startswith("kept"))
        self.assertFalse((target / ".claude/skills/digital-motion").exists())
        self.assertEqual(edited.read_text(encoding="utf-8"), "local note")
        self.assertEqual(result["capabilities"], ["skill:hub-capabilities", "motion:ui-fade-in"])
        self.assertTrue((target / ".claude/skills/hub-capabilities/SKILL.md").is_file())
        report = hublink.verify(target)
        self.assertEqual((report["ok"], report["verified_files"]), (True, 4))

    def test_reviewed_pack_installs_companion_files(self):
        target = self.project()
        result = self.register(target, "pack:motion-runtime", apply=True)
        self.assertEqual(result["files"][".engineering/vendor/hub-motion/hub-motion.mjs"], "create")
        self.assertTrue((target / ".engineering/vendor/hub-motion/hub-motion-base.css").is_file())
        self.assertEqual(hublink.verify(target)["verified_files"], 2)

    def test_unsafe_requests_are_refused(self):
        target = self.project()
        for capability in ("skill:../secrets", "skill:no-such-skill", "motion:no-such-motion", "pack:no-such-pack", "tool:x"):
            with self.assertRaises(ValueError):
                self.register(target, capability, apply=True)
        with self.assertRaises(ValueError):
            hublink.register(target, "main", capabilities=["skill:hub-capabilities"])
        with self.assertRaises(ValueError):
            hublink.register(target, "a" * 40, capabilities=["skill:hub-capabilities"])
        for path in ("../outside", "/etc/passwd", ".git/config", "a/../../b"):
            with self.assertRaises(ValueError):
                hublink._destination(target, path)

    def test_symlinks_are_refused(self):
        target, elsewhere = self.project(), self.project()
        (target / ".engineering").symlink_to(elsewhere, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.register(target, "skill:hub-capabilities", apply=True)
        self.assertFalse(hublink.verify(target)["ok"])
        self.assertEqual(list(elsewhere.iterdir()), [])

    def test_manifest_rules(self):
        good = dict(LEGACY, hub_revision=self.revision)
        self.assertEqual(hublink.validate_manifest(good), [])
        for change in ({"schema_version": 2}, {"hub_revision": "main"}, {"budget_additional_sar": 100},
                       {"budget_additional_sar": False}, {"production_runtime_dependency": True},
                       {"hub_url": "https://example.com/other"}, {"capabilities": "all"},
                       {"capabilities": [{"id": "skill:x", "files": []}]}, {"project": {"id": "Not A Slug"}}):
            self.assertTrue(hublink.validate_manifest(dict(good, **change)), change)

    def test_duplicate_and_nonfinite_manifest_json_are_rejected(self):
        payloads = (
            b'{"schema_version":1,"schema_version":1}',
            b'{"value":NaN}',
            b'{"value":Infinity}',
        )
        for payload in payloads:
            with self.assertRaises(ValueError):
                hublink.load_json_bytes(payload)

    def test_unknown_pin_and_missing_manifest_fail(self):
        target = self.project()
        self.assertFalse(hublink.verify(target)["ok"])
        (target / ".engineering").mkdir()
        (target / hublink.MANIFEST).write_text(json.dumps(dict(LEGACY, hub_revision="a" * 40)), encoding="utf-8")
        report = hublink.verify(target)
        self.assertFalse(report["ok"])
        self.assertEqual(report["checks"][-1]["check"], "pinned-revision-in-hub")

    def test_public_registry(self):
        rows = hublink.projects()
        self.assertTrue(all(row["visibility"] == "public" for row in rows))
        private = dict(rows[0], id="private-example", visibility="private")
        with self.assertRaisesRegex(ValueError, "Only public"):
            hublink.validate_projects(rows + [private])
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            hublink.validate_projects(rows + [rows[0]])


if __name__ == "__main__":
    unittest.main()
