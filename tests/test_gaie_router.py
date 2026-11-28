"""Router acceptance: bilingual intent, project resolution and fail-closed targeting."""
import copy
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from engineering_os import contracts, project_registry
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
        self.assertEqual(plan["repository_check"]["status"], "registered-private")
        # The public files may name BILTIX (a public-safe identifier) but never its repository.
        public = (ROOT / "projects/registry.json").read_text() + (ROOT / "projects/aliases.json").read_text()
        self.assertNotIn("example-owner", public)
        self.assertNotIn("biltix", (ROOT / "projects/registry.json").read_text())
        catalog = {row["id"]: row for row in json.loads((ROOT / "projects/aliases.json").read_text())["catalog"]}
        self.assertEqual(catalog["biltix"]["repository_status"], "unverified")
        self.assertFalse({"repository", "path", "url"} & set(catalog["biltix"]))

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


SADEED = "biz-pulse-ar"
PORTFOLIO = "faisal-aljuhaimy-portfolio"
# (command, intent, project, engine id, side-effect ceiling, decision); None project = new system.
OWNER_COMMANDS = (
    ("طور سديد بالكامل", "upgrade", SADEED, "master-upgrade", "repo-write", "ready-for-grant"),
    ("fully upgrade Sadeed", "upgrade", SADEED, "master-upgrade", "repo-write", "ready-for-grant"),
    ("upgrade Sadeed completely", "upgrade", SADEED, "master-upgrade", "repo-write", "ready-for-grant"),
    ("طور فيصل الجهيمي بورتفوليو", "upgrade", PORTFOLIO, "master-upgrade", "repo-write", "ready-for-grant"),
    ("upgrade the Faisal Aljuhaimy Portfolio", "upgrade", PORTFOLIO, "master-upgrade", "repo-write", "ready-for-grant"),
    ("طور بلتكس", "upgrade", "biltix", "master-upgrade", "repo-write", "ready-for-grant"),
    ("upgrade BILTIX", "upgrade", "biltix", "master-upgrade", "repo-write", "ready-for-grant"),
    ("طور فيديوهات سديد", "cinematic", SADEED, "master-cinematic", "repo-write", "ready-for-grant"),
    ("upgrade Sadeed's videos", "cinematic", SADEED, "master-cinematic", "repo-write", "ready-for-grant"),
    ("سرّع سديد", "accelerate", SADEED, "master-upgrade", "repo-write", "ready-for-grant"),
    ("speed up Sadeed", "accelerate", SADEED, "master-upgrade", "repo-write", "ready-for-grant"),
    ("افحص سديد", "audit", SADEED, "master-audit", "none", "ready-for-grant"),
    ("inspect Sadeed", "audit", SADEED, "master-audit", "none", "ready-for-grant"),
    ("أصلح أخطاء سديد", "repair", SADEED, "self-healing", "repo-write", "ready-for-grant"),
    ("fix Sadeed's bugs", "repair", SADEED, "self-healing", "repo-write", "ready-for-grant"),
    ("ابنِ نظامًا جديدًا لإدارة المشاريع", "build", None, "master-build", "workspace-write", "ready-for-grant"),
    ("build a new project management system", "build", None, "master-build", "workspace-write", "ready-for-grant"),
    ("انشر سديد", "release", SADEED, "master-release", "production", "needs-approval"),
    ("deploy Sadeed", "release", SADEED, "master-release", "production", "needs-approval"),
)
WRITING = {"write:state", "write:workspace", "write:repo-branch", "exec:sandbox", "net:fetch", "ext:github", "ext:deploy",
           "prod:deploy"}


class ControlPlaneRouteTests(unittest.TestCase):
    """Route v2: engine id, roles, capabilities, grant template, scope, tests and evidence under hard rules."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = pathlib.Path(temporary.name) / "gaie"
        self.env = {"GAIE_HOME": str(self.home)}

    def register_private(self):
        """Simulated private registrations (example owner), as the owner would make them with `register`."""
        project_registry.register(PORTFOLIO, environ=self.env, apply=True, repository="https://github.com/example-owner/site",
                                  path="portfolio", deployment_target={"provider": "example-host", "project": "portfolio"})
        project_registry.register("biltix", environ=self.env, apply=True, repository="https://github.com/example-owner/biltix")
        project_registry.register(SADEED, environ=self.env, apply=True,
                                  deployment_target={"provider": "example-host", "project": "sadeed"})

    def route(self, text, **options):
        return router.route(text, environ=self.env, **options)

    def test_owner_commands_route_with_every_required_field(self):
        self.register_private()
        for text, intent, project, engine_id, ceiling, decision in OWNER_COMMANDS:
            plan = self.route(text)
            self.assertEqual(plan["status"], "routed", text)
            self.assertEqual((plan["intent"], plan["project"], plan["engine_id"], plan["side_effect"], plan["decision"]),
                             (intent, project, engine_id, ceiling, decision), text)
            self.assertFalse(plan["executable_by_route"], text)
            self.assertTrue(plan["roles"]["lead"] and plan["roles"]["verifier"], text)
            self.assertNotEqual(plan["roles"]["lead"], plan["roles"]["verifier"], text)
            self.assertTrue(plan["capabilities"] and plan["tests"] and plan["evidence"], text)
            self.assertEqual(plan["grant_template"]["max_side_effect"], ceiling, text)
            self.assertEqual(plan["grant_template"]["role"], plan["roles"]["lead"], text)
            self.assertEqual(next(iter(plan["grant_template"]["engines"])), engine_id, text)
            self.assertEqual(plan["execution_scope"]["max_side_effect"], ceiling, text)
            self.assertFalse(plan["execution_scope"]["default_branch_writes"], text)
            expected = "not-applicable" if project is None else "registered-public" if project == SADEED else "registered-private"
            self.assertEqual(plan["repository_check"]["status"], expected, text)
            grant = router.grant_from_template(plan["grant_template"], grant_id="g-test-route", expires_at="2099-01-01T00:00:00Z")
            self.assertTrue(contracts.validate_grant(grant))
            for perm in plan["permissions"]:
                self.assertIn(perm, contracts.PERMISSIONS, text)

    def test_unregistered_repository_is_named_but_never_guessed(self):
        for text, project in (("طور بلتكس", "biltix"), ("upgrade BILTIX", "biltix"), ("طور فيصل الجهيمي بورتفوليو", PORTFOLIO),
                              ("upgrade Faisal Al-Juhaimy portfolio", PORTFOLIO), ("افحص المختبر الأمني", "security-lab"),
                              ("audit the security lab", "security-lab"), ("طور مؤشرات الأداء", "kpi"), ("upgrade KPI", "kpi")):
            plan = self.route(text)
            self.assertEqual((plan["status"], plan["project"]), ("needs-clarification", project), text)
            self.assertEqual(plan["repository_check"]["status"], "unverified", text)
            self.assertFalse(plan["repository_check"]["repository_known"], text)
            self.assertIsNone(plan["grant_template"], text)
            self.assertIsNone(plan["execution_scope"], text)
            self.assertNotIn("targets", plan, text)
            self.assertIn("register", plan["next_step"], text)
            self.assertNotIn("https://github.com/faisaljohaimy", json.dumps(plan), text)

    def test_unknown_or_ambiguous_project_needs_clarification(self):
        for text in ("طور المشروع", "upgrade the project", "طور الموقع", "افحص المشروع الجديد", "انشر التطبيق", "deploy it"):
            plan = self.route(text)
            self.assertEqual(plan["status"], "needs-clarification", text)
            self.assertIsNone(plan["grant_template"], text)
            self.assertFalse(plan["write_allowed"] or plan["executable_by_route"], text)
            self.assertNotIn("targets", plan, text)
        plan = self.route("طور بلتكس وسديد")  # one of the two has no registered repository
        self.assertEqual((plan["status"], plan["unregistered"]), ("needs-clarification", ["biltix"]))
        self.assertIsNone(plan["project"])
        self.assertEqual(project_registry.resolve("طور سديد وبلتكس", environ=self.env)["candidates"], ["biltix", SADEED])

    def test_audit_never_maps_to_a_writing_grant(self):
        for text in ("افحص سديد", "إفحص سديد", "دقق سديد", "راجع سديد", "audit Sadeed", "inspect Sadeed", "review sadeed",
                     "scan sadeed", "لا تنشر سديد، افحصه فقط", "audit sadeed but do not deploy"):
            plan = self.route(text)
            self.assertEqual((plan["intent"], plan["engine_id"]), ("audit", "master-audit"), text)
            self.assertEqual((plan["side_effect"], plan["grant_template"]["max_side_effect"]), ("none", "none"), text)
            self.assertEqual(plan["grant_template"]["engines"],
                             {"master-audit": ["spec", "inventory", "health", "hub-audit"], "memory": ["search"]}, text)
            self.assertFalse(set(plan["permissions"]) & WRITING, text)
            self.assertEqual(plan["execution_scope"]["kind"], "read-only", text)
            self.assertFalse(plan["execution_scope"]["network"] or plan["execution_scope"]["production"], text)
            self.assertEqual(plan["approvals_required"], [], text)
            self.assertFalse(plan["write_allowed"], text)
            self.assertTrue(plan["read_only"], text)

    def test_performance_and_repair_stay_on_an_isolated_branch(self):
        for text, intent in (("سرّع سديد", "accelerate"), ("سرع سديد", "accelerate"), ("optimize sadeed", "accelerate"),
                             ("أصلح أخطاء سديد", "repair"), ("اصلح سديد", "repair"), ("fix the errors in Sadeed", "repair")):
            plan = self.route(text)
            self.assertEqual(plan["intent"], intent, text)
            scope = plan["execution_scope"]
            self.assertEqual((scope["kind"], scope["branch"]), ("repo-branch", f"claude/gaie-{intent}-{SADEED}"), text)
            self.assertLessEqual(contracts.side_effect_rank(plan["side_effect"]), contracts.side_effect_rank("repo-write"), text)
            self.assertFalse({"ext:github", "ext:deploy", "prod:deploy", "net:fetch"} & set(plan["permissions"]), text)
            self.assertEqual(plan["grant_template"]["paths"], [f"workspace/{SADEED}"], text)
            self.assertEqual(plan["approvals_required"], [], text)
        self.assertEqual(self.route("أصلح أخطاء سديد")["roles"]["lead"], "testing-self-healing-engineer")

    def test_release_always_needs_approval_and_never_executes(self):
        for registered in (False, True):
            if registered:
                self.register_private()
            for text in ("انشر سديد", "أطلق سديد", "deploy Sadeed", "release sadeed", "publish sadeed", "ship sadeed"):
                plan = self.route(text)
                self.assertEqual((plan["status"], plan["intent"], plan["engine_id"]), ("routed", "release", "master-release"), text)
                self.assertEqual(plan["decision"], "needs-approval", text)
                self.assertIn(plan["side_effect"], contracts.GATED, text)
                self.assertFalse(plan["write_allowed"] or plan["executable_by_route"], text)
                gated = {step["side_effect"] for step in plan["approvals_required"]}
                self.assertEqual(gated, {"external-write", "production"}, text)
                self.assertTrue(all(step["needs_approval"] for step in plan["approvals_required"]), text)
                self.assertEqual(plan["grant_template"]["approvals"], [], text)
                self.assertEqual((plan["execution_scope"]["kind"], plan["execution_scope"]["production"]), ("release-gated", True))
                self.assertEqual(bool(plan["blockers"]), not registered, text)  # a missing target is reported, never guessed
        self.assertIn("deployment target", self.route("انشر بلتكس")["blockers"][0])

    def test_new_system_gets_a_workspace_grant_and_a_gated_repository_step(self):
        plan = self.route("ابنِ نظامًا جديدًا لإدارة المشاريع")
        self.assertEqual((plan["engine_id"], plan["side_effect"], plan["target_scope"]), ("master-build", "workspace-write", "new-project"))
        self.assertEqual(plan["grant_template"]["paths"], ["workspace/new-project"])
        self.assertFalse(any("create-repository" in acts for acts in plan["grant_template"]["engines"].values()))
        step = plan["approvals_required"][0]
        self.assertEqual((step["action"], step["side_effect"], step["needs_approval"], step["in_base_grant"]),
                         ("create-repository", "external-write", True, False))
        self.assertFalse({"ext:github", "write:repo-branch"} & set(plan["permissions"]))
        self.assertEqual(plan["repository_check"]["status"], "not-applicable")
        self.assertEqual(plan["roles"]["lead"], "master-build-engine-engineer")

    def test_arabic_normalization_variants_route_identically(self):
        def key(text):
            plan = self.route(text)
            return plan["status"], plan["intent"], plan["engine_id"], plan["project"], plan["side_effect"]
        for variants in (("سرّع سديد", "سرع سديد", "سَرِّعْ سديد", "سـرّع سـديـد"),
                         ("أصلح أخطاء سديد", "اصلح اخطاء سديد", "إصلح أخطاء سديد"),
                         ("ابنِ نظامًا جديدًا لإدارة المشاريع", "ابن نظاما جديدا لادارة المشاريع", "اِبنِ نظاماً جديداً لإدارة المشاريع"),
                         ("طور فيديوهات سديد", "طوّر فيديوهات سديد", "طـور فيديوهات سديد"),
                         ("افحص سديد", "إفحص سديد", "أفحص سديد")):
            first = key(variants[0])
            self.assertEqual(first[0], "routed", variants[0])
            for text in variants[1:]:
                self.assertEqual(key(text), first, text)
        self.assertEqual(self.route("افحص المختبر الامني")["project"], "security-lab")  # hamza on alef folded
        self.assertEqual(self.route("طور سديدة")["status"], "needs-clarification")  # taa marbuta: similar, never selected

    def test_project_names_are_not_focus_words(self):
        project_registry.register("security-lab", environ=self.env, apply=True, repository="https://github.com/example-owner/lab")
        project_registry.register("kpi", environ=self.env, apply=True, repository="https://github.com/example-owner/kpi")
        self.assertEqual((self.route("طور المختبر الأمني")["focus"], self.route("طور المختبر الأمني")["scope"]), ([], "comprehensive"))
        self.assertEqual(self.route("طور مؤشرات الأداء")["scope"], "comprehensive")
        self.assertEqual(self.route("طور أمان المختبر الأمني")["focus"], ["security"])
        self.assertEqual(self.route("audit security lab")["focus"], [])

    def test_all_projects_skips_unregistered_repositories(self):
        plan = self.route("طور جميع مشاريعي")
        self.assertEqual([t["id"] for t in plan["targets"]], [SADEED, "n8n-docs", "wow-bus"])
        self.assertEqual(sorted(s["id"] for s in plan["skipped"]), ["biltix", PORTFOLIO, "kpi", "security-lab"])
        self.assertIsNone(plan["grant_template"])
        self.assertEqual({t["grant_template"]["paths"][0] for t in plan["targets"]},
                         {f"workspace/{t['id']}" for t in plan["targets"]})  # one grant per project, never shared

    def test_private_record_of_one_project_never_appears_in_another_route(self):
        self.register_private()
        text = json.dumps(self.route("طور سديد"), ensure_ascii=False)
        for private in ("example-owner/site", "example-owner/biltix", "portfolio\"", "example-host"):
            self.assertNotIn(private, text)
        plan = self.route("طور فيصل الجهيمي بورتفوليو")
        self.assertEqual(plan["targets"][0]["path"], "portfolio")
        self.assertEqual(plan["grant_template"]["paths"], [f"workspace/{PORTFOLIO}/portfolio"])
        self.assertNotIn("example-owner/biltix", json.dumps(plan))

    def test_tampered_policy_cannot_relax_a_hard_rule(self):
        base = router.policy()

        def tampered(change):
            rules = copy.deepcopy(base)
            change(rules["control_plane"]["intents"])
            return rules

        changes = (
            lambda i: i["audit"].update(max_side_effect="repo-write"),
            lambda i: i["audit"].update(max_side_effect="state-write"),
            lambda i: i["audit"]["permissions"].append("write:repo-branch"),
            lambda i: i["audit"].update(execution="repo-branch"),
            lambda i: i["accelerate"].update(max_side_effect="network"),
            lambda i: i["repair"].update(max_side_effect="external-write"),
            lambda i: i["upgrade"]["permissions"].append("ext:github"),
            lambda i: i["release"].update(approval_required=False),
            lambda i: i["release"].update(max_side_effect="repo-write"),
            lambda i: i["release"].update(gated_steps=[]),
            lambda i: i["build"].update(max_side_effect="external-write"),
            lambda i: i["build"].update(gated_steps=[]),
            lambda i: i["build"]["engines"]["master-build"].append("create-repository"),
            lambda i: i["release"]["engines"]["master-release"].remove("promote"),
            lambda i: i["upgrade"]["engines"].pop("master-upgrade"),
            lambda i: i["repair"]["roles"].update(verifier=i["repair"]["roles"]["lead"]),
            lambda i: i["audit"]["roles"].update(lead="unlisted-role"),
            lambda i: i["upgrade"].update(gated_steps=[dict(i["build"]["gated_steps"][0])]),
            lambda i: i["upgrade"]["capabilities"].append("anything-goes"),
            lambda i: i.pop("audit"),
        )
        for index, change in enumerate(changes):
            with mock.patch.object(router, "policy", return_value=tampered(change)):
                with self.assertRaises(router.RouteError, msg=index):
                    router.route("افحص سديد", environ=self.env)
        rules = copy.deepcopy(base)
        rules["engines"]["audit"]["write"] = True
        with mock.patch.object(router, "policy", return_value=rules), self.assertRaises(router.RouteError):
            router.route("افحص سديد", environ=self.env)

    def test_grant_templates_are_only_templates(self):
        template = self.route("طور سديد")["grant_template"]
        self.assertIsNone(template["grant_id"])
        self.assertIsNone(template["expires_at"])
        filled = router.grant_from_template(template, grant_id="g-test-1", expires_at="2099-01-01T00:00:00Z")
        with self.assertRaises(router.RouteError):
            router.grant_from_template(filled, grant_id="g-test-2", expires_at="2099-01-01T00:00:00Z")
        with self.assertRaises(router.RouteError):
            router.grant_from_template({**template, "approvals": [{"side_effect": "production"}]}, grant_id="g-x-1",
                                       expires_at="2099-01-01T00:00:00Z")
        with self.assertRaises(router.RouteError):
            router.grant_from_template(template, grant_id="no", expires_at="tomorrow")

    def test_fallback_constants_match_the_shared_contracts(self):
        self.assertEqual(router.SIDE_EFFECTS, contracts.SIDE_EFFECTS)
        self.assertEqual(router.GATED, contracts.GATED)
        self.assertEqual(router.PERMISSIONS, contracts.PERMISSIONS)
        self.assertLessEqual(set(router.PERMISSION_FLOOR), contracts.PERMISSIONS)

    def test_legacy_loader_still_routes_when_the_registry_module_is_absent(self):
        with mock.patch.object(router, "_registry_module", return_value=None):
            plan = router.route("طور سديد", environ=self.env)
            self.assertEqual((plan["status"], plan["project"], plan["repository_check"]["status"]),
                             ("routed", SADEED, "registered-public"))
            self.assertEqual(router.route("طور بلتكس", environ=self.env)["status"], "needs-clarification")

    def test_role_engine_and_capability_ids_are_grounded(self):
        rules = router.policy()
        plane = rules["control_plane"]
        listed = set(plane["role_ids"]["registered"]) | set(plane["role_ids"]["provisional"])
        factory = (ROOT / "docs/GAIE_FACTORY.md").read_text(encoding="utf-8")
        for spec in plane["intents"].values():
            self.assertLessEqual({spec["roles"]["lead"], spec["roles"]["verifier"], *spec["roles"]["support"]}, listed)
            for capability in spec["capabilities"]:
                self.assertIn(f"| {capability} |", factory, capability)
        roles_file, engines_file = ROOT / "governance/agent-roles.json", ROOT / "governance/engines.json"
        if roles_file.is_file():  # once the role registry lands, every routed role must be registered there
            data = json.loads(roles_file.read_text(encoding="utf-8"))
            rows = data.get("roles", data) if isinstance(data, dict) else data
            registered = {row["id"] for row in rows}
            self.assertLessEqual(listed - set(plane["role_ids"]["provisional"]), registered)
        if engines_file.is_file():  # ... and every engine id and action must exist with a side effect under the ceiling
            data = json.loads(engines_file.read_text(encoding="utf-8"))
            engines = {row["id"]: row for row in (data.get("engines", data) if isinstance(data, dict) else data)}
            for intent, spec in plane["intents"].items():
                gated = {(step["engine"], step["action"]) for step in spec["gated_steps"]}
                for name, actions in spec["engines"].items():
                    self.assertIn(name, engines, intent)
                    for action in actions:
                        known = engines[name]["actions"]
                        if (name, action) in gated and action not in known:
                            continue  # a gated step the control plane does not implement yet: it cannot run
                        self.assertIn(action, known, (intent, name, action))
                        effect = known[action]["side_effect"]
                        ceiling = spec["max_side_effect"]
                        self.assertLessEqual(contracts.side_effect_rank(effect), contracts.side_effect_rank(ceiling),
                                             (intent, name, action))


if __name__ == "__main__":
    unittest.main()
