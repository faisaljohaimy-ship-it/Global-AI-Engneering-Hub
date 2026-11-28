"""Regressions for the w2-build-upgrade review of the generated application (templates/app-stdlib).

Every test builds an application with the Master Build Engine (verify=False: generation,
static checks and local Git only) from the real engineering_os.requirements output for the
owner's command, or a variant of it, and then drives that application's real HTTP server
on a loopback port in a child process, through the application's own test helpers
(tests/support.py). The child runs with -I and only the application on sys.path, so the
hub is never imported by the code under test. No network beyond loopback is used.
"""
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import textwrap
import unittest

from engineering_os import build_engine as engine
from engineering_os import requirements

_SPEC = importlib.util.spec_from_file_location("_build_engine_fixture", pathlib.Path(__file__).with_name("test_build_engine.py"))
_FIXTURE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_FIXTURE)

PRELUDE = textwrap.dedent("""
    import json, sys
    sys.path.insert(0, sys.argv[1])
    from tests.support import ADMIN, SCHEMA, Running, sample
    from app import auth, db, model
    server = Running()
    result = {}

    def call(method, path, body=None, who=None, **kwargs):
        if who is not None:
            kwargs["session"] = who
        return server.request(method, path, body, **kwargs)

    def status(method, path, body=None, who=None, **kwargs):
        return call(method, path, body, who, **kwargs)[0]

    def new(entity, n, who=None, **values):
        refs = {key: value for key, value in values.items() if SCHEMA.by_name[entity].reference(key)}
        plain = {key: value for key, value in values.items() if key not in refs}
        code, _, record = call("POST", "/api/" + SCHEMA.by_name[entity].collection,
                               sample(SCHEMA.by_name[entity], n, refs, **plain), who)
        assert code == 201, (entity, code, record)
        return record

    def refusal(method, path, body=None, who=None, **kwargs):
        code, _, reply = call(method, path, body, who, **kwargs)
        return [code, reply["error"]["code"] if isinstance(reply, dict) and "error" in reply else None]

    def ids(method, path, who=None):
        code, _, page = call(method, path, None, who)
        return code, sorted(row["id"] for row in page["items"]) if code == 200 else []
""")
EPILOGUE = textwrap.dedent("""
    server.close()
    print(json.dumps(result, sort_keys=True))
""")


def build_app(tmp, spec, name):
    workspace = tmp / "ws"
    workspace.mkdir(exist_ok=True)
    report = engine.build(spec, out_dir=workspace / name, hub_revision=_FIXTURE.main_revision(), workspace=workspace,
                          environ={"GAIE_HOME": str(tmp / "gaie-home")}, now=_FIXTURE.NOW, verify=False)
    return pathlib.Path(report["out_dir"])


def run_scenario(app, scenario, tmp):
    """Run `scenario` (Python source using the PRELUDE helpers) against the app's real server."""
    home = tmp / "child"
    home.mkdir(exist_ok=True)
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home), "TMPDIR": str(home),
           "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"}
    code = PRELUDE + textwrap.dedent(scenario) + EPILOGUE
    run = subprocess.run([sys.executable, "-I", "-c", code, str(app)], cwd=app, env=env, capture_output=True,
                         text=True, timeout=600)
    if run.returncode:
        raise AssertionError("scenario failed:\n" + run.stderr[-4000:])
    return json.loads(run.stdout.strip().splitlines()[-1])


class GeneratedApp(unittest.TestCase):
    """One application per class, built from `spec()` into a short private temporary directory."""

    @classmethod
    def spec(cls):
        return requirements.parse(_FIXTURE.COMMAND)

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix="gbf-", dir="/tmp" if os.path.isdir("/tmp") else None)
        cls.tmp = pathlib.Path(cls._tmp.name)
        cls.app = build_app(cls.tmp, cls.spec(), "project-management")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def scenario(self, source):
        return run_scenario(self.app, source, self.tmp)


class LinkAuthorizationTests(GeneratedApp):
    """W2-BU-01: link routes apply the parent record's write/delete permission, ownership and CSRF/same-origin."""

    def test_reference_roles_are_what_the_scenario_assumes(self):
        schema = json.loads((self.app / "app/schema.json").read_text(encoding="utf-8"))
        roles = schema["auth"]["roles"]
        self.assertEqual((roles["member"], roles["manager"][:3]), (["read", "write:own"], ["read", "write", "delete"]))
        self.assertEqual(schema["auth"]["scoping"]["entity"], "Project")

    def test_member_cannot_change_memberships_of_a_project_it_did_not_create(self):
        result = self.scenario("""
            project = new("Project", 1)
            bob = server.login("member", email="bob@example.invalid")
            mgr = server.login("manager", email="mgr@example.invalid")
            people = {key: new("Member", n, email=key + "@example.invalid") for n, key in enumerate(("bob", "mgr"), 1)}
            members = "/api/projects/%d/members" % project["id"]
            for person in people.values():
                assert status("POST", members, {"member_id": person["id"]}) == 201
            eve = new("Member", 3, who=bob, email="eve@example.invalid")
            result["bob_patch_project"] = status("PATCH", "/api/projects/%d" % project["id"], {"name": "x"}, bob)
            result["bob_removes_manager"] = refusal("DELETE", members + "/%d" % people["mgr"]["id"], None, bob)
            result["manager_still_sees_project"] = status("GET", "/api/projects/%d" % project["id"], who=mgr)
            result["bob_adds_eve"] = refusal("POST", members, {"member_id": eve["id"]}, bob)
            result["members_after"] = ids("GET", members)[1]
            result["expected_members"] = sorted(person["id"] for person in people.values())
            own = call("POST", "/api/projects", sample(SCHEMA.by_name["Project"], 2), bob)[2]
            mine = "/api/projects/%d/members" % own["id"]
            result["bob_adds_eve_to_own_project"] = status("POST", mine, {"member_id": eve["id"]}, bob)
            result["bob_removes_from_own_project_without_delete"] = status("DELETE", mine + "/%d" % eve["id"], who=bob)
            result["manager_removes_bob"] = status("DELETE", members + "/%d" % people["bob"]["id"], who=mgr)
            result["cross_origin_remove"] = status("DELETE", members + "/%d" % people["mgr"]["id"],
                                                   headers={"Origin": "https://attacker.example"})
            result["cross_site_remove"] = status("DELETE", members + "/%d" % people["mgr"]["id"],
                                                 headers={"Sec-Fetch-Site": "cross-site"})
            result["remove_without_csrf"] = status("DELETE", members + "/%d" % people["mgr"]["id"], csrf=False)
            result["members_final"] = ids("GET", members)[1]
            result["manager_id"] = people["mgr"]["id"]
        """)
        self.assertEqual(result["bob_patch_project"], 403)
        self.assertEqual(result["bob_removes_manager"], [403, "forbidden"], "a member has no delete permission")
        self.assertEqual(result["manager_still_sees_project"], 200)
        self.assertEqual(result["bob_adds_eve"], [403, "forbidden"], "write:own does not cover another account's project")
        self.assertEqual(result["members_after"], result["expected_members"])
        self.assertEqual(result["bob_adds_eve_to_own_project"], 201, "write:own covers a project the member created")
        self.assertEqual(result["bob_removes_from_own_project_without_delete"], 403)
        self.assertEqual(result["manager_removes_bob"], 204, "write and delete on a visible project")
        self.assertEqual((result["cross_origin_remove"], result["cross_site_remove"], result["remove_without_csrf"]),
                         (403, 403, 403))
        self.assertEqual(result["members_final"], [result["manager_id"]])

    def test_generated_link_tests_cover_every_role(self):
        run = subprocess.run([sys.executable, "-m", "unittest", "tests.test_api.ApiTests.test_links_project_members"],
                             cwd=self.app, env={"PATH": os.environ.get("PATH", ""), "HOME": str(self.tmp),
                                                "TMPDIR": str(self.tmp), "LANG": "C.UTF-8",
                                                "PYTHONDONTWRITEBYTECODE": "1"},
                             capture_output=True, text=True, timeout=600)
        self.assertEqual(run.returncode, 0, run.stderr[-3000:])
        self.assertIn("_link_permissions", (self.app / "tests/test_api.py").read_text(encoding="utf-8"))


class ReadOwnSubResourceTests(GeneratedApp):
    """W2-BU-02: children, links and progress authorize the parent like GET of the parent (read:own included)."""

    @classmethod
    def spec(cls):
        spec = requirements.parse(_FIXTURE.COMMAND)
        for role in spec["roles"]:
            if role["id"] == "member":
                role["permissions"] = ["read:own", "write:own"]
        return spec

    def test_read_own_role_reads_nothing_through_another_accounts_parent(self):
        result = self.scenario("""
            assert SCHEMA.permissions("member") == {"read:own", "write:own"}
            project = new("Project", 1)
            bob = server.login("member", email="bob@example.invalid")
            me = new("Member", 1, email="bob@example.invalid")
            base = "/api/projects/%d" % project["id"]
            assert status("POST", base + "/members", {"member_id": me["id"]}) == 201
            new("Task", 1, project_id=project["id"])
            for key, path in (("project", base), ("tasks", base + "/tasks"), ("members", base + "/members"),
                              ("progress", base + "/progress"), ("milestones", base + "/milestones")):
                result[key] = status("GET", path, who=bob)
            own = call("POST", "/api/projects", sample(SCHEMA.by_name["Project"], 2), bob)[2]
            mine = "/api/projects/%d" % own["id"]
            bobs = call("POST", "/api/tasks", sample(SCHEMA.by_name["Task"], 3, {"project_id": own["id"]}), bob)[2]
            new("Task", 4, project_id=own["id"])
            result["own_project_tasks"] = ids("GET", mine + "/tasks", bob)
            result["bobs_task"] = bobs["id"]
            result["own_progress"] = call("GET", mine + "/progress", None, bob)[2]
            result["own_members"] = ids("GET", mine + "/members", bob)
            result["admin_sees_both_tasks"] = len(ids("GET", mine + "/tasks")[1])
        """)
        self.assertEqual({key: result[key] for key in ("project", "tasks", "members", "progress", "milestones")},
                         {key: 404 for key in ("project", "tasks", "members", "progress", "milestones")})
        self.assertEqual(result["own_project_tasks"], [200, [result["bobs_task"]]])
        self.assertEqual((result["own_progress"]["total_tasks"], result["admin_sees_both_tasks"]), (1, 2))
        self.assertEqual(result["own_members"], [200, []], "the member record was created by the admin, not by bob")


class PrincipalBindingTests(GeneratedApp):
    """W2-BU-04: a scoped role cannot re-point which principal record identifies an account."""

    def test_manager_cannot_take_over_another_members_projects(self):
        result = self.scenario("""
            mgr = server.login("manager", email="mgr@example.invalid")
            mine, secret = new("Project", 1), new("Project", 2)
            me = new("Member", 1, email="mgr@example.invalid")
            alice = new("Member", 2, email="alice@example.invalid")
            assert status("POST", "/api/projects/%d/members" % mine["id"], {"member_id": me["id"]}) == 201
            assert status("POST", "/api/projects/%d/members" % secret["id"], {"member_id": alice["id"]}) == 201
            result["before"] = ids("GET", "/api/projects", mgr)
            result["move_own_email"] = refusal("PATCH", "/api/members/%d" % me["id"], {"email": "spare@example.invalid"}, mgr)
            result["take_alice_email"] = refusal("PATCH", "/api/members/%d" % alice["id"], {"email": "mgr@example.invalid"}, mgr)
            body = sample(SCHEMA.by_name["Member"], 3, email="mgr@example.invalid")
            result["put_alice_email"] = refusal("PUT", "/api/members/%d" % alice["id"], body, mgr)
            result["rename_alice"] = status("PATCH", "/api/members/%d" % alice["id"], {"name": "Alice A."}, mgr)
            result["put_keeping_email"] = status("PUT", "/api/members/%d" % alice["id"],
                                                 sample(SCHEMA.by_name["Member"], 4, email="alice@example.invalid"), mgr)
            result["after"] = ids("GET", "/api/projects", mgr)
            result["admin_moves_email"] = status("PATCH", "/api/members/%d" % me["id"], {"email": "moved@example.invalid"})
            result["after_admin"] = ids("GET", "/api/projects", mgr)
            result["want"] = mine["id"]
        """)
        self.assertEqual(result["before"], [200, [result["want"]]])
        self.assertEqual(result["move_own_email"], [403, "forbidden"])
        self.assertEqual(result["take_alice_email"], [403, "forbidden"])
        self.assertEqual(result["put_alice_email"], [403, "forbidden"])
        self.assertEqual((result["rename_alice"], result["put_keeping_email"]), (200, 200), "other fields stay writable")
        self.assertEqual(result["after"], [200, [result["want"]]])
        self.assertEqual(result["admin_moves_email"], 200, "an administrator may re-point an identity")
        self.assertEqual(result["after_admin"], [200, []])


COMMENTS_COMMAND ="ابنِ نظامًا جديدًا لإدارة المشاريع مع تعليقات على المهام"


class TransitiveScopingTests(GeneratedApp):
    """W2-BU-03: scoping reaches entities two hops away (Comment -> Task -> Project)."""

    @classmethod
    def spec(cls):
        spec = requirements.parse(COMMENTS_COMMAND)
        spec["slug"] = "project-management"
        return spec

    def test_the_real_spec_has_a_two_hop_entity(self):
        schema = json.loads((self.app / "app/schema.json").read_text(encoding="utf-8"))
        comment = next(e for e in schema["entities"] if e["name"] == "Comment")
        self.assertEqual(schema["auth"]["scoping"]["entity"], "Project")
        self.assertIn("Task", {ref["entity"] for ref in comment["references"]})
        self.assertNotIn("Project", {ref["entity"] for ref in comment["references"]})

    def test_member_sees_only_comments_on_tasks_of_its_projects(self):
        result = self.scenario("""
            bob = server.login("member", email="bob@example.invalid")
            me = new("Member", 1, email="bob@example.invalid")
            author = new("Member", 2, email="exec@example.invalid")
            mine, other = new("Project", 1), new("Project", 2)
            assert status("POST", "/api/projects/%d/members" % mine["id"], {"member_id": me["id"]}) == 201
            seen_task = new("Task", 1, project_id=mine["id"])
            hidden_task = new("Task", 2, project_id=other["id"])
            seen = new("Comment", 1, task_id=seen_task["id"], author_id=author["id"])
            hidden = new("Comment", 2, task_id=hidden_task["id"], author_id=author["id"])
            result["projects"] = ids("GET", "/api/projects", bob)
            result["tasks"] = ids("GET", "/api/tasks", bob)
            result["comments"] = ids("GET", "/api/comments", bob)
            result["hidden_comment"] = status("GET", "/api/comments/%d" % hidden["id"], who=bob)
            result["seen_comment"] = status("GET", "/api/comments/%d" % seen["id"], who=bob)
            result["hidden_task_comments"] = status("GET", "/api/tasks/%d/comments" % hidden_task["id"], who=bob)
            body = sample(SCHEMA.by_name["Comment"], 3, {"task_id": hidden_task["id"], "author_id": me["id"]})
            result["comment_on_hidden_task"] = refusal("POST", "/api/comments", body, bob)
            result["patch_hidden_comment"] = status("PATCH", "/api/comments/%d" % hidden["id"], {"body": "x"}, bob)
            result["admin_comments"] = ids("GET", "/api/comments")
            result["want"] = {"mine": mine["id"], "task": seen_task["id"], "seen": seen["id"], "hidden": hidden["id"]}
        """)
        want = result["want"]
        self.assertEqual(result["projects"], [200, [want["mine"]]])
        self.assertEqual(result["tasks"], [200, [want["task"]]])
        self.assertEqual(result["comments"], [200, [want["seen"]]])
        self.assertEqual((result["hidden_comment"], result["seen_comment"], result["hidden_task_comments"]), (404, 200, 404))
        self.assertEqual(result["comment_on_hidden_task"], [400, "validation_failed"])
        self.assertEqual(result["patch_hidden_comment"], 404)
        self.assertEqual(result["admin_comments"], [200, sorted([want["seen"], want["hidden"]])])


class ScopingBoundTests(unittest.TestCase):
    """W2-BU-03: a model whose scoping filter could not be bounded is refused at build time."""

    def test_too_many_reference_chains_are_refused(self):
        spec = requirements.parse(_FIXTURE.COMMAND)
        parent = "Project"
        for n in range(6):  # Layer<n> reaches Project through 2 ** (n + 1) chains
            name = f"Layer{n}"
            spec["entities"].append({"name": name, "fields": [{"name": "title", "type": "text", "required": True,
                                                               "max": 100}]})
            for side in ("first", "second"):
                spec["relations"].append({"from": name, "to": parent, "kind": "many-to-one", "required": False,
                                          "field": f"{side}_{parent.lower()}"})
            parent = name
        with self.assertRaises(engine.UnsupportedSpec) as refused:
            engine.derive_model(engine.validate_spec(spec))
        self.assertIn("reference chains", str(refused.exception))
        self.assertTrue(engine.derive_model(engine.validate_spec(requirements.parse(COMMENTS_COMMAND)))["auth"]["scoping"])


if __name__ == "__main__":
    unittest.main()
