"""Memory isolation, inventory, bootstrap safety, pack registration and skill integrity.

Files, subprocesses and registration are real. Only unmerged main ancestry is mocked,
as in the existing pack tests. No Claude Code host or model is invoked here.
"""
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import hublink
from engineering_os import gaie_inventory, gaie_memory, gaie_router

ROOT = pathlib.Path(__file__).resolve().parents[1]
SKILLS = ("gaie-master-router", "gaie-build", "gaie-upgrade", "gaie-audit", "gaie-cinematic", "gaie-release")
sys.path.insert(0, str(ROOT / "scripts"))
import gaie_bootstrap  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.tmp = pathlib.Path(temporary.name)
        self.env = {"GAIE_HOME": str(self.tmp / "gaie")}


class MemoryTests(Base):
    def memory(self, project="alpha"):
        return gaie_memory.Memory(project, self.env)

    def test_store_search_dedupe_and_private_modes(self):
        memory = self.memory()
        first = memory.add("decision", "اعتماد modular monolith", "قرار معماري مبني على حجم الفريق", ["Architecture"])
        self.assertEqual(first["status"], "stored")
        self.assertEqual(memory.add("decision", "اعتماد modular monolith", "قرار معماري مبني على حجم الفريق", ["architecture"])["status"], "duplicate")
        memory.add("failure", "Slow dashboard query", "Missing index on incidents.created_at caused 4s load")
        hits = memory.search("معماري")
        self.assertEqual([row["id"] for row in hits], [first["id"]])
        self.assertEqual(memory.search("index incidents")[0]["kind"], "failure")
        self.assertEqual(len(memory.search(kind="decision")), 1)
        self.assertEqual(len(memory.search(tag="architecture")), 1)
        self.assertEqual(memory.path.stat().st_mode & 0o777, 0o600)

    def test_projects_are_isolated(self):
        self.memory("alpha").add("lesson", "alpha only", "private to alpha")
        self.assertEqual(self.memory("beta").search("alpha"), [])
        self.assertEqual(self.memory("beta").search(), [])
        for bad in ("../alpha", "Alpha", "", "a/b"):
            with self.assertRaises(gaie_memory.MemoryError_):
                self.memory(bad)

    def test_credentials_are_refused(self):
        memory = self.memory()
        samples = ("ghp_" + "a" * 36, "sk-ant-" + "b" * 30, "password: hunter2hunter2", "postgres://user:" + "pw12345678" + "@db.example/x",
                   "Bearer " + "c" * 24, "AKIA" + "A" * 16, "-----BEGIN " + "PRIVATE KEY-----")
        for sample in samples:
            with self.assertRaises(gaie_memory.MemoryError_):
                memory.add("lesson", "note", f"value {sample}")
            with self.assertRaises(gaie_memory.MemoryError_):
                memory.add("lesson", sample[:150], "body")
        self.assertEqual(memory.entries(), [])

    def test_links_form_a_project_local_graph(self):
        memory = self.memory()
        cause = memory.add("root-cause", "N+1 query", "Loop issued one query per row")["id"]
        fix = memory.add("repair", "Batch the query", "Single joined query", links=[{"relation": "fixes", "target": cause}],
                         evidence=[{"kind": "unit-tests", "sha256": "a" * 64}])["id"]
        graph = memory.related(cause)
        self.assertEqual(graph["incoming"][0]["from"]["id"], fix)
        with self.assertRaises(gaie_memory.MemoryError_):
            memory.add("repair", "x", "y", links=[{"relation": "fixes", "target": "f" * 64}])
        with self.assertRaises(gaie_memory.MemoryError_):
            memory.add("repair", "x", "y", evidence=[{"kind": "log", "sha256": "raw output"}])
        self.assertNotIn("project", memory.promote(fix))

    def test_removal_reordering_and_more_credential_shapes(self):
        memory = self.memory()
        for index in range(3):
            memory.add("lesson", f"entry {index}", f"body {index}")
        lines = memory.path.read_text().splitlines()
        for damaged in ([lines[0], lines[2]], [lines[1], lines[0], lines[2]], lines[1:], ["[1]"], ['"x"']):
            memory.path.write_text("\n".join(damaged) + "\n")
            with self.assertRaises(gaie_memory.MemoryError_):
                memory.entries()
        memory.path.write_text("\n".join(lines) + "\n")
        self.assertEqual(len(memory.entries()), 3)
        key = "pass" + "word"
        for sample in ('{"%s": "hunter2hunter2xyz"}' % key, "the %s is hunter2hunter2" % key, "%s\uff1ahunter2hunter2" % key,
                       "aws_secret_access_key = wJalrEXAMPLEKEYvalue", "SUPABASE_SERVICE_ROLE_KEY=abcdefghijklmnop",
                       "postgres://admin:" + "pa/ssword99" + "@db.example/x", "Authorization: Basic " + "QWxhZGRpbjpvcGVu",
                       "glpat-" + "a" * 20, "gh" + "p_" + "a" * 10 + "\n" + "a" * 26, "text\u202egnp.exe"):
            with self.assertRaises(gaie_memory.MemoryError_, msg=sample):
                memory.add("lesson", "note", f"value {sample}")
        self.assertEqual(len(memory.entries()), 3)
        self.assertEqual(memory.root.parent.stat().st_mode & 0o777, 0o700)

    def test_tampering_and_symlinks_are_detected(self):
        memory = self.memory()
        memory.add("lesson", "one", "two")
        memory.path.write_text(memory.path.read_text().replace("two", "three"))
        with self.assertRaises(gaie_memory.MemoryError_):
            memory.entries()
        other = self.memory("linked")
        other.root.parent.mkdir(parents=True, exist_ok=True)
        other.root.symlink_to(memory.root, target_is_directory=True)
        with self.assertRaises(gaie_memory.MemoryError_):
            other.entries()


class InventoryTests(Base):
    def test_classifies_surfaces_and_reports_findings_without_reading_secrets(self):
        project = self.tmp / "app"
        files = {"package.json": json.dumps({"dependencies": {"next": "15.0.0", "three": "0.170.0", "@supabase/supabase-js": "2.0.0"},
                                             "scripts": {"build": "next build"}}),
                 "src/app/page.tsx": "x", "src/components/Card.tsx": "x", "src/api/incidents.ts": "x",
                 "supabase/migrations/001.sql": "x", "src/agents/sadeed.ts": "x", "src/locales/ar.json": "{}",
                 "public/intro.mp4": "v" * 64, "public/logo.png": "i", "public/voice.mp3": "a",
                 ".env": "SECRET_VALUE=do-not-print", "node_modules/pkg/index.js": "ignored"}
        for name, data in files.items():
            path = project / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(data)
        (project / "link").symlink_to(self.tmp)
        result = gaie_inventory.inventory(project, large_bytes=32)
        self.assertEqual(result["files_scanned"], len(files) - 1)
        for surface in ("pages-routes", "components", "api", "database", "ai-agents", "i18n"):
            self.assertGreaterEqual(result["surfaces"][surface], 1, surface)
        self.assertEqual(result["stack"], ["Next.js", "Supabase", "Three.js"])
        self.assertEqual(result["large_media"][0]["path"], "public/intro.mp4")
        self.assertEqual(result["signals"]["env_files_present"], [".env"])
        self.assertNotIn("do-not-print", json.dumps(result))
        severities = [row["severity"] for row in result["findings"]]
        self.assertIn("high", severities)
        components = {row["component"] for row in result["coverage_matrix"]}
        self.assertLessEqual({"pages-routes", "api", "database", "videos", "audio", "dependencies", "tests"}, components)
        for row in result["coverage_matrix"]:
            self.assertEqual(set(row), {"component", "current_state", "problem", "required_upgrade", "owner",
                                        "acceptance_criterion", "test", "evidence", "status"})
            self.assertIsNone(row["evidence"])

    def test_hostile_checkout_content_neither_hangs_nor_crashes(self):
        project = self.tmp / "hostile"
        project.mkdir()
        os.mkfifo(project / "package.json")
        (project / "sub").mkdir()
        (project / "sub/package.json").write_text("[1]")
        (project / "requirements.txt").write_bytes(b"flask==3.0\n\xff\xfe broken\n")
        (project / "pyproject.toml").write_text('next = 1\nai = "x"\n')
        (project / "Dockerfile").write_text("FROM scratch")
        result = gaie_inventory.inventory(project)
        self.assertEqual(result["stack"], ["Flask"])
        self.assertFalse(result["signals"]["has_ci"])
        json.dumps(result)

    def test_requires_a_directory(self):
        with self.assertRaises(gaie_inventory.InventoryError):
            gaie_inventory.inventory(self.tmp / "missing")


class BootstrapTests(Base):
    def test_install_is_dry_run_first_idempotent_and_preserves_foreign_files(self):
        claude = self.tmp / "project/.claude"
        foreign = claude / "skills/my-own/SKILL.md"
        clash = claude / "skills/gaie-build/SKILL.md"
        for path, text in ((foreign, "mine"), (clash, "owner's own file"), (claude / "settings.json", "{}")):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        dry = gaie_bootstrap.install(claude, False, apply=False)
        self.assertFalse((claude / "skills/gaie-upgrade").exists())
        self.assertEqual(dry["skills/gaie-upgrade/SKILL.md"], "would create")
        result = gaie_bootstrap.install(claude, False, apply=True)
        self.assertTrue(result["skills/gaie-build/SKILL.md"].startswith("preserved"))
        self.assertEqual((clash.read_text(), foreign.read_text(), (claude / "settings.json").read_text()), ("owner's own file", "mine", "{}"))
        self.assertEqual((claude / "skills/gaie-upgrade/MASTER_UPGRADE.md").read_bytes(), (ROOT / "prompts/MASTER_UPGRADE.md").read_bytes())
        again = gaie_bootstrap.install(claude, False, apply=True)
        self.assertEqual({v for k, v in again.items() if k != "skills/gaie-build/SKILL.md"}, {"unchanged"})
        self.assertEqual(gaie_bootstrap.verify(claude, False)["skills/gaie-build/SKILL.md"], "modified")

    def test_installed_engine_routes_from_the_skill_directory(self):
        claude = self.tmp / "home/.claude"
        gaie_bootstrap.install(claude, False, apply=True)
        self.assertEqual(set(gaie_bootstrap.verify(claude, False).values()), {"current"})
        engine = claude / "skills/gaie-master-router/engine"
        run = subprocess.run([sys.executable, str(engine / "gaie_router.py"), "route", "طور فيديوهات سديد"],
                             capture_output=True, text=True, cwd=self.tmp, env={**os.environ, **self.env})
        plan = json.loads(run.stdout)
        self.assertEqual((run.returncode, plan["engine"], plan["targets"][0]["id"]), (0, "CINEMATIC", "biz-pulse-ar"))
        self.assertTrue(all(row["available"] for row in plan["skills"] if row["skill"].startswith("gaie-")))
        run = subprocess.run([sys.executable, str(engine / "gaie_memory.py"), "--project", "demo", "add", "--kind", "lesson",
                              "--title", "t", "--body", "b"], capture_output=True, text=True, cwd=self.tmp, env={**os.environ, **self.env})
        self.assertEqual(json.loads(run.stdout)["status"], "stored")

    def test_update_and_uninstall_touch_only_unmodified_installed_files(self):
        claude = self.tmp / "p/.claude"
        gaie_bootstrap.install(claude, False, apply=True)
        skill = claude / "skills/gaie-audit/SKILL.md"
        manifest = json.loads((claude / "gaie-install.json").read_text())
        skill.write_text("older reviewed version")
        manifest["files"]["skills/gaie-audit/SKILL.md"] = hashlib.sha256(b"older reviewed version").hexdigest()
        (claude / "gaie-install.json").write_text(json.dumps(manifest))
        self.assertEqual(gaie_bootstrap.verify(claude, False)["skills/gaie-audit/SKILL.md"], "outdated")
        self.assertEqual(gaie_bootstrap.install(claude, False, apply=True)["skills/gaie-audit/SKILL.md"], "updated")
        edited = claude / "skills/gaie-release/SKILL.md"
        edited.write_text("owner edit")
        (claude / "skills/keep/SKILL.md").parent.mkdir()
        (claude / "skills/keep/SKILL.md").write_text("keep")
        self.assertEqual(gaie_bootstrap.uninstall(claude, apply=False)["skills/gaie-audit/SKILL.md"], "would remove")
        self.assertTrue(skill.is_file())
        result = gaie_bootstrap.uninstall(claude, apply=True)
        self.assertTrue(result["skills/gaie-release/SKILL.md"].startswith("preserved"))
        self.assertEqual(edited.read_text(), "owner edit")
        self.assertFalse(skill.exists())
        self.assertFalse((claude / "skills/gaie-master-router").exists())
        self.assertEqual((claude / "skills/keep/SKILL.md").read_text(), "keep")

    def test_poisoned_manifest_cannot_reach_outside_or_claim_other_files(self):
        claude = self.tmp / "v/.claude"
        claude.mkdir(parents=True)
        outside = self.tmp / "outside/pkg/__init__.py"
        outside.parent.mkdir(parents=True)
        outside.write_bytes(b"")
        empty = hashlib.sha256(b"").hexdigest()
        for key in ("../../outside/pkg/__init__.py", str(outside), "skills/my-own/SKILL.md", "settings.json"):
            (claude / "gaie-install.json").write_text(json.dumps({"schema_version": 1, "files": {key: empty}}))
            for action in (lambda: gaie_bootstrap.uninstall(claude, apply=True), lambda: gaie_bootstrap.install(claude, False, apply=True)):
                with self.assertRaises(ValueError, msg=key):
                    action()
        self.assertTrue(outside.is_file())
        (claude / "gaie-install.json").write_text("[]")
        with self.assertRaises(ValueError):
            gaie_bootstrap.install(claude, False, apply=True)

    def test_symlinked_temporary_files_are_not_written_through(self):
        victim = self.tmp / "victim.txt"
        victim.write_text("precious")
        for name in ("skills/gaie-build/SKILL.md.gaie-tmp", "gaie-install.json.gaie-tmp"):
            claude = self.tmp / name.replace("/", "_") / ".claude"
            (claude / name).parent.mkdir(parents=True)
            (claude / name).symlink_to(victim)
            with self.assertRaises(ValueError):
                gaie_bootstrap.install(claude, False, apply=True)
            self.assertEqual(victim.read_text(), "precious")

    def test_identical_preexisting_file_and_directories_survive_uninstall(self):
        claude = self.tmp / "w/.claude"
        mine = claude / "skills/gaie-audit/SKILL.md"
        mine.parent.mkdir(parents=True)
        (claude / "agents").mkdir()
        mine.write_bytes((ROOT / "skills/gaie-audit/SKILL.md").read_bytes())
        result = gaie_bootstrap.install(claude, False, apply=True)
        self.assertTrue(result["skills/gaie-audit/SKILL.md"].startswith("unchanged: identical"))
        gaie_bootstrap.uninstall(claude, apply=True)
        self.assertTrue(mine.is_file())
        self.assertTrue((claude / "skills").is_dir() and (claude / "agents").is_dir())
        self.assertFalse((claude / "skills/gaie-build").exists())

    def test_symlinks_are_refused(self):
        real = self.tmp / "real"
        real.mkdir()
        claude = self.tmp / "q/.claude"
        (claude / "skills").mkdir(parents=True)
        (claude / "skills/gaie-build").symlink_to(real, target_is_directory=True)
        with self.assertRaises(ValueError):
            gaie_bootstrap.install(claude, False, apply=True)
        self.assertEqual(list(real.iterdir()), [])


class IntegrityTests(Base):
    def test_hub_checkout_install_matches_sources(self):
        self.assertEqual(set(gaie_bootstrap.verify(ROOT / ".claude", True).values()), {"current"},
                         "run: python3 scripts/gaie_bootstrap.py install --scope project --target . --apply")

    def test_skill_frontmatter_and_references(self):
        for name in SKILLS:
            text = (ROOT / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
            self.assertTrue(text.startswith("---\n"), name)
            front = dict(line.split(": ", 1) for line in text.split("---\n")[1].strip().splitlines())
            self.assertEqual(front["name"], name)
            self.assertLessEqual(len(front["description"]), 1536)
            self.assertRegex(front["description"], "[ء-ي]", f"{name} needs Arabic trigger phrases")

    def test_audit_host_artifacts_bind_the_read_only_verifier(self):
        skill = (ROOT / "skills/gaie-audit/SKILL.md").read_text(encoding="utf-8")
        agent = (ROOT / "agents/gaie-verifier.md").read_text(encoding="utf-8")
        skill_config = dict(line.split(": ", 1) for line in skill.split("---\n")[1].strip().splitlines())
        agent_config = dict(line.split(": ", 1) for line in agent.split("---\n")[1].strip().splitlines())
        self.assertEqual(skill_config["context"], "fork")
        self.assertEqual(skill_config["agent"], agent_config["name"])
        self.assertEqual(skill_config["background"], "false")
        self.assertEqual(skill_config["allowed-tools"].split(", "), ["Read", "Grep", "Glob"])
        self.assertEqual(agent_config["tools"].split(", "), ["Read", "Grep", "Glob"])
        self.assertEqual(set(agent_config), {"name", "description", "tools", "disallowedTools"})
        self.assertTrue({"Bash", "Write", "Edit", "Agent", "Skill", "mcp__*"} <=
                        set(agent_config["disallowedTools"].split(", ")))
        self.assertNotIn("!`", skill)

        pack = json.loads((ROOT / "catalog/packs.json").read_text(encoding="utf-8"))["packs"]["gaie-factory"]
        self.assertEqual(pack["files"]["agents/gaie-verifier.md"], ".claude/agents/gaie-verifier.md")
        self.assertEqual(pack["files"]["engineering_os/workspace_policy.py"], ".engineering/gaie/workspace_policy.py")

    def test_plugin_manifests_stay_inside_the_repository(self):
        plugin = json.loads((ROOT / ".claude-plugin/plugin.json").read_text())
        market = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text())
        self.assertEqual((plugin["name"], market["plugins"][0]["name"], market["plugins"][0]["source"]), ("gaie", "gaie", "./"))
        for path in plugin["agents"]:
            self.assertTrue(path.startswith("./") and ".." not in path and (ROOT / path).is_file())

    def test_pack_registers_and_runs_vendored_in_a_project(self):
        project = self.tmp / "product"
        project.mkdir()
        with mock.patch("hublink.on_main", return_value=True):
            revision = hublink.head()
            committed = all(hublink.has_commit(revision) and self._at(revision, path) for path in
                            ("engineering_os/gaie_router.py", "skills/gaie-build/SKILL.md", "prompts/MASTER_BUILD.md"))
            if not committed or subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain"], capture_output=True, text=True).stdout.strip():
                self.skipTest("pack registration reproduces a clean committed revision")
            hublink.register(project, revision, capabilities=["pack:gaie-factory"], apply=True)
            self.assertTrue(hublink.verify(project)["ok"])
        for name in SKILLS:
            self.assertEqual((project / ".claude/skills" / name / "SKILL.md").read_bytes(), (ROOT / "skills" / name / "SKILL.md").read_bytes())
        self.assertEqual((project / ".claude/agents/gaie-verifier.md").read_bytes(),
                         (ROOT / "agents/gaie-verifier.md").read_bytes())
        env = {**os.environ, **self.env}
        env.pop("PYTHONDONTWRITEBYTECODE", None)
        env.pop("PYTHONPYCACHEPREFIX", None)
        run = subprocess.run([sys.executable, ".engineering/gaie/gaie_router.py", "route", "افحص سديد"],
                             capture_output=True, text=True, cwd=project, env=env)
        self.assertEqual(run.returncode, 0, run.stderr or run.stdout)
        plan = json.loads(run.stdout)
        self.assertEqual((plan["engine"], plan["read_only"]), ("AUDIT", True))
        self.assertTrue(all(row["available"] for row in plan["skills"] if row["skill"].startswith("gaie-")))
        self.assertFalse((project / ".engineering/gaie/__pycache__").exists())
        run = subprocess.run([sys.executable, ".engineering/gaie/gaie_inventory.py", "."], capture_output=True, text=True, cwd=project)
        self.assertTrue(json.loads(run.stdout)["signals"]["hub_linked"])

    @staticmethod
    def _at(revision, path):
        try:
            hublink.read(revision, path)
            return True
        except Exception:
            return False


if __name__ == "__main__":
    unittest.main()
