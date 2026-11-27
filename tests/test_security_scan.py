import base64
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("hub_security_scan", ROOT / "scripts/security_scan.py")
scan = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = scan
SPEC.loader.exec_module(scan)


def key(prefix, count=40):
    return prefix + "A1b2C3d4" * (count // 8 + 1)


def lock_files(extra=0):
    manifest = {"name": "fixture", "private": True, "devDependencies": {"example": "1.2.3"}}
    lock = {"lockfileVersion": 3, "packages": {"": manifest, "node_modules/example": {
        "version": "1.2.3", "resolved": "https://registry.npmjs.org/example/-/example-1.2.3.tgz", "integrity": "sha512-" + "A" * 86 + "=="}}}
    scopes = ["motion-library/verify", "motion-library/chromium-stack"] + [f"future/quality-{i}" for i in range(extra)]
    return {f"{scope}/{name}": json.dumps(data).encode() for scope in scopes for name, data in (("package.json", manifest), ("package-lock.json", lock))}


def audit_receipt(high=0, critical=0, moderate=0, returncode=None):
    counts = {"info": 0, "low": 0, "moderate": moderate, "high": high, "critical": critical, "total": high + critical + moderate}
    return types.SimpleNamespace(returncode=int(bool(high or critical)) if returncode is None else returncode,
                                 stdout=json.dumps({"auditReportVersion": 2, "metadata": {"vulnerabilities": counts}}).encode(), stderr=b"")


class SecretTests(unittest.TestCase):
    def rules(self, text, path="example.txt"):
        return {f.rule for f in scan.secret_findings(path, text)}

    def test_known_provider_credentials_are_detected_without_entropy_guesses(self):
        samples = [
            (key("sk-" + "proj-"), "openai-or-anthropic-key"),
            (key("sk-" + "ant-"), "openai-or-anthropic-key"),
            (key("gh" + "p_"), "github-token"),
            (key("github_" + "pat_", 80), "github-token"),
            ("AK" + "IA" + "A" * 16, "aws-access-key"),
            ("AI" + "za" + "A" * 35, "google-api-key"),
            (key("sk_" + "live_"), "stripe-secret"),
            (key("xox" + "b-"), "slack-token"),
            (key("sb_" + "secret_"), "supabase-secret"),
            ("sk" + "_" + "a" * 48, "elevenlabs-key"),
            ("re" + "_" + "A" * 8 + "_" + "B" * 24, "resend-key"),
        ]
        for value, expected in samples:
            with self.subTest(expected=expected):
                self.assertIn(expected, self.rules(value))

    def test_private_key_markers_cover_encrypted_and_openssh(self):
        for kind in ("", "RSA ", "EC ", "OPENSSH ", "ENCRYPTED ", "PGP "):
            value = "-----BEGIN " + kind + "PRIVATE KEY" + (" BLOCK" if kind == "PGP " else "") + "-----"
            self.assertIn("private-key", self.rules(value))

    def test_credential_urls_query_tokens_and_literal_bypass_values(self):
        token = key("opaque-")
        examples = [("postgres://owner:" + token + "@db.example/test", "credential-url"),
                    ("https://site.example/?_vercel_share=" + token, "token-in-url"),
                    ("https://site.example/?X-Amz-Signature=" + "a" * 64, "token-in-url"),
                    ('{"VERCEL_AUTOMATION_BYPASS_SECRET": "' + token + '"}', "literal-secret"),
                    ("export VERCEL_TOKEN=" + token, "literal-secret"),
                    ("Authorization: Bearer " + token, "bearer-token")]
        for source, expected in examples:
            with self.subTest(rule=expected):
                self.assertIn(expected, self.rules(source, ".env.production"))

    def test_privileged_jwt_is_a_secret_but_anon_role_is_not(self):
        encode = lambda data: base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()
        make = lambda role: encode({"alg": "HS256"}) + "." + encode({"role": role, "iss": "fixture"}) + "." + "a" * 32
        self.assertIn("privileged-jwt", self.rules(make("service_role")))
        self.assertNotIn("privileged-jwt", self.rules(make("anon")))

    def test_safe_hashes_placeholders_and_runtime_references_do_not_trigger(self):
        safe = ["a" * 40, "b" * 64, "sha512-" + "A" * 86 + "==",
                '{"sha256":"' + "a" * 64 + '"}',
                '{"API_KEY":"replace-with-your-token"}',
                '{"API_KEY":"${SECRET_FROM_ENV}"}',
                "VERCEL_TOKEN=${{ secrets.VERCEL_TOKEN }}",
                "PASSWORD = os.environ.get('PASSWORD')",
                '"Authorization": "Bearer ${TOKEN_FROM_RUNTIME}"',
                "https://example.test/?sha256=" + "a" * 64,
                "postgres://user:${PASSWORD}@localhost/db"]
        for source in safe:
            with self.subTest(source=source):
                self.assertEqual(self.rules(source, "config.yml"), set())

    def test_report_contains_locations_and_rule_ids_but_no_source_or_value(self):
        value = key("gh" + "p_")
        report = scan.scan({"config.txt": ("safe\n" + value + "\n").encode()})
        self.assertEqual(report["status"], "fail")
        self.assertEqual(report["findings"][0]["line"], 2)
        self.assertNotIn(value, json.dumps(report))
        self.assertNotIn(value, json.dumps(scan.scan({value + ".txt": value.encode()})))

    def test_binary_skip_is_counted_and_private_env_files_fail_even_when_empty(self):
        report = scan.scan({"image.bin": b"\0data", ".env.production": b"", ".env.example": b"API_KEY=<set-at-runtime>"})
        self.assertEqual(report["binary_files_skipped"], 1)
        self.assertEqual(report["findings"], [{"path": ".env.production", "line": 1, "rule": "private-configuration-file"}])


class ASTTests(unittest.TestCase):
    def rules(self, text):
        return {row.rule for row in scan.python_findings("fixture.py", text)}

    def test_shell_apis_and_import_aliases_are_detected(self):
        sources = ["import subprocess as sp\nsp.run('echo x',shell=True)",
                   "from subprocess import check_output as invoke\ninvoke('x',shell=enabled)",
                   "from subprocess import run\nrun('x',**{'shell': True})"]
        for source in sources:
            with self.subTest(source=source):
                self.assertIn("subprocess-shell", self.rules(source))
        for source in ["import os as system\nsystem.system('echo x')", "from subprocess import getoutput\ngetoutput('echo x')"]:
            self.assertIn("implicit-shell", self.rules(source))

    def test_safe_subprocess_argument_arrays_and_unrelated_methods_are_allowed(self):
        for source in ["import subprocess\nsubprocess.run(['echo','safe'],shell=False)",
                       "from subprocess import run\nrun(['echo','safe'])",
                       "import subprocess\nsubprocess.run(['echo','safe'],**{'shell':False})",
                       "runner.run('job', shell=True)"]:
            self.assertFalse(self.rules(source))

    def test_unsafe_deserialization_and_temporary_name_rules(self):
        sources = [("import pickle as p\np.loads(data)", "pickle-deserialization"),
                   ("import yaml\nyaml.load(data)", "unsafe-yaml-loader"),
                   ("import yaml\nyaml.load(data,Loader=yaml.FullLoader)", "unsafe-yaml-loader"),
                   ("import yaml\nyaml.unsafe_load(data,Loader=yaml.SafeLoader)", "unsafe-yaml-loader"),
                   ("from tempfile import mktemp as name\nname()", "insecure-temporary-name")]
        for source, rule in sources:
            with self.subTest(rule=rule):
                self.assertIn(rule, self.rules(source))

    def test_safe_yaml_loader_aliases_and_syntax_failure(self):
        self.assertFalse(self.rules("import yaml\nyaml.load(data,Loader=yaml.SafeLoader)"))
        self.assertFalse(self.rules("from yaml import load as parse, CSafeLoader as Loader\nparse(data,Loader=Loader)"))
        self.assertFalse(self.rules("import yaml\nyaml.load(data,yaml.CSafeLoader)"))
        self.assertIn("python-syntax-or-complexity", self.rules("def incomplete("))


class IndexTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = pathlib.Path(directory.name)
        self.git("init", "--quiet")

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.root), *args], stderr=subprocess.DEVNULL).decode().strip()

    def stage(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data)
        self.git("add", "--", name)

    def test_scan_uses_index_bytes_and_ignores_untracked_files(self):
        self.stage("config.txt", "safe")
        (self.root / "config.txt").write_text(key("gh" + "p_"))
        (self.root / "untracked.txt").write_text(key("gh" + "p_"))
        files = scan.index(self.root)
        self.assertEqual(files, {"config.txt": b"safe"})
        self.assertEqual(scan.scan(files)["status"], "pass")
        self.git("add", "config.txt")
        (self.root / "config.txt").write_text("safe again")
        self.assertEqual(scan.scan(scan.index(self.root))["status"], "fail")

    def test_optional_diff_scope_is_bound_to_full_base_commit(self):
        self.stage("same.txt", "safe")
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.test", "commit", "-qm", "fixture")
        base = self.git("rev-parse", "HEAD")
        self.stage("new.txt", "candidate")
        self.assertEqual(scan.index(self.root, base), {"new.txt": b"candidate"})
        with self.assertRaises(ValueError):
            scan.index(self.root, "main")

    def test_symlink_and_size_count_total_bounds_fail_closed(self):
        self.stage("one.txt", "1234567")
        with mock.patch.object(scan, "MAX_FILE_BYTES", 4), self.assertRaises(ValueError):
            scan.index(self.root)
        self.stage("two.txt", "1234567")
        with mock.patch.object(scan, "MAX_FILES", 1), self.assertRaises(ValueError):
            scan.index(self.root)
        with mock.patch.object(scan, "MAX_TOTAL_BYTES", 10), self.assertRaises(ValueError):
            scan.index(self.root)
        (self.root / "link").symlink_to("one.txt")
        self.git("add", "link")
        with self.assertRaises(ValueError):
            scan.index(self.root)


class ProcessBoundTests(unittest.TestCase):
    def test_output_is_capped_before_collecting_a_large_child_response(self):
        with self.assertRaises(ValueError):
            scan.bounded_run([sys.executable, "-c", "print('x' * 16384)"], limit=128)

    def test_timeout_kills_child_and_errors_do_not_include_its_output(self):
        with self.assertRaises(subprocess.TimeoutExpired) as caught:
            scan.bounded_run([sys.executable, "-c", "import time; time.sleep(2)"], timeout=0.02)
        self.assertNotIn("time.sleep", str(caught.exception))


class DependencyTests(unittest.TestCase):
    def test_both_existing_locks_and_future_quality_scope_are_discovered(self):
        paths = scan.lock_scopes(lock_files(extra=1))
        self.assertEqual(len(paths), 3)
        self.assertIn("future/quality-0/package-lock.json", paths)
        with self.assertRaises(ValueError):
            scan.lock_scopes(lock_files(extra=7))
        files = lock_files()
        del files[next(iter(scan.REQUIRED_LOCKS))]
        with self.assertRaises(ValueError):
            scan.lock_scopes(files)

    def test_unpinned_ranges_foreign_tarballs_and_missing_integrity_fail(self):
        for field, value in [("resolved", "https://registry.npmjs.org.evil.test/a.tgz"), ("integrity", ""), ("version", "latest")]:
            files = lock_files()
            name = next(iter(scan.REQUIRED_LOCKS))
            lock = json.loads(files[name])
            lock["packages"]["node_modules/example"][field] = value
            files[name] = json.dumps(lock).encode()
            with self.subTest(field=field), self.assertRaises(ValueError):
                scan.lock_scopes(files)
        files = lock_files()
        name = "motion-library/verify/package.json"
        package = json.loads(files[name])
        package["devDependencies"]["example"] = "^1.2.3"
        files[name] = json.dumps(package).encode()
        with self.assertRaises(ValueError):
            scan.lock_scopes(files)

    def test_audit_is_lock_only_runs_no_install_or_fix_and_drops_authentication(self):
        calls = []
        def runner(args, **options):
            self.assertEqual(args[:2], ["npm", "audit"])
            self.assertIn("--package-lock-only", args)
            self.assertIn("--ignore-scripts", args)
            self.assertNotIn("--omit=dev", args)
            self.assertNotIn("fix", args)
            env = options["env"]
            self.assertNotIn("GH_TOKEN", env)
            self.assertNotIn("VERCEL_TOKEN", env)
            self.assertNotIn("npm_config__authToken", env)
            self.assertEqual(json.loads((options["cwd"] / "package-lock.json").read_text())["lockfileVersion"], 3)
            calls.append(args)
            return audit_receipt(moderate=1)
        with mock.patch.dict(os.environ, {"GH_TOKEN": "private", "VERCEL_TOKEN": "private", "npm_config__authToken": "private"}):
            result = scan.audit_locks(lock_files(), runner)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(len(calls), 2)

    def test_high_critical_and_unavailable_audits_block(self):
        for receipt in [audit_receipt(high=1), audit_receipt(critical=1), types.SimpleNamespace(returncode=1, stdout=b'{"error":{"message":"private text"}}'), types.SimpleNamespace(returncode=2, stdout=b"private text")]:
            result = scan.audit_locks(lock_files(), lambda *args, **kwargs: receipt)
            self.assertEqual(result["status"], "fail")
            self.assertNotIn("private text", json.dumps(result))
        result = scan.audit_locks(lock_files(), mock.Mock(side_effect=subprocess.TimeoutExpired("npm", 60)))
        self.assertTrue(all(row["status"] == "audit-unavailable" for row in result["lock_scopes"]))

    def test_malformed_audit_severity_cannot_report_success(self):
        receipt = audit_receipt()
        data = json.loads(receipt.stdout)
        data["metadata"]["vulnerabilities"]["high"] = False
        receipt.stdout = json.dumps(data).encode()
        self.assertEqual(scan.audit_locks(lock_files(), lambda *args, **kwargs: receipt)["status"], "fail")

    def test_malformed_manifest_or_package_types_fail_closed(self):
        for replacement in ([], None):
            files = lock_files()
            files["motion-library/verify/package.json"] = json.dumps(replacement).encode()
            with self.assertRaises(ValueError):
                scan.lock_scopes(files)
            files = lock_files()
            name = "motion-library/verify/package-lock.json"
            data = json.loads(files[name])
            data["packages"]["node_modules/example"] = replacement
            files[name] = json.dumps(data).encode()
            with self.assertRaises(ValueError):
                scan.lock_scopes(files)


if __name__ == "__main__":
    unittest.main()
