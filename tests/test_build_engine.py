"""Master Build Engine (L16): specification gate, workspace safety, generation, receipts, repository gate.

Builds here use verify=False (generation, static checks, local Git) so they stay fast;
tests/test_build_engine_e2e.py runs Scenario A with the generated unit/API/acceptance and
Playwright suites. Everything is real: files, SQLite, Git and receipts. No network is used
and no GitHub call is made; the push mechanics are proven against a local bare repository.
"""
import copy
import hashlib
import importlib
import inspect
import json
import os
import pathlib
import socket
import stat
import subprocess
import tempfile
import unittest
import urllib.request
from unittest import mock

import hublink
from engineering_os import build_engine as engine
from engineering_os import contracts, factory, requirements

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
    """Hand-written gaie.spec/1 fixture in the SPEC_FORMAT shape (plus the required `mode`)."""
    return {
        "schema": "gaie.spec/1",
        "mode": "deterministic",
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
                            "GET /api/projects returns 200 and lists the created records"]},
            {"id": "F2", "title": {"ar": "المهام تنتمي إلى المشاريع", "en": "Tasks belong to projects"},
             "acceptance": ["POST /api/tasks with a project_id that does not exist returns 400",
                            "GET /api/tasks/{id} with an unknown id returns 404",
                            "GET /api/projects/{id}/tasks returns 200 and only that project's tasks"]},
            {"id": "F3", "title": {"ar": "تعديل المهام وحذفها", "en": "Edit and delete tasks"},
             "acceptance": ["PATCH /api/tasks/{id} with a valid body returns 200 and the updated record",
                            "DELETE /api/tasks/{id} as admin returns 204",
                            "DELETE /api/tasks/{id} as member returns 403"]},
            {"id": "F4", "title": {"ar": "واجهة ثنائية اللغة", "en": "Bilingual interface"},
             "acceptance": ["GET /?lang=ar returns 200 and html with dir=rtl and lang=ar",
                            "GET /?lang=en returns 200 and html with dir=ltr and lang=en"]},
            {"id": "F5", "title": {"ar": "التحقق من المدخلات", "en": "Input validation"},
             "acceptance": ["POST /api/projects without title returns 400",
                            "POST /api/projects with status=not_a_value returns 400",
                            "GET /api/tasks without a session returns 401"]},
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
        self.assertTrue(requirements.is_ready(spec))
        self.assertEqual(engine.validate_spec(spec), spec)
        first = engine.plan(spec)
        self.assertEqual(first, engine.plan(copy.deepcopy(spec)))
        self.assertEqual(first["collections"], ["/api/projects", "/api/tasks"])
        self.assertEqual(first["factory_stages"], ["requirements", "architecture", "database", "api", "backend",
                                                   "frontend", "testing", "security", "documentation", "release"])
        self.assertEqual(first["unmapped_criteria"], {})
        self.assertEqual(first["acceptance"], {"criteria": 21, "executable": 13})
        self.assertEqual(first["translation_gaps"], [])
        self.assertEqual({item["id"] for item in first["open_items"]}, {"OI-REPO", "OI-LICENSE", "OI-DEPLOY", "OI-IDENTITY"})

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
            "mode": change(["mode"], KeyError),
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
            "relation entity": change(["relations", 0, "to"], "Ghost"),
            "relation kind": change(["relations", 0, "kind"], "one-to-one"),
            "duplicate entity": change(["entities", 1, "name"], "Project"),
            "control text": change(["title", "en"], "Project\x00System"),
            "secret text": change(["title", "en"], "Project " + token),
            "untestable criterion": change(["features", 0, "acceptance"], ["Projects can be created"]),
            "no acceptance": change(["features", 0, "acceptance"], []),
            "source digest": change(["source", "sha256"], "0" * 64),
            "paid services": change(["constraints", "no_paid_services"], False),
            "nfr keys": change(["nfr"], {"security": []}),
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
            "ai": ("ai", {"needed": True, "use_cases": ["summaries"], "provider": "local-model"}),
            "integrations": ("integrations", [{"id": "email", "title": {"ar": "بريد", "en": "Email"}, "paid": False,
                                               "network": True, "approved": True}]),
            "product type": ("product_type", "mobile-app"),
            "runtime": ("constraints", {"runtime": "node", "database": "sqlite", "no_paid_services": True}),
            "no administrator": ("roles", [{"id": "member", "permissions": ["read"]}]),
            "reserved table": ("entities", scenario_a_spec()["entities"] + [
                {"name": "AppAccount", "fields": [{"name": "title", "type": "text", "required": True}]}]),
        }
        for label, (key, value) in cases.items():
            with self.subTest(label):
                spec = scenario_a_spec()
                spec[key] = value
                if label == "reserved table":
                    spec["relations"].append({"from": "AppAccount", "to": "Project", "kind": "many-to-one", "required": False})
                with self.assertRaises(engine.UnsupportedSpec):
                    engine.validate_spec(spec)
        spec = scenario_a_spec()
        spec["relations"].append({"from": "Project", "to": "Task", "kind": "many-to-many", "required": True})
        with self.assertRaises(engine.UnsupportedSpec):
            engine.validate_spec(spec)

    def test_open_questions_go_to_the_owner(self):
        spec = requirements.parse("ابن نظاما جديدا")
        self.assertFalse(requirements.is_ready(spec))
        with self.assertRaises(engine.OpenQuestions):
            engine.validate_spec(spec)
        planned = engine.plan(spec, allow_open_questions=True)
        self.assertEqual(planned["ready"], False)
        self.assertTrue(planned["open_questions"])


class ModelTests(unittest.TestCase):
    def model(self, spec=None):
        spec = engine.validate_spec(spec or scenario_a_spec())
        return spec, engine.derive_model(spec)

    def test_model_order_relations_labels_and_auth(self):
        spec = scenario_a_spec()
        spec["entities"].reverse()
        _, model = self.model(spec)
        self.assertEqual([e["name"] for e in model["entities"]], ["Project", "Task"])
        task = model["entities"][1]
        self.assertEqual(task["references"], [{"field": "project_id", "attr": "project", "entity": "Project",
                                               "table": "project", "required": True, "relation": "many-to-one"}])
        self.assertEqual(task["default_order"], ["due_date"])
        self.assertEqual(model["entities"][0]["children"], [{"collection": "tasks", "entity": "Task", "field": "project_id"}])
        self.assertEqual(model["labels"]["ar"]["entities"]["Project"], {"singular": "مشروع", "plural": "المشاريع"})
        self.assertEqual(model["labels"]["ar"]["fields"]["Task"]["project_id"], "مشروع")
        self.assertEqual(model["labels"]["ar"]["values"]["Project"]["status"]["planned"], "مخطط")
        self.assertEqual(model["auth"]["admin_role"], "admin")
        self.assertIsNone(model["auth"]["principal"])
        self.assertIsNone(model["auth"]["scoping"])
        self.assertEqual(model["auth"]["pbkdf2_iterations"], 600000)
        self.assertEqual(model["nfr"], {"p95_ms": 200, "latency_records": 1000, "page_size": 50, "max_page_size": 200})

    def test_the_api_reference_states_the_authorization_the_generated_server_enforces(self):
        """W2-BU-01..04 (lane build-fixes) changed link, sub-resource, scoping and principal rules; docs/API.md says so."""
        spec, model = self.model(requirements.parse(COMMAND))
        doc = " ".join(engine._api_doc(spec, model).split())
        project = next(entity for entity in model["entities"] if entity["links"])
        base, link = f"/api/{project['collection']}", project["links"][0]
        self.assertIn(f"`{base}/{{id}}/{link['segment']}` | 200 / 201 | 400, 401, 403, 404, 409 |", doc)
        self.assertIn(f"| DELETE | `{base}/{{id}}/{link['segment']}/{{{link['target_key']}}}` | 204 | 401, 403, 404 |", doc)
        for sentence in ("`:own` limits a permission to records the account created",
                         "sub-resources (children, links, progress) are authorized like their parent record",
                         "adding a link needs write and removing one needs write and delete on its source record",
                         "(and every record whose references lead to them)",
                         "only a `*` role can change the principal e-mail field that identifies an account"):
            self.assertIn(sentence, doc)
        for stale in ("limits writes to records", "(and their children)", "| 204 | 404 |"):
            self.assertNotIn(stale, doc)

    def test_the_api_reference_states_the_sign_in_limits_of_the_template(self):
        """build-fixes-2 request: docs/API.md names Retry-After and the three windows auth.py enforces."""
        import math
        import re
        spec, model = self.model(requirements.parse(COMMAND))
        doc = " ".join(engine._api_doc(spec, model).split())
        auth = (ROOT / "templates/app-stdlib/app/auth.py").read_text(encoding="utf-8")
        def constant(name):  # an integer or a product of integers, as auth.py writes them
            factors = re.search(rf"^{name} = ([0-9 *]+)", auth, re.M).group(1).split("*")
            return math.prod(int(factor) for factor in factors)
        value = {name: constant(name) for name in ("LOCKOUT_SECONDS", "LOCKOUT_FAILURES", "ADDRESS_FAILURES",
                                                   "ACCOUNT_FAILURES", "KNOWN_SECONDS")}
        self.assertEqual((value["LOCKOUT_FAILURES"], value["LOCKOUT_SECONDS"] // 60), engine.SIGNIN_LIMIT)
        for sentence in ("`429 too_many_attempts` from `POST /api/login` carries `Retry-After` (seconds)",
                         f"sliding {value['LOCKOUT_SECONDS'] // 60}-minute windows",
                         f"{value['LOCKOUT_FAILURES']} per e-mail and client address",
                         f"{value['ADDRESS_FAILURES']} per client address (any e-mails)",
                         f"{value['ACCOUNT_FAILURES']} per e-mail across addresses",
                         f"within {value['KNOWN_SECONDS'] // 86400} days"):
            self.assertIn(sentence, doc)
        self.assertIn("## Entities", doc.split("Retry-After", 1)[1])  # below the route table, not inside it

    def test_real_requirements_output_derives_rules_scoping_and_links(self):
        spec, model = self.model(requirements.parse(COMMAND))
        self.assertEqual([e["name"] for e in model["entities"]], ["Project", "Member", "Milestone", "Task"])
        task = next(e for e in model["entities"] if e["name"] == "Task")
        self.assertEqual([ref["field"] for ref in task["references"]], ["project_id", "assignee_id", "milestone_id"])
        project = model["entities"][0]
        self.assertEqual(project["links"][0]["segment"], "members")
        self.assertEqual(model["auth"]["principal"], {"entity": "Member", "email_field": "email"})
        self.assertEqual(model["auth"]["scoping"]["entity"], "Project")
        self.assertEqual(model["nfr"]["latency_records"], 10000)
        checks, unmapped = engine.compile_acceptance(spec, model)
        self.assertEqual((len(checks), unmapped), (64, {}))
        self.assertEqual(model["rules"]["progress"][0]["key"], "tasks")
        self.assertEqual(model["rules"]["overdue"], [{"entity": "Task", "date": "due_date", "field": "status", "value": "done"}])
        self.assertEqual(model["rules"]["completion"][0]["entity"], "Milestone")
        kinds = {check["route"]["kind"] for check in checks}
        self.assertEqual(kinds, {"collection", "item", "children", "progress", "link", "login", "logout", "page"})

    def test_translation_gaps_are_reported(self):
        spec = scenario_a_spec()
        spec["entities"].append({"name": "Widget", "fields": [{"name": "gizmo", "type": "text", "required": True}]})
        spec["relations"].append({"from": "Project", "to": "Widget", "kind": "many-to-many", "required": False})
        _, model = self.model(spec)
        self.assertIn("entity Widget", model["translation_gaps"])
        self.assertIn("field Widget.gizmo", model["translation_gaps"])
        self.assertEqual(model["entities"][0]["links"][0]["segment"], "widgets")
        self.assertIn("OI-I18N", {item["id"] for item in engine.open_items_for(spec, model)})
        up, down = engine.migrations_sql(model)
        self.assertIn('CREATE TABLE "project_widgets_link"', up)
        self.assertIn('DROP TABLE IF EXISTS "project_widgets_link"', down)

    def test_unsupported_criteria_are_unmapped_with_a_reason(self):
        spec = scenario_a_spec()
        spec["features"][0]["acceptance"] += ["GET /api/projects?archived=true returns 200 and only archived projects",
                                              "POST /api/reports with a valid body returns 201 and the record",
                                              "GET /api/projects returns 200 and a delightful page"]
        planned = engine.plan(spec)
        self.assertEqual(sorted(planned["unmapped_criteria"]), ["f1-a3", "f1-a4", "f1-a5"])
        self.assertIn("route", planned["unmapped_criteria"]["f1-a4"])
        spec, model = self.model(spec)
        checks, unmapped = engine.compile_acceptance(spec, model)
        self.assertEqual(len(checks), 13)
        self.assertEqual(set(unmapped), {"f1-a3", "f1-a4", "f1-a5"})

    def test_non_functional_statements_map_to_named_evidence(self):
        _, model = self.model()
        api = engine.API_ID
        cases = {
            "no secrets in repo": {"static:security:secrets"},
            "keyboard navigable": {"e2e:keyboard"},
            "parameterized SQL": {api + "test_sql_injection_is_inert"},
            "ar rtl": {"e2e:ar:language", api + "test_pages_follow_requested_locale"},
            "CSRF token on cookie sessions": {api + "test_csrf_token_required", api + "test_cross_origin_write_refused",
                                              api + "test_login_logout_cycle"},
            "members see only projects they belong to": set(),
            "The product feels delightful": set(),
        }
        for text, expected in cases.items():
            with self.subTest(text):
                self.assertEqual(set(engine.map_statement(model, ["ar", "en"], text)), expected)

    def test_generated_migrations_apply_and_revert(self):
        _, model = self.model()
        up, down = engine.migrations_sql(model)
        problems, detail = engine._migration_check({"migrations/0001_initial.up.sql": up.encode(),
                                                    "migrations/0001_initial.down.sql": down.encode()}, model)
        self.assertEqual(problems, [])
        self.assertEqual(detail["tables"], ["app_account", "app_session", "project", "task"])
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
        for required in ("app/server.py", "app/db.py", "app/auth.py", "app/model.py", "app/schema.json",
                         "app/acceptance.json", "app/seed_data.json", "static/index.ar.html", "static/index.en.html",
                         "static/app.js", "static/i18n.json", "tests/test_api.py", "tests/test_acceptance.py",
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
        self.assertEqual({row["id"] for row in link["used"]}, {"template:app-stdlib", "catalog:microsoft/playwright",
                                                               "engine:requirements", "engine:factory", "skill:gaie-build"})
        readme = (self.app / "README.md").read_text()
        for heading in ("## Run", "## Test", "## API", "## Security", "## Open items for the owner"):
            self.assertIn(heading, readme)
        self.assertIn("OI-LICENSE", readme)
        self.assertIn("create-account", readme)
        for lang, direction in (("ar", "rtl"), ("en", "ltr")):
            page = (self.app / f"static/index.{lang}.html").read_text()
            self.assertIn(f'<html lang="{lang}" dir="{direction}">', page)
            self.assertIn('<label for="login-password"', page)
        self.assertIn("نظام إدارة المشاريع", (self.app / "static/index.ar.html").read_text())
        package = json.loads((self.app / "package.json").read_text())
        self.assertEqual(package["devDependencies"], {"playwright": "1.65.1"})
        self.assertNotIn("license", package)
        schema = json.loads((self.app / "app/schema.json").read_text())
        self.assertEqual(schema["auth"]["roles"], {"admin": ["*"], "member": ["read", "write:own"]})
        seed = json.loads((self.app / "app/seed_data.json").read_text())
        self.assertEqual(seed["label"], "synthetic")

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
        self.assertEqual(factory.evaluate_factory(plan, receipts, artifact_root=root)["verified_count"], 2)
        artifact = root / "artifacts/requirements.json"
        artifact.write_text(artifact.read_text().replace("synthetic", "changed"))
        self.assertEqual(factory.evaluate_factory(plan, receipts, artifact_root=root)["verified_count"], 0)

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

    def test_registry_sources_are_reported(self):
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
        found = engine.find_existing(scenario_a_spec(), workspace=workspace, environ=self.environ, registry=object())
        self.assertIn("not callable", found["sources"][-1]["status"])
        found = engine.find_existing(scenario_a_spec(), workspace=workspace, environ=self.environ)
        self.assertEqual(found["sources"][-1]["source"], "project_registry")
        self.assertEqual(found["matches"], [])
        home = pathlib.Path(self.environ["GAIE_HOME"])
        home.mkdir(exist_ok=True)
        (home / "projects.json").write_text("{not json")
        with self.assertRaises(engine.BuildError):
            engine.find_existing(scenario_a_spec(), workspace=workspace, environ=self.environ)


class GeneratedFileModeTests(Workspace):
    """The generated application is private on disk: directories 0700, files 0600, manage.py 0700 (L09 private-mode)."""

    def setUp(self):
        super().setUp()
        previous = os.umask(0)  # the widest umask: every mode below comes from the engine, none from the caller
        try:
            self.report = self.build()
        finally:
            os.umask(previous)
        self.app = pathlib.Path(self.report["out_dir"])

    def scaffold(self):
        """{path: git mode} of the files _write_files wrote (the source commit), read from Git itself."""
        listing = git(self.app, "ls-tree", "-r", self.report["source_commit"]).stdout.splitlines()
        return {line.split("\t", 1)[1]: line.split()[0] for line in listing}

    def test_the_application_directory_and_its_scaffold_are_private(self):
        self.assertEqual(stat.S_IMODE(self.app.stat().st_mode), 0o700)
        files = self.scaffold()
        self.assertIn("manage.py", files)
        directories = {parent for relative in files for parent in pathlib.PurePosixPath(relative).parents
                       if str(parent) != "."}
        for relative in sorted(directories):
            self.assertEqual(stat.S_IMODE((self.app / relative).stat().st_mode), 0o700, relative)
        for relative in files:
            expected = 0o700 if relative == "manage.py" else 0o600
            self.assertEqual(stat.S_IMODE((self.app / relative).lstat().st_mode), expected, relative)

    def test_only_manage_py_keeps_the_execute_bit_the_repository_records(self):
        files = self.scaffold()
        self.assertEqual({path for path, mode in files.items() if mode == "100755"}, {"manage.py"})
        self.assertEqual({mode for path, mode in files.items() if path != "manage.py"}, {"100644"})
        self.assertTrue(os.access(self.app / "manage.py", os.X_OK))

    def test_the_callers_umask_does_not_change_the_source_commit(self):
        other = self.tmp / "second-workspace"
        other.mkdir()
        again = engine.build(scenario_a_spec(), out_dir=other / "project-management", hub_revision=self.revision,
                             workspace=other, environ=self.environ, now=NOW, verify=False)
        self.assertEqual(again["source_commit"], self.report["source_commit"])

    def test_a_generated_path_that_is_a_symlink_is_not_followed(self):
        target = self.workspace / "linked-app"
        target.mkdir(mode=0o700)
        outside = self.tmp / "outside.txt"
        outside.write_text("owner data\n")
        (target / "README.md").symlink_to(outside)
        with self.assertRaises(OSError):
            engine._write_files(target, {"README.md": b"generated\n"})
        self.assertEqual(outside.read_text(), "owner data\n")


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
        self.assertIsNone(result["registered"])
        self.assertEqual(git(self.bare, "rev-parse", "refs/heads/main").stdout.strip(), head)
        clone = self.tmp / "clone"
        git(self.tmp, "clone", "-q", "-b", "main", str(self.bare), str(clone))
        self.assertTrue((clone / "app/server.py").is_file())
        self.assertEqual(len(git(clone, "log", "--oneline").stdout.splitlines()), 2)

    def test_an_application_outside_the_grant_paths_is_not_pushed(self):
        """W2-BU-08: the grant's paths bind the approval; nothing is read, written or pushed outside them."""
        elsewhere = copy.deepcopy(self.grant)
        elsewhere["paths"] = [str(self.workspace / "some-other-approved-app")]
        link = self.tmp / "inside"
        link.mkdir()
        (link / "app").symlink_to(self.app, target_is_directory=True)
        through_link = copy.deepcopy(self.grant)
        through_link["paths"] = [str(link)]
        request = self.app / ".gaie/repository-request.json"
        before = request.read_bytes()
        for label, grant, app in (("grant for another path", elsewhere, self.app),
                                  ("symlink inside the grant to an app outside it", through_link, link / "app")):
            with self.subTest(label):
                with self.assertRaises(engine.ApprovalRequired) as refused:
                    engine.publish(app, remote=str(self.bare), grant=grant, token=self.token, now=NOW)
                self.assertIn("outside the grant", str(refused.exception))
                self.assertEqual(self.refs(), "", "nothing reached the bare repository")
        self.assertEqual(request.read_bytes(), before)
        self.assertEqual(engine.publish(self.app, remote=str(self.bare), grant=self.grant, token=self.token,
                                       now=NOW)["status"], "pushed")

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

    def test_published_project_is_registered_privately(self):
        url = "https://github.com/example/project-management.git"
        planned = engine.register_project(self.app, url, environ=self.environ)
        self.assertEqual(planned["status"], "would-register")
        self.assertFalse((pathlib.Path(self.environ["GAIE_HOME"]) / "projects.json").exists())
        done = engine.register_project(self.app, url, environ=self.environ, apply=True)
        self.assertEqual(done["status"], "registered")
        from engineering_os import project_registry
        record = project_registry.load(self.environ)["project-management"]
        self.assertEqual(record["repository"], "https://github.com/example/project-management")
        self.assertEqual(record["private"]["approved_hub_revision"], self.revision)
        fresh = self.tmp / "fresh"
        fresh.mkdir()
        with self.assertRaises(engine.DuplicateProject) as caught:
            engine.build(scenario_a_spec(), out_dir=fresh / "pm", hub_revision=self.revision, workspace=fresh,
                         environ=self.environ, verify=False)
        self.assertEqual(caught.exception.matches[0]["source"], "private-overlay")


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
        result = engine.engine("plan-app", {"spec": scenario_a_spec()}, {})
        self.assertEqual(result["project"], "project-management")
        with self.assertRaises(engine.BuildError):
            engine.engine("deploy", {}, {})
        with self.assertRaises(engine.BuildError):
            engine.engine("build", {"spec": scenario_a_spec(), "out_dir": "/tmp/x", "hub_revision": "a" * 40,
                                    "shell": "rm -rf /"}, {})
        with self.assertRaises(engine.SpecError):
            engine.engine("plan-app", {"spec": {"schema": "gaie.spec/1"}}, {})
        existing = {action for row in json.loads((ROOT / "governance/engines.json").read_text())
                    if row["id"] == "master-build" for action in row["actions"]}
        from engineering_os import adapters
        # The control plane reaches the generators by delegation: exactly the delegated build actions overlap,
        # the adapter's own planning actions keep distinct names, and publish (external-write) is never registered.
        self.assertEqual(existing & set(engine.ENGINE_RECORD["actions"]), set(adapters.BUILD_ACTIONS),
                         "only the delegated build actions overlap the adapter's")
        self.assertNotIn("publish", existing, "publish is never registered")

    def test_template_manifest_matches_the_template_directory(self):
        manifest, files = engine._template_files()
        self.assertEqual(set(files) - set(manifest["files"]), {"manifest.json", "glossary.json", "ui-strings.json"})
        self.assertFalse((ROOT / "templates/app-stdlib/.gitignore").exists())


class RequirementsIntegrationTests(Workspace):
    def test_requirements_parse_output_is_buildable(self):
        try:
            module = importlib.import_module("engineering_os.requirements")
        except ImportError:
            self.skipTest("engineering_os.requirements is not in this branch (written by the L15 agent)")
        spec = module.parse(COMMAND)
        self.assertTrue(module.is_ready(spec))
        planned = engine.plan(spec)
        self.assertEqual((planned["acceptance"], planned["unmapped_criteria"]), ({"criteria": 80, "executable": 64}, {}))
        report = self.build(spec, name=spec["slug"])
        self.assertEqual(report["static_checks"], {key: "passed" for key in report["static_checks"]})
        app = pathlib.Path(report["out_dir"])
        checks = json.loads((app / "app/acceptance.json").read_text())["checks"]
        parsed = module.acceptance_checks(spec)["checks"]
        self.assertEqual([c["criterion"] for c in checks], [c["criterion"] for c in parsed])


if __name__ == "__main__":
    unittest.main()
