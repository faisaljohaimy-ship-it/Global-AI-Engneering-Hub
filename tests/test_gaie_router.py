"""Router acceptance: bilingual intent, project resolution and fail-closed targeting."""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

from engineering_os import gaie_router as router

ROOT = pathlib.Path(__file__).resolve().parents[1]


class RouterTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = pathlib.Path(temporary.name) / "gaie"
        self.env = {"GAIE_HOME": str(self.home)}

    def route(self, text, **options):
        return router.route(text, environ=self.env, **options)

    def assertRoute(self, text, intent, engine, skill, targets, scope=None):
        plan = self.route(text)
        self.assertEqual(plan["status"], "routed", text)
        self.assertEqual((plan["intent"], plan["engine"], plan["skill"]), (intent, engine, skill), text)
        self.assertEqual([t["id"] for t in plan["targets"]], targets, text)
        if scope:
            self.assertEqual(plan["scope"], scope, text)
        return plan

    def test_owner_acceptance_phrases(self):
        sadeed = ["biz-pulse-ar"]
        self.assertRoute("طور سديد بالكامل", "upgrade", "MASTER_UPGRADE", "gaie-upgrade", sadeed, "comprehensive")
        self.assertRoute("طور سديد", "upgrade", "MASTER_UPGRADE", "gaie-upgrade", sadeed, "comprehensive")
        self.assertRoute("طور فيديوهات سديد", "cinematic", "CINEMATIC", "gaie-cinematic", sadeed, "media")
        self.assertRoute("سرّع سديد", "accelerate", "MASTER_UPGRADE", "gaie-upgrade", sadeed, "performance")
        self.assertRoute("أصلح أخطاء سديد", "repair", "MASTER_UPGRADE", "gaie-upgrade", sadeed, "self-healing")
        self.assertRoute("انشر سديد", "release", "RELEASE", "gaie-release", sadeed)
        audit = self.assertRoute("افحص سديد", "audit", "AUDIT", "gaie-audit", sadeed)
        self.assertTrue(audit["read_only"])
        self.assertFalse(audit["write_allowed"])
        self.assertTrue(any("Read-only" in gate for gate in audit["gates"]))

    def test_build_routes_to_a_new_project_without_a_target(self):
        for text in ("ابنِ نظامًا جديدًا لإدارة المشاريع", "ابنِ نظامًا جديدًا بالذكاء الاصطناعي", "Build a new project management system"):
            plan = self.assertRoute(text, "build", "MASTER_BUILD", "gaie-build", [], "comprehensive")
            self.assertEqual(plan["target_scope"], "new-project")
            self.assertEqual(plan["prompt"], "prompts/MASTER_BUILD.md")
        self.assertIn("ai", self.route("ابنِ نظامًا جديدًا بالذكاء الاصطناعي")["focus"])

    def test_all_projects_lists_every_registered_project_independently(self):
        plan = self.assertRoute("طور جميع مشاريعي", "upgrade", "MASTER_UPGRADE", "gaie-upgrade",
                                ["biz-pulse-ar", "n8n-docs", "wow-bus"])
        self.assertEqual(plan["target_scope"], "all-registered-projects")
        self.assertTrue(plan["agents"]["per_target"])
        self.assertTrue(all(t["repository_verified"] is False for t in plan["targets"]))

    def test_english_and_arabic_agree(self):
        for arabic, english in (("طور سديد", "upgrade SADEED"), ("افحص سديد", "Audit Sadeed"),
                                ("سرّع سديد", "please speed up sadeed"), ("انشر سديد", "deploy Sadeed")):
            a, e = self.route(arabic), self.route(english)
            self.assertEqual((a["intent"], a["targets"]), (e["intent"], e["targets"]))
            self.assertEqual((a["language"], e["language"]), ("ar", "en"))

    def test_arabic_normalization(self):
        self.assertEqual(router.normalize("سَرِّعْ أَداءَ «سديد»"), ["سرع", "اداء", "سديد"])
        self.assertRoute("طَوِّرْ لسديد", "upgrade", "MASTER_UPGRADE", "gaie-upgrade", ["biz-pulse-ar"])
        plan = self.route("طور واجهات وقواعد بيانات سديد")
        self.assertEqual(plan["focus"], ["database", "interface"])
        self.assertEqual(plan["scope"], "focused")

    def test_unknown_or_similar_project_is_never_guessed(self):
        for text in ("طور بلتكس", "upgrade Biltix", "طور سديدة", "upgrade sadeeed", "طور المشروع"):
            plan = self.route(text)
            self.assertEqual(plan["status"], "needs-clarification", text)
            self.assertFalse(plan["write_allowed"])
            self.assertNotIn("targets", plan)
        self.assertEqual(self.route("طور سديدة")["suggestions"], ["biz-pulse-ar"])

    def test_negation_prohibits_instead_of_routing(self):
        plan = self.route("لا تنشر سديد، افحصه فقط")
        self.assertEqual((plan["intent"], plan["prohibited"]), ("audit", ["release"]))
        plan = self.route("طور سديد ولا تنشره")
        self.assertEqual((plan["intent"], plan["prohibited"]), ("upgrade", ["release"]))
        plan = self.route("audit sadeed but do not deploy")
        self.assertEqual((plan["intent"], plan["prohibited"]), ("audit", ["release"]))
        self.assertEqual(self.route("لا تنشر سديد")["status"], "needs-clarification")

    def test_conflicting_or_empty_commands_need_clarification(self):
        for text in ("افحص ثم انشر سديد", "مرحبا", "سديد", "ابن سديد", "طور سديد وجميع مشاريعي"):
            self.assertEqual(self.route(text)["status"], "needs-clarification", text)
        for bad in ("", "   ", "x" * 2001, None):
            with self.assertRaises(router.RouteError):
                self.route(bad)

    def test_statements_questions_and_distant_negations_never_become_commands(self):
        for text in ("لا اريد ان تنشر سديد", "لن تنشر سديد", "لم ننشر سديد بعد", "يمنع ان تنشر سديد",
                     "do not ever again deploy sadeed", "you shouldn't deploy sadeed", "cannot deploy sadeed",
                     "don`t deploy sadeed", "it is forbidden to deploy sadeed", "deploy sadeed is forbidden",
                     "avoid release of sadeed", "deploy sadeed? no", "not only audit but deploy sadeed",
                     "deploy sadeed without audit", "ماذا حدث في سديد", "تحسن اداء سديد كثيرا", "حسن يعمل على سديد",
                     "فرق سديد ممتاز", "ورقة عمل سديد", "عجلة سديد", "what is the speed of sadeed",
                     "release notes for sadeed", "did we deploy sadeed yesterday?", "the ship page of sadeed is broken",
                     "هل ننشر سديد؟", "بل مشاريعي طور"):
            plan = self.route(text)
            self.assertEqual(plan["status"], "needs-clarification", text)
            self.assertFalse(plan["write_allowed"], text)

    def test_negated_or_embedded_project_names_are_not_targets(self):
        for text in ("upgrade sadeed but not wow bus", "طور سديد وليس واو باص", "deploy sadeed, not wow bus",
                     "build sadeeed", "ابن سديدة", "create sadeeed dashboard", "upgrade my-sadeed-fork", "طور الراي السديد"):
            self.assertEqual(self.route(text)["status"], "needs-clarification", text)
        self.assertEqual([t["id"] for t in self.route("طور سديد او باص")["targets"]], ["biz-pulse-ar"])

    def test_combined_command_is_comprehensive(self):
        plan = self.route("طور سديد وسرعه واصلح اخطاءه")
        self.assertEqual((plan["intent"], plan["scope"]), ("upgrade", "comprehensive"))

    def test_remote_must_be_github_or_the_local_proxy(self):
        slug = "faisaljohaimy-ship-it/biz-pulse-ar"
        for url in (f"https://github.com/{slug}.git", f"git@github.com:{slug}.git", f"http://local_proxy@127.0.0.1:9/git/{slug}"):
            self.assertEqual(router.remote_slug(url), slug, url)
        for url in (f"https://gitlab.com/{slug}.git", f"https://evil.example/mirror/{slug}", f"/srv/other/{slug}",
                    f"https://github.com.evil.example/{slug}", "https://github.com/a/.."):
            self.assertIsNone(router.remote_slug(url), url)

    def test_workspace_guard_needs_every_target_and_survives_empty_or_inherited_git_settings(self):
        checkout = self.home.parent / "sadeed"
        checkout.mkdir()
        subprocess.run(["git", "init", "-q", str(checkout)], check=True)
        subprocess.run(["git", "-C", str(checkout), "remote", "add", "origin",
                        "https://github.com/faisaljohaimy-ship-it/biz-pulse-ar.git"], check=True)
        self.assertTrue(self.route("طور سديد", workspace_path=checkout)["write_allowed"])
        self.assertFalse(self.route("upgrade sadeed and upgrade wow bus", workspace_path=checkout)["write_allowed"])
        self.assertFalse(self.route("طور جميع مشاريعي", workspace_path=checkout)["write_allowed"])
        empty = self.route("طور سديد", workspace_path="")
        self.assertFalse(empty["write_allowed"])
        self.assertFalse(empty["targets"][0]["workspace_matches"])
        os.environ["GIT_DIR"] = str(checkout / ".git")
        self.addCleanup(os.environ.pop, "GIT_DIR", None)
        self.assertFalse(self.route("طور سديد", workspace_path=ROOT)["write_allowed"])

    def test_upgrade_subsumes_speed_and_repair(self):
        plan = self.route("طور سديد وسرعه واصلح اخطاءه")
        self.assertEqual((plan["status"], plan["intent"]), ("routed", "upgrade"))

    def test_agent_allocation_is_bounded_and_adaptive(self):
        full, small = self.route("طور سديد")["agents"], self.route("انشر سديد")["agents"]
        self.assertLessEqual(full["recommended_total"], 20)
        self.assertEqual(full["independent_verifiers"], 1)
        self.assertLess(small["recommended_total"], full["recommended_total"])

    def test_plan_reports_real_skill_availability_and_zero_budget(self):
        plan = self.route("طور سديد")
        self.assertTrue(all(row["available"] for row in plan["skills"]))
        self.assertEqual(plan["budget"]["additional_cost"], 0)
        for names in router.policy()["supporting_skills"].values():
            for name in names:
                self.assertTrue((ROOT / "skills" / name / "SKILL.md").is_file(), name)
        for engine in router.policy()["engines"].values():
            self.assertTrue((ROOT / "skills" / engine["skill"] / "SKILL.md").is_file())
            if engine["prompt"]:
                self.assertTrue((ROOT / engine["prompt"]).is_file())

    def test_workspace_guard_blocks_writes_in_another_repository(self):
        plan = self.route("طور سديد", workspace_path=ROOT)
        self.assertFalse(plan["targets"][0]["workspace_matches"])
        self.assertFalse(plan["write_allowed"])
        self.assertIn("do not edit", plan["workspace_note"])
        checkout = self.home.parent / "checkout"
        checkout.mkdir()
        subprocess.run(["git", "init", "-q", str(checkout)], check=True)
        subprocess.run(["git", "-C", str(checkout), "remote", "add", "origin",
                        "http://local_proxy@127.0.0.1:1/git/faisaljohaimy-ship-it/biz-pulse-ar"], check=True)
        plan = self.route("طور سديد", workspace_path=checkout)
        self.assertTrue(plan["targets"][0]["workspace_matches"])
        self.assertTrue(plan["write_allowed"])

    def write_overlay(self, projects):
        self.home.mkdir(parents=True, exist_ok=True)
        (self.home / "projects.json").write_text(json.dumps({"schema_version": 1, "projects": projects}), encoding="utf-8")

    def test_private_overlay_adds_projects_without_touching_the_public_registry(self):
        self.write_overlay([{"id": "biltix", "repository": "https://github.com/example-owner/biltix",
                             "aliases": ["بلتكس", "BILTIX"]}])
        plan = self.assertRoute("طور بلتكس", "upgrade", "MASTER_UPGRADE", "gaie-upgrade", ["biltix"])
        self.assertEqual(plan["targets"][0]["visibility"], "private")
        self.assertEqual(plan["targets"][0]["source"], "private-overlay")
        self.assertNotIn("biltix", (ROOT / "projects/registry.json").read_text() + (ROOT / "projects/aliases.json").read_text())

    def test_conflicting_registries_fail_closed(self):
        cases = ([{"id": "other", "repository": "https://github.com/example-owner/other", "aliases": ["سديد"]}],
                 [{"id": "copy", "repository": "https://github.com/faisaljohaimy-ship-it/biz-pulse-ar"}],
                 [{"id": "biz-pulse-ar", "repository": "https://github.com/example-owner/x"}],
                 [{"id": "bad", "repository": "git@github.com:example-owner/x.git"}],
                 [{"id": "o", "repository": "https://github.com/example-owner/o", "aliases": ["بسديد"]}],
                 [{"id": "o", "repository": "https://github.com/example-owner/o", "aliases": ["sadeed pro"]}],
                 [{"id": "o", "repository": "https://github.com/example-owner/o", "aliases": ["طور"]}],
                 [{"id": "o", "repository": "https://github.com/example-owner/..", "aliases": ["oo"]}],
                 [{"id": "o", "repository": "https://github.com/example-owner/o", "visibility": 7}],
                 ["not-an-object"])
        for projects in cases:
            self.write_overlay(projects)
            with self.assertRaises(router.RouteError, msg=projects):
                self.route("طور سديد")
        (self.home / "projects.json").write_text('{"schema_version": true, "projects": []}')
        with self.assertRaises(router.RouteError):
            self.route("طور سديد")

    def test_private_state_must_be_outside_git(self):
        with self.assertRaises(router.RouteError):
            router.gaie_home({"GAIE_HOME": str(ROOT / "private")})

    def test_public_alias_file_names_only_registered_public_projects(self):
        registered = {row["id"] for row in json.loads((ROOT / "projects/registry.json").read_text())["projects"]}
        aliases = json.loads((ROOT / "projects/aliases.json").read_text())["aliases"]
        self.assertLessEqual(set(aliases), registered)

    def test_cli_exit_codes(self):
        env = {**os.environ, **self.env}
        run = lambda *args: subprocess.run([sys.executable, str(ROOT / "hub.py"), *args], capture_output=True, text=True, env=env, cwd=ROOT)
        ok = run("route", "طور سديد")
        self.assertEqual(ok.returncode, 0)
        self.assertEqual(json.loads(ok.stdout)["engine"], "MASTER_UPGRADE")
        unclear = run("route", "طور بلتكس")
        self.assertEqual(unclear.returncode, 2)
        self.assertEqual(json.loads(unclear.stdout)["status"], "needs-clarification")


if __name__ == "__main__":
    unittest.main()
