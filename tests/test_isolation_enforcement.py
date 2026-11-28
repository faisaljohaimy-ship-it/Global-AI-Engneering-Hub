"""Isolation of target code: SEC-07 (detectors.Sandbox: heal, upgrade, runtime detectors) and
SEC-12 (layers.verify), plus the measured evidence docs/evidence/gaie-20-layers/isolation.json.

Every check is either positive enforcement, measured with real children, where this host builds
the governor's full sandbox, or a measured refusal where it cannot; never a silent pass.
GAIE_REQUIRE_FULL_SANDBOX=1 turns a missing full tier into a failure (the CI job that enables
user namespaces sets it). Planted values are random per run; nothing secret-shaped is tracked.
"""
import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engineering_os import contracts, detectors, governor, layers, upgrade_engine  # noqa: E402
from scripts import isolation_evidence as evidence  # noqa: E402

EVIDENCE = ROOT / "docs" / "evidence" / "gaie-20-layers" / "isolation.json"
FULL = governor.isolation_probe()["tier"] == "full"
REQUIRED = os.environ.get("GAIE_REQUIRE_FULL_SANDBOX") == "1"
PLAIN = {"tier": "plain", "root_netns": False, "userns_netns": False, "unshare": True, "root": False, "full_checks": None}
OS_LAUNCHERS = ("governor.sandbox_run strict", "governor.sandbox_run loopback", "detectors.Sandbox os",
                "layers._run strict", "layers._run loopback")
# A wall that a launcher does not own: the loopback profile writes where its caller lets it, and
# layers._run has no .git pointer in its per-run workspace (the repository is read-only).
OPEN_BY_DESIGN = {("governor.sandbox_run loopback", "git_pointer_write"), ("layers._run strict", "git_pointer_write"),
                  ("layers._run loopback", "git_pointer_write")}


def planted():
    return "planted-" + os.urandom(12).hex()


def tree(base, files):
    base = pathlib.Path(base)
    for rel, text in files.items():
        path = base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")
    return base


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="gaie-iso-", dir="/tmp" if os.path.isdir("/tmp") else None)).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.outside = self.tmp / "outside"
        self.outside.mkdir()
        self.marker = self.outside / "marker.txt"
        self.marker.write_text("host-only")

    def walls_target(self, name, env_name, extra=""):
        """A target whose tests pass only while the walls hold (each failure names what leaked)."""
        return tree(self.tmp / name, {"app.py": "def add(a, b):\n    return a + b\n", "tests/test_walls.py": f'''
            import os, subprocess, sys, unittest
            import app
            MARKER, OUTSIDE, ENV = {str(self.marker)!r}, {str(self.outside)!r}, {env_name!r}


            class Walls(unittest.TestCase):
                def test_add(self):
                    self.assertEqual(app.add(2, 3), 5)

                def test_outside_marker_is_unreadable(self):
                    with self.assertRaises(OSError):
                        open(MARKER).read()

                def test_writing_outside_fails(self):
                    with self.assertRaises(OSError):
                        open(os.path.join(OUTSIDE, "escaped.txt"), "w").write("x")

                def test_etc_shadow_and_passwd_are_hidden(self):
                    for path in ("/etc/shadow", "/etc/passwd"):
                        with self.assertRaises(OSError):
                            open(path).read(1)

                def test_no_capabilities(self):
                    eff = [l.split()[1] for l in open("/proc/self/status") if l.startswith("CapEff")][0]
                    self.assertEqual(eff, "0000000000000000")

                def test_a_child_meets_the_same_walls(self):
                    done = subprocess.run([sys.executable, "-c", "open(%r).read()" % MARKER], capture_output=True)
                    self.assertNotEqual(done.returncode, 0)

                def test_ambient_variable_is_absent(self):
                    self.assertNotIn(ENV, os.environ)
            {textwrap.indent(textwrap.dedent(extra), "    ")}
            '''})


class RequiredTierTests(unittest.TestCase):
    def test_full_tier_is_present_when_required(self):
        if not REQUIRED:
            raise unittest.SkipTest(f"GAIE_REQUIRE_FULL_SANDBOX is not set (tier here: {governor.isolation_probe()['tier']})")
        self.assertTrue(FULL, f"the full sandbox is required here; probe: {governor.isolation_probe()}")


class PropertyMatrixTests(unittest.TestCase):
    """The evidence generator's matrix, measured now with real children on this host."""

    @classmethod
    def setUpClass(cls):
        cls.matrix = evidence.measure()

    def test_os_launchers_enforce_every_wall_or_refuse(self):
        self.assertFalse(REQUIRED and not FULL, "GAIE_REQUIRE_FULL_SANDBOX=1 but the full tier is missing")
        for launcher in OS_LAUNCHERS:
            rows = self.matrix["launchers"][launcher]
            self.assertEqual(set(rows["properties"]), set(evidence.PROPERTIES), launcher)
            for name, row in rows["properties"].items():
                with self.subTest(launcher=launcher, property=name):
                    self.assertIn(row["status"], evidence.STATUSES)
                    if not FULL:
                        self.assertFalse(rows["ran"])
                        self.assertIn(row["status"], ("refused", "not-available"))
                    elif (launcher, name) in OPEN_BY_DESIGN or name == "af_inet6_host_loopback" and not socket.has_ipv6:
                        self.assertNotEqual(row["status"], "refused")
                    elif name == "af_inet6_host_loopback":
                        self.assertIn(row["status"], ("enforced", "not-available"))
                    else:
                        self.assertEqual(row["status"], "enforced", row["observed"])

    def test_process_only_mode_scrubs_the_environment_and_reports_the_rest_open(self):
        for launcher in ("detectors.Sandbox process-only", "layers._run process-only"):
            rows = self.matrix["launchers"][launcher]["properties"]
            with self.subTest(launcher=launcher):
                self.assertEqual(rows["ambient_environment_variable"]["status"], "enforced")
                self.assertEqual(rows["descendant_outlives_run"]["status"], "enforced")
                self.assertEqual(rows["read_outside_file"]["status"], "not-enforced")  # honest: no filesystem wall
                self.assertEqual(rows["write_outside_workspace"]["status"], "not-enforced")

    def test_a_host_without_the_full_tier_refuses_and_runs_nothing(self):
        rows = self.matrix["plain_tier_behaviour"]
        for name in ("governor.sandbox_run strict", "governor.sandbox_run loopback", "detectors.Sandbox (default os)"):
            self.assertEqual(rows[name]["status"], "refused", name)
        self.assertIn("process-only", rows["layers._run (verify)"]["observed"])
        self.assertEqual(rows["nothing executed by a refusing launcher"]["status"], "enforced")


class Sec07Tests(Case):
    def test_hostile_target_tests_under_upgrade_are_contained_or_refused(self):
        """The reviewer's PoC (F5) through upgrade(): read and write outside, /etc/shadow, root, a child."""
        name = "GAIE_FAKE_SECRET"
        target = self.walls_target("target", name)
        work = self.tmp / "work"
        work.mkdir(mode=0o700)
        with mock.patch.dict(os.environ, {name: planted()}):
            report = upgrade_engine.upgrade(str(target), command="fix errors in this project", workdir=str(work))
        self.assertFalse((self.outside / "escaped.txt").exists())
        self.assertEqual(self.marker.read_text(), "host-only")
        if not FULL:
            self.assertFalse(REQUIRED, "GAIE_REQUIRE_FULL_SANDBOX=1 but the full tier is missing")
            self.assertIn("refused", report["blocked"])
            self.assertEqual((report["sandbox"]["os_sandbox"], report["guarantees"]["network_guard"]),
                             (False, "target-code-not-run"))
            return
        outcomes = report["baseline"]["tests"]["outcomes"]
        self.assertEqual(len(outcomes), 7, outcomes)
        self.assertEqual(set(outcomes.values()), {"passed"}, outcomes)
        self.assertEqual(set(report["sandbox"]["tiers"]), {"governor-full"})
        self.assertTrue(report["sandbox"]["os_sandbox"] and report["guarantees"]["os_sandbox_claimed"])

    def test_heal_runs_target_tests_inside_the_walls(self):
        from engineering_os import healing
        name = "GAIE_FAKE_SECRET"
        target = self.walls_target("heal-target", name)
        seen = []
        real = detectors.Sandbox._record

        def spy(box, tier, **extra):
            row = real(box, tier, **extra)
            seen.append(row)
            return row
        with mock.patch.dict(os.environ, {name: planted()}), mock.patch.object(detectors.Sandbox, "_record", spy):
            result = healing.heal(target, workdir=self.tmp / "heal-work", tests={"start": "tests", "pattern": "test_*.py"}, now=1_800_000_000)
        self.assertTrue(seen)
        self.assertFalse((self.outside / "escaped.txt").exists())
        if not FULL:
            self.assertEqual({row["tier"] for row in seen}, {"refused"})
            self.assertEqual(result["status"], "blocked")
            return
        self.assertEqual({row["tier"] for row in seen}, {"governor-full"})
        self.assertTrue(all(row["fs_isolated"] and row["network"] == "private-loopback" for row in seen))
        self.assertEqual(set(result["baseline_tests"].values()), {"passed"}, result["baseline_tests"])

    def test_default_isolation_refuses_on_a_plain_host_and_runs_nothing(self):
        flag = self.outside / "ran.txt"
        target = tree(self.tmp / "t", {"suite/case_flag.py": f'''
            import unittest
            class F(unittest.TestCase):
                def test_flag(self):
                    open({str(flag)!r}, "w").write("ran")
            ''', "work.py": "def f():\n    return 1\n"})
        box = detectors.Sandbox(self.tmp / "box")
        with mock.patch.object(governor, "isolation_probe", return_value=PLAIN):
            result = box.run_tests(target, "suite", "case_*.py")
            memory = detectors.detect_memory(target, {"memory": [{"module": "work", "function": "f", "args": [], "calls": 10,
                                                                  "threshold_bytes": 1024}]}, sandbox=box)
            apis, integrations = detectors.detect_http(target, None, {"app": {"script": "work.py"}}, sandbox=box)
        self.assertEqual((result["status"], result["isolation"]["tier"], result["isolation"]["mode"]), ("refused", "refused", "os"))
        self.assertNotIn("tests", result)
        self.assertEqual((memory["status"], apis["status"], integrations["status"]), ("refused", "refused", "refused"))
        self.assertFalse(flag.exists())
        self.assertEqual(box.summary()["os_sandbox"], False)

    def test_process_only_is_an_explicit_audited_opt_in(self):
        with self.assertRaises(detectors.DetectorError):
            detectors.Sandbox(self.tmp / "bad", isolation="none")
        self.assertFalse((self.tmp / "bad" / governor.AUDIT_FILE).exists())
        quiet = detectors.Sandbox(self.tmp / "os-box")
        self.assertFalse((self.tmp / "os-box" / governor.AUDIT_FILE).exists())
        self.assertIsNone(quiet.audit_log)
        box = detectors.Sandbox(self.tmp / "box", isolation="process-only")
        self.assertEqual(governor.verify_audit(self.tmp / "box"), 1)
        record = json.loads((self.tmp / "box" / governor.AUDIT_FILE).read_text())
        self.assertEqual((record["decision"], record["action"]), ("allow", "sandbox-process-only"))
        target = tree(self.tmp / "t", {"suite/case_ok.py": "import unittest\nclass T(unittest.TestCase):\n    def test_ok(self):\n        pass\n"})
        result = box.run_tests(target, "suite", "case_*.py")
        self.assertEqual(result["status"], "ok")
        self.assertEqual((result["isolation"]["mode"], result["isolation"]["opt_in"], result["isolation"]["fs_isolated"]),
                         ("process-only", True, False))
        with self.assertRaises(governor.GovernorDenied) as refusal:  # an opt-in that cannot be audited is refused
            detectors.Sandbox(ROOT / ".gaie-iso-test-scratch", isolation="process-only")
        self.assertEqual(refusal.exception.reason, "audit-in-repository")
        shutil.rmtree(ROOT / ".gaie-iso-test-scratch", ignore_errors=True)

    def test_output_is_bounded_and_only_its_tail_is_read(self):
        """Review M4: a noisy test crashes its run at the file limit; the parent reads a tail only."""
        target = tree(self.tmp / "t", {"suite/case_noise.py": '''
            import sys, unittest
            class N(unittest.TestCase):
                def test_noise(self):
                    for _ in range(3):
                        sys.stderr.write("x" * (1024 * 1024))
                        sys.stderr.flush()
            '''})
        modes = ["process-only"] + (["os"] if FULL else [])
        for mode in modes:
            with self.subTest(mode=mode), mock.patch.object(detectors, "SANDBOX_FILE_MB", 1):
                box = detectors.Sandbox(self.tmp / ("box-" + mode), isolation=mode)
                result = box.run_tests(target, "suite", "case_*.py")
                # Python ignores SIGXFSZ: the write past the limit fails with EFBIG inside the test
                self.assertEqual(result["tests"], {"case_noise.N.test_noise": "error"}, result.get("log_tail"))
                self.assertIn("File too large", result["details"]["case_noise.N.test_noise"]["message"])
                self.assertLessEqual(len(result["log_tail"]), 2000)
                for log in box.scratch.glob("results/*/driver.log"):
                    self.assertLessEqual(log.stat().st_size, 1024 * 1024)
        sparse = self.tmp / "sparse.log"
        with open(sparse, "wb") as handle:
            handle.truncate(1024 ** 3)  # 1 GiB, no blocks allocated
            handle.seek(1024 ** 3 - 4)
            handle.write(b"tail")
        self.assertEqual(detectors._tail(sparse, 4), b"tail")
        self.assertEqual(len(detectors._tail(sparse, 2000)), 2000)

    def test_no_helper_outlives_its_run(self):
        """Review L1: a helper started in its own session dies with the run, in both modes."""
        tag = "gaie-iso-helper-" + os.urandom(6).hex()
        target = tree(self.tmp / "t", {"suite/case_daemon.py": f'''
            import subprocess, unittest
            class D(unittest.TestCase):
                def test_daemon(self):
                    subprocess.Popen(["sleep", "30", {tag!r}], start_new_session=True)
            '''})
        for mode in ["process-only"] + (["os"] if FULL else []):
            with self.subTest(mode=mode):
                result = detectors.Sandbox(self.tmp / ("box-" + mode), isolation=mode).run_tests(target, "suite", "case_*.py")
                self.assertEqual(result["tests"], {"case_daemon.D.test_daemon": "passed"})
                alive = [p for p in os.listdir("/proc") if p.isdigit() and tag.encode() in _cmdline(p)]
                self.assertEqual(alive, [])

    def test_sendmsg_is_guarded_and_the_namespace_is_the_boundary(self):
        """Review L4: the guard covers sendmsg; in the OS mode even the C socket methods meet errno 101."""
        target = tree(self.tmp / "t", {"suite/case_udp.py": '''
            import errno, socket, unittest, _socket
            class U(unittest.TestCase):
                def test_sendmsg_guarded(self):
                    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    with self.assertRaises(PermissionError):
                        sock.sendmsg([b"x"], [], 0, ("192.0.2.1", 9))
                    sock.close()

                def test_raw_methods_past_the_guard(self):
                    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    with self.assertRaises(OSError) as raised:
                        _socket.socket.sendmsg(sock, [b"x"], [], 0, ("192.0.2.1", 9))
                    self.assertEqual(raised.exception.errno, errno.ENETUNREACH)
                    sock.close()
            '''})
        modes = [("process-only", {"case_udp.U.test_sendmsg_guarded": "passed"})]
        if FULL:
            modes.append(("os", {"case_udp.U.test_sendmsg_guarded": "passed", "case_udp.U.test_raw_methods_past_the_guard": "passed"}))
        for mode, expected in modes:
            with self.subTest(mode=mode):
                result = detectors.Sandbox(self.tmp / ("box-" + mode), isolation=mode).run_tests(
                    target, "suite", "case_*.py", only=sorted(expected))
                self.assertEqual(result["tests"], expected, result.get("details"))


def _cmdline(pid):
    try:
        return pathlib.Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return b""


def layer_record(lid, tests):
    return {"id": lid, "name": {"en": f"Isolation {lid}", "ar": "طبقة اختبار العزل"}, "responsibilities": ["Hold a probe."],
            "interfaces": ["probe_pkg:value"], "inputs": ["none"], "outputs": ["none"], "depends_on": [],
            "permissions": ["read:repo"], "skills": [], "tools": ["python3"],
            "agents": ["agent-isolation-security-engineer"], "tests": list(tests), "scenarios": [],
            "evidence": {"rule": "tests-pass"}}


class Sec12Tests(Case):
    """layers.verify: exact minimal environment everywhere; the governor sandbox where available."""

    def build(self, env_name):
        root = tree(self.tmp / "tree", {
            "probe_pkg/__init__.py": "def value():\n    return 1\n",
            "tests/test_env_probe.py": f'''
                import os, unittest
                import probe_pkg
                class Env(unittest.TestCase):
                    def test_interface(self):
                        self.assertEqual(probe_pkg.value(), 1)

                    def test_ambient_variable_is_absent(self):
                        self.assertNotIn({env_name!r}, os.environ)
                        self.assertLessEqual(set(os.environ), {{"PATH", "HOME", "TMPDIR", "LANG", "LC_CTYPE"}})
                ''',
            "tests/test_fs_probe.py": f'''
                import os, unittest
                import probe_pkg
                class Fs(unittest.TestCase):
                    def test_interface(self):
                        self.assertEqual(probe_pkg.value(), 1)

                    def test_secret_outside_is_unreadable(self):
                        with self.assertRaises(OSError):
                            open({str(self.marker)!r}).read()

                    def test_repository_is_read_only(self):
                        with self.assertRaises(OSError):
                            open(os.path.join(os.getcwd(), "escaped.txt"), "w").write("x")
                ''',
        })
        records = []
        for lid in contracts.LAYER_IDS:
            records.append(layer_record(lid, ["tests/test_env_probe.py"] if lid != "L02" else ["tests/test_fs_probe.py"]))
        (root / "governance").mkdir()
        (root / "governance/layers.json").write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
        return root

    def verify(self, root, ids, env_name):
        with mock.patch.dict(os.environ, {env_name: planted()}):
            return layers.verify(ids, state_dir=self.tmp / "state", root=root)

    def receipt(self, lid):
        return json.loads((self.tmp / "state" / f"{lid}.json").read_text(encoding="utf-8"))

    def test_layer_tests_see_no_planted_secret_or_ambient_variable(self):
        root = self.build("GAIE_FAKE_SECRET")
        report = self.verify(root, ["L01", "L02"], "GAIE_FAKE_SECRET")
        status = {row["id"]: row["status"] for row in report["layers"]}
        self.assertEqual(status["L01"], "VERIFIED")  # the environment is scrubbed on every host
        self.assertFalse((root / "escaped.txt").exists() and FULL)
        execution = self.receipt("L02")["execution"]
        if not FULL:
            self.assertFalse(REQUIRED, "GAIE_REQUIRE_FULL_SANDBOX=1 but the full tier is missing")
            self.assertEqual(status["L02"], "FAILED")  # measured: no filesystem wall without the sandbox, recorded
            self.assertEqual((execution["mode"], execution["sandboxed"]), ("subprocess", False))
            return
        self.assertEqual(status["L02"], "VERIFIED")
        self.assertEqual((execution["mode"], execution["sandboxed"], execution["tier"]), ("governor-sandbox", True, "full"))
        self.assertEqual(self.receipt("L02")["tests"][0]["isolation"]["profile"], "strict")

    def test_process_only_exceptions_keep_the_scrubbed_environment_and_say_why(self):
        # recheck-security item 1: an exception is keyed by its path and the SHA-256 of the reviewed bytes
        root = self.build("GAIE_FAKE_SECRET")
        pin = {"sha256": layers._hash_file(root, "tests/test_env_probe.py"), "executes": {}, "reason": "fixture exception"}
        with mock.patch.dict(layers.PROCESS_ONLY_TESTS, {"tests/test_env_probe.py": pin}):
            report = self.verify(root, ["L01"], "GAIE_FAKE_SECRET")
        self.assertEqual(report["layers"][0]["status"], "VERIFIED")
        receipt = self.receipt("L01")
        row = receipt["tests"][0]
        self.assertEqual((row["isolation"]["profile"], row["isolation"]["sandboxed"], row["isolation"]["reason"]),
                         ("process-only", False, "fixture exception"))
        self.assertEqual((row["isolation"]["exception"]["matched"], row["isolation"]["tier"]),
                         (True, governor.isolation_probe()["tier"]))
        self.assertIn("fixture exception", receipt["execution"]["process_only"])
        self.assertFalse(receipt["execution"]["sandboxed"])

    def test_an_exception_file_edited_after_review_runs_strict(self):
        """recheck-security item 1: the same exception, keyed by path only, ran an edited file unsandboxed."""
        root = self.build("GAIE_FAKE_SECRET")
        pin = {"sha256": layers._hash_file(root, "tests/test_fs_probe.py"), "executes": {}, "reason": "fixture exception"}
        probe = root / "tests/test_fs_probe.py"
        probe.write_text(probe.read_text(encoding="utf-8") + "\n# edited after the review\n", encoding="utf-8")
        with mock.patch.dict(layers.PROCESS_ONLY_TESTS, {"tests/test_fs_probe.py": pin}):
            report = self.verify(root, ["L02"], "GAIE_FAKE_SECRET")
        row = self.receipt("L02")["tests"][0]
        self.assertEqual((row["isolation"]["exception"]["matched"], row["isolation"]["exception"]["changed"]),
                         (False, ["tests/test_fs_probe.py"]))
        if not FULL:
            self.assertFalse(REQUIRED, "GAIE_REQUIRE_FULL_SANDBOX=1 but the full tier is missing")
            self.assertEqual(row["isolation"]["profile"], "process-only")  # measured fallback, recorded
            return
        self.assertEqual(report["layers"][0]["status"], "VERIFIED")  # the walls held: secret unreadable, repo read-only
        self.assertEqual((row["isolation"]["profile"], row["isolation"]["sandboxed"]), ("strict", True))
        self.assertIn("differs from its review", row["isolation"]["reason"])

    def test_a_plain_host_falls_back_and_records_it(self):
        root = self.build("GAIE_FAKE_SECRET")
        with mock.patch.object(governor, "isolation_probe", return_value=PLAIN), \
                mock.patch.object(governor, "sandbox_run", side_effect=AssertionError("no sandbox on a plain host")):
            report = self.verify(root, ["L01"], "GAIE_FAKE_SECRET")
        self.assertEqual(report["layers"][0]["status"], "VERIFIED")
        receipt = self.receipt("L01")
        self.assertEqual((receipt["execution"]["mode"], receipt["execution"]["tier"]), ("subprocess", "plain"))
        self.assertIn("tier plain", receipt["tests"][0]["isolation"]["reason"])

    def test_measured_exception_list_names_existing_files_with_reasons(self):
        for test, entry in layers.PROCESS_ONLY_TESTS.items():
            self.assertTrue((ROOT / test).is_file(), test)
            self.assertGreater(len(entry["reason"]), 40, test)
            self.assertRegex(entry["sha256"], r"^[0-9a-f]{64}$", test)
            self.assertTrue(layers._exception(ROOT, test)["matched"], f"{test}: review it, then re-pin "
                            f"{layers.exception_digests(ROOT)[test]}")
        self.assertLessEqual(set(layers.LOOPBACK_TESTS), {str(p.relative_to(ROOT)) for p in (ROOT / "tests").glob("test_*")})


class EvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = EVIDENCE.read_text(encoding="utf-8")
        cls.document = json.loads(cls.text)
        cls.matrix = next(probe["result"] for probe in cls.document["probes"]
                          if isinstance(probe["result"], dict) and "launchers" in probe["result"])

    def test_evidence_is_bound_to_the_code_it_measured(self):
        stale = evidence.stale(EVIDENCE)
        self.assertEqual(stale, [], "the measured code changed: run python3 scripts/isolation_evidence.py "
                                    "--out docs/evidence/gaie-20-layers/isolation.json on a full-tier host")

    def test_a_changed_digest_is_detected(self):
        with tempfile.TemporaryDirectory() as folder:
            copy = json.loads(self.text)
            result = next(p["result"] for p in copy["probes"] if isinstance(p["result"], dict) and "sources" in p["result"])
            first = sorted(result["sources"])[0]
            result["sources"][first] = "0" * 64
            path = pathlib.Path(folder) / "isolation.json"
            path.write_text(json.dumps(copy), encoding="utf-8")
            self.assertEqual(evidence.stale(path), [first])

    def test_evidence_is_measured_public_safe_and_states_its_host(self):
        doc = self.document
        self.assertEqual((doc["measured"], doc["simulated"]), (True, False))
        self.assertEqual(set(doc), set(governor.isolation_report()))
        self.assertIn("tests/test_isolation_enforcement.py", doc["tests"])
        for key in ("kernel", "machine", "caller_is_root", "uid_is_root", "ipv6", "libseccomp", "measured_here_only"):
            self.assertIn(key, doc["host"])
        self.assertIsNone(governor.check_payload(doc))
        for private in ("/home/", "/root", "/tmp/", "planted-"):
            self.assertNotIn(private, self.text)
        self.assertEqual(self.matrix["statuses"], list(evidence.STATUSES))
        self.assertEqual(set(self.matrix["launchers"]), set(evidence.LAUNCHERS))
        for launcher, rows in self.matrix["launchers"].items():
            self.assertEqual(set(rows["properties"]), set(evidence.PROPERTIES), launcher)
            for row in rows["properties"].values():
                self.assertIn(row["status"], evidence.STATUSES)
        self.assertEqual(self.matrix["plain_tier_behaviour"]["detectors.Sandbox (default os)"]["status"], "refused")

    def test_live_matrix_equals_the_evidence_only_on_a_matching_host(self):
        """The evidence describes the host it was measured on; elsewhere it is not re-asserted."""
        host = self.document["host"]
        same = (FULL and self.document["tier"] == "full" and host["uid_is_root"] == (os.geteuid() == 0)
                and host["ipv6"] == os.path.exists("/proc/net/if_inet6") and evidence.stale(EVIDENCE) == [])
        if not same:
            raise unittest.SkipTest("this host differs from the measured one (tier, uid or IPv6): evidence not re-asserted")
        live = evidence.measure(names=["governor.sandbox_run strict", "detectors.Sandbox os", "layers._run strict"])
        for launcher, rows in live["launchers"].items():
            recorded = self.matrix["launchers"][launcher]["properties"]
            self.assertEqual({k: v["status"] for k, v in rows["properties"].items()},
                             {k: v["status"] for k, v in recorded.items()}, launcher)


if __name__ == "__main__":
    unittest.main()
