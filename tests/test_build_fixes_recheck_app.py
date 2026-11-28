"""Regressions for the recheck-build review of the generated application (templates/app-stdlib).

Each class builds an application with the Master Build Engine (verify=False) from the real
engineering_os.requirements output for the owner's command and drives that application's
real HTTP server on loopback in a child process (helpers from tests/test_build_fixes_app.py),
or runs the application's own generated tests, unmodified and on a mutated copy, to show that
a generated test fails when the behaviour it stands for is removed. No network beyond loopback.
"""
import ast
import importlib.util
import os
import pathlib
import shutil
import subprocess
import sys
import unittest

_SPEC = importlib.util.spec_from_file_location("_build_fixes_app", pathlib.Path(__file__).with_name("test_build_fixes_app.py"))
_APP = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_APP)
engine, requirements = _APP.engine, _APP.requirements
TEMPLATE = pathlib.Path(__file__).resolve().parents[1] / "templates" / "app-stdlib"


def run_generated(app, tmp, names):
    """Run generated tests of `app` by id; (return code, output tail)."""
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(tmp), "TMPDIR": str(tmp), "LANG": "C.UTF-8",
           "PYTHONDONTWRITEBYTECODE": "1"}
    run = subprocess.run([sys.executable, "-m", "unittest", *names], cwd=app, env=env, capture_output=True, text=True,
                         timeout=600)
    return run.returncode, run.stderr[-3000:]


class MutatedApp(_APP.GeneratedApp):
    """A generated application plus a helper that runs its tests against a mutated copy."""

    def mutant(self, name, path, old, new):
        """A copy of the application where `old` (which must occur in `path`) becomes `new`."""
        copy = self.tmp / "mutants" / name
        if copy.exists():
            shutil.rmtree(copy)
        shutil.copytree(self.app, copy, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        source = (copy / path).read_text(encoding="utf-8")
        self.assertTrue(old in source, f"mutation {name}: the code it changes is not in {path}")
        (copy / path).write_text(source.replace(old, new), encoding="utf-8")
        return copy

    def assertGeneratedPasses(self, names, app=None):
        code, output = run_generated(app or self.app, self.tmp, names)
        self.assertEqual(code, 0, output)

    def assertGeneratedFails(self, names, app):
        code, output = run_generated(app, self.tmp, names)
        self.assertNotEqual(code, 0, "the generated test did not notice the mutation")
        self.assertIn("FAILED", output)


LIMITS_LINE = 'limits = {"pair": LOCKOUT_FAILURES, "address": ADDRESS_FAILURES, "account": ACCOUNT_FAILURES}'
LOCKOUT = "tests.test_api.ApiTests.test_login_lockout"


class SignInCeilingTests(MutatedApp):
    """recheck-build W2-BU-07 residual: failures are also counted per client address and per
    e-mail across addresses, before any hashing; unknown e-mails keep the same PBKDF2 work."""

    def test_rotating_emails_from_one_address_is_refused_before_hashing(self):
        result = self.scenario("""
            import http.client
            calls, original = [], auth.hash_password
            auth.hash_password = lambda *args, **kwargs: calls.append(args[1]) or original(*args, **kwargs)

            def login_from(address, email, secret):
                del calls[:]
                connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=30,
                                                        source_address=(address, 0))
                try:
                    body = json.dumps({"email": email, "password": secret}).encode()
                    connection.request("POST", "/api/login", body=body, headers={"Content-Type": "application/json"})
                    response = connection.getresponse()
                    response.read()
                    return [response.status, list(calls), response.getheader("Retry-After")]
                finally:
                    connection.close()

            per_address, per_account = getattr(auth, "ADDRESS_FAILURES", 20), getattr(auth, "ACCOUNT_FAILURES", 20)
            result["limits"] = [auth.LOCKOUT_FAILURES, per_address, per_account]
            result["spray"] = [login_from("127.0.0.5", "spray%d@example.invalid" % n, "wrong-password-1")
                               for n in range(per_address + 3)]
            result["other_address"] = login_from("127.0.0.6", "spray0@example.invalid", "wrong-password-1")
            email, password = server.account(ADMIN)
            result["guesses"] = [login_from("127.0.1.%d" % (n // auth.LOCKOUT_FAILURES + 1), email, "wrong-guess-1")
                                 for n in range(per_account)]
            result["fresh_address_after_ceiling"] = login_from("127.0.2.1", email, password)
            known, unknown = server.account(ADMIN)[0], "nobody@example.invalid"
            result["work"] = [login_from("127.0.3.1", who, "wrong-password-1")[:2] for who in (known, unknown)]
            result["iterations"] = SCHEMA.auth["pbkdf2_iterations"]
            auth.hash_password = original
        """)
        pair, per_address, per_account = result["limits"]
        self.assertEqual(pair, 5)
        self.assertGreater(per_address, pair)
        self.assertGreater(per_account, pair)
        spray = result["spray"]
        work = [result["iterations"]]
        self.assertEqual([row[:2] for row in spray[:per_address]], [[401, work]] * per_address,
                         "each admitted unknown e-mail costs one full PBKDF2")
        for status, hashes, retry in spray[per_address:]:
            self.assertEqual((status, hashes), (429, []), "refused before any lookup or hashing")
            self.assertRegex(retry or "", r"^[1-9][0-9]*$")
        self.assertEqual(result["other_address"][:2], [401, work], "another address is not throttled by this one")
        self.assertEqual([row[0] for row in result["guesses"]], [401] * per_account)
        self.assertEqual(result["fresh_address_after_ceiling"][:2], [429, []], "the per-e-mail ceiling holds every address")
        self.assertEqual(result["work"][1], [401, work], "an unknown e-mail costs the schema's PBKDF2 work")
        self.assertEqual((result["work"][0][0], len(result["work"][0][1])), (401, 1), "a known one costs one PBKDF2")

    def test_generated_lockout_test_fails_without_each_counter(self):
        self.assertGeneratedPasses([LOCKOUT])
        for name, new in (("no-address-counter", LIMITS_LINE.replace('"address": ADDRESS_FAILURES', '"address": 10 ** 9')),
                          ("no-account-ceiling", LIMITS_LINE.replace('"account": ACCOUNT_FAILURES', '"account": 10 ** 9'))):
            with self.subTest(name):
                self.assertGeneratedFails([LOCKOUT], self.mutant(name, "app/auth.py", LIMITS_LINE, new))


WINDOW_RULE = "        return recent[-limit] + LOCKOUT_SECONDS - now\n"
SIGNIN = "rate limit on sign-in (5 failures per 15 minutes)"
SECURE_COMMAND = "build a new secure project management system"  # its NFR list carries SIGNIN


def _constants(path, names):
    """Module-level constants of a template file, evaluated from their literal expressions."""
    found = {}
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", None) in names:
            allowed = (ast.Expression, ast.Constant, ast.BinOp, ast.Mult, ast.Tuple, ast.Load)
            expression = ast.Expression(node.value)
            assert all(isinstance(part, allowed) for part in ast.walk(expression)), ast.dump(node.value)
            found[node.targets[0].id] = eval(compile(expression, str(path), "eval"), {"__builtins__": {}})  # noqa: S307
    return found


class SignInStatementTests(MutatedApp):
    """recheck-build W2-BU-06 residual: 'rate limit on sign-in (5 failures per 15 minutes)' is reported
    passed only through a generated test that proves those numbers against the implementation."""

    def model(self):
        spec = engine.validate_spec(requirements.parse(SECURE_COMMAND))
        model = engine.derive_model(spec)
        engine.compile_acceptance(spec, model)
        return spec, model

    def test_the_statement_maps_only_with_the_implemented_numbers(self):
        spec, model = self.model()
        self.assertIn(SIGNIN, [text for items in spec["nfr"].values() for text in items])
        self.assertEqual(engine.map_statement(model, spec["locales"], SIGNIN), [engine.API_ID + "test_login_lockout"])
        for text in ("rate limit on sign-in (9 failures per 15 minutes)", "rate limit on sign-in (5 failures per 10 minutes)",
                     "rate limit on sign-in (5 failures per 15 minutes per account)",
                     "rate limit on sign-in (5 failures per 15 minutes) and on every endpoint"):
            with self.subTest(text):
                self.assertEqual(engine.map_statement(model, spec["locales"], text), [])

    def test_engine_template_and_generated_test_state_the_same_numbers(self):
        failures, minutes = engine.SIGNIN_LIMIT
        self.assertEqual(_constants(TEMPLATE / "app/auth.py", {"LOCKOUT_FAILURES", "LOCKOUT_SECONDS"}),
                         {"LOCKOUT_FAILURES": failures, "LOCKOUT_SECONDS": minutes * 60})
        self.assertEqual(_constants(TEMPLATE / "tests/test_api.py", {"STATED_SIGNIN_LIMIT"}),
                         {"STATED_SIGNIN_LIMIT": (failures, minutes * 60)})
        self.assertEqual(engine.SIGNIN_LIMIT, (5, 15), "the numbers of the statement requirements writes")

    def test_one_pair_gets_exactly_five_checked_failures_in_any_fifteen_minutes(self):
        result = self.scenario("""
            import http.client, threading
            sessions, now = auth.Sessions(SCHEMA), [0.0]
            sessions.clock = lambda: now[0]
            checked = []
            with db.session(server.db_path) as connection:
                while now[0] < 2 * 900:
                    try:
                        sessions.login(connection, "admin@example.invalid", "wrong-guess-123", source="198.51.100.7")
                    except auth.AuthError as error:
                        if error.status == 401:
                            checked.append(int(now[0]))
                    now[0] += 1
            result["checked"] = checked

            def login_from(address, replies):
                connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=60, source_address=(address, 0))
                try:
                    body = json.dumps({"email": "nobody@example.invalid", "password": "wrong-guess-123"}).encode()
                    connection.request("POST", "/api/login", body=body, headers={"Content-Type": "application/json"})
                    response = connection.getresponse()
                    response.read()
                    replies.append(response.status)
                finally:
                    connection.close()

            replies = []
            threads = [threading.Thread(target=login_from, args=("127.0.0.7", replies)) for _ in range(12)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            result["parallel"] = sorted(replies)
        """)
        self.assertEqual(result["checked"], [0, 1, 2, 3, 4, 900, 901, 902, 903, 904])
        self.assertEqual(result["parallel"], [401] * 5 + [429] * 7, "parallel requests cannot pass the limit")

    def test_generated_test_fails_when_the_policy_is_not_the_stated_one(self):
        self.assertGeneratedPasses([LOCKOUT])
        backoff = "        return max(0, recent[-1] + min(LOCKOUT_SECONDS, 30 * 2 ** (len(recent) - limit)) - now)\n"
        mutants = (("doubling-backoff", "app/auth.py", WINDOW_RULE, backoff),  # 9 failures per 15 minutes
                   ("window-from-latest", "app/auth.py", WINDOW_RULE, WINDOW_RULE.replace("[-limit]", "[-1]")),
                   ("six-failures", "app/auth.py", "LOCKOUT_FAILURES = 5 ", "LOCKOUT_FAILURES = 6 "),
                   ("ten-minutes", "app/auth.py", "LOCKOUT_SECONDS = 900 ", "LOCKOUT_SECONDS = 600 "),
                   ("no-known-address", "app/auth.py", 'if not (kind == "account" and known is not None))', ")"))
        for name, path, old, new in mutants:
            with self.subTest(name):
                self.assertGeneratedFails([LOCKOUT], self.mutant(name, path, old, new))


ITEM_ROUTE = ('            mode = self._permit(account, method)\n'
              '            scope = db.Scope(self.schema, account, account["principal_id"], own=(method in SAFE_METHODS and mode == "own"))\n'
              '            if method in ("PUT", "PATCH"):\n'
              '                return self._update(entity, record_id, account, scope, mode, partial=method == "PATCH")\n')
VALIDATED = "        values = self._validated(entity, payload, base=stored if partial else None)"
RAW_MERGE = "{**{c: stored.get(c) for c in entity.columns}, **{k: v for k, v in payload.items() if k in entity.columns}}"
WRITE_MUTANTS = (  # (name, NFR statement whose evidence must catch it, [(path, old, new)])
    ("patch-drops-write-own", "role check on every endpoint",
     [("app/server.py", ITEM_ROUTE, ITEM_ROUTE.replace("scope, mode, partial", 'scope, "all" if method == "PATCH" else mode, partial'))]),
    ("put-drops-write-own", "role check on every endpoint",
     [("app/server.py", ITEM_ROUTE, ITEM_ROUTE.replace("scope, mode, partial", 'scope, "all" if method == "PUT" else mode, partial'))]),
    ("put-patch-skip-the-permission", "role check on every endpoint",
     [("app/server.py", ITEM_ROUTE, ITEM_ROUTE.replace("mode = self._permit(account, method)",
                                                        'mode = "all" if method in ("PUT", "PATCH") else self._permit(account, method)'))]),
    ("sub-resources-skip-the-permission", "role check on every endpoint",
     [("app/server.py", 'modes = (self._permit(account, "PUT"), self._permit(account, "DELETE"))', 'modes = ("all",)'),
      ("app/server.py", 'modes = (self._permit(account, "PUT" if method == "POST" else "GET"),)', 'modes = ("all",)'),
      ("app/server.py", 'modes = (self._permit(account, "GET"),)', 'modes = ("all",)')]),
    ("patch-skips-validation", "input validation on every write endpoint",
     [("app/server.py", VALIDATED, f"        values = {RAW_MERGE} if partial else self._validated(entity, payload, base=None)")]),
    ("put-skips-validation", "input validation on every write endpoint",
     [("app/server.py", VALIDATED, "        values = self._validated(entity, payload, base=stored) if partial else "
                                   "{c: payload.get(c) for c in entity.columns}")]),
)


class WriteEndpointEvidenceTests(MutatedApp):
    """recheck-build W2-BU-06 evidence gap: 'role check on every endpoint' and 'input validation on every
    write endpoint' are evidenced by generated tests that cover PUT and PATCH (ownership included) and
    the link, child and progress routes, and those tests fail when the server drops the check."""

    def evidence(self, statement):
        spec = engine.validate_spec(requirements.parse(_APP._FIXTURE.COMMAND))
        model = engine.derive_model(spec)
        engine.compile_acceptance(spec, model)
        return [test for test in engine.map_statement(model, spec["locales"], statement) if test.startswith("tests.")]

    def test_rows_name_the_update_and_sub_resource_tests(self):
        api = engine.API_ID
        roles = set(self.evidence("role check on every endpoint"))
        self.assertTrue({api + "test_role_check_on_every_endpoint", api + "test_unauthenticated_requests_refused",
                         api + "test_links_project_members", api + "test_children_project_tasks",
                         api + "test_progress_uses_one_aggregate_query"} <= roles, sorted(roles))
        validation = set(self.evidence("input validation on every write endpoint"))
        self.assertTrue({api + "test_validation_task", api + "test_validation_project", api + "test_links_project_members",
                         engine.VALIDATION_ID + "test_types_task"} <= validation, sorted(validation))
        source = (self.app / "tests/test_api.py").read_text(encoding="utf-8")
        self.assertIn("def _item_writes_for_roles(self):", source)
        self.assertIn("def _validation_on_update(self, entity, required):", source)

    def test_the_rows_evidence_fails_when_put_or_patch_loses_a_check(self):
        rows = {statement: self.evidence(statement)
                for statement in ("role check on every endpoint", "input validation on every write endpoint")}
        for tests in rows.values():
            self.assertGeneratedPasses(tests)
        for name, statement, edits in WRITE_MUTANTS:
            with self.subTest(name):
                copy = None
                for path, old, new in edits:
                    copy = self.mutant(name, path, old, new) if copy is None else self._edit(copy, path, old, new)
                self.assertGeneratedFails(rows[statement], copy)

    def _edit(self, copy, path, old, new):
        source = (copy / path).read_text(encoding="utf-8")
        self.assertTrue(old in source, f"the code a mutation changes is not in {path}")
        (copy / path).write_text(source.replace(old, new), encoding="utf-8")
        return copy


if __name__ == "__main__":
    unittest.main()
