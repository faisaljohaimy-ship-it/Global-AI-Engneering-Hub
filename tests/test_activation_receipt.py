"""The committed activation receipt must agree with its generator, its locks and its schema.

These tests install nothing and run neither the tools nor the engine sweep. They read the
committed receipt and call the generator's own validation and tool-table functions on empty
temporary folders, so they pass on CI where none of the tools exists.
"""
import copy
import hashlib
import importlib.util
import json
import pathlib
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("activation_receipt", ROOT / "scripts" / "activation_receipt.py")
gen = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gen)
RECEIPT = json.loads((ROOT / gen.RECEIPT).read_text())


def sha(relative):
    return hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()


def first(rows, status="ran-here"):
    return next(index for index, row in enumerate(rows) if row["status"] == status)


class ReceiptBindingTests(unittest.TestCase):
    def test_committed_receipt_satisfies_the_schema(self):
        self.assertEqual(gen.validate(RECEIPT), [])
        self.assertIn(RECEIPT["mode"], ("full", "no-tools"))
        self.assertEqual(set(RECEIPT["statuses"]), set(gen.STATUSES))
        self.assertEqual((RECEIPT["provider_calls"], RECEIPT["paid_services"], RECEIPT["keys_read"], RECEIPT["deployments"]),
                         (0, 0, 0, 0))

    def test_receipt_is_bound_to_its_generator(self):
        generator = RECEIPT["generator"]
        self.assertEqual(generator["path"], "scripts/activation_receipt.py")
        self.assertEqual(generator["sha256"], sha("scripts/activation_receipt.py"),
                         "the generator changed: regenerate with " + gen.COMMAND)
        self.assertEqual(generator["regenerate"], gen.COMMAND)
        self.assertIn(gen.COMMAND, (ROOT / "scripts" / "activation_receipt.py").read_text().split('"""')[1])

    def test_tool_rows_are_bound_to_the_record_locks_tests_and_script(self):
        record = json.loads((ROOT / gen.TOOLS_RECORD).read_text())
        self.assertEqual([row["id"] for row in RECEIPT["tools"]], [tool["id"] for tool in record["tools"]])
        for tool, row in zip(record["tools"], RECEIPT["tools"]):
            self.assertEqual(row["version_locked"], tool["version"], tool["id"])
            self.assertEqual(row["lock"], tool["lock"], tool["id"])
            self.assertEqual(row["lock_sha256"], sha(tool["lock"]) if tool["lock"] else None, tool["id"])
            self.assertEqual(row["test_sha256"], sha(tool["test"]), tool["id"])
            self.assertEqual(row["script_sha256"], sha(gen.ACTIVATE), tool["id"])
            if row["status"] == "ran-here":
                self.assertEqual(row["digest"], row["lock_sha256"])
                self.assertEqual(row["version_installed"], tool["version"])
                self.assertTrue(row["lock_check"]["matches_lock"])
                self.assertTrue(any(line.startswith("passed") for line in row["output_head"]), tool["id"])
            if RECEIPT["mode"] == "no-tools":
                self.assertEqual(row["status"], "not-installed", tool["id"])
        context7 = next(row for row in RECEIPT["tools"] if row["id"] == "upstash/context7")
        self.assertIn(context7["status"], ("not-installed", "installed-test-blocked"), "Context7 needs a key and has no lock")

    def test_headroom_row_is_bound_to_its_lock_and_launcher_and_states_the_limits(self):
        row = RECEIPT["headroom"]
        self.assertEqual(row["lock_sha256"], sha(gen.HEADROOM_LOCK))
        self.assertEqual(row["launcher"], {path: sha(path) for path in gen.HEADROOM_LAUNCHER})
        if row["status"] != "ran-here":
            return
        measured = row["measurement"]
        self.assertEqual(row["version_installed"], row["version_locked"])
        self.assertTrue(measured["full_retrieval"]["sha256_matches_original"])
        self.assertEqual(measured["byte_reduction"], measured["input_bytes"] - measured["output_bytes"])
        self.assertEqual(measured["exact_tokens"], {"before": None, "after": None})
        self.assertIsNone(measured["context_usage"])
        self.assertIsNone(measured["billing"])
        self.assertIs(measured["native_agent_interception"], False)
        self.assertEqual(row["limits"], gen.HEADROOM_LIMITS)
        if measured["status"] != "optimized":
            self.assertEqual(measured["byte_reduction"], 0, "a fallback claims no reduction")

    def test_engine_rows_follow_the_generator_cases_and_name_registered_engines(self):
        cases, denials = gen.engine_cases(pathlib.Path("/nonexistent"), ROOT)
        called = [row for row in RECEIPT["engines"] if row["action"] is not None]
        self.assertEqual([(row["engine"], row["action"]) for row in called], [(case[0], case[1]) for case in cases])
        registered = {record["id"] for record in json.loads((ROOT / "governance" / "engines.json").read_text())}
        self.assertLessEqual({row["engine"] for row in RECEIPT["engines"]}, registered | set(RECEIPT["registered_engines"]))
        self.assertLessEqual({row["engine"] for row in called}, registered)
        for row in called:
            self.assertEqual(row["via"], "hub.py invoke")
            self.assertTrue(row["command"].startswith(f"python3 hub.py invoke {row['engine']} {row['action']} "))
        self.assertEqual([(row["engine"], row["action"], row["expected_reason"]) for row in RECEIPT["refusals"]],
                         [(case[0], case[1], case[4]) for case in denials])
        for row in RECEIPT["refusals"]:
            if row["status"] == "ran-here":
                self.assertEqual((row["exit"], row["reason"]), (3, row["expected_reason"]))

    def test_wave2_and_skill_rows_name_existing_sources(self):
        self.assertEqual([row["engine"] for row in RECEIPT["wave2"]],
                         ["requirements", "build_engine", "orchestrator", "video_pipeline", "upgrade_engine", "healing"])
        for row in RECEIPT["wave2"]:
            self.assertTrue((ROOT / row["digest_of"]).is_file(), row["digest_of"])
            self.assertIs(row["governed"], False)
            if "fixture_unchanged" in row and row["status"] == "ran-here":
                self.assertTrue(row["fixture_unchanged"])
        self.assertEqual([row["skill"] for row in RECEIPT["skills"]],
                         sorted(path.name for path in (ROOT / "skills").glob("gaie-*")))
        for row in RECEIPT["skills"]:
            self.assertTrue(row["native_skill_load"].startswith("not tested"))

    def test_history_files_are_marked_dated_and_kept_as_measured(self):
        notes = (ROOT / "docs" / "evidence" / "README.md").read_text()
        self.assertEqual([item["path"] for item in RECEIPT["history"]], [item["path"] for item in gen.HISTORY])
        for item in RECEIPT["history"]:
            self.assertEqual(item["status"], "dated history")
            self.assertEqual(item["sha256"], sha(item["path"]), "a dated evidence file was rewritten")
            self.assertIn(pathlib.Path(item["path"]).name, notes)
        self.assertIn(gen.RECEIPT.split("docs/evidence/")[1], notes)

    def test_no_row_quotes_catalogue_values_as_measured(self):
        self.assertIn("not host detection", RECEIPT["catalogue_values"])
        for section in ("tools", "engines", "wave2", "skills"):
            for row in RECEIPT[section]:
                for key in (row.get("observed") or {}):
                    self.assertIsNone(gen.CATALOGUE_KEY.search(key), f"{section} quotes catalogue field {key}")
                for key in ("installed", "operational", "live_recheck_performed"):
                    self.assertNotIn(key, row)


class ValidationTests(unittest.TestCase):
    def mutated(self, change):
        receipt = copy.deepcopy(RECEIPT)
        change(receipt)
        return gen.validate(receipt)

    def test_ran_here_without_exit_status_or_digest_is_refused(self):
        index = first(RECEIPT["engines"])
        cases = {
            "without an exit status": lambda r: r["engines"][index].pop("exit"),
            "exit None": lambda r: r["engines"][index].update(exit=None),
            "a boolean exit": lambda r: r["engines"][index].update(exit=True),
            "without a sha256 digest": lambda r: r["engines"][index].update(digest=None),
            "a short digest": lambda r: r["engines"][index].update(digest="abc"),
            "with exit 1": lambda r: r["engines"][index].update(exit=1),
            "without a command": lambda r: r["engines"][index].update(command=None),
            "without a duration": lambda r: r["engines"][index].pop("duration_s"),
        }
        for name, change in cases.items():
            with self.subTest(name):
                self.assertTrue(self.mutated(change), name)

    def test_refusal_must_exit_3_to_count_as_ran(self):
        index = first(RECEIPT["refusals"])
        self.assertTrue(self.mutated(lambda r: r["refusals"][index].update(exit=0)))

    def test_no_tools_mode_cannot_claim_a_tool_or_headroom_ran(self):
        def tool(receipt):
            receipt["mode"] = "no-tools"
            receipt["tools"][0].update(status="ran-here", exit=0, digest="a" * 64, command="x", duration_s=1.0,
                                       lock_check={"matches_lock": True}, version_installed=receipt["tools"][0]["version_locked"])

        def headroom(receipt):
            receipt["mode"] = "no-tools"
            receipt["headroom"].update(status="installed-test-blocked", reason="x")
        self.assertTrue(any("--no-tools" in problem for problem in self.mutated(tool)))
        self.assertTrue(any("--no-tools" in problem for problem in self.mutated(headroom)))

    def test_tool_ran_here_needs_a_matching_lock_and_version(self):
        def change(field, value):
            def apply(receipt):
                receipt["mode"] = "full"
                receipt["tools"][0].update(status="ran-here", exit=0, digest="a" * 64, command="x", duration_s=1.0,
                                           lock_check={"matches_lock": True}, version_installed=receipt["tools"][0]["version_locked"])
                receipt["tools"][0][field] = value
            return apply
        self.assertEqual(self.mutated(change("command", "x")), [])
        self.assertTrue(self.mutated(change("lock_check", {"matches_lock": False})))
        self.assertTrue(self.mutated(change("version_installed", "0.0.0")))

    def test_unknown_status_missing_reason_private_path_and_secret_are_refused(self):
        self.assertTrue(self.mutated(lambda r: r["engines"][0].update(status="passed")))
        self.assertTrue(self.mutated(lambda r: r["tools"][-1].update(status="not-installed", reason="")))
        self.assertTrue(self.mutated(lambda r: r["host"].update(note="/home/someone/checkout")))
        self.assertTrue(self.mutated(lambda r: r["host"].update(note="/tmp/gaie-act-x/state")))
        credential = {"api" + "_key": "v" * 16}  # built at run time: a synthetic value, not a credential
        self.assertTrue(self.mutated(lambda r: r["host"].update(credential)))
        self.assertTrue(self.mutated(lambda r: r.update(schema="gaie.activation-receipt/0")))
        self.assertTrue(self.mutated(lambda r: r["host"].pop("cpu_count")))
        self.assertEqual(gen.validate([]), ["the receipt is not a JSON object"])

    def test_redactor_removes_host_paths_and_scratch_folders(self):
        with tempfile.TemporaryDirectory(prefix="gaie-t-") as folder:
            redact = gen.Redactor((folder, "<scratch>"))
            text = redact.text(f"{folder}/state and /home/someone/x and {ROOT}/hub.py and /opt/tools/bin/node")
            self.assertEqual(text, "<scratch>/state and <host-path> and <hub>/hub.py and <host-path>")
            self.assertEqual(redact.tree({"a": [f"{folder}/x"]}), {"a": ["<scratch>/x"]})
            self.assertEqual(redact.text("tests/fixtures/upgrade/taskapp and 6/6 passed"),
                             "tests/fixtures/upgrade/taskapp and 6/6 passed")


class ToolTableTests(unittest.TestCase):
    def test_no_tools_mode_reports_every_tool_not_installed_without_looking(self):
        with tempfile.TemporaryDirectory(prefix="gaie-t-") as folder:
            scratch = pathlib.Path(folder)
            rows = gen.tool_rows(scratch / "missing" / "activation", True, scratch)
            self.assertEqual({row["status"] for row in rows}, {"not-installed"})
            self.assertTrue(all(row["probed"] is False and row["exit"] is None and row["reason"] for row in rows))
            headroom = gen.headroom_row(scratch / "missing" / "python", True, scratch)
            self.assertEqual((headroom["status"], headroom["probed"]), ("not-installed", False))
            self.assertEqual(sorted(path.name for path in scratch.iterdir()), [])

    def test_full_mode_never_installs_a_missing_tool(self):
        with tempfile.TemporaryDirectory(prefix="gaie-t-") as folder:
            scratch = pathlib.Path(folder)
            tools = scratch / "tools" / "activation"
            tools.mkdir(parents=True)
            rows = gen.tool_rows(tools, False, scratch)
            self.assertEqual({row["status"] for row in rows}, {"not-installed"})
            self.assertTrue(all(row["probed"] is True and row["reason"] for row in rows))
            self.assertEqual(list(tools.iterdir()), [], "nothing was installed")
            headroom = gen.headroom_row(scratch / "tools" / "headroom-venv" / "bin" / "python", False, scratch)
            self.assertEqual(headroom["status"], "not-installed")

    def test_lock_comparisons_report_drift(self):
        pins = gen.lock_pins("alpha==1.0 \\\n    --hash=sha256:" + "a" * 64 + "\nBeta_Two==2.0\n")
        self.assertEqual(pins, {"alpha": "1.0", "beta-two": "2.0"})
        with tempfile.TemporaryDirectory(prefix="gaie-t-") as folder:
            home = pathlib.Path(folder)
            tool = {"lock": "activation/locks/chrome-devtools-mcp/package-lock.json", "package": "chrome-devtools-mcp"}
            version, check = gen.compare_npm(tool, home)
            self.assertIsNone(version)
            self.assertIn("error", check)
            lock = json.loads((ROOT / tool["lock"]).read_text())
            (home / "node_modules" / "chrome-devtools-mcp").mkdir(parents=True)
            (home / "node_modules" / ".package-lock.json").write_text(json.dumps(lock))
            (home / "node_modules" / "chrome-devtools-mcp" / "package.json").write_text(json.dumps({"version": "1.13.0"}))
            self.assertEqual(gen.compare_npm(tool, home)[1]["matches_lock"], True)
            entry = lock["packages"]["node_modules/chrome-devtools-mcp"]
            entry["integrity"] = "sha512-other"
            (home / "node_modules" / ".package-lock.json").write_text(json.dumps(lock))
            self.assertEqual(gen.compare_npm(tool, home)[1]["matches_lock"], False)


if __name__ == "__main__":
    unittest.main()
