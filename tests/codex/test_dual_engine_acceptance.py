"""Exercise shared GAIE policy and recovery through two installed CLI layouts."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from engineering_os import master_docs, motion_policy


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = Path("skills/gaie-master-router/engine")


class DualEngineAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="gaie-dual-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        cls.layouts = {}
        for engine, script, directory in (
            ("codex", "gaie_codex_portable.py", ".agents"),
            ("claude-code", "gaie_bootstrap.py", ".claude"),
        ):
            project = cls.root / engine
            project.mkdir()
            cls.run_cli(ROOT / "scripts" / script, "install", "--scope", "project",
                        "--target", project, "--apply", cwd=project)
            cls.layouts[engine] = project / directory

    @classmethod
    def run_cli(cls, script, *args, cwd, status=0):
        env = {"PATH": os.defpath, "HOME": str(cls.root), "LANG": "C.UTF-8",
               "GAIE_HOME": str(cls.root / "private")}
        result = subprocess.run(
            [sys.executable, "-B", str(script), *map(str, args)], cwd=cwd, env=env,
            text=True, capture_output=True, timeout=30,
        )
        if result.returncode != status:
            raise AssertionError(f"{script.name} exited {result.returncode}: {result.stderr or result.stdout}")
        return json.loads(result.stdout)

    def run_engine(self, engine, script, *args, status=0):
        layout = self.layouts[engine]
        return self.run_cli(layout / RUNTIME / script, *args, cwd=layout.parent, status=status)

    def test_j_natural_language_plans_agree_and_never_grant_writes(self):
        cases = [
            ("Build a new project management system", "master-build", 0),
            ("ابنِ نظامًا جديدًا لإدارة المشاريع", "master-build", 0),
            ("طور سديد بالكامل", "master-upgrade", 0),
            ("طور بلتكس", "master-upgrade", 2),
            ("طور البورتفوليو", "master-upgrade", 2),
            ("طور فيديوهات سديد", "master-cinematic", 0),
            ("طور الأفلام والفيديوهات", "master-cinematic", 2),
            ("سرّع سديد", "master-upgrade", 0),
            ("أصلح أخطاء سديد", "self-healing", 0),
            ("Audit Sadeed", "master-audit", 0),
            ("افحص سديد", "master-audit", 0),
            ("انشر سديد", "master-release", 0),
            ("للتدقيق فقط: طوّر سديد", None, 2),
        ]
        for request, expected, status in cases:
            with self.subTest(request=request):
                plans = [self.run_engine(engine, "gaie_router.py", "route", request, status=status)
                         for engine in self.layouts]
                self.assertEqual(plans[0].get("engine_id"), expected)
                keys = ("status", "decision", "intent", "engine_id", "project", "read_only",
                        "write_allowed", "grant_template", "executable_by_route")
                self.assertEqual({k: plans[0].get(k) for k in keys}, {k: plans[1].get(k) for k in keys})
                self.assertFalse(plans[0]["write_allowed"])
                self.assertFalse(plans[0]["executable_by_route"])
                grant = plans[0]["grant_template"]
                if expected == "master-audit":
                    self.assertTrue(plans[0]["read_only"])
                    self.assertEqual(grant["max_side_effect"], "none")
                    self.assertEqual(set(grant["engines"]), {"master-audit"})
                else:
                    self.assertIsNone(grant)

    def test_k_installed_layouts_match_the_same_pinned_master_documents(self):
        manifest = master_docs.load_manifest()
        self.assertTrue(master_docs.verify()["ok"])
        report = self.run_engine("codex", "master_docs.py", "status", "--json")
        self.assertTrue(report["ok"], report)
        for engine, layout in self.layouts.items():
            for entry in manifest["documents"].values():
                with self.subTest(engine=engine, version=entry["version"]):
                    self.assertEqual((layout / entry["installed_as"]["claude"]).read_bytes(),
                                     (ROOT / entry["path"]).read_bytes())

    def test_k_committed_hub_skills_still_match_their_generated_sources(self):
        result = self.run_cli(ROOT / "scripts/gaie_codex_bootstrap.py", "check", cwd=ROOT)
        self.assertTrue(result["ok"], result)

    def test_l_both_layouts_discover_the_same_central_team(self):
        for intent in ("build", "upgrade"):
            teams = [self.run_engine(engine, "agent_team.py", "show", "--intent", intent, "--cpus", "4", "--json")
                     for engine in self.layouts]
            self.assertEqual(teams[0], teams[1])
            self.assertEqual(len(teams[0]["roles"]) + len(teams[0]["omitted"]), 20)
            self.assertLessEqual(teams[0]["concurrency"]["effective"], 20)

    def test_n_codex_policy_copy_matches_the_enforced_motion_source(self):
        policy = ROOT / "governance/policies/motion-purpose.json"
        codex_copy = self.layouts["codex"] / RUNTIME / policy.name
        self.assertEqual(codex_copy.read_bytes(), policy.read_bytes())
        report = motion_policy.report(ROOT)
        self.assertTrue(report["ok"], report.get("violations"))
        self.assertEqual(report["unclassified"], 0)

    def test_o_fresh_process_can_restore_and_claim_the_other_engine_checkpoint(self):
        source = self.root / "task-source"
        target = self.root / "task-target"
        checkpoint = self.root / "checkpoint.json"
        spec = self.root / "task.json"
        spec.write_text(json.dumps({
            "id": "handover", "title": "Bilingual handover fixture", "project": "fixture",
            "branch": "codex/parity-fixture", "paths": ["src/"], "priority": 1,
        }), encoding="utf-8")
        evidence = self.root / "receipt.json"
        evidence.write_text(json.dumps([{"kind": "fixture", "sha256": "a" * 64}]), encoding="utf-8")

        def task(engine, state, *args):
            return self.run_engine(engine, "orchestration.py", "--state-dir", state, *args)

        task("codex", source, "create", "--spec", spec, "--revision", "0",
             "--actor", "fixture-coordinator", "--role", "orchestrator", "--engine", "codex")
        first = task("codex", source, "claim", "--task", "handover", "--version", "1",
                     "--actor", "fixture-codex", "--role", "development", "--engine", "codex")
        task("codex", source, "handover", "--task", "handover", "--version", "2",
             "--actor", "fixture-codex", "--role", "development", "--engine", "codex",
             "--lease", first["lease"]["id"], "--note", "Resume this fixture", "--receipts", evidence)
        saved = task("codex", source, "checkpoint", "--output", checkpoint)
        restored = task("claude-code", target, "restore", "--input", checkpoint)
        self.assertEqual(restored["state_sha256"], saved["state_sha256"])
        accepted = task("claude-code", target, "claim", "--task", "handover", "--version", "3",
                        "--actor", "fixture-claude", "--role", "development", "--engine", "claude-code")
        self.assertEqual(accepted["handover"]["from"]["engine"], "codex")
        self.assertEqual(accepted["owner"]["engine"], "claude-code")
        self.assertEqual(task("codex", source, "status")["revision"], 3)
        self.assertEqual(task("claude-code", target, "status")["revision"], 4)

        task("claude-code", target, "handover", "--task", "handover", "--version", "4",
             "--actor", "fixture-claude", "--role", "development", "--engine", "claude-code",
             "--lease", accepted["lease"]["id"], "--note", "Return this fixture", "--receipts", evidence)
        returned_checkpoint = self.root / "returned-checkpoint.json"
        returned_state = self.root / "returned-state"
        saved = task("claude-code", target, "checkpoint", "--output", returned_checkpoint)
        restored = task("codex", returned_state, "restore", "--input", returned_checkpoint)
        self.assertEqual(restored["state_sha256"], saved["state_sha256"])
        returned = task("codex", returned_state, "claim", "--task", "handover", "--version", "5",
                        "--actor", "fixture-codex", "--role", "development", "--engine", "codex")
        self.assertEqual(returned["handover"]["from"]["engine"], "claude-code")
        self.assertEqual(returned["owner"]["engine"], "codex")
        self.assertEqual(task("claude-code", target, "status")["revision"], 5)
        self.assertEqual(task("codex", returned_state, "status")["revision"], 6)


if __name__ == "__main__":
    unittest.main()
