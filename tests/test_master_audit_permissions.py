"""Exercise the real CLI audit grant without a provider, model or project runner."""
import json
import os
import pathlib
import stat
import subprocess
import sys
import tempfile
import unittest

from engineering_os import control, gaie_inventory

ROOT = pathlib.Path(__file__).resolve().parents[1]


class MasterAuditPermissionsTests(unittest.TestCase):
    def test_bilingual_audit_grants_can_read_and_cannot_write(self):
        with tempfile.TemporaryDirectory() as directory:
            base = pathlib.Path(directory)
            project = base / "product"
            project.mkdir()
            (project / "module.py").write_text("VALUE = 3\n", encoding="utf-8")
            state = base / "state"
            env = {**os.environ, "GAIE_HOME": str(base / "gaie"), "PYTHONPYCACHEPREFIX": str(base / "caches")}
            env.pop("PYTHONDONTWRITEBYTECODE", None)

            def cli(*args, expected=0):
                result = subprocess.run(
                    [sys.executable, str(ROOT / "hub.py"), *args], cwd=project, env=env,
                    text=True, capture_output=True, timeout=30,
                )
                self.assertEqual(result.returncode, expected, result.stderr or result.stdout)
                return json.loads(result.stdout)

            for request in ("Audit Sadeed", "دقّق سديد"):
                with self.subTest(request=request):
                    plan = cli("route", request)
                    self.assertTrue(plan["read_only"])
                    self.assertFalse(plan["write_allowed"])
                    self.assertEqual(plan["grant_template"]["max_side_effect"], "none")
                    self.assertEqual(set(plan["grant_template"]["engines"]), {"master-audit"})
                    grant = base / "trusted-grant.json"
                    grant.write_text(json.dumps({
                        **plan["grant_template"], "grant_id": "g-fixture-audit",
                        "paths": [str(project)], "expires_at": "2099-01-01T00:00:00Z",
                    }), encoding="utf-8")
                    options = ("--grant", str(grant), "--state", str(state), "--task", "audit-fixture")
                    reply = cli("invoke", "master-audit", "inventory",
                                "--payload", json.dumps({"target": str(project)}), *options)
                    self.assertEqual(reply["receipt"]["side_effect"], "none")
                    self.assertEqual(reply["result"]["files_scanned"], 1)
                    cli("invoke", "master-audit", "inventory",
                        "--payload", json.dumps({"target": str(base)}), *options, expected=3)
                    cli("invoke", "memory", "put", "--payload", "{}", *options, expected=3)
                    cli("invoke", "quality-assurance", "run-tests",
                        "--payload", '{"modules":["tests.test_hub"]}', *options, expected=3)

            self.assertEqual(sorted(item.name for item in project.iterdir()), ["module.py"])
            self.assertEqual((project / "module.py").read_text(encoding="utf-8"), "VALUE = 3\n")
            self.assertFalse((state / "memory").exists())
            self.assertFalse((base / "gaie").exists())
            self.assertFalse((base / "caches" / ROOT.relative_to(ROOT.anchor)).exists())

    def test_audit_ignores_manifest_aliases_and_rejects_an_aliased_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            base = pathlib.Path(directory)
            project = base / "product"
            project.mkdir()
            outside = base / "outside.json"
            outside.write_text('{"identity_verified":true,"dependencies":{"next":"15.0.0"}}', encoding="utf-8")
            os.link(outside, project / "package.json")
            (project / ".github").symlink_to(base)
            self.assertEqual(gaie_inventory.inventory(project)["stack"], [])
            (project / ".engineering").mkdir()
            contract = project / ".engineering/project.json"
            contract.symlink_to(outside)
            with self.assertRaisesRegex(ValueError, "symlink project identity"):
                control.health(project)
            contract.unlink()
            os.mkfifo(contract)
            with self.assertRaisesRegex(ValueError, "regular files"):
                control.health(project)
            self.assertTrue(stat.S_ISFIFO(contract.stat().st_mode))

    def test_workspace_runner_requires_private_assignments_and_an_enrolled_agent(self):
        with tempfile.TemporaryDirectory() as directory:
            base = pathlib.Path(directory)
            workspace = base / "work"
            workspace.mkdir(mode=0o700)
            config = base / "assignments.json"
            config.write_text(json.dumps({"assigned": {"path": str(workspace), "intent": "build"}}))
            command = [
                sys.executable, str(ROOT / "hub.py"), "workspace-run", "--assignments", str(config),
                "--timeout", "5", "--agent", "unassigned", "--",
                "python3", "-c", "from pathlib import Path; Path('unexpected.txt').touch()",
            ]
            for mode, reason in ((0o644, "must be private"), (0o600, "no assigned write workspace")):
                with self.subTest(mode=mode):
                    config.chmod(mode)
                    result = subprocess.run(command, text=True, capture_output=True, timeout=15)
                    self.assertEqual(result.returncode, 3, result.stderr or result.stdout)
                    self.assertIn(reason, json.loads(result.stdout)["reason"])
                    self.assertEqual(list(workspace.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
