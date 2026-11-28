"""Codex installation and optional native, no-model skill discovery."""
import json
import os
import pathlib
import selectors
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

from engineering_os import master_docs
from scripts import gaie_bootstrap, gaie_codex_portable


ROOT = pathlib.Path(__file__).resolve().parents[2]
INSTALL = ROOT / "scripts/gaie_codex_portable.py"
SKILLS = set(gaie_bootstrap.pack()["skills"])
CODEX = shutil.which("codex")


class CodexPortableTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="gaie-codex-test-")
        self.addCleanup(temporary.cleanup)
        self.root = pathlib.Path(temporary.name)
        self.home, self.project = self.root / "home", self.root / "project"
        self.home.mkdir(mode=0o700)
        self.project.mkdir(mode=0o700)
        self.env = {
            "PATH": os.environ["PATH"], "LANG": "C.UTF-8", "HOME": str(self.home),
            "CODEX_HOME": str(self.root / "codex"),
            "OPENAI_BASE_URL": "http://127.0.0.1:1/v1",
            "HTTP_PROXY": "http://127.0.0.1:1", "HTTPS_PROXY": "http://127.0.0.1:1",
            "ALL_PROXY": "http://127.0.0.1:1",
        }

    def cli(self, command, *, scope="project", write=False, target=None, expected=0):
        options = ["--scope", scope]
        if scope == "project":
            options.extend(("--target", str(target or self.project)))
        if write:
            options.append("--apply")
        result = subprocess.run([sys.executable, "-B", str(INSTALL), command, *options],
                                cwd=self.project, env=self.env, text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, expected, result.stderr or result.stdout)
        return json.loads(result.stdout)

    def test_project_install_verifies_and_rolls_back_without_owning_foreign_files(self):
        root = self.project / ".agents"
        self.assertEqual(set(self.cli("install")["files"].values()), {"would create"})
        self.assertFalse(root.exists())
        foreign = root / "skills/gaie-audit/REFERENCE.md"
        foreign.parent.mkdir(parents=True)
        foreign.write_bytes((ROOT / "skills/gaie-audit/SKILL.md").read_bytes())
        self.assertEqual(set(self.cli("install", write=True)["files"].values()), {"created", "unchanged"})
        self.assertEqual(set(self.cli("verify")["files"].values()), {"current"})
        self.assertEqual(set(self.cli("install", write=True)["files"].values()), {"unchanged"})
        manifest = json.loads((root / gaie_codex_portable.MANIFEST).read_bytes())
        self.assertNotIn(foreign.relative_to(root).as_posix(), manifest["files"])
        self.assertEqual(set(self.cli("uninstall")["files"].values()), {"would remove"})
        self.assertEqual(set(self.cli("uninstall", write=True)["files"].values()), {"removed"})
        self.assertTrue(foreign.is_file())
        self.assertFalse((root / gaie_codex_portable.MANIFEST).exists())

    def test_unowned_engine_collision_prevents_any_discoverable_install(self):
        root = self.project / ".agents"
        engine = root / gaie_codex_portable.ENGINE / "gaie_router.py"
        engine.parent.mkdir(parents=True)
        engine.write_text("# unrelated file\n")
        result = self.cli("install", write=True, expected=1)
        self.assertEqual(result["files"][engine.relative_to(root).as_posix()], "preserved: unowned or locally modified")
        self.assertEqual(list(root.rglob("SKILL.md")), [])
        self.assertEqual(engine.read_text(), "# unrelated file\n")
        self.assertFalse((root / gaie_codex_portable.MANIFEST).exists())

    def test_installed_drift_survives_and_linked_or_shared_directories_are_refused(self):
        root = self.project / ".agents"
        outside = self.root / "outside"
        outside.mkdir()
        root.mkdir()
        skills = root / "skills"
        skills.symlink_to(outside, target_is_directory=True)
        self.assertEqual(self.cli("install", write=True, expected=1)["status"], "error")
        self.assertEqual(list(outside.iterdir()), [])
        skills.unlink()
        skills.mkdir(mode=0o777)
        skills.chmod(0o777)
        self.assertEqual(self.cli("install", write=True, expected=1)["status"], "error")
        skills.chmod(0o755)
        self.cli("install", write=True)
        edited = skills / "gaie-audit/SKILL.md"
        edited.write_text("local edit")
        self.assertEqual(self.cli("verify", expected=1)["files"][edited.relative_to(root).as_posix()], "modified")
        result = self.cli("uninstall", write=True, expected=1)
        self.assertEqual(result["files"][edited.relative_to(root).as_posix()], "preserved: locally modified")
        self.assertEqual(edited.read_text(), "local edit")

    def test_portable_loader_rejects_drift_and_wrappers_bind_canonical_skills(self):
        self.cli("install", write=True)
        root = self.project / ".agents"
        engine = root / gaie_codex_portable.ENGINE
        portable = subprocess.run([sys.executable, "-B", str(engine / "master_docs.py"), "show", "MASTER_BUILD"],
                                  cwd=self.project, env=self.env, capture_output=True, timeout=10)
        document = master_docs.load_manifest(ROOT)["documents"]["MASTER_BUILD"]
        self.assertEqual(portable.returncode, 0, portable.stderr.decode())
        self.assertEqual(portable.stdout, (ROOT / document["path"]).read_bytes())
        (root / document["installed_as"]["claude"]).write_bytes(b"local edits\n")
        refused = subprocess.run([sys.executable, "-B", str(engine / "master_docs.py"), "show", "MASTER_BUILD"],
                                 cwd=self.project, env=self.env, capture_output=True, timeout=10)
        self.assertNotEqual(refused.returncode, 0)
        projected = gaie_codex_portable.plan()
        wrappers = {relative: content for relative, content in projected.items() if relative.endswith("/SKILL.md")}
        self.assertEqual(set(wrappers), {f"skills/{name}/SKILL.md" for name in SKILLS})
        for relative, wrapper in wrappers.items():
            self.assertIn(gaie_bootstrap.sha((ROOT / relative).read_bytes()).encode(), wrapper)
            reference = relative.replace("/SKILL.md", "/REFERENCE.md")
            self.assertEqual(projected[reference], (ROOT / relative).read_bytes())
        self.assertIn(b"engine/gaie_router.py", wrappers["skills/gaie-master-router/SKILL.md"])
        self.assertIn(b"independently enforced read-only", wrappers["skills/gaie-audit/SKILL.md"])

    def test_hub_and_other_hub_checkouts_are_refused(self):
        for marker in ("catalog/packs.json", "engineering_os/master_docs.py", "scripts/gaie_codex_bootstrap.py"):
            path = self.project / marker
            path.parent.mkdir(exist_ok=True, parents=True)
            path.touch()
        for target in (ROOT, self.project):
            with self.subTest(target=target):
                result = self.cli("install", write=True, target=target, expected=1)
                self.assertIn("gaie_codex_bootstrap.py check", result["error"])
        self.assertFalse((self.project / ".agents").exists())

    @unittest.skipUnless(CODEX, "Codex CLI is unavailable for native no-model discovery")
    def test_fresh_native_sessions_discover_project_and_user_skills(self):
        for scope, native_scope in (("project", "repo"), ("user", "user")):
            with self.subTest(scope=scope):
                self.cli("install", scope=scope, write=True)
                codex_home = self.root / f"codex-{scope}"
                codex_home.mkdir(mode=0o700)
                env = {**self.env, "CODEX_HOME": str(codex_home)}
                skills = self.discover_native_skills(env, self.project)
                found = {entry["name"]: entry for entry in skills if entry["name"] in SKILLS}
                self.assertEqual(set(found), SKILLS)
                self.assertTrue(all(entry["enabled"] and entry["scope"] == native_scope for entry in found.values()))
                self.cli("uninstall", scope=scope, write=True)

    def discover_native_skills(self, env, project):
        # This protocol sends no thread, turn, login or model request.
        with subprocess.Popen([CODEX, "app-server", "--listen", "stdio://"], cwd=project, env=env,
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as process:
            entries = [
                {"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "gaie-fixture", "version": "1.0.0"}}},
                {"method": "initialized"},
                {"id": 2, "method": "skills/list", "params": {"cwds": [str(project)], "forceReload": True}},
            ]
            try:
                process.stdin.write(b"".join(json.dumps(entry).encode() + b"\n" for entry in entries))
                process.stdin.flush()
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout, selectors.EVENT_READ)
                    deadline, pending = time.monotonic() + 15, b""
                    while time.monotonic() < deadline:
                        if not selector.select(max(0, deadline - time.monotonic())):
                            break
                        chunk = os.read(process.stdout.fileno(), 65536)
                        if not chunk:
                            break
                        lines = (pending + chunk).split(b"\n")
                        pending = lines.pop()
                        for line in lines:
                            entry = json.loads(line)
                            if entry.get("id") == 2:
                                self.assertNotIn("error", entry, entry)
                                return entry["result"]["data"][0]["skills"]
                self.fail("fresh Codex app-server did not return skills/list")
            finally:
                process.stdin.close()
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()


if __name__ == "__main__":
    unittest.main()
