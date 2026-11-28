"""Acceptance Scenario A: «ابنِ نظامًا جديدًا لإدارة المشاريع» built end to end, then run without the hub.

1. The hub files the engine needs are copied into a private Git repository (branch
   main) so the build pins a real, reviewed-looking hub commit of the code under test.
2. The engine runs in a child process with only that copy on sys.path and builds the
   application into a private workspace: generation, local Git, the generated unit +
   API tests and the Playwright E2E test (Arabic and English) all run for real.
3. The factory receipts are re-validated here with engineering_os.factory.
4. The hub copy is renamed away; the application's tests, its E2E test and its server
   still work, which proves the application is operationally independent of the hub.

Needs Node.js with Playwright resolvable via require('playwright') and a Chromium
build; the test is skipped (with the reason) when they are not available.
"""
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
import urllib.request

from engineering_os import factory

ROOT = pathlib.Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("_build_engine_fixture", pathlib.Path(__file__).with_name("test_build_engine.py"))
_FIXTURE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_FIXTURE)
HUB_FILES = ("hublink.py", "scripts/security_scan.py", "catalog/capabilities/playwright.json",
             "motion-library/verify/package-lock.json", "governance/policies/gaie-routes.json",
             "projects/registry.json", "projects/aliases.json")
HUB_DIRS = ("engineering_os", "templates/app-stdlib")
BUILD = textwrap.dedent("""
    import json, sys
    hub, spec_path, out_dir, revision, workspace, home, report_path = sys.argv[1:8]
    sys.path.insert(0, hub)
    from engineering_os import build_engine
    spec = json.load(open(spec_path, encoding="utf-8"))
    report = build_engine.build(spec, out_dir=out_dir, hub_revision=revision, workspace=workspace,
                                environ={"GAIE_HOME": home}, now="2026-11-28T00:00:00Z")
    open(report_path, "w", encoding="utf-8").write(json.dumps(report, ensure_ascii=False))
""")


def _playwright_missing():
    node = shutil.which("node")
    if node is None:
        return "node is not installed"
    probe = subprocess.run([node, "-e", "require('playwright')"], capture_output=True, text=True, timeout=60)
    if probe.returncode:
        return "Playwright for Node is not resolvable via require('playwright')"
    return None


def _env(home):
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(home), "TMPDIR": str(home), "LANG": "C.UTF-8",
           "PYTHONDONTWRITEBYTECODE": "1"}
    for key in ("NODE_PATH", "PLAYWRIGHT_BROWSERS_PATH", "APP_CHROMIUM_EXECUTABLE"):
        if os.environ.get(key):
            env[key] = os.environ[key]
    return env


def _git(cwd, *args):
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(cwd), "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_CONFIG_GLOBAL": os.devnull, "LC_ALL": "C", "GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL":
           "fixture@example.invalid", "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid"}
    result = subprocess.run(["git", "-c", "core.hooksPath=" + os.devnull, "-C", str(cwd), *args],
                            capture_output=True, text=True, env=env)
    if result.returncode:
        raise AssertionError(f"git {args[0]} failed: {result.stderr}")
    return result.stdout.strip()


MISSING = _playwright_missing()


@unittest.skipIf(MISSING, MISSING or "")
class ScenarioATests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix="gaie-scenario-a-")
        cls.tmp = pathlib.Path(cls._tmp.name)
        cls.hub = cls.tmp / "hub-copy"
        for relative in HUB_FILES:
            target = cls.hub / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, target)
        for relative in HUB_DIRS:
            shutil.copytree(ROOT / relative, cls.hub / relative, ignore=shutil.ignore_patterns("__pycache__"))
        _git(cls.hub, "init", "-q", "--template=", "-b", "main")
        _git(cls.hub, "add", "--all")
        _git(cls.hub, "commit", "-q", "-m", "hub fixture at the code under test")
        cls.revision = _git(cls.hub, "rev-parse", "HEAD")
        cls.workspace = cls.tmp / "workspace"
        cls.workspace.mkdir()
        cls.app = cls.workspace / "project-management"
        spec_path = cls.tmp / "spec.json"
        spec_path.write_text(json.dumps(_FIXTURE.scenario_a_spec(), ensure_ascii=False), encoding="utf-8")
        report_path = cls.tmp / "report.json"
        home = cls.tmp / "home"
        home.mkdir()
        run = subprocess.run([sys.executable, "-I", "-c", BUILD, str(cls.hub), str(spec_path), str(cls.app),
                              cls.revision, str(cls.workspace), str(cls.tmp / "gaie-home"), str(report_path)],
                             cwd=cls.tmp, env=_env(home), capture_output=True, text=True, timeout=1200)
        if run.returncode:
            raise AssertionError("build failed: " + run.stderr[-3000:])
        cls.report = json.loads(report_path.read_text(encoding="utf-8"))
        cls.moved = cls.tmp / "hub-moved-away"
        cls.hub.rename(cls.moved)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_1_build_passes_every_generated_suite(self):
        report = self.report
        tests = report["tests"]
        self.assertEqual(tests["python"]["status"], "passed", tests["python"])
        summary = tests["python"]["summary"]
        self.assertEqual((summary["ran"], summary["passed"], summary["failed"], summary["errors"]), (47, 47, 0, 0))
        self.assertEqual(tests["e2e"]["status"], "passed", tests["e2e"])
        self.assertEqual(tests["e2e"]["failures"], [])
        self.assertTrue(tests["e2e"]["browser"].startswith("chromium"))
        self.assertEqual(report["static_checks"], {key: "passed" for key in report["static_checks"]})
        self.assertEqual(len(report["coverage"]), 18)
        self.assertEqual({row["status"] for row in report["coverage"]}, {"passed"})
        self.assertTrue(report["pin_on_main"])
        self.assertTrue(report["reproducible_from_pin"])
        self.assertEqual(report["provider_calls"], 0)
        self.assertFalse(report["deployment_authorized"])
        self.assertEqual(report["repository"], {"status": "awaiting-approval", "request": ".gaie/repository-request.json",
                                                "visibility": "private"})
        self.assertEqual(report["untracked_after_build"], [])

    def test_2_factory_accepts_the_receipts(self):
        self.assertTrue(self.report["ok"])
        root = self.app / ".gaie/factory"
        request = json.loads((root / "request.json").read_text(encoding="utf-8"))
        receipts = json.loads((root / "receipts.json").read_text(encoding="utf-8"))
        plan = factory.plan_factory(request)
        self.assertEqual(plan, json.loads((root / "plan.json").read_text(encoding="utf-8")))
        result = factory.evaluate_factory(plan, receipts, artifact_root=root)
        self.assertTrue(result["delivery_review_ready"])
        self.assertEqual(result["verified_count"], 10)
        self.assertEqual([stage["status"] for stage in result["stages"]], ["verified"] * 10)
        self.assertEqual(request["source_revision"], self.report["source_commit"])
        self.assertEqual({row["id"] for row in request["requirements"]},
                         {"f1", "f2", "f3", "f4", "f5", "nfr-accessibility", "nfr-i18n", "nfr-performance", "nfr-security"})
        browser = json.loads((root / "details/frontend-browser.json").read_text(encoding="utf-8"))
        self.assertEqual(browser["evidence"]["e2e:ar:task:create"], "passed")
        self.assertEqual(browser["evidence"]["e2e:en:project:create"], "passed")

    def test_3_application_runs_without_the_hub(self):
        self.assertFalse(self.hub.exists())
        for path in self.app.rglob("*"):
            if path.is_file() and ".git" not in path.parts:
                text = path.read_text(encoding="utf-8", errors="replace")
                self.assertNotIn(str(self.hub), text, path)
                self.assertNotIn(str(ROOT), text, path)
        home = self.tmp / "after"
        home.mkdir(exist_ok=True)
        report = home / "python.json"
        run = subprocess.run([sys.executable, "-I", "manage.py", "test", "--report", str(report)], cwd=self.app,
                             env=_env(home), capture_output=True, text=True, timeout=600)
        self.assertEqual(run.returncode, 0, run.stderr[-2000:])
        summary = json.loads(report.read_text(encoding="utf-8"))["summary"]
        self.assertEqual((summary["ran"], summary["passed"]), (47, 47))
        e2e = subprocess.run([shutil.which("node"), "tests/e2e/ui.e2e.mjs"], cwd=self.app, env={**_env(home),
                             "APP_PYTHON": sys.executable}, capture_output=True, text=True, timeout=600)
        result = json.loads(e2e.stdout.strip().splitlines()[-1])
        self.assertEqual((e2e.returncode, result["ok"]), (0, True), result)
        self.assertEqual(len(result["cases"]), 19)
        self.assertIn("e2e:no-external-requests", {row["id"] for row in result["cases"]})
        self.assertEqual(_git(self.app, "status", "--porcelain"), "")

    def test_4_server_serves_the_bilingual_app_without_the_hub(self):
        home = self.tmp / "serve"
        home.mkdir(exist_ok=True)
        server = subprocess.Popen([sys.executable, "-I", "manage.py", "serve", "--port", "0", "--db", str(home / "db.sqlite3")],
                                  cwd=self.app, env=_env(home), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        try:
            line = server.stdout.readline()
            self.assertRegex(line, r"^listening on http://127\.0\.0\.1:\d+$")
            base = line.split()[-1]
            with urllib.request.urlopen(base + "/") as response:
                page = response.read().decode("utf-8")
                self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
            self.assertIn('<html lang="ar" dir="rtl">', page)
            request = urllib.request.Request(base + "/api/projects", method="POST",
                                             data=json.dumps({"title": "مشروع", "status": "active"}).encode("utf-8"),
                                             headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(request) as response:
                self.assertEqual(response.status, 201)
                self.assertEqual(json.loads(response.read())["title"], "مشروع")
        finally:
            server.terminate()
            server.wait(timeout=30)
            server.stdout.close()
        refused = subprocess.run([sys.executable, "-I", "manage.py", "serve", "--host", "0.0.0.0", "--port", "0"],
                                 cwd=self.app, env=_env(home), capture_output=True, text=True, timeout=60)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("no user authentication", refused.stderr)


if __name__ == "__main__":
    unittest.main()
