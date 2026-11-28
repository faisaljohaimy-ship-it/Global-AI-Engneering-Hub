"""Acceptance and rejection paths for the SQLite repair profile."""

import hashlib
import itertools
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

from engineering_os import healing_runtime as runtime
from engineering_os.healing import HealingError
from engineering_os.orchestration import sha


def request(settings_json, project="sample"):
    return {
        "schema_version": 1,
        "project": project,
        "settings_json": settings_json,
        "settings_sha256": hashlib.sha256(settings_json.encode()).hexdigest(),
    }


class HealingRuntimeTests(unittest.TestCase):
    def test_each_option_changes_observed_sqlite_behavior_and_restores_it(self):
        keys = tuple(runtime.OPTIONS)
        for toggles in itertools.product((False, True), repeat=len(keys)):
            with self.subTest(toggles=toggles):
                settings = dict(zip(keys, toggles))
                # Preserve the exact original formatting and newline during rollback.
                given = request(json.dumps(settings, indent=2) + "\r\n")
                receipt = runtime.repair_sqlite(given)
                failing_options = sorted(key for key in keys if not settings[key])
                self.assertEqual(receipt["changed_settings"], failing_options)
                for option, test in runtime.OPTIONS.items():
                    self.assertIs(receipt["before"][test], settings[option])
                    self.assertIs(receipt["after"][test], True)
                self.assertTrue(receipt["after"]["valid_write_persists"])
                self.assertTrue(receipt["after"]["distinct_streams_preserved"])
                self.assertEqual(receipt["before"], receipt["rollback"])
                self.assertEqual(receipt["rollback_sha256"], given["settings_sha256"])
                self.assertTrue(receipt["rollback_verified"])
                if failing_options:
                    self.assertEqual(receipt["status"], "repair-verified")
                    self.assertEqual(json.loads(receipt["candidate_json"]), dict.fromkeys(keys, True))
                    self.assertEqual(receipt["candidate_sha256"],
                                     hashlib.sha256(receipt["candidate_json"].encode()).hexdigest())
                else:
                    self.assertEqual(receipt["status"], "healthy")
                    self.assertIsNone(receipt["candidate_json"])
                    self.assertEqual(receipt["candidate_sha256"], given["settings_sha256"])
                self.assertTrue(receipt["runtime_tested"])
                self.assertFalse(receipt["untrusted_code_executed"])
                self.assertFalse(receipt["deployment_allowed"])

    def test_receipt_replays_and_rejects_tampering_even_when_rehashed(self):
        given = request('{"foreign_keys":true,"atomic_batches":false,"deduplicate":true}')
        report = runtime.repair_sqlite(given)
        self.assertEqual(runtime.verify_sqlite_repair(given, report), report)
        with self.assertRaises(HealingError):
            runtime.verify_sqlite_repair({**given, "project": "different"}, report)
        tampered = {**report, "deployment_allowed": True}
        with self.assertRaises(HealingError):
            runtime.verify_sqlite_repair(given, tampered)
        del tampered["receipt_sha256"]
        tampered["receipt_sha256"] = sha(tampered)
        with self.assertRaises(HealingError):
            runtime.verify_sqlite_repair(given, tampered)

    def test_candidate_cannot_be_returned_after_regression_or_rollback_mismatch(self):
        given = request('{"foreign_keys":false,"atomic_batches":true,"deduplicate":true}')
        probe = runtime._probe
        for stage in ("candidate", "rollback"):
            def simulate_regression(root, current_stage):
                actual = probe(root, current_stage)
                if current_stage == stage:
                    actual["valid_write_persists"] = False
                return actual

            with self.subTest(stage=stage), patch.object(runtime, "_probe", simulate_regression):
                report = runtime.repair_sqlite(given)
                self.assertEqual(report["status"], "blocked")
                self.assertIsNone(report["candidate_json"])

    def test_rejects_unsupported_and_changed_input_before_allocating_workspace(self):
        good = request('{"foreign_keys":false,"atomic_batches":true,"deduplicate":true}')
        bad = [
            {**good, "settings_sha256": "0" * 64},
            {**good, "schema_version": True},
            {**good, "command": "extra"},
            request('{"foreign_keys":false,"foreign_keys":true,"atomic_batches":true,"deduplicate":true}'),
            request('{"foreign_keys":0,"atomic_batches":true,"deduplicate":true}'),
            request('{"foreign_keys":false,"atomic_batches":true}'),
            request('{"foreign_keys":false,"atomic_batches":true,"deduplicate":true,"extra":null}'),
            request("[" * 2_000 + "]" * 2_000),
        ]
        with patch.object(runtime.tempfile, "TemporaryDirectory") as temporary:
            for given in bad:
                with self.subTest(case=bad.index(given)), self.assertRaises(HealingError):
                    runtime.repair_sqlite(given)
            temporary.assert_not_called()

    def test_scratch_configuration_and_database_are_deleted(self):
        given = request('{"foreign_keys":true,"atomic_batches":false,"deduplicate":true}')
        create = tempfile.TemporaryDirectory
        allocated = []

        def allocate(**kwargs):
            result = create(**kwargs)
            allocated.append(pathlib.Path(result.name))
            self.assertEqual(allocated[-1].stat().st_mode & 0o777, 0o700)
            return result

        with patch.object(runtime.tempfile, "TemporaryDirectory", allocate):
            receipt = runtime.repair_sqlite(given)
        self.assertEqual(receipt["status"], "repair-verified")
        self.assertEqual(len(allocated), 1)
        self.assertFalse(allocated[0].exists())
