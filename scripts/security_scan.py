#!/usr/bin/env python3
"""Bounded, read-only checks of the Git index; never prints matched source values.

`scan` checks tracked text and a limited set of Python AST execution hazards.
`dependencies` audits exact npm lock snapshots using the public registry, without
installation, lifecycle scripts, provider credentials, or automatic fixes.
"""

import argparse
import ast
import base64
import dataclasses
import json
import os
import pathlib
import re
import selectors
import subprocess
import sys
import tempfile
import time

MAX_FILES = 10000
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_LOCKS = 8
REQUIRED_LOCKS = frozenset(("motion-library/verify/package-lock.json", "motion-library/chromium-stack/package-lock.json"))
EXACT_VERSION = re.compile(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?")

SECRET_PATTERNS = (
    ("private-key", re.compile(r"-----BEGIN (?:RSA |DSA |EC |OPENSSH |ENCRYPTED |PGP )?PRIVATE KEY(?: BLOCK)?-----")),
    ("openai-or-anthropic-key", re.compile(r"\bsk-(?:(?:proj|svcacct|admin|ant)-[A-Za-z0-9_-]{20,}|[A-Za-z0-9]{32,})\b")),
    ("github-token", re.compile(r"\b(?:gh[opsur]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{60,})\b")),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("google-api-key", re.compile(r"\bAIza[A-Za-z0-9_-]{35}\b")),
    ("stripe-secret", re.compile(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{20,}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("supabase-secret", re.compile(r"\bsb_secret_[A-Za-z0-9_-]{20,}\b")),
    ("elevenlabs-key", re.compile(r"\bsk_[a-f0-9]{48}\b")),
    ("resend-key", re.compile(r"\bre_[A-Za-z0-9]{8}_[A-Za-z0-9]{24}\b")),
    ("bearer-token", re.compile(r"\bBearer\s+[A-Za-z0-9_./+=-]{16,}\b", re.I)),
)
CREDENTIAL_URL = re.compile(r"\b(?:https?|postgres(?:ql)?|mysql|rediss?|mongodb(?:\+srv)?)://[^\s/:@]+:(?P<password>[^\s/@]+)@", re.I)
TOKEN_QUERY = re.compile(r"[?&](?:_vercel_share|x-vercel-protection-bypass|access_token|auth_token|token|api_key|password|x-amz-signature|x-goog-signature)=(?P<value>[^\s&#\"'<>]{16,})", re.I)
SENSITIVE_NAME = r"(?:[A-Za-z0-9_]*(?:API_KEY|ACCESS_TOKEN|AUTH_TOKEN|CLIENT_SECRET|BYPASS_SECRET|BYPASS_TOKEN|PRIVATE_KEY|PASSWORD|VERCEL_TOKEN|FINN_GITHUB_TOKEN|FINN_VERCEL_TOKEN)[A-Za-z0-9_]*|token|secret)"
QUOTED_VALUE = re.compile(r"(?<![\w])(?:[\"']?" + SENSITIVE_NAME + r"[\"']?)\s*[:=]\s*(?P<quote>[\"'])(?P<value>[^\r\n\"']{16,})(?P=quote)", re.I)
ENV_VALUE = re.compile(r"^\s*(?:export\s+)?" + SENSITIVE_NAME + r"\s*[:=]\s*(?P<value>[^\s#\"']{16,})", re.I | re.M)
JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.(?P<body>[A-Za-z0-9_-]{8,})\.[A-Za-z0-9_-]{16,}\b")
TEMPLATE = re.compile(r"^(?:\$\{|\{\{|<|process\.env\.|os\.environ|os\.getenv|secrets\.)")
PLACEHOLDERS = frozenset(("your-api-key-here", "replace-with-your-token", "replace-with-a-secret", "example-token-value", "set-in-provider-env"))


def placeholder(value):
    return bool(TEMPLATE.match(value)) or value.casefold() in PLACEHOLDERS


def pairs(rows):
    output = {}
    for key, value in rows:
        if key in output:
            raise ValueError("duplicate JSON key")
        output[key] = value
    return output


def parse_json(data):
    return json.loads(data, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("invalid JSON number")))


@dataclasses.dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str


def secret_findings(path, source):
    hits = []
    for rule, pattern in SECRET_PATTERNS:
        hits.extend(Finding(path, source.count("\n", 0, match.start()) + 1, rule) for match in pattern.finditer(source))
    for rule, pattern, field in (("credential-url", CREDENTIAL_URL, "password"), ("token-in-url", TOKEN_QUERY, "value"), ("literal-secret", QUOTED_VALUE, "value")):
        for match in pattern.finditer(source):
            if not placeholder(match[field]):
                hits.append(Finding(path, source.count("\n", 0, match.start()) + 1, rule))
    if pathlib.PurePosixPath(path).suffix.lower() in {".yml", ".yaml", ".toml", ".env"} or pathlib.PurePosixPath(path).name.startswith(".env"):
        for match in ENV_VALUE.finditer(source):
            if not placeholder(match["value"]):
                hits.append(Finding(path, source.count("\n", 0, match.start()) + 1, "literal-secret"))
    for match in JWT.finditer(source):
        try:
            body = parse_json(base64.urlsafe_b64decode(match["body"] + "=" * (-len(match["body"]) % 4)))
            if isinstance(body, dict) and body.get("role") in ("service_role", "supabase_admin"):
                hits.append(Finding(path, source.count("\n", 0, match.start()) + 1, "privileged-jwt"))
        except (ValueError, UnicodeError):
            pass
    return hits


def python_findings(path, source):
    """Import-aware syntax checks, not whole-program taint analysis."""
    try:
        tree = ast.parse(source, filename="<tracked-python>")
    except (SyntaxError, ValueError, RecursionError):
        return [Finding(path, 1, "python-syntax-or-complexity")]
    imports = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for entry in node.names:
                imports[entry.asname or entry.name.split(".")[0]] = entry.name if entry.asname else entry.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and node.module:
            for entry in node.names:
                imports[entry.asname or entry.name] = node.module + "." + entry.name

    def qualified(node):
        if isinstance(node, ast.Name):
            return imports.get(node.id, node.id)
        if isinstance(node, ast.Attribute):
            return qualified(node.value) + "." + node.attr
        return ""

    def false_literal(node):
        return isinstance(node, ast.Constant) and node.value in (False, None, 0, "")

    hits = []
    for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
        name = qualified(call.func)
        rule = None
        if name in {"subprocess.run", "subprocess.call", "subprocess.check_call", "subprocess.check_output", "subprocess.Popen"}:
            for keyword in call.keywords:
                if keyword.arg == "shell" and not false_literal(keyword.value):
                    rule = "subprocess-shell"
                if keyword.arg is None and isinstance(keyword.value, ast.Dict):
                    for key, value in zip(keyword.value.keys, keyword.value.values):
                        if isinstance(key, ast.Constant) and key.value == "shell" and not false_literal(value):
                            rule = "subprocess-shell"
        elif name in {"os.system", "os.popen", "subprocess.getoutput", "subprocess.getstatusoutput"}:
            rule = "implicit-shell"
        elif name in {"pickle.load", "pickle.loads"}:
            rule = "pickle-deserialization"
        elif name in {"yaml.load", "yaml.unsafe_load"}:
            safe = any(k.arg == "Loader" and qualified(k.value) in {"yaml.SafeLoader", "yaml.CSafeLoader"} for k in call.keywords)
            safe = safe or len(call.args) > 1 and qualified(call.args[1]) in {"yaml.SafeLoader", "yaml.CSafeLoader"}
            if name == "yaml.unsafe_load" or not safe:
                rule = "unsafe-yaml-loader"
        elif name == "tempfile.mktemp":
            rule = "insecure-temporary-name"
        if rule:
            hits.append(Finding(path, call.lineno, rule))
    return hits


def bounded_run(args, *, cwd=None, env=None, timeout=20, limit=MAX_FILE_BYTES, capture_output=True, check=False):
    """Stop a child at its time/output boundary without retaining stderr or values."""
    deadline, output = time.monotonic() + timeout, bytearray()
    with subprocess.Popen(args, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as process:
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise subprocess.TimeoutExpired("bounded audit command", timeout)
                block = os.read(process.stdout.fileno(), min(65536, limit + 1 - len(output)))
                if not block:
                    break
                output.extend(block)
                if len(output) > limit:
                    raise ValueError("command output exceeds bound")
            code = process.wait(timeout=max(0.001, deadline - time.monotonic()))
            if check and code:
                raise subprocess.CalledProcessError(code, "bounded audit command")
            return subprocess.CompletedProcess(args, code, bytes(output), b"")
        finally:
            selector.close()
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)


def git(root, *args, limit=MAX_TOTAL_BYTES):
    return bounded_run(["git", "-C", str(root), *args], timeout=20, limit=limit, check=True).stdout


def index(root, base=None):
    """Read stage-zero blobs, including staged files; never follows worktree links."""
    raw = git(root, "ls-files", "--stage", "-z", limit=4 * 1024 * 1024)
    entries = raw.rstrip(b"\0").split(b"\0") if raw else []
    if len(entries) > MAX_FILES:
        raise ValueError("too many tracked files")
    changed = None
    if base is not None:
        if not re.fullmatch(r"[a-f0-9]{40}", base):
            raise ValueError("base must be an immutable commit SHA")
        changed = set(git(root, "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z", base, "--").rstrip(b"\0").split(b"\0"))
    output, total = {}, 0
    for row in entries:
        info, name = row.split(b"\t", 1)
        mode, oid, stage = info.split()
        if changed is not None and name not in changed:
            continue
        if mode not in (b"100644", b"100755") or stage != b"0" or not re.fullmatch(rb"[a-f0-9]{40,64}", oid):
            raise ValueError("non-regular or unmerged index entry")
        size = int(git(root, "cat-file", "-s", oid.decode(), limit=128))
        total += size
        if size > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
            raise ValueError("tracked content exceeds scan bounds")
        data = git(root, "cat-file", "blob", oid.decode(), limit=MAX_FILE_BYTES)
        if len(data) != size:
            raise ValueError("Git blob size mismatch")
        decoded = name.decode("utf-8", errors="replace")
        if decoded in output:
            raise ValueError("ambiguous index path encoding")
        output[decoded] = data
    return output


def scan(files):
    findings, text_count, binary_count = [], 0, 0
    for path, data in files.items():
        name = pathlib.PurePosixPath(path).name
        if (name == ".env" or name.startswith(".env.") and name not in {".env.example", ".env.sample", ".env.template"}) or pathlib.PurePosixPath(path).suffix.lower() in {".pem", ".key", ".p12", ".pfx"}:
            findings.append(Finding(path, 1, "private-configuration-file"))
        if b"\0" in data:
            binary_count += 1
            continue
        text_count += 1
        source = data.decode("utf-8", errors="replace")
        findings.extend(secret_findings(path, source))
        if pathlib.PurePosixPath(path).suffix.lower() == ".py":
            findings.extend(python_findings(path, source))
    unique = sorted(set(findings), key=lambda item: (item.path, item.line, item.rule))
    return {"status": "pass" if not unique else "fail", "tracked_text_files": text_count, "binary_files_skipped": binary_count,
            "findings": [{"path": redact_path(row.path), "line": row.line, "rule": row.rule} for row in unique]}


def redact_path(path):
    if QUOTED_VALUE.search(path) or ENV_VALUE.search(path):
        return "[redacted-path]"
    for _, pattern in SECRET_PATTERNS:
        path = pattern.sub("[redacted]", path)
    path = CREDENTIAL_URL.sub("[redacted-url]", path)
    return TOKEN_QUERY.sub("[redacted-query]", path)


def lock_scopes(files, required=REQUIRED_LOCKS):
    locks = sorted(path for path in files if pathlib.PurePosixPath(path).name == "package-lock.json")
    if not required.issubset(locks) or not locks or len(locks) > MAX_LOCKS:
        raise ValueError("required lock scope missing or too many lock scopes")
    for lock_path in locks:
        package_path = str(pathlib.PurePosixPath(lock_path).with_name("package.json"))
        if package_path not in files:
            raise ValueError("lock scope has no tracked package manifest")
        manifest, lock = parse_json(files[package_path]), parse_json(files[lock_path])
        if not isinstance(manifest, dict) or not isinstance(lock, dict) or lock.get("lockfileVersion") not in (2, 3) or not isinstance(lock.get("packages"), dict):
            raise ValueError("unsupported lockfile")
        packages = lock["packages"]
        if "" not in packages or not isinstance(packages[""], dict) or len(packages) > MAX_FILES:
            raise ValueError("invalid lock package count")
        for group in ("dependencies", "devDependencies", "optionalDependencies"):
            declared = manifest.get(group, {})
            if not isinstance(declared, dict) or declared != packages[""].get(group, {}) or not all(isinstance(value, str) and EXACT_VERSION.fullmatch(value) for value in declared.values()):
                raise ValueError("root dependencies must be exact and match lockfile")
        for name, package in packages.items():
            if name and (not isinstance(package, dict) or not EXACT_VERSION.fullmatch(str(package.get("version", ""))) or package.get("link") or not re.fullmatch(r"https://registry\.npmjs\.org/[A-Za-z0-9@%._~+/-]+", str(package.get("resolved", ""))) or not re.fullmatch(r"sha512-[A-Za-z0-9+/]+={0,2}", str(package.get("integrity", "")))):
                raise ValueError("unreviewed or unpinned lockfile source")
    return locks


def audit_locks(files, runner=None):
    runner = runner or bounded_run
    results = []
    for lock_path in lock_scopes(files):
        package_path = str(pathlib.PurePosixPath(lock_path).with_name("package.json"))
        with tempfile.TemporaryDirectory(prefix="hub-npm-audit-") as temp:
            folder = pathlib.Path(temp)
            (folder / "package.json").write_bytes(files[package_path])
            (folder / "package-lock.json").write_bytes(files[lock_path])
            (folder / "user.npmrc").write_text("")
            (folder / "global.npmrc").write_text("")
            allowed = {"PATH", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "all_proxy", "no_proxy", "NODE_EXTRA_CA_CERTS", "SSL_CERT_FILE", "SSL_CERT_DIR"}
            env = {key: value for key, value in os.environ.items() if key in allowed}
            env.update({"npm_config_userconfig": str(folder / "user.npmrc"), "npm_config_globalconfig": str(folder / "global.npmrc"), "npm_config_cache": str(folder / "cache"), "npm_config_update_notifier": "false"})
            try:
                result = runner(["npm", "audit", "--package-lock-only", "--json", "--ignore-scripts", "--audit-level=high", "--registry=https://registry.npmjs.org/"], cwd=folder, env=env, capture_output=True, timeout=60, check=False)
                if result.returncode not in (0, 1) or len(result.stdout) > MAX_FILE_BYTES:
                    raise ValueError("npm audit unavailable")
                receipt = parse_json(result.stdout)
                counts = receipt["metadata"]["vulnerabilities"]
                if not isinstance(counts, dict) or receipt.get("auditReportVersion") != 2 or receipt.get("error") or not all(type(counts.get(level)) is int and counts[level] >= 0 for level in ("info", "low", "moderate", "high", "critical")):
                    raise ValueError("invalid audit response")
                summary = {level: counts[level] for level in ("info", "low", "moderate", "high", "critical")}
                results.append({"scope": str(pathlib.PurePosixPath(lock_path).parent), "status": "fail" if summary["high"] or summary["critical"] else "pass", "vulnerabilities": summary})
            except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired):
                results.append({"scope": str(pathlib.PurePosixPath(lock_path).parent), "status": "audit-unavailable"})
    return {"status": "pass" if all(row["status"] == "pass" for row in results) else "fail", "lock_scopes": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("scan", "dependencies"))
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path(__file__).resolve().parents[1])
    parser.add_argument("--base", help="Scan changed index blobs relative to a full commit SHA (scan command only)")
    args = parser.parse_args()
    try:
        if args.command == "dependencies" and args.base:
            raise ValueError("dependency audit always checks all tracked lock scopes")
        files = index(args.root, args.base)
        report = scan(files) if args.command == "scan" else audit_locks(files)
    except (ValueError, OSError, subprocess.SubprocessError, RecursionError):
        report = {"status": "fail", "error": "Input, Git, or scan boundary failed; inspect tracked index and documented limits."}
    print(json.dumps(report, indent=2, ensure_ascii=True))
    return int(report["status"] != "pass")


if __name__ == "__main__":
    sys.exit(main())
