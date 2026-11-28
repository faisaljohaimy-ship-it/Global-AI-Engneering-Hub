"""Review fix w2-memory-heal-orch L7: the documented resume commands work from a project checkout.

MEMORY.md section 5 used `python3 -m engineering_os.gaie_memory`, which fails outside the hub checkout.
These tests run every form the section now names, from a project directory outside the hub, with a
private GAIE_HOME: the hub path form, the module form (only from the hub root), and the vendored copy
with and without the engine beside it. Synthetic project; no network.
"""
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOC = ROOT / "docs/specs/gaie-20-layers/MEMORY.md"
PACK = {"engineering_os/gaie_memory.py": "gaie_memory.py", "engineering_os/gaie_router.py": "gaie_router.py",
        "engineering_os/workspace_policy.py": "workspace_policy.py", "governance/policies/gaie-routes.json": "gaie-routes.json",
        "projects/registry.json": "projects.json", "projects/aliases.json": "aliases.json"}
ENGINE = {"engineering_os/memory.py": "memory.py", "engineering_os/orchestration.py": "orchestration.py",
          "scripts/security_scan.py": "security_scan.py"}


class ResumeCommandLineTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="gaie-l7-")
        self.addCleanup(temporary.cleanup)
        self.tmp = pathlib.Path(temporary.name)
        os.chmod(self.tmp, 0o700)
        self.project = self.tmp / "project"
        self.project.mkdir()
        (self.project / "app.py").write_text("def total():\n    return 1\n")
        self.home = self.tmp / "home"
        self.home.mkdir(mode=0o700)
        self.env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
        self.env["GAIE_HOME"] = str(self.home)

    def run_m(self, prefix, *args, cwd=None, env=None):
        run = subprocess.run([*prefix, "--project", "demo", *args], capture_output=True, text=True, timeout=60,
                             cwd=cwd or self.project, env=env or self.env)
        return run.returncode, run.stdout + run.stderr

    def resume(self, prefix):
        code, out = self.run_m(prefix, "task", "--id", "checkout", "--title", "Checkout flow", "--done", "index",
                               "--remaining", "write tests")
        self.assertEqual(code, 0, out)
        code, out = self.run_m(prefix, "next", "--task", "checkout")
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(out)[0]["next"], "write tests")
        code, out = self.run_m(prefix, "brief")
        self.assertEqual(code, 0, out)
        code, out = self.run_m(prefix, "status", "--root", ".")
        self.assertEqual(code, 0, out)

    def vendor(self, files):
        target = self.project / ".engineering/gaie"
        target.mkdir(parents=True, exist_ok=True)
        for source, name in files.items():
            shutil.copyfile(ROOT / source, target / name)
        return [sys.executable, str(target / "gaie_memory.py")]

    def test_the_documented_hub_form_runs_from_a_project_checkout(self):
        documented = re.search(r'^M="python3 (\S+) --project \$P"', DOC.read_text(), re.M)
        self.assertIsNotNone(documented, "MEMORY.md section 5 must define M")
        self.assertEqual(documented.group(1), "/path/to/hub/engineering_os/gaie_memory.py")
        self.resume([sys.executable, str(ROOT / "engineering_os/gaie_memory.py")])

    def test_the_module_form_needs_the_hub_root_or_pythonpath(self):
        code, out = self.run_m([sys.executable, "-m", "engineering_os.gaie_memory"], "brief")
        self.assertNotEqual(code, 0)
        self.assertIn("No module named 'engineering_os'", out)
        code, out = self.run_m([sys.executable, "-m", "engineering_os.gaie_memory"], "brief", cwd=ROOT)
        self.assertNotIn("No module named", out)
        code, out = self.run_m([sys.executable, "-m", "engineering_os.gaie_memory"], "brief",
                               env={**self.env, "PYTHONPATH": str(ROOT)})
        self.assertNotIn("No module named", out)

    def test_the_vendored_copy_needs_the_engine_beside_it(self):
        prefix = self.vendor(PACK)
        code, out = self.run_m(prefix, "brief")
        self.assertIn("this command needs the unified engine", out)
        self.vendor(ENGINE)
        self.resume(prefix)


if __name__ == "__main__":
    unittest.main()
