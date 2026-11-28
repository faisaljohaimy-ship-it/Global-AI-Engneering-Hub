"""Regressions for the recheck-build review of the generated application (templates/app-stdlib).

Each class builds an application with the Master Build Engine (verify=False) from the real
engineering_os.requirements output for the owner's command and drives that application's
real HTTP server on loopback in a child process (helpers from tests/test_build_fixes_app.py),
or runs the application's own generated tests, unmodified and on a mutated copy, to show that
a generated test fails when the behaviour it stands for is removed. No network beyond loopback.
"""
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


if __name__ == "__main__":
    unittest.main()
