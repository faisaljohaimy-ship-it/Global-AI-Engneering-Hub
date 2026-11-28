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
    def test_runtime_provenance_binds_relative_public_files_without_private_paths(self):
        import hashlib
        import json
        policy=json.loads((ROOT/'catalog/capabilities/playwright.json').read_text())
        reference=policy['provenance_manifest']
        path=ROOT/reference['path']
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),reference['sha256'])
        manifest=json.loads(path.read_text())
        for row in [reference,*manifest['files']]:
            relative=pathlib.PurePosixPath(row['path'])
            self.assertFalse(relative.is_absolute());self.assertNotIn('..',relative.parts)
            self.assertTrue(row['path'].startswith('docs/evidence/'))
            self.assertFalse((ROOT/row['path']).is_symlink())
            self.assertRegex(row['sha256'],r'^[a-f0-9]{64}$')
            self.assertEqual(hashlib.sha256((ROOT/row['path']).read_bytes()).hexdigest(),row['sha256'])
        for name,digest in manifest['source_sha256'].items():
            self.assertEqual(hashlib.sha256((ROOT/name).read_bytes()).hexdigest(),digest)
        for forbidden in ('/workspace/','/home/','download_url','_vercel_share','x-vercel-protection-bypass','private_project'):
            self.assertNotIn(forbidden,json.dumps(manifest))

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
        workflows = sorted((ROOT / ".github/workflows").glob("*.yml")) + [ROOT / "templates/hub-link.yml"]
        for path in workflows:
            workflow = path.read_text()
            uses = re.findall(r"uses:\s*[^@\s]+@([^\s#]+)", workflow)
            self.assertTrue(uses, path)
            self.assertTrue(all(re.fullmatch(r"[0-9a-f]{40}", value) for value in uses), path)
            self.assertIn("permissions:\n  contents: read", workflow, path)
            self.assertIn("timeout-minutes:", workflow, path)
            self.assertNotIn("pull_request_target", workflow, path)

    def test_browser_verifier_dependency_is_exact_and_integrity_locked(self):
        import json
        policy = json.loads((ROOT / 'catalog/capabilities/playwright.json').read_text())
        row = next(r for r in json.loads((ROOT / 'catalog/registry.json').read_text()) if r['id'] == 'microsoft/playwright')
        self.assertEqual(row['status'], 'approved')
        self.assertEqual(row['revision'], policy['revision'])
        self.assertRegex(policy['revision'], r'^[a-f0-9]{40}$')
        self.assertRegex(policy['version'], r'^\d+\.\d+\.\d+$')
        for scope in ('verify', 'chromium-stack', 'quality'):
            package = json.loads((ROOT / f'motion-library/{scope}/package.json').read_text())
            lock = json.loads((ROOT / f'motion-library/{scope}/package-lock.json').read_text())
            self.assertEqual(package['devDependencies']['playwright'], policy['version'])
            for name in ('playwright', 'playwright-core'):
                entry = lock['packages']['node_modules/' + name]
                self.assertEqual(entry['version'], policy['version'])
                self.assertEqual(entry['integrity'], policy['npm_integrities'][name])
                self.assertEqual(entry['license'], 'Apache-2.0')

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
