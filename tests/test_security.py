import pathlib
import re
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bgh[opsu]_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{24,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)


class SecurityTests(unittest.TestCase):
    def test_tracked_text_has_no_obvious_secrets(self):
        files = subprocess.check_output(
            ["git", "ls-files"], cwd=ROOT, text=True
        ).splitlines()
        findings = []
        for relative in files:
            path = ROOT / relative
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for pattern in SECRET_PATTERNS:
                if pattern.search(text):
                    findings.append(relative)
        self.assertEqual(findings, [])

    def test_actions_are_sha_pinned_and_permissions_read_only(self):
        workflow = (ROOT / ".github/workflows/verify.yml").read_text()
        uses = re.findall(r"uses:\s*[^@\s]+@([^\s#]+)", workflow)
        self.assertTrue(uses)
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{40}", value) for value in uses))
        self.assertIn("permissions:\n  contents: read", workflow)
        self.assertIn("timeout-minutes:", workflow)

    def test_no_tracked_environment_or_key_files(self):
        files = set(
            subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).splitlines()
        )
        forbidden = [
            name
            for name in files
            if pathlib.PurePosixPath(name).name.startswith(".env")
            or pathlib.PurePosixPath(name).suffix in {".pem", ".key", ".p12"}
        ]
        self.assertEqual(forbidden, [])


if __name__ == "__main__":
    unittest.main()
