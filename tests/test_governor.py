"""Scenario E evidence: the Security Governor (engineering_os/governor.py).

Every rule is proven by an allowed case and a refused case. Credential look-alikes are
assembled at run time from fragments, so no token-shaped literal is ever tracked, and
no test ever writes to a kernel control file.
"""
import datetime
import hashlib
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engineering_os import contracts, governor  # noqa: E402
from engineering_os.governor import GovernorDenied  # noqa: E402

FUTURE = "2099-01-01T00:00:00Z"
EVIDENCE = ROOT / "docs" / "evidence" / "gaie-20-layers" / "isolation.json"


def body(n, seed="gaie", upper=False):
    """Deterministic look-alike characters (never a real credential)."""
    text = ""
    while len(text) < n:
        seed = hashlib.sha256(seed.encode()).hexdigest()
        text += seed
    text = text[:n]
    return text.upper() if upper else text


def fakes():
    return {
        "github-token": "gh" + "p_" + body(36, "a"),
        "github-pat": "github" + "_pat_" + body(82, "b"),
        "aws-access-key": "AK" + "IA" + body(16, "c", upper=True),
        "openai-project-key": "sk-" + "proj-" + body(40, "d"),
        "openai-legacy-key": "sk-" + body(48, "e"),
        "anthropic-key": "sk-" + "ant-" + "api03-" + body(60, "f"),
        "slack-token": "xo" + "xb-" + "1234567890-" + body(24, "g"),
        "private-key": "-----BEGIN " + "RSA PRIVATE" + " KEY-----\n" + body(64, "h") + "\n-----END RSA PRIVATE KEY-----",
    }


def spec(side_effect, permissions=("read:repo",)):
    return {"side_effect": side_effect, "permissions": list(permissions), "summary": "test action"}


def grant(**changes):
    record = {"grant_id": "g-test-0001", "role": "master-build-engineer",
              "engines": {"master-build": ["plan", "build"], "deployer": ["publish", "release"]},
              "paths": ["workspace"], "max_side_effect": "workspace-write", "expires_at": FUTURE,
              "approvals": []}
    record.update(changes)
    return record


def approval(engine, action, side_effect, token, digest=governor.approval_token_sha256):
    return {"engine": engine, "action": action, "side_effect": side_effect, "approved_by": "owner",
            "token_sha256": digest(token)}


class Denied:
    """assert helper: the call raises GovernorDenied with exactly this reason."""

    def __init__(self, case, reason):
        self.case, self.reason = case, reason

    def __enter__(self):
        return self

    def __exit__(self, kind, exc, tb):
        self.case.assertIsNotNone(kind, f"expected GovernorDenied({self.reason!r}), nothing was raised")
        self.case.assertTrue(issubclass(kind, GovernorDenied), f"expected GovernorDenied, got {kind.__name__}: {exc}")
        self.case.assertEqual(exc.reason, self.reason, str(exc))
        return True


class Workspace(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp(prefix="gaie-gov-test-")
        self.addCleanup(shutil.rmtree, tmp, True)
        self.tmp = Path(os.path.realpath(tmp))
        self.base = self.tmp / "base"
        self.workspace = self.base / "workspace"
        self.outside = self.tmp / "outside"
        for folder in (self.workspace, self.outside):
            folder.mkdir(parents=True)
        (self.outside / "secret.txt").write_text("host-only")

    def denied(self, reason):
        return Denied(self, reason)

    def run_in(self, cmd=("true",), **kw):
        kw.setdefault("cwd", self.workspace)
        kw.setdefault("timeout", 10)
        kw.setdefault("allowed_paths", [self.workspace])
        return governor.sandbox_run(list(cmd) if isinstance(cmd, tuple) else cmd, **kw)


class ErrorTests(unittest.TestCase):
    def test_denial_is_a_permission_error_with_a_machine_reason(self):
        exc = GovernorDenied("engine-not-granted", "detail")
        self.assertIsInstance(exc, PermissionError)
        self.assertEqual((exc.reason, exc.detail, str(exc)), ("engine-not-granted", "detail", "engine-not-granted: detail"))
        self.assertEqual(str(GovernorDenied("grant-expired")), "grant-expired")


class CheckTests(Workspace):
    def check(self, record=..., engine="master-build", action="build", side_effect="workspace-write", **kw):
        kw.setdefault("base", self.base)
        return governor.check(grant() if record is ... else record, engine, action, spec(side_effect), **kw)

    def test_granted_action_is_allowed(self):
        result = self.check(paths=["workspace/out.txt"])
        self.assertEqual(result, {"allowed": True, "grant_id": "g-test-0001", "side_effect": "workspace-write",
                                  "reason": "granted"})
        self.assertEqual(self.check(side_effect="none"), {"allowed": True, "grant_id": "g-test-0001",
                                                          "side_effect": "none", "reason": "granted"})

    def test_invalid_grant_is_refused(self):
        broken = [None, "g", {}, grant(extra=1), grant(grant_id="bad"), grant(max_side_effect="godmode"),
                  grant(expires_at="tomorrow"), grant(expires_at="2026-13-40T00:00:00Z"),
                  grant(engines={"Bad Engine": ["x"]}), grant(approvals=[{"side_effect": "none"}]),
                  grant(approvals=[dict(approval("deployer", "publish", "external-write", "t"), token_sha256=7)])]
        for record in broken:
            with self.subTest(record=record), self.denied("invalid-grant"):
                self.check(record)

    def test_invalid_action_spec_is_refused(self):
        for action_spec in (None, "workspace-write", {}, {"side_effect": "teleport"},
                            {"side_effect": "none", "permissions": ["root:all"]}):
            with self.subTest(action_spec=action_spec), self.denied("invalid-action-spec"):
                governor.check(grant(), "master-build", "build", action_spec)

    def test_engine_must_be_granted(self):
        for engine in ("memory", "", None, ["master-build"]):
            with self.subTest(engine=engine), self.denied("engine-not-granted"):
                self.check(engine=engine)

    def test_action_must_be_granted(self):
        for action in ("deploy", "", None, ["build"], "publish"):
            with self.subTest(action=action), self.denied("action-not-granted"):
                self.check(action=action)

    def test_side_effect_must_not_exceed_the_grant(self):
        self.assertTrue(self.check(side_effect="state-write")["allowed"])
        for side_effect in ("repo-write", "network", "external-write", "production"):
            with self.subTest(side_effect=side_effect), self.denied("side-effect-exceeds-grant"):
                self.check(side_effect=side_effect)

    def test_expired_grant_is_refused_from_the_expiry_second_on(self):
        record = grant(expires_at="2030-06-01T12:00:00Z")
        before = datetime.datetime(2030, 6, 1, 11, 59, 59, tzinfo=datetime.timezone.utc)
        self.assertTrue(self.check(record, now=before)["allowed"])
        self.assertTrue(self.check(record, now="2030-06-01T11:59:59Z")["allowed"])
        self.assertTrue(self.check(record, now=datetime.datetime(2030, 6, 1, 11, 0))["allowed"])  # naive = UTC
        for now in ("2030-06-01T12:00:00Z", datetime.datetime(2030, 6, 1, 12, 0, tzinfo=datetime.timezone.utc),
                    "2030-06-01T14:00:00+02:00", before.timestamp() + 1, "2031-01-01T00:00:00Z"):
            with self.subTest(now=now), self.denied("grant-expired"):
                self.check(record, now=now)
        with self.denied("grant-expired"):  # the real clock: a grant that ended in the past
            self.check(grant(expires_at="2020-01-01T00:00:00Z"))
        for now in ("yesterday", "2030-06-01T11:00:00", object(), True, float("nan")):
            with self.subTest(now=now), self.denied("invalid-time"):
                self.check(record, now=now)

    def gated(self, side_effect="external-write", max_side_effect="external-write", approvals=()):
        return grant(max_side_effect=max_side_effect, approvals=list(approvals))

    def test_gated_class_needs_a_matching_approval_token(self):
        token = "approval-" + body(24, "token")
        record = self.gated(approvals=[approval("deployer", "publish", "external-write", token)])
        allowed = governor.check(record, "deployer", "publish", spec("external-write"), approval_token=token)
        self.assertEqual(allowed["reason"], "approved")
        for missing in (None, "", 42, "x" * (governor.MAX_TOKEN_CHARS + 1)):
            with self.subTest(token=missing), self.denied("approval-missing"):
                governor.check(record, "deployer", "publish", spec("external-write"), approval_token=missing)
        with self.denied("approval-mismatch"):
            governor.check(record, "deployer", "publish", spec("external-write"), approval_token=token + "x")
        with self.denied("approval-missing"):  # the approval names another action
            governor.check(record, "deployer", "release", spec("external-write"), approval_token=token)
        no_approvals = self.gated()
        with self.denied("approval-missing"):
            governor.check(no_approvals, "deployer", "publish", spec("external-write"), approval_token=token)

    def test_approval_must_name_the_same_side_effect_class(self):
        token = "approval-" + body(24, "class")
        record = self.gated(max_side_effect="production", approvals=[approval("deployer", "publish", "production", token)])
        with self.denied("approval-missing"):
            governor.check(record, "deployer", "publish", spec("external-write"), approval_token=token)

    def test_contracts_digest_of_the_token_is_accepted_too(self):
        token = "approval-" + body(24, "compat")
        record = self.gated(approvals=[approval("deployer", "publish", "external-write", token, contracts.sha256)])
        self.assertTrue(governor.check(record, "deployer", "publish", spec("external-write"), approval_token=token)["allowed"])
        for wrong in (token + "x", token.upper(), " " + token):
            with self.subTest(token=wrong), self.denied("approval-mismatch"):
                governor.check(record, "deployer", "publish", spec("external-write"), approval_token=wrong)

    def test_production_is_refused_unless_the_grant_is_for_production_and_approved(self):
        # check() only decides; nothing is deployed by any test.
        token = "approval-" + body(24, "prod")
        prod = approval("deployer", "release", "production", token)
        for max_side_effect in ("none", "workspace-write", "network", "external-write"):
            with self.subTest(max_side_effect=max_side_effect), self.denied("side-effect-exceeds-grant"):
                governor.check(self.gated(max_side_effect=max_side_effect, approvals=[prod]),
                               "deployer", "release", spec("production"), approval_token=token)
        record = self.gated(max_side_effect="production", approvals=[prod])
        with self.denied("approval-missing"):
            governor.check(record, "deployer", "release", spec("production"))
        with self.denied("approval-mismatch"):
            governor.check(record, "deployer", "release", spec("production"), approval_token="wrong-token-value")
        self.assertEqual(governor.check(record, "deployer", "release", spec("production"), approval_token=token),
                         {"allowed": True, "grant_id": "g-test-0001", "side_effect": "production", "reason": "approved"})

    def test_paths_inside_the_grant_are_allowed(self):
        (self.workspace / "sub").mkdir()
        for path in ("workspace", "workspace/out.txt", "workspace/sub/../new.txt", str(self.workspace / "abs.txt"),
                     "./workspace/sub/deep/not-yet.txt"):
            with self.subTest(path=path):
                self.assertTrue(self.check(paths=[path])["allowed"])
        self.assertTrue(self.check(paths=())["allowed"])
        self.assertTrue(self.check(grant(paths=[]))["allowed"])  # no path asked, none needed

    def test_traversal_absolute_and_prefix_paths_are_refused(self):
        (self.base / "workspace-evil").mkdir()
        for path in ("../outside/secret.txt", "workspace/../../outside/secret.txt", "workspace/../escape.txt",
                     str(self.outside / "secret.txt"), "/etc/passwd", "/", "workspace-evil/x", ".."):
            with self.subTest(path=path), self.denied("path-outside-grant"):
                self.check(paths=["workspace/fine.txt", path])
        with self.denied("path-outside-grant"):
            self.check(grant(paths=[]), paths=["workspace/out.txt"])

    def test_symlink_escapes_are_refused(self):
        os.symlink(self.outside, self.workspace / "link-dir")
        os.symlink(self.outside / "secret.txt", self.workspace / "link-file")
        os.symlink(self.outside / "missing.txt", self.workspace / "dangling")
        os.symlink("../../outside", self.workspace / "relative-link")
        for path in ("workspace/link-dir", "workspace/link-dir/secret.txt", "workspace/link-file",
                     "workspace/dangling", "workspace/relative-link/secret.txt"):
            with self.subTest(path=path), self.denied("path-outside-grant"):
                self.check(paths=[path])
        os.symlink(self.workspace / "inner", self.workspace / "inner-link")
        self.assertTrue(self.check(paths=["workspace/inner-link/x"])["allowed"])  # a link that stays inside

    def test_malformed_paths_are_refused(self):
        for paths in ("workspace/out.txt", b"workspace", [""], ["workspace/\0x"], [b"workspace"], [None], {"a": 1}):
            with self.subTest(paths=paths), self.denied("invalid-path"):
                self.check(paths=paths)

    def test_grant_paths_resolve_under_the_base_and_absolute_grants_are_honoured(self):
        with self.denied("invalid-grant"):
            self.check(grant(paths=["workspace/../../outside"]), paths=["workspace/x"])
        os.symlink(self.outside, self.base / "escape")
        with self.denied("invalid-grant"):
            self.check(grant(paths=["escape"]), paths=["escape/secret.txt"])
        absolute = grant(paths=[str(self.outside)])
        self.assertTrue(self.check(absolute, paths=[str(self.outside / "secret.txt")])["allowed"])
        with self.denied("path-outside-grant"):
            self.check(absolute, paths=[str(self.workspace / "x")])

    def test_default_base_is_the_current_directory(self):
        previous = os.getcwd()
        os.chdir(self.base)
        try:
            result = governor.check(grant(), "master-build", "build", spec("workspace-write"), paths=["workspace/a"])
            self.assertTrue(result["allowed"])
            with self.denied("path-outside-grant"):
                governor.check(grant(), "master-build", "build", spec("workspace-write"), paths=["../outside/x"])
        finally:
            os.chdir(previous)

    def test_every_documented_reason_has_a_refusing_case(self):
        token = "approval-" + body(24, "matrix")
        gated = self.gated(approvals=[approval("deployer", "publish", "external-write", token)])
        cases = {
            "invalid-grant": lambda: self.check(grant(role="Not A Role")),
            "invalid-action-spec": lambda: governor.check(grant(), "master-build", "build", {"side_effect": "x"}),
            "engine-not-granted": lambda: self.check(engine="memory"),
            "action-not-granted": lambda: self.check(action="deploy"),
            "side-effect-exceeds-grant": lambda: self.check(side_effect="repo-write"),
            "grant-expired": lambda: self.check(now="2099-01-01T00:00:01Z"),
            "approval-missing": lambda: governor.check(gated, "deployer", "publish", spec("external-write")),
            "approval-mismatch": lambda: governor.check(gated, "deployer", "publish", spec("external-write"),
                                                        approval_token="nope"),
            "path-outside-grant": lambda: self.check(paths=["../outside"]),
            "secret-in-payload": lambda: governor.check_payload({"note": fakes()["github-token"]}),
        }
        for reason, call in cases.items():
            with self.subTest(reason=reason), self.denied(reason):
                call()
        self.assertLessEqual(set(cases), set(governor.REASONS))


class PayloadTests(unittest.TestCase):
    def test_clean_payloads_pass(self):
        for payload in ({"task": "build the site", "files": ["a.py"], "n": 3, "ok": True, "x": None},
                        "plain words about a token and a secret", b"bytes", [], {},
                        {"digest": hashlib.sha256(b"x").hexdigest(), "token_sha256": "0" * 64},
                        {"short": "sk-short", "gh": "gh" + "p_abc", "aws": "AK" + "IA123"}):
            with self.subTest(payload=payload):
                self.assertIsNone(governor.check_payload(payload))

    def test_every_credential_family_is_refused_without_echoing_it(self):
        for family, value in fakes().items():
            for payload in ({"note": value}, {"nested": [{"deep": "prefix " + value + " suffix"}]},
                            [value], value, value.encode(), {value: "as a key"}):
                with self.subTest(family=family, shape=type(payload).__name__):
                    with self.assertRaises(GovernorDenied) as caught:
                        governor.check_payload(payload)
                    exc = caught.exception
                    self.assertEqual(exc.reason, "secret-in-payload")
                    for text in (str(exc), repr(exc), exc.detail, json.dumps(exc.args)):
                        self.assertNotIn(value[8:24], text)

    def test_quoted_assignments_inside_text_are_refused(self):
        line = 'api_key = "' + body(32, "quoted") + '"'
        with self.assertRaises(GovernorDenied) as caught:
            governor.check_payload({"config": line})
        self.assertEqual(caught.exception.reason, "secret-in-payload")

    def test_payloads_that_cannot_be_scanned_are_refused(self):
        deep = []
        for _ in range(governor.MAX_PAYLOAD_DEPTH + 5):
            deep = [deep]
        for payload in ({1: "int key"}, {"x": object()}, {"x": float("inf")}, deep, object()):
            with self.subTest(payload=type(payload).__name__), self.assertRaises(GovernorDenied) as caught:
                governor.check_payload(payload)
            self.assertEqual(caught.exception.reason, "invalid-payload")
        with mock.patch.object(governor, "MAX_PAYLOAD_CHARS", 10), self.assertRaises(GovernorDenied) as caught:
            governor.check_payload({"text": "a" * 20})
        self.assertEqual(caught.exception.reason, "payload-too-large")


class AuditTests(Workspace):
    def state(self):
        return self.tmp / "state"

    def lines(self):
        return (self.state() / governor.AUDIT_FILE).read_text().splitlines()

    def test_records_carry_the_decision_and_a_payload_digest_never_the_payload(self):
        secret = fakes()["anthropic-key"]
        payload = {"prompt": "PLAIN-PAYLOAD-TEXT-MARKER", "key": secret}
        governor.audit(self.state(), {"decision": "deny", "reason": "secret-in-payload", "grant_id": "g-test-0001",
                                      "engine": "master-build", "action": "build", "payload": payload,
                                      "approval_token": "TOKEN-MARKER", "paths": ["PATH-MARKER"]},
                       now="2026-11-28T10:00:00Z")
        raw = (self.state() / governor.AUDIT_FILE).read_bytes()
        for marker in (b"PLAIN-PAYLOAD-TEXT-MARKER", secret.encode(), secret[8:24].encode(), b"TOKEN-MARKER",
                       b"PATH-MARKER"):
            self.assertNotIn(marker, raw)
        record = json.loads(raw)
        self.assertEqual(set(record), {"seq", "at", "decision", "reason", "grant_id", "engine", "action",
                                       "side_effect", "payload_sha256", "prev_sha256", "record_sha256"})
        self.assertEqual((record["decision"], record["reason"], record["engine"], record["action"], record["at"]),
                         ("deny", "secret-in-payload", "master-build", "build", "2026-11-28T10:00:00.000000Z"))
        self.assertEqual(record["payload_sha256"], contracts.sha256(payload))
        self.assertEqual(stat.S_IMODE((self.state() / governor.AUDIT_FILE).stat().st_mode), 0o600)

    def test_allow_result_of_check_is_auditable_and_bytes_payloads_are_hashed(self):
        result = governor.check(grant(), "master-build", "plan", spec("none"))
        governor.audit(self.state(), dict(result, engine="master-build", action="plan", payload=b"raw-bytes"))
        record = json.loads(self.lines()[0])
        self.assertEqual((record["decision"], record["reason"], record["side_effect"], record["grant_id"]),
                         ("allow", "granted", "none", "g-test-0001"))
        self.assertEqual(record["payload_sha256"], hashlib.sha256(b"raw-bytes").hexdigest())

    def test_secret_looking_fields_are_redacted(self):
        secret = fakes()["github-token"]
        governor.audit(self.state(), {"decision": "deny", "reason": "engine-not-granted", "engine": secret,
                                      "action": "x" * 500, "grant_id": 12})
        record = json.loads(self.lines()[0])
        self.assertEqual(record["engine"], "[redacted]")
        self.assertEqual(len(record["action"]), 80)
        self.assertEqual(record["grant_id"], "[invalid]")
        self.assertNotIn(secret[4:20], "\n".join(self.lines()))

    def test_log_is_append_only_and_hash_chained(self):
        for n in range(3):
            governor.audit(self.state(), {"decision": "allow", "reason": "granted", "engine": f"e{n}"})
        first = self.lines()
        governor.audit(self.state(), {"decision": "deny", "reason": "grant-expired"})
        after = self.lines()
        self.assertEqual(after[:3], first)
        self.assertEqual([json.loads(line)["seq"] for line in after], [0, 1, 2, 3])
        self.assertEqual(json.loads(after[3])["prev_sha256"], json.loads(after[2])["record_sha256"])
        self.assertEqual(governor.verify_audit(self.state()), 4)

    def test_tampering_is_detected(self):
        for n in range(3):
            governor.audit(self.state(), {"decision": "deny", "reason": "engine-not-granted", "engine": f"e{n}"})
        path = self.state() / governor.AUDIT_FILE
        original = path.read_text()
        for broken in (original.replace('"deny"', '"allow"', 1), "\n".join(original.splitlines()[1:]) + "\n",
                       original.splitlines()[0] + "\n" + original.splitlines()[2] + "\n", original + "{not json}\n"):
            path.write_text(broken)
            with self.subTest(broken=broken[:40]), self.assertRaises(GovernorDenied) as caught:
                governor.verify_audit(self.state())
            self.assertEqual(caught.exception.reason, "audit-tampered")
        path.write_text(original[:-1])  # an incomplete last line blocks further appends
        with self.assertRaises(GovernorDenied) as caught:
            governor.audit(self.state(), {"decision": "deny", "reason": "x"})
        self.assertEqual(caught.exception.reason, "audit-tampered")

    def test_concurrent_writers_keep_one_chain(self):
        def writer(n):
            for i in range(20):
                governor.audit(self.state(), {"decision": "allow", "reason": "granted", "engine": f"w{n}-{i}"})
        threads = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(governor.verify_audit(self.state()), 80)

    def test_unsafe_locations_and_events_are_refused(self):
        with self.assertRaises(GovernorDenied) as caught:
            governor.audit(ROOT / "governor-state", {"decision": "deny", "reason": "x"})
        self.assertEqual(caught.exception.reason, "audit-in-repository")
        self.assertFalse((ROOT / "governor-state").exists())
        self.state().mkdir(mode=0o700)
        os.symlink(self.outside / "elsewhere.jsonl", self.state() / governor.AUDIT_FILE)
        with self.assertRaises(GovernorDenied) as caught:
            governor.audit(self.state(), {"decision": "deny", "reason": "x"})
        self.assertEqual(caught.exception.reason, "audit-failed")
        self.assertFalse((self.outside / "elsewhere.jsonl").exists())
        for event in (None, {}, {"decision": "maybe"}, {"allowed": "yes"}):
            with self.subTest(event=event), self.assertRaises(GovernorDenied) as caught:
                governor.audit(self.tmp / "state2", event)
            self.assertEqual(caught.exception.reason, "invalid-audit-event")
        self.assertEqual(governor.verify_audit(self.tmp / "never-written"), 0)

    def test_backing_file_rejects_alias_permissions_and_nondisk_streams(self):
        event = {"decision": "allow"}
        self.state().mkdir(mode=0o700)
        destination = self.state() / governor.AUDIT_FILE
        untouched = self.outside / "untouched.txt"
        untouched.write_text("")
        untouched.chmod(0o600)
        for make in (
            lambda: os.link(untouched, destination),
            lambda: destination.write_text(""),
            lambda: os.mkfifo(destination, mode=0o600),
        ):
            with self.subTest(make=make):
                make()
                if stat.S_ISREG(destination.stat().st_mode) and destination.stat().st_nlink == 1:
                    destination.chmod(0o644)
                with self.denied("audit-failed"):
                    governor.audit(self.state(), event)
                with self.denied("audit-tampered"):
                    governor.verify_audit(self.state())
                destination.unlink()
        self.assertEqual(untouched.read_text(), "")
        self.state().chmod(0o755)
        with self.denied("audit-failed"):
            governor.audit(self.state(), event)
        self.assertFalse(destination.exists())


def host_alive(marker):
    """Live host processes whose command line holds marker (zombies are not running)."""
    found = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            cmdline = Path(f"/proc/{entry}/cmdline").read_bytes()
            state = Path(f"/proc/{entry}/stat").read_text().rsplit(")", 1)[1].split()[0]
        except OSError:
            continue
        if marker.encode() in cmdline and state != "Z":
            found.append(entry)
    return found


class SandboxArgumentTests(Workspace):
    """Preconditions are refused before anything runs, on every host."""

    def test_cwd_outside_allowed_paths_is_refused(self):
        with self.denied("path-outside-grant"):
            self.run_in(cwd=self.outside)
        with self.denied("path-outside-grant"):
            self.run_in(cwd=self.base)
        os.symlink(self.outside, self.workspace / "link")
        with self.denied("path-outside-grant"):
            self.run_in(cwd=self.workspace / "link")
        with self.denied("path-outside-grant"):
            self.run_in(allowed_paths=[])

    def test_bad_commands_paths_names_and_limits_are_refused(self):
        refusals = [
            ("invalid-command", {"cmd": "echo hi"}), ("invalid-command", {"cmd": []}),
            ("invalid-command", {"cmd": ["echo", 3]}), ("invalid-command", {"cmd": ["", "x"]}),
            ("allowed-path-too-broad", {"allowed_paths": ["/"]}), ("allowed-path-too-broad", {"allowed_paths": ["/usr"]}),
            ("allowed-path-too-broad", {"read_paths": ["/"]}), ("invalid-path", {"allowed_paths": ["/proc/self"]}),
            ("invalid-path", {"allowed_paths": [str(self.tmp / "missing")]}),
            ("invalid-path", {"allowed_paths": str(self.workspace)}), ("invalid-path", {"cwd": self.workspace / "nope"}),
            ("invalid-env-name", {"env_allow": ["BAD NAME"]}), ("invalid-env-name", {"env_allow": "PATH"}),
            ("invalid-env-name", {"env_allow": ["1X"]}), ("invalid-limit", {"timeout": 0}),
            ("invalid-limit", {"timeout": float("inf")}), ("invalid-limit", {"memory_mb": 1}),
            ("invalid-limit", {"network": "no"}), ("invalid-limit", {"cpu_seconds": True}),
        ]
        for reason, kw in refusals:
            cmd = kw.pop("cmd", ("true",))
            with self.subTest(reason=reason, kw=kw), self.denied(reason):
                self.run_in(cmd, **kw)

    def test_fallback_tier_reports_no_filesystem_isolation_honestly(self):
        plain = {"tier": "plain", "root_netns": False, "userns_netns": False, "unshare": True, "root": False,
                 "full_checks": None}
        with mock.patch.object(governor, "isolation_probe", return_value=plain):
            with self.denied("network-isolation-unavailable"):
                self.run_in()
            result = self.run_in(("sh", "-c", "echo ran"), network=True)
        self.assertEqual((result["stdout"], result["fs_isolated"], result["network_isolated"]), ("ran\n", False, False))
        probe = governor.isolation_probe()
        for name in ("root_netns", "userns_netns"):
            if not probe[name]:
                continue
            fallback = dict(plain, **{name: True})
            code = "import socket;socket.create_connection(('1.1.1.1', 443), timeout=3)"
            with self.subTest(net=name), mock.patch.object(governor, "isolation_probe", return_value=fallback):
                result = self.run_in((sys.executable, "-I", "-c", code))
            self.assertEqual((result["fs_isolated"], result["network_isolated"]), (False, True))
            self.assertNotEqual(result["returncode"], 0)
            self.assertIn("Network is unreachable", result["stderr"])


class StrictSandboxTests(Workspace):
    """Strict profiles never dispatch through the degraded namespace tier."""

    def setUp(self):
        super().setUp()
        self.workspace.chmod(0o700)

    def test_strict_scope_refuses_ambient_authority_and_unsafe_writable_roots(self):
        for changes in (
            {"network": True},
            {"env_allow": ("PATH",)},
            {"allowed_paths": [self.workspace, self.outside]},
            {"read_paths": [self.workspace]},
            {"read_only": True},
        ):
            with self.subTest(changes=changes), self.denied("invalid-sandbox-mode"):
                self.run_in(require_fs_isolation=True, **changes)
        (self.workspace / ".git").mkdir()
        with self.denied("invalid-sandbox-mode"):
            self.run_in(require_fs_isolation=True)
        (self.workspace / ".git").rmdir()
        self.workspace.chmod(0o755)
        with self.denied("invalid-sandbox-mode"):
            self.run_in(require_fs_isolation=True)

    def test_strict_scope_refuses_preexisting_writable_aliases_and_ipc(self):
        with self.denied("path-outside-grant"):
            self.run_in(cwd=self.outside, read_only=True, allowed_paths=[], read_paths=[self.workspace])
        alias = self.workspace / "alias.txt"
        os.link(self.outside / "secret.txt", alias)
        with self.denied("invalid-sandbox-mode"):
            self.run_in(require_fs_isolation=True)
        alias.unlink()
        os.mkfifo(self.workspace / "fixture.fifo", mode=0o600)
        with self.denied("invalid-sandbox-mode"):
            self.run_in(read_only=True, allowed_paths=[], read_paths=[self.workspace])

    def test_strict_audit_and_agent_never_enter_plain_runner(self):
        marker = self.workspace / "marker.txt"
        code = f"printf 'mutation\\n' > {marker}"
        plain = {"tier": "plain", "root_netns": True, "userns_netns": False}
        with mock.patch.object(governor, "isolation_probe", return_value=plain), \
                mock.patch.object(governor, "_run_plain", side_effect=AssertionError("plain dispatch forbidden")):
            with self.denied("filesystem-isolation-unavailable"):
                self.run_in(("sh", "-c", code), require_fs_isolation=True)
            with self.denied("filesystem-isolation-unavailable"):
                self.run_in(("sh", "-c", code), read_only=True, allowed_paths=[], read_paths=[self.workspace])
        self.assertFalse(marker.exists())

    def test_namespace_bootstrap_imports_cannot_write_bytecode(self):
        directory = str(self.workspace)
        with mock.patch.object(governor, "_launch", side_effect=RuntimeError("bootstrap intercepted")) as launch:
            with self.assertRaisesRegex(RuntimeError, "bootstrap intercepted"):
                governor._run_full(["true"], cwd=directory, timeout=1, network=False, env={"PATH": os.defpath},
                                   allowed=[], readable=[directory], limits={}, strict=True)
        argv = launch.call_args.args[0]
        bootstrap = argv[argv.index("--") + 1 : argv.index("--") + 6]
        self.assertEqual(bootstrap, [sys.executable, "-I", "-B", "-S", "-c"])
        (self.workspace / "synthetic_boot_module.py").write_text("answer = 42\n")
        program = "import sys;sys.path.insert(0,sys.argv[1]);import synthetic_boot_module"
        result = subprocess.run([*bootstrap, program, directory], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.workspace / "__pycache__").exists())

    def test_real_strict_boundary_or_measured_refusal(self):
        marker = self.workspace / "marker.txt"
        marker.write_text("source")
        pointer = self.workspace / ".git"
        pointer.write_text("gitdir: /workspace-metadata-fixture\n")
        actor_file = self.workspace / "write.txt"
        neighbour = self.outside / "write.txt"
        code = (
            'set -eu; test "$(cat marker.txt)" = source; '
            'if (printf overwrite > "$1") 2>/dev/null; then exit 7; fi; '
            'if (printf overwrite > .git) 2>/dev/null; then exit 8; fi; '
            'if (printf output > write.txt) 2>/dev/null; then echo wrote; else echo denied; fi; '
            'test -z "${GAIE_BOUNDARY_FIXTURE-}"; test ! -e /etc/passwd'
        )
        if governor.isolation_probe()["tier"] != "full":
            for options in ({"require_fs_isolation": True},
                            {"read_only": True, "allowed_paths": [], "read_paths": [self.workspace]}):
                with self.denied("filesystem-isolation-unavailable"):
                    self.run_in(("sh", "-c", code, "fixture", str(neighbour)), **options)
            self.assertFalse(actor_file.exists())
            self.assertFalse(neighbour.exists())
            return
        with mock.patch.dict(os.environ, {"GAIE_BOUNDARY_FIXTURE": "ambient"}):
            command = ("sh", "-c", code, "fixture", str(neighbour))
            audit = self.run_in(command, read_only=True, allowed_paths=[], read_paths=[self.workspace])
            self.assertEqual(audit["returncode"], 0, audit["stderr"])
            self.assertEqual(audit["stdout"], "denied\n")
            self.assertTrue(audit["fs_isolated"] and audit["network_isolated"])
            self.assertFalse(actor_file.exists())
            actor = self.run_in(command, require_fs_isolation=True)
            self.assertEqual(actor["returncode"], 0, actor["stderr"])
        self.assertEqual(actor["stdout"], "wrote\n")
        self.assertTrue(actor["fs_isolated"] and actor["network_isolated"])
        self.assertEqual(actor_file.read_text(), "output")
        self.assertEqual(marker.read_text(), "source")
        self.assertEqual(pointer.read_text(), "gitdir: /workspace-metadata-fixture\n")
        self.assertFalse(neighbour.exists())

    def test_socket_filter_applies_to_a_real_child_for_ip_and_pathname_sockets(self):
        source = """
import errno
import socket
from engineering_os.governor import _disable_socket_creation
with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM):
    pass  # Establish that the inherited policy did not already block pathname sockets.
try:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM):
        pass
except OSError as error:
    assert error.errno == errno.EPERM, error  # Some hosts already deny IP sockets.
_disable_socket_creation()
for family in (socket.AF_INET, socket.AF_UNIX):
    try:
        with socket.socket(family, socket.SOCK_STREAM):
            raise AssertionError("socket creation should be denied")
    except OSError as error:
        assert error.errno == errno.EPERM, error
"""
        result = subprocess.run([sys.executable, "-c", source], cwd=ROOT,
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)


class SandboxTests(Workspace):
    """The walls of the full sandbox, checked from inside and from the host."""

    @classmethod
    def setUpClass(cls):
        probe = governor.isolation_probe()
        if probe["tier"] != "full":
            raise unittest.SkipTest("expected limitation of this host: the full sandbox cannot be built here "
                                    f"(probe: {probe}); sandbox_run reports fs_isolated False, see "
                                    "SECURITY_GOVERNOR.md and SandboxArgumentTests")

    def py(self, code, *args, **kw):
        kw.setdefault("cwd", self.workspace)
        kw.setdefault("timeout", 20)
        kw.setdefault("allowed_paths", [self.workspace])
        return governor.sandbox_run([sys.executable, "-I", "-S", "-c", code, *map(str, args)], **kw)

    def report(self, code, *args, **kw):
        result = self.py(code, *args, **kw)
        self.assertEqual(result["returncode"], 0, result["stderr"])
        return json.loads(result["stdout"])

    def test_writes_land_only_in_allowed_paths(self):
        code = r"""
import json, os, sys
r = {}
for name, path in (("inside", "made.txt"), ("outside", sys.argv[1] + "/escaped.txt"), ("usr", "/usr/escaped.txt"),
                   ("etc", "/etc/escaped.txt"), ("root", "/escaped.txt"), ("tmp", "/tmp/private.txt")):
    try:
        with open(path, "w") as handle:
            handle.write("x")
        r[name] = "written"
    except OSError as exc:
        r[name] = exc.errno
print(json.dumps(r))
"""
        seen = self.report(code, self.outside)
        self.assertEqual(seen["inside"], "written")
        self.assertTrue((self.workspace / "made.txt").exists())
        for name in ("outside", "usr", "etc", "root"):
            self.assertNotEqual(seen[name], "written", name)
        self.assertEqual(sorted(p.name for p in self.outside.iterdir()), ["secret.txt"])
        self.assertFalse(Path("/usr/escaped.txt").exists() or Path("/etc/escaped.txt").exists())
        self.assertEqual(seen["tmp"], "written")  # the sandbox's own /tmp is private memory, gone afterwards
        self.assertFalse(Path("/tmp/private.txt").exists())

    def test_host_files_outside_the_sandbox_are_not_even_readable(self):
        code = r"""
import json, os, sys
r = {}
for name, path in (("outside", sys.argv[1] + "/secret.txt"), ("home", "/root"), ("repo", sys.argv[2])):
    r[name] = os.path.exists(path)
r["top"] = sorted(os.listdir("/"))
r["dev"] = sorted(os.listdir("/dev"))
print(json.dumps(r))
"""
        seen = self.report(code, self.outside, ROOT)
        self.assertEqual((seen["outside"], seen["home"], seen["repo"]), (False, False, False))
        self.assertLessEqual(set(seen["top"]), {"bin", "dev", "etc", "lib", "lib32", "lib64", "libx32", "proc",
                                                "sbin", "tmp", "usr"})
        self.assertLessEqual(set(seen["dev"]), {"fd", "full", "null", "random", "shm", "stderr", "stdin",
                                                "stdout", "tty", "urandom", "zero"})

    def test_read_paths_are_visible_but_read_only(self):
        code = r"""
import json, sys
r = {"read": open(sys.argv[1] + "/secret.txt").read()}
try:
    open(sys.argv[1] + "/new.txt", "w").write("x"); r["write"] = "written"
except OSError as exc:
    r["write"] = exc.errno
print(json.dumps(r))
"""
        seen = self.report(code, self.outside, read_paths=[self.outside])
        self.assertEqual(seen, {"read": "host-only", "write": 30})  # EROFS
        self.assertFalse((self.outside / "new.txt").exists())

    def test_no_capability_no_remount_no_kernel_writes(self):
        code = r"""
import ctypes, json, os
libc = ctypes.CDLL(None, use_errno=True)
r = {"status": {l.split(":")[0]: l.split()[1] for l in open("/proc/self/status") if l.startswith(("Cap", "NoNewPrivs"))}}
for name, target, flags in (("remount_root_rw", b"/", 32 | 4096), ("remount_cwd_rw", os.getcwd().encode(), 32 | 4096)):
    r[name] = 0 if libc.mount(None, target, None, ctypes.c_ulong(flags), None) == 0 else ctypes.get_errno()
r["tmpfs_over_usr"] = 0 if libc.mount(b"t", b"/usr", b"tmpfs", ctypes.c_ulong(0), None) == 0 else ctypes.get_errno()
r["umount_proc"] = 0 if libc.umount2(b"/proc", 2) == 0 else ctypes.get_errno()
try:
    os.close(os.open("/proc/self/comm", os.O_WRONLY)); r["proc_write_open"] = "opened"
except OSError as exc:
    r["proc_write_open"] = exc.errno
r["sys"] = os.path.exists("/sys/kernel")
r["pid1_fds"] = []
for fd in os.listdir("/proc/1/fd"):
    try:
        os.close(os.open("/proc/1/fd/" + fd, os.O_WRONLY)); r["pid1_fds"].append("opened")
    except OSError as exc:
        r["pid1_fds"].append(exc.errno)
try:
    os.unshare(os.CLONE_NEWUSER | os.CLONE_NEWNS)
    r["nested_remount_root_rw"] = 0 if libc.mount(None, b"/", None, ctypes.c_ulong(32 | 4096), None) == 0 else ctypes.get_errno()
except OSError as exc:
    r["nested_remount_root_rw"] = "no-userns:%d" % exc.errno
print(json.dumps(r))
"""
        seen = self.report(code)
        for cap in ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb"):
            self.assertEqual(seen["status"][cap], "0000000000000000", cap)
        self.assertEqual(seen["status"]["NoNewPrivs"], "1")
        for name in ("remount_root_rw", "remount_cwd_rw", "tmpfs_over_usr", "umount_proc", "nested_remount_root_rw"):
            self.assertNotEqual(seen[name], 0, name)
        self.assertEqual(seen["proc_write_open"], 30)  # EROFS: /proc is mounted read-only; nothing is written
        self.assertFalse(seen["sys"])
        self.assertTrue(seen["pid1_fds"])
        self.assertNotIn("opened", seen["pid1_fds"])  # pid 1 is not dumpable: its status pipe cannot be forged

    def test_no_network_unless_asked(self):
        listener = socket.socket()
        self.addCleanup(listener.close)
        listener.bind(("127.0.0.1", 0))
        listener.listen(4)
        code = r"""
import json, socket, sys
r = {}
for name, target in (("loopback_host_listener", ("127.0.0.1", int(sys.argv[1]))), ("public_ip", ("1.1.1.1", 443)),
                     ("public_name", ("example.com", 443))):
    try:
        socket.create_connection(target, timeout=3).close(); r[name] = "connected"
    except OSError as exc:
        r[name] = type(exc).__name__
print(json.dumps(r))
"""
        port = listener.getsockname()[1]
        result = self.py(code, port)
        seen = json.loads(result["stdout"])
        self.assertTrue(result["network_isolated"])
        self.assertEqual(set(seen.values()) & {"connected"}, set(), seen)
        listener.setblocking(False)
        with self.assertRaises(BlockingIOError):
            listener.accept()
        opened = self.py(code, port, network=True)  # control: the same program reaches the host listener
        self.assertFalse(opened["network_isolated"])
        self.assertEqual(json.loads(opened["stdout"])["loopback_host_listener"], "connected")

    def test_host_unix_sockets_are_out_of_reach(self):
        # An AF_UNIX path is limited to about 107 bytes, so the host socket sits in a short host
        # directory instead of under a possibly long TMPDIR; it is outside every granted path too.
        short = tempfile.mkdtemp(prefix="gaie-sock-", dir="/tmp")
        self.addCleanup(shutil.rmtree, short, True)
        path = Path(short) / "control.sock"
        server = socket.socket(socket.AF_UNIX)
        self.addCleanup(server.close)
        server.bind(str(path))
        server.listen(1)
        code = r"""
import socket, sys
s = socket.socket(socket.AF_UNIX)
try:
    s.connect(sys.argv[1]); print("connected")
except OSError as exc:
    print(type(exc).__name__)
"""
        self.assertEqual(self.py(code, path)["stdout"].strip(), "FileNotFoundError")

    def test_parent_secrets_do_not_leak_into_the_environment(self):
        secret = fakes()["openai-project-key"]
        with mock.patch.dict(os.environ, {"GAIE_FAKE_SECRET": secret, "GAIE_VISIBLE": "shown"}):
            result = governor.sandbox_run(["env"], cwd=self.workspace, timeout=10, allowed_paths=[self.workspace],
                                          env_allow=("GAIE_VISIBLE", "GAIE_NOT_SET"))
        env = dict(line.split("=", 1) for line in result["stdout"].splitlines())
        self.assertEqual(env, {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": str(self.workspace), "LANG": "C",
                               "GAIE_VISIBLE": "shown"})
        self.assertNotIn(secret, result["stdout"] + result["stderr"])

    def test_own_pid_namespace_and_nothing_survives_the_run(self):
        marker = "31.%d" % (os.getpid() % 100000)
        code = r"""
import json, os, subprocess, sys
subprocess.Popen(["sleep", sys.argv[2]], start_new_session=True)
try:
    os.kill(int(sys.argv[1]), 0); seen = "host pid visible"
except OSError as exc:
    seen = type(exc).__name__
print(json.dumps({"host_pid": seen, "me": os.getpid()}))
"""
        seen = self.report(code, os.getpid(), marker)
        self.assertEqual(seen["host_pid"], "ProcessLookupError")
        self.assertLess(seen["me"], 10)
        deadline = time.time() + 5
        while host_alive("sleep\0" + marker) and time.time() < deadline:
            time.sleep(0.05)
        self.assertEqual(host_alive("sleep\0" + marker), [])

    def test_timeout_and_cpu_limits_are_enforced(self):
        started = time.time()
        slow = governor.sandbox_run(["sleep", "30"], cwd=self.workspace, timeout=1, allowed_paths=[self.workspace])
        self.assertEqual(slow["limit"], "timeout")
        self.assertLess(time.time() - started, 6)
        started = time.time()
        busy = self.py("while True:\n    pass\n", timeout=20, cpu_seconds=1)
        self.assertEqual(busy["limit"], "cpu")
        self.assertNotEqual(busy["returncode"], 0)
        self.assertLess(time.time() - started, 10)
        fine = self.py("print(sum(range(1000)))")
        self.assertEqual((fine["returncode"], fine["stdout"], fine["limit"]), (0, "499500\n", None))

    def test_memory_and_file_size_limits_are_enforced(self):
        memory = self.py("try:\n    b = bytearray(2 * 1024**3)\n    print('allocated')\nexcept MemoryError:\n"
                         "    print('refused')\n", memory_mb=256)
        self.assertEqual(memory["stdout"].strip(), "refused")
        big = self.py("open('big.bin', 'wb').write(b'x' * (3 * 1024 * 1024))", file_mb=1)
        self.assertNotEqual(big["returncode"], 0)
        self.assertIn("File too large", big["stderr"])
        self.assertLessEqual((self.workspace / "big.bin").stat().st_size, 1024 * 1024)

    def test_missing_program_and_exit_codes_pass_through(self):
        missing = governor.sandbox_run(["governor-no-such-program"], cwd=self.workspace, timeout=10,
                                       allowed_paths=[self.workspace])
        self.assertEqual((missing["returncode"], missing["limit"]), (127, None))
        self.assertEqual(self.py("raise SystemExit(7)")["returncode"], 7)

    def test_programs_outside_system_directories_can_start(self):
        tool = self.workspace / "tool.sh"
        tool.write_text("#!/bin/sh\necho tool-ran\n")
        tool.chmod(0o755)
        ran = governor.sandbox_run(["./tool.sh"], cwd=self.workspace, timeout=10, allowed_paths=[self.workspace])
        self.assertEqual(ran["stdout"], "tool-ran\n", ran["stderr"])
        with mock.patch.dict(os.environ, {"PATH": "/governor-nowhere:/usr/bin:/bin"}):
            custom = governor.sandbox_run(["sh", "-c", 'echo "$PATH"'], cwd=self.workspace, timeout=10,
                                          allowed_paths=[self.workspace], env_allow=("PATH",))
        self.assertEqual(custom["stdout"], "/governor-nowhere:/usr/bin:/bin\n", custom["stderr"])
        node = shutil.which("node")
        if node and not any(os.path.realpath(node).startswith(d + "/") for d in governor.SYSTEM_DIRS):
            js = governor.sandbox_run(["node", "-e", "console.log(6*7)"], cwd=self.workspace, timeout=20,
                                      allowed_paths=[self.workspace])
            self.assertEqual(js["stdout"], "42\n", js["stderr"])

    def test_known_limitation_process_count_is_not_capped(self):
        """Honest record: a uid-0-mapped sandbox is exempt from RLIMIT_NPROC, so the number of
        processes is bounded only by the timeout and the pid namespace teardown (see the doc)."""
        code = r"""
import subprocess
procs = [subprocess.Popen(["sleep", "5"]) for _ in range(40)]
print(len(procs))
"""
        self.assertEqual(self.py(code, timeout=20)["stdout"].strip(), "40")

    def test_probe_saw_every_wall_hold(self):
        checks = governor.isolation_probe()["full_checks"]
        self.assertEqual(checks["write_inside"], "ok")
        self.assertTrue(checks["host_sees_inside_write"])
        self.assertFalse(checks["host_sees_outside_write"] or checks["host_listener_contacted"])
        self.assertEqual(checks["cap_eff"], "0000000000000000")


def require_full_tier():
    """True when GAIE_REQUIRE_FULL_SANDBOX=1: a missing full tier is then a failure, never a skip."""
    return os.environ.get("GAIE_REQUIRE_FULL_SANDBOX") == "1"


def host_address():
    """A non-loopback IPv4 address of this host (the source of its default route), or None."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            probe.connect(("192.0.2.1", 9))  # UDP connect sends nothing; it only selects a source
        except OSError:
            return None
        address = probe.getsockname()[0]
    return None if address.startswith("127.") or address == "0.0.0.0" else address


class RequiredTierTests(unittest.TestCase):
    def test_required_full_tier_is_present(self):
        """CI sets GAIE_REQUIRE_FULL_SANDBOX=1 on a runner with user namespaces: this fails there,
        instead of letting SandboxTests skip, when the full tier cannot be built."""
        probe = governor.isolation_probe()
        if not require_full_tier():
            raise unittest.SkipTest(f"GAIE_REQUIRE_FULL_SANDBOX is not set (tier here: {probe['tier']})")
        self.assertEqual(probe["tier"], "full", f"the full sandbox is required here; probe: {probe}")


class LoopbackSandboxTests(Workspace):
    """loopback=True: a private loopback inside the sandbox; the host network stays unreachable."""

    INSIDE = r"""
import json, socket, sys, threading
port, host = int(sys.argv[1]), sys.argv[2]
r = {}
server = socket.socket()
try:
    server.bind(("127.0.0.1", port))  # the host listener holds this port in the host namespace
    server.listen(1)
    def serve():
        peer, _ = server.accept()
        peer.sendall(peer.recv(1).upper())
        peer.close()
    threading.Thread(target=serve, daemon=True).start()
    client = socket.create_connection(("127.0.0.1", port), timeout=3)
    client.sendall(b"x")
    r["inside_exchange"] = client.recv(1).decode()
    client.close()
except OSError as exc:
    r["inside_exchange"] = "errno:%s" % exc.errno
import os
r["etc"] = sorted(os.listdir("/etc")) if os.path.isdir("/etc") else "absent"
for name, target in (("host_address", (host, port)), ("public_ip", ("1.1.1.1", 443))):
    if target[0] == "-":
        continue
    try:
        socket.create_connection(target, timeout=2).close()
        r[name] = "connected"
    except OSError as exc:
        r[name] = "errno:%s" % exc.errno
print(json.dumps(r, sort_keys=True))
"""

    def test_loopback_argument_is_checked_on_every_host(self):
        for reason, kw in (("invalid-limit", {"loopback": "yes"}),
                           ("invalid-sandbox-mode", {"loopback": True, "network": True}),
                           ("invalid-sandbox-mode", {"loopback": True, "require_fs_isolation": True}),
                           ("invalid-sandbox-mode", {"loopback": True, "read_only": True, "allowed_paths": [],
                                                     "read_paths": [self.workspace]})):
            with self.subTest(kw=kw), self.denied(reason):
                self.run_in(**kw)
        plain = {"tier": "plain", "root_netns": True, "userns_netns": True, "unshare": True, "root": True,
                 "full_checks": None}
        marker = self.workspace / "ran.txt"
        with mock.patch.object(governor, "isolation_probe", return_value=plain), \
                mock.patch.object(governor, "_run_plain", side_effect=AssertionError("plain dispatch forbidden")):
            with self.denied("network-isolation-unavailable"):
                self.run_in(("sh", "-c", f"echo x > {marker}"), loopback=True)
        self.assertFalse(marker.exists())

    def test_private_loopback_or_measured_refusal(self):
        listeners = []
        for address in ("127.0.0.1", host_address()):
            if address is None:
                continue
            listener = socket.socket()
            self.addCleanup(listener.close)
            listener.bind((address, 0 if not listeners else listeners[0].getsockname()[1]))
            listener.listen(4)
            listener.setblocking(False)
            listeners.append(listener)
        port = listeners[0].getsockname()[1]
        host = host_address() or "-"
        command = (os.path.realpath(sys.executable), "-I", "-S", "-c", self.INSIDE, str(port), host)
        if governor.isolation_probe()["tier"] != "full":
            self.assertFalse(require_full_tier(), "GAIE_REQUIRE_FULL_SANDBOX=1 but the full tier is missing")
            with self.denied("network-isolation-unavailable"):
                self.run_in(command, loopback=True, timeout=20)
            return
        result = self.run_in(command, loopback=True, timeout=20)
        self.assertEqual(result["returncode"], 0, result["stderr"])
        self.assertTrue(result["fs_isolated"] and result["network_isolated"])
        seen = json.loads(result["stdout"])
        self.assertEqual(seen["inside_exchange"], "X")  # same port number as the host listener: own namespace
        self.assertEqual(seen["etc"], [])  # host configuration files (passwd, shadow, keys) are not mounted
        self.assertEqual(seen["public_ip"], "errno:101")
        if host != "-":
            self.assertEqual(seen["host_address"], "errno:101")
        for listener in listeners:
            with self.assertRaises(BlockingIOError):
                listener.accept()
        default = self.run_in(command, timeout=20)  # the default is unchanged: no interface is up
        plain_profile = json.loads(default["stdout"])
        self.assertEqual(plain_profile["inside_exchange"], "errno:101", default["stderr"])
        self.assertIn("passwd", plain_profile["etc"])  # unchanged default: legacy calls still see /etc


class EvidenceTests(unittest.TestCase):
    def test_isolation_evidence_is_measured_and_public_safe(self):
        evidence = json.loads(EVIDENCE.read_text())
        self.assertEqual((evidence["schema"], evidence["measured"], evidence["simulated"]), ("gaie-isolation/v1", True, False))
        self.assertIn(evidence["tier"], ("full", "plain"))
        self.assertEqual(evidence["enforced"]["filesystem_writes_only_in_allowed_paths"], evidence["tier"] == "full")
        self.assertFalse(evidence["enforced"]["process_count_limit"])
        self.assertTrue(all(probe["command"] for probe in evidence["probes"]))
        text = EVIDENCE.read_text()
        self.assertIsNone(governor.check_payload(evidence))
        for private in ("/home/", "/root", "/tmp/", "gaie-governor-probe"):
            self.assertNotIn(private, text)

    def test_report_matches_the_live_probe_shape(self):
        report = governor.isolation_report()
        self.assertEqual(set(report), set(json.loads(EVIDENCE.read_text())))
        self.assertEqual(report["tier"], governor.isolation_probe()["tier"])


if __name__ == "__main__":
    unittest.main()
