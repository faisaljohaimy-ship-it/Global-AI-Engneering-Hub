"""Project registry: bilingual resolution, public-safe catalog, private records and isolation."""
import copy
import json
import os
import pathlib
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from engineering_os import gaie_router as router
from engineering_os import project_registry as registry

ROOT = pathlib.Path(__file__).resolve().parents[1]
SITE = "https://github.com/example-owner/site"  # simulated: example owner, never a real private repository


class RegistryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = pathlib.Path(temporary.name) / "gaie"
        self.env = {"GAIE_HOME": str(self.home)}
        self.public_bytes = {name: (ROOT / "projects" / name).read_bytes() for name in ("registry.json", "aliases.json")}

    def tearDown(self):
        for name, data in self.public_bytes.items():  # nothing is ever written into the repository
            self.assertEqual((ROOT / "projects" / name).read_bytes(), data, name)

    def register(self, project_id, **fields):
        return registry.register(project_id, environ=self.env, apply=True, **fields)

    # --- normalization and resolution ---------------------------------------------------------

    def test_arabic_name_normalization(self):
        for variants in (("المختبر الأمني", "المختبر الامني", "المُختَبَر الأمْنِي", "المختـــبر الإمني"),
                         ("مؤشرات الأداء", "موشرات الاداء", "مؤشّرات الأداء"),
                         ("سديدة", "سديده"), ("بورتفوليو", "بورتفوليـو"), ("SADEED", "sadeed", "Sadeed")):
            self.assertEqual({registry.normalize_name(v) for v in variants}, {registry.normalize_name(variants[0])}, variants)
        self.assertNotEqual(registry.normalize_name("سديد"), registry.normalize_name("سديدة"))

    def test_resolve_each_covered_project_in_both_languages(self):
        cases = {"biz-pulse-ar": ("طور سديد", "SADEED"), "biltix": ("بلتكس", "Biltix", "بيلتكس"),
                 "faisal-aljuhaimy-portfolio": ("فيصل الجهيمي بورتفوليو", "Faisal Aljuhaimy Portfolio", "the portfolio"),
                 "kpi": ("مؤشرات الأداء", "KPI", "kpis"), "security-lab": ("المختبر الأمني", "security lab", "مختبر الأمن"),
                 "wow-bus": ("واو باص",)}
        for project, texts in cases.items():
            for text in texts:
                result = registry.resolve(text, environ=self.env)
                self.assertEqual((result["status"], result["project"]["id"]), ("resolved", project), text)
                self.assertNotIn("private", result["project"], text)
        sadeed = registry.resolve("سديد", environ=self.env)["project"]
        self.assertEqual(sadeed["names"], {"en": "SADEED", "ar": "سديد"})
        self.assertEqual(sadeed["repository_check"]["status"], "registered-public")
        self.assertEqual(registry.resolve("بلتكس", environ=self.env)["project"]["repository_check"]["status"], "unverified")

    def test_unknown_similar_and_ambiguous_names_need_clarification(self):
        unknown = registry.resolve("المشروع", environ=self.env)
        self.assertEqual((unknown["status"], unknown["candidates"]), ("needs-clarification", []))
        self.assertIn("security-lab", unknown["known_projects"])
        similar = registry.resolve("سديدة", environ=self.env)
        self.assertEqual((similar["status"], similar["candidates"]), ("needs-clarification", ["biz-pulse-ar"]))
        self.assertNotIn("project", similar)
        both = registry.resolve("سديد وبلتكس", environ=self.env)
        self.assertEqual((both["status"], both["candidates"]), ("needs-clarification", ["biltix", "biz-pulse-ar"]))
        for bad in ("", "  ", None, "x" * 2001):
            with self.assertRaises(registry.RegistryError):
                registry.resolve(bad, environ=self.env)

    # --- public catalog -------------------------------------------------------------------------

    def test_public_catalog_holds_only_public_safe_identifiers(self):
        data = json.loads((ROOT / "projects/aliases.json").read_text(encoding="utf-8"))
        public = {row["id"] for row in json.loads((ROOT / "projects/registry.json").read_text())["projects"]}
        ids = {row["id"] for row in data["catalog"]}
        self.assertLessEqual({"biz-pulse-ar", "biltix", "faisal-aljuhaimy-portfolio", "kpi", "security-lab"}, ids)
        for row in data["catalog"]:
            self.assertLessEqual(set(row), registry.CATALOG_FIELDS, row["id"])
            self.assertEqual(row["repository_status"] == "public-registry", row["id"] in public, row["id"])
            for value in registry._strings(row):
                self.assertNotRegex(value, r"://|github\.com|@", row["id"])
        self.assertLessEqual(set(data["aliases"]), public)

    def test_catalog_tampering_fails_closed(self):
        public, legacy, catalog = registry._public_sources()
        cases = []
        for change in (lambda c: c[3].update(repository="https://github.com/example-owner/x"),
                       lambda c: c[3].update(note="lives at https://github.com/example-owner/x"),
                       lambda c: c[3].update(note="ask owner@example.com"),
                       lambda c: c[3].update(repository_status="public-registry"),
                       lambda c: c[0].update(repository_status="unverified"),
                       lambda c: c[3].update(names={"en": "BILTIX"}),
                       lambda c: c[3].update(names={"en": "BILTIX", "ar": "BILTIX"}),
                       lambda c: c[3].update(observed={"exists": True, "visibility": "private", "date": "x", "method": "y"}),
                       lambda c: c.append(copy.deepcopy(c[3])),
                       lambda c: c[3].update(aliases=["سديد"]),
                       lambda c: c[3].update(aliases=["طور"])):
            rows = copy.deepcopy(catalog)
            change(rows)
            cases.append(rows)
        for rows in cases:
            with self.assertRaises(router.RouteError, msg=rows):
                registry._build(public, legacy, rows, [])
        self.assertTrue(registry._build(public, legacy, catalog, []))

    # --- private registry ---------------------------------------------------------------------

    def test_register_is_a_dry_run_unless_applied_and_writes_only_outside_git(self):
        planned = registry.register("biltix", environ=self.env, repository=SITE, path="hse")
        self.assertEqual(planned["status"], "would-register")
        self.assertFalse(self.home.exists())
        done = self.register("biltix", repository=SITE, path="hse")
        self.assertEqual((done["status"], done["record_sha256"]), ("registered", planned["record_sha256"]))
        path = self.home / "projects.json"
        self.assertEqual(done["private_registry"], str(path))
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(json.loads(path.read_text())["projects"][0]["repository"], SITE)
        self.assertEqual(registry.get("biltix", environ=self.env)["repository_check"]["status"], "registered-private")
        with self.assertRaises(router.RouteError):
            registry.private_path({"GAIE_HOME": str(ROOT / "private-state")})  # inside a Git work tree
        with self.assertRaises(router.RouteError):
            registry.register("biltix", environ={"GAIE_HOME": str(ROOT / "private-state")}, apply=True, repository=SITE)
        self.assertFalse((ROOT / "private-state").exists())

    def test_register_refuses_overwrite_without_replace(self):
        self.register("kpi", repository="https://github.com/example-owner/kpi")
        with self.assertRaises(registry.RegistryError):
            self.register("kpi", repository="https://github.com/example-owner/kpi2")
        self.register("kpi", repository="https://github.com/example-owner/kpi2", replace=True)
        self.assertEqual(registry.get("kpi", private=True, environ=self.env)["private"]["repository"],
                         "https://github.com/example-owner/kpi2")

    def test_register_validation_negative_cases(self):
        bad = (
            ("Bad Id", {"repository": SITE}),
            ("kpi", {"repository": "http://github.com/example-owner/kpi"}),
            ("kpi", {"repository": "git@github.com:example-owner/kpi.git"}),
            ("kpi", {"repository": "https://gitlab.com/example-owner/kpi"}),
            ("kpi", {"repository": "https://github.com/example-owner/.."}),
            ("kpi", {"repository": SITE, "path": "../escape"}),
            ("kpi", {"repository": SITE, "path": "/abs"}),
            ("kpi", {"repository": SITE, "path": ".git/hooks"}),
            ("kpi", {"repository": SITE, "path": "a/../../b"}),
            ("kpi", {"path": "orphan"}),
            ("kpi", {"repository": SITE, "approved_hub_revision": "main"}),
            ("kpi", {"repository": SITE, "capability_manifest": "../x.json"}),
            ("kpi", {"repository": SITE, "project_skills": ["Not A Slug"]}),
            ("kpi", {"repository": SITE, "deployment_target": {"token": "ghp_" + "a" * 36}}),
            ("kpi", {"repository": SITE, "deployment_target": {"note": "password=hunter2hunter2"}}),
            ("kpi", {"repository": SITE, "database_target": {"url": "postgres://user:" + "fake-pw" + "@db.example/x"}}),
            ("kpi", {"repository": SITE, "database_target": {"size": 1.5}}),
            ("kpi", {"repository": SITE, "deployment_target": {}}),
            ("kpi", {"repository": SITE, "visibility": "secret"}),
            ("kpi", {"repository": SITE, "owner_email": "x"}),
            ("kpi", {"repository": SITE, "aliases": ["طور"]}),             # alias is a command word
            ("kpi", {"repository": SITE, "aliases": ["سديد"]}),            # alias of another project
            ("kpi", {"repository": SITE, "aliases": ["kpi‮"]}),       # control character
            ("biz-pulse-ar", {"repository": "https://github.com/example-owner/other"}),  # conflicts with public row
            ("biz-pulse-ar", {"path": "sub"}),
            ("copy", {"repository": "https://github.com/faisaljohaimy-ship-it/biz-pulse-ar"}),  # repo under two ids
            ("brand-new", {}),                                             # private-only project needs a repository
        )
        for project, fields in bad:
            with self.assertRaises((registry.RegistryError, router.RouteError), msg=(project, fields)):
                self.register(project, **fields)
        self.assertFalse((self.home / "projects.json").exists())

    def test_two_projects_may_share_a_repository_only_in_different_folders(self):
        self.register("faisal-aljuhaimy-portfolio", repository=SITE, path="portfolio")
        self.register("security-lab", repository=SITE, path="lab")
        with self.assertRaises(registry.RegistryError):
            self.register("kpi", repository=SITE, path="lab")
        with self.assertRaises(registry.RegistryError):
            self.register("kpi", repository=SITE + ".git", path="portfolio")  # same repository, other spelling
        self.register("kpi", repository=SITE)  # the whole repository is a different place from its folders
        self.assertEqual(registry.get("security-lab", private=True, environ=self.env)["private"]["path"], "lab")

    def test_private_registry_file_is_validated_on_every_read(self):
        self.home.mkdir(parents=True)
        path = self.home / "projects.json"
        for content in ('{"schema_version": 2, "projects": []}', '{"schema_version": true, "projects": []}',
                        '{"schema_version": 1, "projects": {}}', '{"schema_version": 1, "projects": [{"id": "kpi", "x": 1}]}',
                        '{"schema_version": 1, "projects": [{"id": "kpi"}, {"id": "kpi"}]}', "[]",
                        '{"schema_version": 1, "schema_version": 1, "projects": []}'):
            path.write_text(content, encoding="utf-8")
            with self.assertRaises((router.RouteError, ValueError), msg=content):
                registry.load(self.env)
        path.unlink()
        target = self.home / "elsewhere.json"
        target.write_text('{"schema_version": 1, "projects": []}')
        path.symlink_to(target)
        with self.assertRaises(registry.RegistryError):
            registry.load(self.env)
        with self.assertRaises(registry.RegistryError):
            self.register("kpi", repository=SITE)

    # --- isolation ----------------------------------------------------------------------------

    def test_one_projects_private_record_is_never_returned_for_another(self):
        self.register("biltix", repository="https://github.com/example-owner/biltix", aliases=["بلتكس برو"],
                      deployment_target={"provider": "example-host", "project": "biltix-prod"},
                      database_target={"provider": "example-db", "project": "biltix-db"},
                      approved_hub_revision="a" * 40, project_skills=["gaie-upgrade"], authorized_integrations=["example-host"])
        self.register("kpi", repository="https://github.com/example-owner/kpi",
                      deployment_target={"provider": "example-host", "project": "kpi-prod"})
        biltix_secret_words = ("biltix-prod", "biltix-db", "example-owner/biltix", "بلتكس برو", "a" * 40)
        kpi = json.dumps(registry.get("kpi", private=True, environ=self.env), ensure_ascii=False)
        sadeed = json.dumps(registry.get("biz-pulse-ar", private=True, environ=self.env), ensure_ascii=False)
        for word in biltix_secret_words:
            self.assertNotIn(word, kpi)
            self.assertNotIn(word, sadeed)
        self.assertIn("kpi-prod", kpi)
        self.assertIsNone(registry.get("biz-pulse-ar", private=True, environ=self.env)["private"])
        public = registry.get("biltix", environ=self.env)
        self.assertNotIn("private", public)
        self.assertNotIn("biltix-prod", json.dumps(public, ensure_ascii=False))
        self.assertNotIn("بلتكس برو", public["aliases"])  # private aliases stay private
        resolved = registry.resolve("بلتكس برو", environ=self.env)  # ... but still resolve for the owner
        self.assertEqual(resolved["project"]["id"], "biltix")
        self.assertNotIn("biltix-prod", json.dumps(resolved, ensure_ascii=False))
        rows = registry.routing_rows(self.env)
        self.assertNotIn("biltix-prod", json.dumps({k: v for k, v in rows["kpi"].items() if k != "_keys"}, ensure_ascii=False))
        self.assertEqual(registry.get("biltix", private=True, environ=self.env)["private"]["deployment_target"]["project"],
                         "biltix-prod")
        with self.assertRaises(registry.RegistryError):
            registry.get("unknown-project", environ=self.env)
        other = {"GAIE_HOME": str(self.home.parent / "other-home")}  # another private home sees nothing
        self.assertEqual(registry.get("biltix", environ=other)["repository_check"]["status"], "unverified")

    def test_private_only_project_exposes_no_private_name_in_its_public_view(self):
        self.register("client-x", repository="https://github.com/example-owner/client-x", aliases=["عميل اكس"])
        view = registry.get("client-x", environ=self.env)
        self.assertEqual((view["aliases"], view["names"], view["visibility"]), (["client-x"], None, "private"))
        self.assertEqual(registry.resolve("عميل اكس", environ=self.env)["project"]["id"], "client-x")

    def test_history_append_is_validated_and_bounded(self):
        with self.assertRaises(registry.RegistryError):
            registry.append("kpi", "release_history", {"revision": "x"}, environ=self.env, apply=True)  # not registered
        self.register("kpi", repository="https://github.com/example-owner/kpi")
        self.assertEqual(registry.append("kpi", "checkpoints", {"label": "baseline"}, environ=self.env)["status"], "would-append")
        self.assertEqual(registry.get("kpi", private=True, environ=self.env)["private"]["checkpoints"], [])
        registry.append("kpi", "release_history", {"revision": "b" * 40, "result": "simulated"}, environ=self.env, apply=True)
        registry.append("kpi", "checkpoints", {"label": "baseline", "tests": 12}, environ=self.env, apply=True)
        private = registry.get("kpi", private=True, environ=self.env)["private"]
        self.assertEqual(private["release_history"], [{"revision": "b" * 40, "result": "simulated"}])
        self.assertEqual(private["checkpoints"], [{"label": "baseline", "tests": 12}])
        for field, entry in (("deployment_target", {"a": "b"}), ("release_history", {"token": "sk-" + "x" * 30}),
                             ("checkpoints", "text"), ("checkpoints", {"Bad Key": "x"})):
            with self.assertRaises(registry.RegistryError, msg=(field, entry)):
                registry.append("kpi", field, entry, environ=self.env, apply=True)
        with mock.patch.object(registry, "MAX_HISTORY", 1), self.assertRaises(registry.RegistryError):
            registry.append("kpi", "checkpoints", {"label": "second"}, environ=self.env, apply=True)

    def test_router_uses_the_registry(self):
        self.assertEqual(router.route("طور بلتكس", environ=self.env)["status"], "needs-clarification")
        self.register("biltix", repository="https://github.com/example-owner/biltix")
        plan = router.route("طور بلتكس", environ=self.env)
        self.assertEqual((plan["status"], plan["project"], plan["repository_check"]["status"]),
                         ("routed", "biltix", "registered-private"))
        self.assertEqual(plan["targets"][0]["repository"], "https://github.com/example-owner/biltix")

    def test_vendored_copy_with_the_registry_beside_the_router(self):
        engine = self.home.parent / "engine"
        engine.mkdir()
        for source, name in (("engineering_os/gaie_router.py", "gaie_router.py"), ("engineering_os/gaie_memory.py", "gaie_memory.py"),
                             ("engineering_os/project_registry.py", "project_registry.py"),
                             ("governance/policies/gaie-routes.json", "gaie-routes.json"),
                             ("projects/registry.json", "projects.json"), ("projects/aliases.json", "aliases.json")):
            (engine / name).write_bytes((ROOT / source).read_bytes())
        env = {**os.environ, **self.env}
        run = lambda *args: subprocess.run([sys.executable, *args], capture_output=True, text=True, env=env, cwd=self.home.parent)
        done = run(str(engine / "project_registry.py"), "register", "biltix", "--repository",
                   "https://github.com/example-owner/biltix", "--apply")
        self.assertEqual(json.loads(done.stdout)["status"], "registered", done.stderr)
        plan = json.loads(run(str(engine / "gaie_router.py"), "route", "upgrade BILTIX").stdout)
        self.assertEqual((plan["status"], plan["engine_id"], plan["repository_check"]["status"]),
                         ("routed", "master-upgrade", "registered-private"))
        audit = json.loads(run(str(engine / "gaie_router.py"), "route", "افحص سديد").stdout)
        self.assertEqual(audit["grant_template"]["max_side_effect"], "none")

    def test_cli(self):
        env = {**os.environ, **self.env}
        run = lambda *args: subprocess.run([sys.executable, "-m", "engineering_os.project_registry", *args],
                                           capture_output=True, text=True, env=env, cwd=ROOT)
        dry = run("register", "kpi", "--repository", "https://github.com/example-owner/kpi", "--deployment", "provider=example")
        self.assertEqual((dry.returncode, json.loads(dry.stdout)["status"]), (0, "would-register"))
        self.assertFalse(self.home.exists())
        done = run("register", "kpi", "--repository", "https://github.com/example-owner/kpi", "--deployment", "provider=example",
                   "--skill", "gaie-upgrade", "--apply")
        self.assertEqual((done.returncode, json.loads(done.stdout)["status"]), (0, "registered"))
        private = run("get", "kpi", "--private")
        self.assertEqual(json.loads(private.stdout)["private"]["deployment_target"], {"provider": "example"})
        self.assertNotIn("private", json.loads(run("get", "kpi").stdout))
        unclear = run("resolve", "المشروع")
        self.assertEqual((unclear.returncode, json.loads(unclear.stdout)["status"]), (2, "needs-clarification"))
        bad = run("register", "kpi", "--repository", "https://evil.example/kpi", "--replace", "--apply")
        self.assertEqual((bad.returncode, json.loads(bad.stdout)["status"]), (1, "error"))
        listed = json.loads(run("list").stdout)
        self.assertIn("security-lab", {row["id"] for row in listed})
        self.assertNotIn("example-owner", run("list").stdout)


if __name__ == "__main__":
    unittest.main()
