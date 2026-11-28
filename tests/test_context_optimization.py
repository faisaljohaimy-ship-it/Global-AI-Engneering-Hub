"""The context-optimization skill: the wrapper, the MCP probe, the locks and the evidence.

Nothing here needs Headroom, Serena or the network. The wrapper is pointed at an empty
tool folder, so these tests exercise the path every machine has: store the original,
show a plain view, keep the error lines, fetch the original back.
"""
import hashlib
import importlib.util
import json
import os
import pathlib
import re
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest

import hub

ROOT = pathlib.Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "ultra-context-optimization"
SCRIPTS = SKILL / "scripts"
ERROR = "ValueError: bad frame 7 at render.py:91"


def module(name):
    spec = importlib.util.spec_from_file_location(f"skill_{name}", SCRIPTS / f"{name}.py")
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def long_log(lines=1800):
    half = "\n".join(f"step {number} ok" for number in range(lines // 2))
    return f"{half}\n{ERROR}\n{half}\nRan {lines} steps\n"


class WrapperTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.hr = module("hr")
        self.hr.STORE = pathlib.Path(self.folder.name) / "store"
        self.hr.TOOL_HOME = pathlib.Path(self.folder.name) / "no-tools"
        self.saved = os.environ.get("HR_SESSION")
        os.environ["HR_SESSION"] = "test-a"
        self.addCleanup(self.restore)

    def restore(self):
        if self.saved is None:
            os.environ.pop("HR_SESSION", None)
        else:
            os.environ["HR_SESSION"] = self.saved

    def test_view_is_shorter_keeps_the_error_and_the_original_comes_back(self):
        text = long_log()
        shown, facts = self.hr.view(text, "", "make build")
        self.assertLess(len(shown), len(text) // 2)
        self.assertIn(ERROR, shown)
        self.assertIn("plain head and tail", facts["via"])
        self.assertIn(f"hr get {facts['ref']}", shown)
        back, meta = self.hr.load(facts["ref"])
        self.assertEqual(back, text)
        self.assertEqual(meta["sha256"], hashlib.sha256(text.encode()).hexdigest())
        self.assertEqual(meta["lines"], text.count("\n"))

    def test_short_output_is_printed_unchanged_and_not_stored(self):
        shown, facts = self.hr.view("ok\n", "", "true")
        self.assertEqual(shown, "ok\n")
        self.assertEqual(facts["via"], "as it is")
        self.assertFalse(self.hr.STORE.exists())

    def test_output_that_cannot_be_shortened_is_printed_unchanged_and_not_kept(self):
        text = "\n".join(f"line {number} of a short but wide listing " + "x" * 40 for number in range(40)) + "\n"
        shown, facts = self.hr.view(text, "", "ls -la")
        self.assertEqual(shown, text)
        self.assertEqual(facts["via"], "as it is")
        self.assertEqual(list((self.hr.STORE / "test-a").glob("*")), [])

    def test_a_view_is_never_compressed_again(self):
        first, _ = self.hr.view(long_log(), "", "make build")
        second, facts = self.hr.view(first + "x\n" * 2000, "", "cat view")
        self.assertEqual(facts["via"], "already a view")
        self.assertTrue(second.startswith(self.hr.MARK))

    def test_one_session_cannot_read_another(self):
        _, facts = self.hr.view(long_log(), "", "make build")
        os.environ["HR_SESSION"] = "test-b"
        with self.assertRaises(SystemExit) as refused:
            self.hr.load(facts["ref"])
        self.assertIn("no stored output", str(refused.exception))

    def test_store_is_private(self):
        _, facts = self.hr.view(long_log(), "", "make build")
        folder = self.hr.STORE / "test-a"
        self.assertEqual(stat.S_IMODE(folder.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((folder / f"{facts['ref']}.raw").stat().st_mode), 0o600)

    def test_references_must_be_hexadecimal(self):
        with self.assertRaises(SystemExit):
            self.hr.load("../../etc/passwd")

    def test_error_phrases_are_found_inside_one_very_long_line(self):
        record = '{"status":"failed","error":"ConnectionResetError: upstream closed at gateway/pool.py:218"}'
        line = "[" + ",".join(['{"status":"ok"}'] * 400 + [record]) + "]"
        kept = [found for _, found in self.hr.must_keep(line)]
        self.assertEqual(kept, ["ConnectionResetError: upstream closed at gateway/pool.py:218"])

    def test_the_command_decides_the_kind_of_output(self):
        cases = {
            "python3 -m unittest discover -s tests -v": "log",
            "npm run build": "log",
            "node --test packages/motion-sdk/test/*.test.mjs": "log",
            "rg -n defineMotion packages": "search",
            "git diff main...HEAD": "diff",
            "cat evidence/chromium.json": "",
            "git log --stat -30": "",
        }
        for command, kind in cases.items():
            self.assertEqual(self.hr.kind_of(command, "plain text"), kind, command)
        self.assertEqual(self.hr.kind_of("cat evidence/chromium.json", '  [{"a": 1}]'), "json")

    def test_the_worker_gets_no_credentials_and_is_told_to_stay_offline(self):
        os.environ["ANTHROPIC_API_KEY"] = "not-a-real-key"
        self.addCleanup(os.environ.pop, "ANTHROPIC_API_KEY", None)
        env = self.hr.worker_env()
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertFalse([name for name in env if "PROXY" in name.upper() or "TOKEN" in name.upper()])
        self.assertEqual((env["HEADROOM_OFFLINE"], env["HEADROOM_TELEMETRY"], env["HEADROOM_UPDATE_CHECK"]), ("1", "off", "0"))

    def test_command_line_passes_the_exit_status_and_fetches_exact_lines(self):
        env = {**os.environ, "HR_STORE": str(self.hr.STORE), "HR_TOOL_HOME": str(self.hr.TOOL_HOME), "HR_SESSION": "cli"}

        def hr(*arguments):
            return subprocess.run([sys.executable, str(SCRIPTS / "hr.py"), *arguments], capture_output=True, text=True, env=env)

        ran = hr("run", "--", "bash", "-c", "seq 1 3000; echo 'fatal: boom' >&2; exit 3")
        self.assertEqual(ran.returncode, 3)
        self.assertIn("rc=3", ran.stdout)
        self.assertIn("fatal: boom", ran.stdout)
        ref = ran.stdout.split("[hr ref=", 1)[1].split()[0]
        self.assertEqual(hr("get", ref, "--lines", "1499:1501").stdout.split(), ["1499:1499", "1500:1500", "1501:1501"])
        self.assertEqual(hr("get", ref, "--grep", "^fatal").stdout.strip(), "3001:fatal: boom")
        self.assertEqual(hr("verify", ref).returncode, 0)
        raw = next((self.hr.STORE / "cli").glob("*.raw"))
        raw.write_text(raw.read_text() + "tampered\n")
        changed = hr("verify", ref)
        self.assertEqual(changed.returncode, 1)
        self.assertIn("CHANGED", changed.stdout)
        unsplit = hr("run", "--", "seq 1 3")
        self.assertNotEqual(unsplit.returncode, 0)
        self.assertIn("separate words", unsplit.stderr)


class ProbeTests(unittest.TestCase):
    SERVER = textwrap.dedent("""
        import json, sys
        for line in sys.stdin:
            message = json.loads(line)
            if "id" not in message:
                continue
            method = message["method"]
            if method == "initialize":
                result = {"serverInfo": {"name": "fake", "version": "0"}, "capabilities": {}}
            elif method == "tools/list":
                result = {"tools": [{"name": "echo", "description": "Say it back."}]}
            else:
                result = {"content": [{"type": "text", "text": message["params"]["arguments"]["say"]}]}
            print("a log line that is not JSON")
            print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}), flush=True)
    """)

    def test_it_lists_and_calls_tools_of_a_local_server(self):
        probe = module("mcp_probe")
        with tempfile.TemporaryDirectory() as folder:
            script = pathlib.Path(folder) / "server.py"
            script.write_text(self.SERVER)
            with probe.Server([sys.executable, str(script)], timeout=20) as server:
                self.assertEqual(server.info["name"], "fake")
                self.assertEqual([tool["name"] for tool in server.tools()], ["echo"])
                self.assertEqual(server.call("echo", {"say": "exact words"}), ("exact words", False))

    def test_a_server_that_dies_is_reported(self):
        probe = module("mcp_probe")
        with self.assertRaises(probe.ServerError):
            probe.Server([sys.executable, "-c", "raise SystemExit(4)"], timeout=10)


class SupplyTests(unittest.TestCase):
    def test_python_locks_pin_every_package_with_a_hash(self):
        for name in ("headroom", "serena"):
            pinned = (SKILL / "locks" / f"{name}.in").read_text().split()
            self.assertTrue(all(re.fullmatch(r"[a-z0-9-]+==[0-9.]+", line) for line in pinned), pinned)
            lock = (SKILL / "locks" / f"{name}.lock").read_text()
            entries = re.split(r"\n(?=[A-Za-z0-9_.-]+==)", lock)[1:]
            self.assertGreater(len(entries), 20)
            for entry in entries:
                self.assertIn("--hash=sha256:", entry, entry.splitlines()[0])
            self.assertIn(pinned[0], lock)

    def test_npm_locks_pin_exact_versions_with_integrity_from_the_registry(self):
        for name in ("repomix", "context-mode"):
            wanted = json.loads((SKILL / "locks" / name / "package.json").read_text())["dependencies"]
            self.assertTrue(all(re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version) for version in wanted.values()), wanted)
            packages = json.loads((SKILL / "locks" / name / "package-lock.json").read_text())["packages"]
            for path, package in packages.items():
                if path:
                    self.assertTrue(package["integrity"].startswith("sha512-"), path)
                    self.assertTrue(package["resolved"].startswith("https://registry.npmjs.org/"), path)

    def test_bootstrap_installs_only_checked_pinned_things(self):
        script = (SCRIPTS / "bootstrap.sh").read_text()
        self.assertIn("--require-hashes", script)
        self.assertIn("npm ci --ignore-scripts", script)
        self.assertRegex(script, r'NODE24_SHA256="[0-9a-f]{64}"')
        self.assertIn("sha256sum -c", script)
        for forbidden in ("@latest", "sudo ", "npm install -g", "pip install --user"):
            self.assertFalse(forbidden in script, forbidden)
        self.assertIsNone(re.search(r"\|\s*(sh|bash)\b", script), "a download is piped into a shell")

    def test_no_script_reroutes_model_requests_or_starts_a_proxy(self):
        scripts = [path for path in SCRIPTS.iterdir() if path.suffix in (".py", ".sh")]
        self.assertGreaterEqual(len(scripts), 6)
        for script in scripts:
            text = script.read_text()
            self.assertFalse("ANTHROPIC_BASE_URL" in text, script.name)
            self.assertIsNone(re.search(r"headroom['\", ]+(proxy|wrap|init|deploy|install)\b", text), script.name)


class SkillTests(unittest.TestCase):
    def test_skill_is_found_by_the_hub(self):
        text = (SKILL / "SKILL.md").read_text()
        front = re.match(r"---\nname: ([a-z-]+)\ndescription: (.+)\n---\n", text)
        self.assertIsNotNone(front)
        self.assertEqual(front.group(1), "ultra-context-optimization")
        self.assertLessEqual(len(text.splitlines()), 150)
        found = [item for item in hub.recommend("tool output") if item["kind"] == "skill"]
        self.assertIn("ultra-context-optimization", [item["id"] for item in found])
        for reference in re.findall(r"`((?:references|evidence|scripts|locks)/[A-Za-z0-9_./-]*)`", text):
            self.assertTrue((SKILL / reference).exists(), reference)

    def test_evidence_adds_up_and_names_no_private_path(self):
        evidence = json.loads((SKILL / "evidence" / "headroom.json").read_text())
        self.assertEqual(evidence["failures"], [])
        self.assertTrue(all(evidence["checks"].values()), evidence["checks"])
        rows = evidence["samples"]
        self.assertEqual(sum(row["tokens"] for row in rows), evidence["total"]["tokens"])
        self.assertEqual(sum(row["view_tokens"] for row in rows), evidence["total"]["view_tokens"])
        self.assertTrue(all(row["error_lines_missing"] == 0 and row["original_intact"] for row in rows))
        self.assertIn("proxy", evidence["token_counter"])
        for path in (SKILL / "evidence").iterdir():
            text = path.read_text()
            for private in ("/home/", "/root/", "/Users/", "/tmp/", "@gmail", "session_0"):
                self.assertFalse(private in text, f"{path.name} contains {private}")

    def test_measurements_page_quotes_the_evidence(self):
        evidence = json.loads((SKILL / "evidence" / "headroom.json").read_text())
        page = (SKILL / "references" / "measurements.md").read_text()
        for row in evidence["samples"]:
            self.assertIn(f"| {row['sample']} | {row['chars']:,} | {row['view_chars']:,} | {row['tokens']:,} | {row['view_tokens']:,} |", page)
        self.assertIn(f"{evidence['total']['tokens']:,} tokens", page)
        self.assertIn(f"{evidence['total']['view_tokens']:,} tokens", page)


if __name__ == "__main__":
    unittest.main()
