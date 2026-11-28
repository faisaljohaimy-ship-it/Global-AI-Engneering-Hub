"""Master Build Engine (L16): specification gate, workspace safety, generation, receipts, repository gate.

Builds here use verify=False (generation, static checks, local Git) so they stay fast;
tests/test_build_engine_e2e.py runs Scenario A with the generated unit/API/Playwright
suites. Everything is real: files, SQLite, Git and receipts. No network is used and no
GitHub call is made; the push mechanics are proven against a local bare repository.
"""
import copy
import hashlib
import importlib
import inspect
import json
import os
import pathlib
import socket
import subprocess
import tempfile
import unittest
import urllib.request
from unittest import mock

import hublink
from engineering_os import build_engine as engine
from engineering_os import contracts, factory

ROOT = pathlib.Path(__file__).resolve().parents[1]
COMMAND = "ابنِ نظامًا جديدًا لإدارة المشاريع"
NOW = "2026-11-28T00:00:00Z"


def main_revision():
    for ref in ("refs/remotes/origin/main", "refs/heads/main"):
        result = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--verify", "--quiet", ref],
                                capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout.strip()
    return hublink.head()


def scenario_a_spec():
    """Hand-written gaie.spec/1 fixture in exactly the SPEC_FORMAT shape (Scenario A)."""
    return {
        "schema": "gaie.spec/1",
        "source": {"command": COMMAND, "language": "ar", "sha256": hashlib.sha256(COMMAND.encode()).hexdigest()},
        "title": {"ar": "نظام إدارة المشاريع", "en": "Project Management System"},
        "slug": "project-management",
        "product_type": "web-app",
        "domain": "project-management",
        "locales": ["ar", "en"],
        "roles": [{"id": "admin", "permissions": ["*"]}, {"id": "member", "permissions": ["read", "write:own"]}],
        "entities": [
            {"name": "Project", "fields": [
                {"name": "title", "type": "text", "required": True, "max": 200},
                {"name": "status", "type": "enum", "values": ["planned", "active", "done"], "required": True}]},
            {"name": "Task", "fields": [
                {"name": "title", "type": "text", "required": True, "max": 200},
                {"name": "due_date", "type": "date", "required": False},
                {"name": "done", "type": "bool", "required": True, "default": False}]},
        ],
        "relations": [{"from": "Task", "to": "Project", "kind": "many-to-one", "required": True}],
        "features": [
            {"id": "F1", "title": {"ar": "إنشاء المشاريع وعرضها", "en": "Create and list projects"},
             "acceptance": ["POST /api/projects with a valid body returns 201 and the record",
                            "GET /api/projects lists created projects"]},
            {"id": "F2", "title": {"ar": "المهام تنتمي إلى المشاريع", "en": "Tasks belong to projects"},
             "acceptance": ["POST /api/tasks with a project_id that does not exist returns 409",
                            "Deleting a project that still has tasks returns 409",
                            "GET /api/tasks/{id} returns 404 for an unknown task"]},
            {"id": "F3", "title": {"ar": "تعديل المهام وحذفها", "en": "Edit and delete tasks"},
             "acceptance": ["PUT /api/tasks/{id} updates a task",
                            "DELETE /api/tasks/{id} removes a task and returns 204"]},
            {"id": "F4", "title": {"ar": "واجهة ثنائية اللغة", "en": "Bilingual interface"},
             "acceptance": ["A project and a task can be created through the UI in Arabic (RTL)",
                            "A project and a task can be created through the UI in English (LTR)"]},
            {"id": "F5", "title": {"ar": "التحقق من المدخلات", "en": "Input validation"},
             "acceptance": ["Invalid input returns 400 with field errors"]},
        ],
        "nfr": {"security": ["input validation", "no secrets in repo", "parameterized SQL"],
                "performance": ["p95 API latency < 200 ms locally"],
                "accessibility": ["keyboard navigable", "labels on form fields"],
                "i18n": ["ar rtl", "en ltr"]},
        "ai": {"needed": False, "use_cases": []},
        "integrations": [],
        "constraints": {"runtime": "python3-stdlib", "database": "sqlite", "no_paid_services": True},
        "open_questions": [],
    }


def git(cwd, *args):
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(cwd), "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_CONFIG_GLOBAL": os.devnull, "LC_ALL": "C"}
    return subprocess.run(["git", "-c", "core.hooksPath=" + os.devnull, "-C", str(cwd), *args],
                          capture_output=True, text=True, env=env)


class Workspace(unittest.TestCase):
    """A private workspace and GAIE_HOME outside every Git repository."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="gaie-build-test-")
        self.addCleanup(temporary.cleanup)
        self.tmp = pathlib.Path(temporary.name)
        self.workspace = self.tmp / "workspace"
        self.workspace.mkdir()
        self.environ = {"GAIE_HOME": str(self.tmp / "gaie-home")}
        self.revision = main_revision()

    def build(self, spec=None, name="project-management", **kwargs):
        options = {"hub_revision": self.revision, "workspace": self.workspace, "environ": self.environ,
                   "now": NOW, "verify": False}
        options.update(kwargs)
        return engine.build(spec or scenario_a_spec(), out_dir=self.workspace / name, **options)


class SpecificationTests(unittest.TestCase):
    def test_fixture_is_valid_and_planning_is_deterministic(self):
        spec = scenario_a_spec()
        self.assertEqual(engine.validate_spec(spec), spec)
        first = engine.plan(spec)
        self.assertEqual(first, engine.plan(copy.deepcopy(spec)))
        self.assertEqual(first["collections"], ["/api/projects", "/api/tasks"])
        self.assertEqual(first["factory_stages"], ["requirements", "architecture", "database", "api", "backend",
                                                   "frontend", "testing", "security", "documentation", "release"])
        self.assertEqual(first["unmapped_criteria"], [])
        self.assertEqual(first["translation_gaps"], [])
        self.assertEqual(first["expected_tests"], {"python": 47, "e2e": 19})
        self.assertEqual({item["id"] for item in first["open_items"]}, {"OI-REPO", "OI-LICENSE", "OI-DEPLOY", "OI-AUTH"})

    def test_invalid_specifications_are_refused(self):
        def change(path, value):
            spec = scenario_a_spec()
            target = spec
            for key in path[:-1]:
                target = target[key]
            if value is KeyError:
                del target[path[-1]]
            else:
                target[path[-1]] = value
            return spec

        token = "gh" + "p_" + "A1b2C3d4" * 5
        cases = {
            "schema": change(["schema"], "gaie.spec/2"),
            "missing key": change(["nfr"], KeyError),
            "extra key": {**scenario_a_spec(), "extra": 1},
            "slug": change(["slug"], "Project Management"),
            "locales": change(["locales"], ["fr"]),
            "entity name": change(["entities", 0, "name"], "project"),
            "field type": change(["entities", 0, "fields", 0, "type"], "blob"),
            "enum values": change(["entities", 0, "fields", 1, "values"], []),
            "values on text": change(["entities", 0, "fields", 0, "values"], ["a"]),
            "reserved field": change(["entities", 0, "fields", 0, "name"], "id"),
            "default type": change(["entities", 1, "fields", 2, "default"], "no"),
            "text max": change(["entities", 0, "fields", 0, "max"], 0),
            "relation entity": change(["relations", 0, "to"], "Ghost"),
            "relation kind": change(["relations", 0, "kind"], "one-to-one"),
            "duplicate entity": change(["entities", 1, "name"], "Project"),
            "control text": change(["title", "en"], "Project\x00System"),
            "secret text": change(["title", "en"], "Project " + token),
            "no acceptance": change(["features", 0, "acceptance"], []),
            "feature id": change(["features", 1, "id"], "F1"),
            "source digest": change(["source", "sha256"], "not-a-digest"),
            "paid services": change(["constraints", "no_paid_services"], False),
            "not an object": ["not", "a", "spec"],
        }
        spec = scenario_a_spec()
        spec["relations"] = [{"from": "Task", "to": "Task", "kind": "many-to-one", "required": True}]
        cases["required self relation"] = spec
        spec = scenario_a_spec()
        spec["relations"].append({"from": "Project", "to": "Task", "kind": "many-to-one", "required": True})
        cases["required cycle"] = spec
        for label, spec in cases.items():
            with self.subTest(label):
                with self.assertRaises(engine.SpecError):
                    engine.plan(spec)

    def test_unsupported_requests_are_refused_not_dropped(self):
        cases = {
            "ai": ("ai", {"needed": True, "use_cases": ["summaries"]}),
            "integrations": ("integrations", ["email"]),
            "product type": ("product_type", "mobile-app"),
            "runtime": ("constraints", {"runtime": "node", "database": "sqlite", "no_paid_services": True}),
        }
        for label, (key, value) in cases.items():
            with self.subTest(label):
                spec = scenario_a_spec()
                spec[key] = value
                with self.assertRaises(engine.UnsupportedSpec):
                    engine.validate_spec(spec)
        spec = scenario_a_spec()
        spec["relations"].append({"from": "Project", "to": "Task", "kind": "many-to-many", "required": True})
        with self.assertRaises(engine.UnsupportedSpec):
            engine.validate_spec(spec)

    def test_open_questions_go_to_the_owner(self):
        spec = scenario_a_spec()
        spec["open_questions"] = ["Which identity provider should be used?"]
        with self.assertRaises(engine.OpenQuestions):
            engine.validate_spec(spec)
        self.assertEqual(engine.validate_spec(spec, allow_open_questions=True)["open_questions"], spec["open_questions"])


class ModelTests(unittest.TestCase):
    def test_model_order_relations_and_labels(self):
        spec = scenario_a_spec()
        spec["entities"].reverse()
        model = engine.derive_model(engine.validate_spec(spec))
        self.assertEqual([e["name"] for e in model["entities"]], ["Project", "Task"])
        task = model["entities"][1]
        self.assertEqual(task["references"], [{"field": "project_id", "entity": "Project", "table": "project",
                                               "required": True, "relation": "many-to-one"}])
        self.assertEqual(task["label_field"], "title")
        self.assertEqual(model["labels"]["ar"]["entities"]["Project"], {"singular": "مشروع", "plural": "المشاريع"})
        self.assertEqual(model["labels"]["ar"]["fields"]["Task"]["project_id"], "مشروع")
        self.assertEqual(model["labels"]["ar"]["values"]["Project"]["status"]["planned"], "مخطط")
        self.assertEqual(model["p95_ms"], 200)

    def test_translation_gaps_are_reported_and_many_to_many_is_modelled(self):
        spec = scenario_a_spec()
        spec["entities"].append({"name": "Widget", "fields": [{"name": "gizmo", "type": "text", "required": True}]})
        spec["relations"].append({"from": "Project", "to": "Widget", "kind": "many-to-many", "required": False})
        model = engine.derive_model(engine.validate_spec(spec))
        self.assertIn("entity Widget", model["translation_gaps"])
        self.assertIn("field Widget.gizmo", model["translation_gaps"])
        project = model["entities"][0]
        self.assertEqual(project["links"][0]["field"], "widget_ids")
        self.assertIn("OI-I18N", {item["id"] for item in engine.open_items_for(spec, model)})
        up, down = engine.migrations_sql(model)
        self.assertIn('CREATE TABLE "project_widget_link"', up)
        self.assertIn('DROP TABLE IF EXISTS "project_widget_link"', down)

    def test_acceptance_criteria_map_to_named_evidence(self):
        spec = engine.validate_spec(scenario_a_spec())
        model = engine.derive_model(spec)
        api = engine.API_ID
        cases = {
            "POST /api/projects with a valid body returns 201 and the record": {api + "test_create_project"},
            "PUT /api/tasks/{id} updates a task": {api + "test_update_task"},
            "GET /api/tasks/{id} returns 404 for an unknown task": {api + "test_not_found_task"},
            "POST /api/tasks with a project_id that does not exist returns 409": {
                api + "test_create_task", api + "test_reference_task_project_id_missing",
                api + "test_reference_task_project_id_delete_parent"},
            "A project and a task can be created through the UI in Arabic (RTL)": {
                "e2e:ar:language", "e2e:ar:project:create", "e2e:ar:task:create"},
            "no secrets in repo": {"static:security:secrets"},
            "keyboard navigable": {"e2e:keyboard"},
            "parameterized SQL": {api + "test_sql_injection_is_inert"},
        }
        for text, expected in cases.items():
            with self.subTest(text):
                self.assertEqual(set(engine.map_criterion(model, spec["locales"], text, [])), expected)
        self.assertEqual(engine.map_criterion(model, spec["locales"], "The product feels delightful", []), [])
        spec["features"][0]["acceptance"].append("The product feels delightful")
        self.assertEqual(engine.plan(spec)["unmapped_criteria"], ["f1-a3"])

    def test_generated_migrations_apply_and_revert(self):
        spec = engine.validate_spec(scenario_a_spec())
        model = engine.derive_model(spec)
        up, down = engine.migrations_sql(model)
        problems, detail = engine._migration_check({"migrations/0001_initial.up.sql": up.encode(),
                                                    "migrations/0001_initial.down.sql": down.encode()}, model)
        self.assertEqual(problems, [])
        self.assertEqual(detail["tables"], ["project", "task"])
        self.assertIn("ON DELETE RESTRICT", up)
        broken = up.replace('"project_id" INTEGER NOT NULL REFERENCES "project" ("id") ON DELETE RESTRICT,', "")
        problems, _ = engine._migration_check({"migrations/0001_initial.up.sql": broken.encode(),
                                               "migrations/0001_initial.down.sql": down.encode()}, model)
        self.assertTrue(problems)


class WorkspaceSafetyTests(Workspace):
    def test_out_dir_outside_the_workspace_is_refused(self):
        outside = self.tmp / "elsewhere"
        outside.mkdir()
        (self.workspace / "link").symlink_to(outside, target_is_directory=True)
        (self.workspace / "busy").mkdir()
        (self.workspace / "busy" / "file.txt").write_text("keep")
        cases = {
            "sibling of workspace": self.tmp / "project-management",
            "dot-dot escape": self.workspace / ".." / "project-management",
            "relative": pathlib.Path("project-management"),
            "nested": self.workspace / "a" / "project-management",
            "symlink escape": self.workspace / "link" / "project-management",
            "symlink target": self.workspace / "link",
            "not empty": self.workspace / "busy",
            "workspace itself": self.workspace,
            "bad name": self.workspace / "Project_Management",
            "system path": pathlib.Path("/etc/project-management"),
        }
        for label, out_dir in cases.items():
            with self.subTest(label):
                with self.assertRaises(engine.WorkspaceError):
                    engine.build(scenario_a_spec(), out_dir=out_dir, hub_revision=self.revision,
                                 workspace=self.workspace, environ=self.environ, verify=False)
        self.assertEqual(sorted(p.name for p in outside.iterdir()), [])
        self.assertFalse((self.tmp / "project-management").exists())
        self.assertEqual((self.workspace / "busy" / "file.txt").read_text(), "keep")

    def test_workspace_inside_the_hub_or_a_git_tree_is_refused(self):
        repo = self.tmp / "some-repo"
        repo.mkdir()
        git(repo, "init", "-q")
        for workspace in (ROOT / "projects", repo):
            with self.subTest(str(workspace.name)):
                with self.assertRaises(engine.WorkspaceError):
                    engine.build(scenario_a_spec(), out_dir=workspace / "project-management",
                                 hub_revision=self.revision, workspace=workspace, environ=self.environ, verify=False)
        self.assertFalse((ROOT / "projects" / "project-management").exists())

    def test_hub_revision_must_be_a_pinned_hub_commit(self):
        for revision in ("main", "f" * 40, "0" * 39, None):
            with self.subTest(revision):
                with self.assertRaises(engine.BuildError):
                    self.build(hub_revision=revision)
        self.assertEqual(list(self.workspace.iterdir()), [])


class GeneratedApplicationTests(Workspace):
    def setUp(self):
        super().setUp()
        self.report = self.build()
        self.app = pathlib.Path(self.report["out_dir"])

    def test_generated_application_is_independent_and_linked(self):
        self.assertEqual(self.report["static_checks"], {key: "passed" for key in self.report["static_checks"]})
        self.assertEqual(len(self.report["static_checks"]), 9)
        tracked = git(self.app, "ls-files").stdout.split()
        for required in ("app/server.py", "app/db.py", "app/model.py", "app/schema.json", "app/seed_data.json",
                         "static/index.html", "static/app.js", "static/i18n.json", "tests/test_api.py",
                         "tests/test_validation.py", "tests/e2e/ui.e2e.mjs", "migrations/0001_initial.up.sql",
                         "migrations/0001_initial.down.sql", "README.md", "CHANGELOG.md", "LICENSE-PENDING.md",
                         "docs/API.md", "docs/ARCHITECTURE.md", ".gaie/link.json", ".gaie/spec.json",
                         ".gaie/repository-request.json", ".gaie/factory/receipts.json", ".gitignore"):
            self.assertIn(required, tracked)
        self.assertNotIn("LICENSE", tracked)
        for relative in tracked:
            text = (self.app / relative).read_text(encoding="utf-8")
            self.assertNotIn(str(ROOT), text, relative)
            self.assertNotIn(str(self.tmp), text, relative)
            if relative.endswith(".py"):
                self.assertNotRegex(text, r"(?m)^\s*(?:from|import)\s+(?:engineering_os|hublink|hub)\b", relative)
        link = json.loads((self.app / ".gaie/link.json").read_text())
        self.assertEqual(hublink.validate_manifest(link), [])
        self.assertEqual(link["hub_revision"], self.revision)
        self.assertFalse(link["production_runtime_dependency"])
        self.assertEqual(link["runtime_imports_from_hub"], [])
        self.assertEqual({row["id"] for row in link["used"]},
                         {"template:app-stdlib", "catalog:microsoft/playwright", "engine:factory", "skill:gaie-build"})
        readme = (self.app / "README.md").read_text()
        for heading in ("## Run", "## Test", "## API", "## Security", "## Open items for the owner"):
            self.assertIn(heading, readme)
        self.assertIn("OI-LICENSE", readme)
        index = (self.app / "static/index.html").read_text()
        self.assertIn('<html lang="ar" dir="rtl">', index)
        self.assertIn("نظام إدارة المشاريع", index)
        package = json.loads((self.app / "package.json").read_text())
        self.assertEqual(package["devDependencies"], {"playwright": "1.65.1"})
        self.assertNotIn("license", package)

    def test_application_is_its_own_git_repository(self):
        log = git(self.app, "log", "--format=%H %an <%ae> %s").stdout.splitlines()
        self.assertEqual(len(log), 2)
        self.assertTrue(log[1].startswith(self.report["source_commit"]))
        self.assertIn("feat: initial project-management application", log[1])
        self.assertTrue(log[0].startswith(self.report["evidence_commit"]))
        self.assertEqual(git(self.app, "status", "--porcelain").stdout, "")
        self.assertEqual(git(self.app, "branch", "--show-current").stdout.strip(), "main")
        self.assertEqual(git(self.app, "remote").stdout, "")
        self.assertEqual(list((self.app / ".git" / "hooks").glob("*")), [])
        self.assertEqual(self.report["untracked_after_build"], [])

    def test_unverified_build_is_never_delivery_ready(self):
        evaluation = self.report["factory"]
        self.assertFalse(self.report["ok"])
        self.assertFalse(evaluation["delivery_review_ready"])
        statuses = {stage["id"]: stage["status"] for stage in evaluation["stages"]}
        # Only stages whose checks are fully static can verify; the database stage also needs the
        # generated migration tests to have run, and every later stage needs executed suites.
        self.assertEqual({k for k, v in statuses.items() if v == "verified"}, {"requirements", "architecture"})
        self.assertEqual(statuses["database"], "blocked")
        self.assertEqual(statuses["api"], "blocked")
        self.assertEqual(self.report["tests"]["python"]["status"], "not-run")
        self.assertEqual(engine.evaluate(self.app), evaluation)
        detail = json.loads((self.app / ".gaie/factory/details/api-contract.json").read_text())
        self.assertEqual(detail["status"], "not-run")
        self.assertFalse(evaluation["deployment_authorized"])
        self.assertEqual(self.report["provider_calls"], 0)

    def test_receipts_are_factory_receipts_and_tampering_withdraws_them(self):
        root = self.app / ".gaie/factory"
        request = json.loads((root / "request.json").read_text())
        self.assertEqual(request["source_revision"], self.report["source_commit"])
        plan = factory.plan_factory(request)
        receipts = json.loads((root / "receipts.json").read_text())
        before = factory.evaluate_factory(plan, receipts, artifact_root=root)
        self.assertEqual(before["verified_count"], 2)
        artifact = root / "artifacts/requirements.json"
        artifact.write_text(artifact.read_text().replace("synthetic", "changed"))
        after = factory.evaluate_factory(plan, receipts, artifact_root=root)
        self.assertEqual(after["verified_count"], 0)

    def test_source_commit_is_deterministic(self):
        other = self.tmp / "second-workspace"
        other.mkdir()
        again = engine.build(scenario_a_spec(), out_dir=other / "project-management", hub_revision=self.revision,
                             workspace=other, environ=self.environ, now=NOW, verify=False)
        self.assertEqual(again["source_commit"], self.report["source_commit"])

    def test_duplicates_are_refused(self):
        with self.assertRaises(engine.DuplicateProject) as caught:
            self.build(name="project-management-two")
        self.assertEqual(caught.exception.matches[0]["source"], "workspace")
        self.assertFalse((self.workspace / "project-management-two").exists())

    def test_duplicate_projects_in_registries_are_refused(self):
        workspace = self.tmp / "fresh"
        workspace.mkdir()
        home = pathlib.Path(self.environ["GAIE_HOME"])
        home.mkdir()
        (home / "projects.json").write_text(json.dumps({"schema_version": 1, "projects": [
            {"id": "project-management", "repository": "https://github.com/example/project-management",
             "aliases": ["project management system"]}]}))
        with self.assertRaises(engine.DuplicateProject) as caught:
            engine.build(scenario_a_spec(), out_dir=workspace / "pm", hub_revision=self.revision,
                         workspace=workspace, environ=self.environ, verify=False)
        self.assertEqual(caught.exception.matches[0]["source"], "private-overlay")
        public = scenario_a_spec()
        public["slug"] = "wow-bus"
        with self.assertRaises(engine.DuplicateProject):
            engine.build(public, out_dir=workspace / "wow-bus", hub_revision=self.revision, workspace=workspace,
                         environ={"GAIE_HOME": str(self.tmp / "other-home")}, verify=False)
        self.assertEqual(list(workspace.iterdir()), [])

    def test_project_registry_is_used_when_available_and_skipped_when_absent(self):
        workspace = self.tmp / "registry"
        workspace.mkdir()
        calls = []

        def finder(slug, title=None):
            calls.append((slug, title["en"]))
            return [{"id": slug, "repository": "https://github.com/example/" + slug}]

        with self.assertRaises(engine.DuplicateProject):
            engine.build(scenario_a_spec(), out_dir=workspace / "pm", hub_revision=self.revision,
                         workspace=workspace, environ=self.environ, registry=finder, verify=False)
        self.assertEqual(calls, [("project-management", "Project Management System")])
        found = engine.find_existing(scenario_a_spec(), workspace=workspace, environ=self.environ,
                                     registry=type("Module", (), {})())
        self.assertIn("no find_existing", found["sources"][-1]["status"])
        try:
            importlib.import_module("engineering_os.project_registry")
        except ImportError:
            found = engine.find_existing(scenario_a_spec(), workspace=workspace, environ=self.environ)
            self.assertIn("not present", found["sources"][-1]["status"])


class NoNetworkTests(Workspace):
    def test_build_makes_no_network_calls(self):
        attempts = []

        def refuse(*args, **kwargs):
            attempts.append(args)
            raise AssertionError("network access attempted")

        with mock.patch.object(socket.socket, "connect", refuse), \
                mock.patch.object(socket, "create_connection", refuse), \
                mock.patch.object(urllib.request, "urlopen", refuse):
            report = self.build()
        self.assertEqual(attempts, [])
        self.assertEqual(report["provider_calls"], 0)
        request = json.loads((pathlib.Path(report["out_dir"]) / ".gaie/repository-request.json").read_text())
        self.assertEqual(request["network_calls_made"], 0)


class RepositoryGateTests(Workspace):
    def setUp(self):
        super().setUp()
        self.app = pathlib.Path(self.build()["out_dir"])
        self.bare = self.tmp / "remote.git"
        git(self.tmp, "init", "-q", "--bare", str(self.bare))
        self.token = "owner-approval-" + "7" * 24
        self.grant = {"grant_id": "g-owner-publish", "role": "master-build-engineer",
                      "engines": {"master-build": ["publish"]}, "paths": [str(self.workspace)],
                      "max_side_effect": "external-write", "expires_at": "2099-01-01T00:00:00Z",
                      "approvals": [{"side_effect": "external-write", "engine": "master-build", "action": "publish",
                                     "approved_by": "owner", "token_sha256": hashlib.sha256(self.token.encode()).hexdigest()}]}

    def refs(self):
        return git(self.bare, "for-each-ref").stdout

    def test_request_is_written_and_nothing_is_pushed_without_approval(self):
        request = json.loads((self.app / ".gaie/repository-request.json").read_text())
        self.assertEqual((request["name"], request["visibility"], request["status"]),
                         ("project-management", "private", "awaiting-approval"))
        self.assertIn("Project Management System", request["description"])
        with self.assertRaises(engine.ApprovalRequired):
            engine.publish(self.app, remote=str(self.bare))
        with self.assertRaises(engine.ApprovalRequired):
            engine.engine("publish", {"app_dir": str(self.app), "remote": str(self.bare)})
        with mock.patch.object(engine, "_git", side_effect=AssertionError("git must not run")):
            with self.assertRaises(engine.ApprovalRequired):
                engine.publish(self.app, remote="https://github.com/example/project-management.git")
        self.assertEqual(self.refs(), "")

    def test_forged_expired_or_narrow_approvals_are_refused(self):
        variants = {"wrong token": (self.grant, "guess"), "no token": (self.grant, None)}
        expired = copy.deepcopy(self.grant)
        expired["expires_at"] = "2020-01-01T00:00:00Z"
        variants["expired"] = (expired, self.token)
        narrow = copy.deepcopy(self.grant)
        narrow["max_side_effect"] = "workspace-write"
        variants["below external-write"] = (narrow, self.token)
        other_action = copy.deepcopy(self.grant)
        other_action["engines"] = {"master-build": ["build"]}
        variants["action not granted"] = (other_action, self.token)
        other_engine = copy.deepcopy(self.grant)
        other_engine["approvals"][0]["engine"] = "master-upgrade"
        variants["approval for another engine"] = (other_engine, self.token)
        malformed = copy.deepcopy(self.grant)
        malformed["approvals"][0]["token_sha256"] = "x"
        variants["malformed grant"] = (malformed, self.token)
        for label, (grant, token) in variants.items():
            with self.subTest(label):
                with self.assertRaises(engine.ApprovalRequired):
                    engine.publish(self.app, remote=str(self.bare), grant=grant, token=token, now=NOW)
        self.assertEqual(self.refs(), "")

    def test_approved_push_reaches_a_local_bare_repository(self):
        result = engine.publish(self.app, remote=str(self.bare), grant=self.grant, token=self.token, now=NOW)
        head = git(self.app, "rev-parse", "HEAD").stdout.strip()
        self.assertEqual((result["status"], result["remote_kind"], result["commit"]), ("pushed", "local-bare", head))
        self.assertEqual(git(self.bare, "rev-parse", "refs/heads/main").stdout.strip(), head)
        clone = self.tmp / "clone"
        git(self.tmp, "clone", "-q", "-b", "main", str(self.bare), str(clone))
        self.assertTrue((clone / "app/server.py").is_file())
        self.assertEqual(len(git(clone, "log", "--oneline").stdout.splitlines()), 2)

    def test_unsafe_remotes_are_refused_even_with_approval(self):
        not_bare = self.tmp / "plain"
        not_bare.mkdir()
        for remote in ("--upload-pack=touch /tmp/x", "ext::sh -c touch% /tmp/x", "git@github.com:example/x.git",
                       "https://github.com/example/another-name.git", "http://github.com/example/project-management",
                       "file:///etc", str(not_bare), "relative/path", ""):
            with self.subTest(remote):
                with self.assertRaises(engine.BuildError):
                    engine.publish(self.app, remote=remote, grant=self.grant, token=self.token, now=NOW)
        self.assertEqual(self.refs(), "")


class EngineContractTests(unittest.TestCase):
    def test_engine_record_satisfies_the_shared_contract(self):
        record = contracts.validate_engine(copy.deepcopy(engine.ENGINE_RECORD), check_imports=True)
        self.assertEqual(record["layer"], "L16")
        self.assertEqual(record["actions"]["publish"]["side_effect"], "external-write")
        self.assertIn(record["actions"]["publish"]["side_effect"], contracts.GATED)
        self.assertEqual(record["actions"]["build"]["side_effect"], "workspace-write")
        self.assertEqual(list(inspect.signature(engine.engine).parameters)[:3], ["action", "payload", "ctx"])

    def test_health_and_entrypoint(self):
        self.assertEqual(engine.health()["ok"], True)
        result = engine.engine("plan", {"spec": scenario_a_spec()}, {})
        self.assertEqual(result["project"], "project-management")
        with self.assertRaises(engine.BuildError):
            engine.engine("deploy", {}, {})
        with self.assertRaises(engine.BuildError):
            engine.engine("build", {"spec": scenario_a_spec(), "out_dir": "/tmp/x", "hub_revision": "a" * 40,
                                    "shell": "rm -rf /"}, {})
        with self.assertRaises(engine.SpecError):
            engine.engine("plan", {"spec": {"schema": "gaie.spec/1"}}, {})

    def test_template_manifest_matches_the_template_directory(self):
        manifest, files = engine._template_files()
        self.assertEqual(set(files) - set(manifest["files"]), {"manifest.json", "glossary.json", "ui-strings.json"})
        self.assertFalse((ROOT / "templates/app-stdlib/.gitignore").exists())


class RequirementsIntegrationTests(Workspace):
    def test_requirements_parse_output_is_buildable(self):
        try:
            requirements = importlib.import_module("engineering_os.requirements")
        except ImportError:
            self.skipTest("engineering_os.requirements is not in this branch yet (written by the L15 agent)")
        parse = getattr(requirements, "parse", None)
        if parse is None:
            self.skipTest("engineering_os.requirements has no parse() yet")
        spec = parse(COMMAND)
        self.assertEqual(spec["schema"], "gaie.spec/1")
        planned = engine.plan(spec, allow_open_questions=True)
        self.assertEqual(planned["project"], spec["slug"])
        if not spec["open_questions"]:
            report = self.build(spec, name=spec["slug"])
            self.assertEqual(report["static_checks"], {key: "passed" for key in report["static_checks"]})


if __name__ == "__main__":
    unittest.main()
