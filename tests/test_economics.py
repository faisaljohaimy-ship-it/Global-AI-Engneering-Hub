"""Synthetic ledger tests; no real billing, subscription or provider evidence."""
import copy
import hashlib
import pathlib
import unittest
from unittest import mock

from engineering_os.economics import EconomicsError, measure_runtime, recommend_model, summarize
from engineering_os.orchestration import sha


def ledger():
    pricing = {"input_per_million_usd": "2", "cached_input_per_million_usd": "0.2", "output_per_million_usd": "10"}
    return {
        "schema_version": 1, "project": "synthetic-project",
        "actors": [{"id": "coordinator", "role": "coordinator", "complete": True},
                   {"id": "worker", "role": "worker", "complete": True}],
        "tasks": [{"id": "feature-task", "source_sha256": "a" * 64,
                   "scope": {"feature": "checkout", "mvp": "store", "enterprise": "commerce"},
                   "verification": {"status": "passed", "source_sha256": "a" * 64, "receipt_sha256": "b" * 64}}],
        "usage": [{"id": "request-1", "actor": "coordinator", "task": None, "attempt": 1,
                   "model": "synthetic-model", "tool": "planner", "source": "provider-reported",
                   "receipt_sha256": "c" * 64, "started_at": 0, "ended_at": 8,
                   "input_tokens": 1000, "cached_input_tokens": 200, "output_tokens": 100,
                   "pricing": pricing, "charge": {"amount_usd": "0.01", "receipt_sha256": "d" * 64}},
                  {"id": "request-2", "actor": "worker", "task": "feature-task", "attempt": 1,
                   "model": "synthetic-model", "tool": "compiler", "source": "provider-reported",
                   "receipt_sha256": "e" * 64, "started_at": 2, "ended_at": 10,
                   "input_tokens": 2000, "cached_input_tokens": 500, "output_tokens": 200,
                   "pricing": pricing, "charge": {"amount_usd": "0.02", "receipt_sha256": "f" * 64}}],
        "overheads": [{"id": "review", "task": "feature-task", "category": "human-review",
                       "seconds": 30, "estimate_usd": "2", "charge": {"amount_usd": "1", "receipt_sha256": "1" * 64}}]}


class EconomicsTests(unittest.TestCase):
    def test_measure_runtime_uses_real_timings_and_source_bytes(self):
        request = ledger()
        result = measure_runtime({"schema_version": 1, "operation": "economics",
                                  "request": request, "repeats": 3})
        self.assertEqual(result["request_sha256"], sha(request))
        self.assertEqual(result["output_sha256"], sha(summarize(request)))
        self.assertEqual(result["provider_calls"], 0)
        self.assertIsNone(result["tokens"])
        self.assertIsNone(result["charged_usd"])
        for metric in ("wall", "thread_cpu"):
            timings = result[metric]
            self.assertEqual(len(timings["samples_ns"]), 3)
            self.assertTrue(all(value > 0 for value in timings["samples_ns"]))
            self.assertEqual(timings["p50_ns"], sorted(timings["samples_ns"])[1])
            self.assertEqual(timings["p95_ns"], max(timings["samples_ns"]))
        root = pathlib.Path(__file__).resolve().parents[1]
        for path, expected in result["source_sha256"].items():
            self.assertEqual(hashlib.sha256((root / path).read_bytes()).hexdigest(), expected)
        self.assertEqual(result.pop("receipt_sha256"), sha(result))

    def test_runtime_measurement_rejects_non_allowlisted_and_unbounded_work(self):
        envelope = {"schema_version": 1, "operation": "economics", "request": ledger(),
                    "repeats": 3}
        for change in ({"repeats": 21}, {"repeats": True}, {"operation": "shell"},
                       {"request": {"data": "a" * (256 * 1024)}}, {"argv": ["run"]}):
            with self.subTest(change=list(change)), self.assertRaises(EconomicsError):
                measure_runtime({**envelope, **change})
    def test_counts_coordinator_and_workers_without_doublecounting_cache(self):
        result = summarize(ledger())
        self.assertTrue(result["accounting_complete"])
        self.assertEqual(result["summary"]["input_tokens"], 3000)
        self.assertEqual(result["summary"]["cached_input_tokens"], 700)
        self.assertEqual(result["summary"]["total_tokens"], 3300)
        self.assertEqual(result["summary"]["tokens_per_verified_task"], "3300")
        self.assertEqual(result["by_role"]["coordinator"]["total_tokens"], 1100)
        self.assertEqual(result["by_role"]["worker"]["total_tokens"], 2200)
        self.assertEqual(result["time"]["observed_call_wall_span_seconds"], "10")
        self.assertEqual(result["time"]["worker_call_seconds_sum"], "8")
        self.assertIsNone(result["time"]["full_development_time_seconds"])

    def test_decimal_estimates_do_not_replace_actual_charges(self):
        result = summarize(ledger())
        self.assertEqual(result["summary"]["estimated_usd"], "2.00774")
        self.assertEqual(result["summary"]["charged_usd"], "1.03")
        self.assertIsNone(result["subscription_allowance"])
        self.assertEqual(result["overheads_by_category"]["human-review"]["overhead_seconds"], "30")

    def test_scope_costs_are_direct_and_coordinator_is_explicitly_unallocated(self):
        result = summarize(ledger())
        for kind, scope in (("feature", "checkout"), ("mvp", "store"), ("enterprise", "commerce")):
            self.assertEqual(result["by_scope"][kind][scope]["total_tokens"], 2200)
            self.assertEqual(result["unallocated_by_scope"][kind]["total_tokens"], 1100)
            self.assertEqual(result["by_scope"][kind][scope]["estimated_usd"], "2.0051")
        self.assertIn("not additive", " ".join(result["notes"]))

    def test_unknown_rates_and_invoices_remain_unknown_with_known_subtotal(self):
        value = ledger()
        value["usage"][0]["pricing"] = None
        value["usage"][1]["charge"] = None
        result = summarize(value)
        self.assertIsNone(result["summary"]["estimated_usd"])
        self.assertIsNone(result["summary"]["charged_usd"])
        self.assertEqual(result["summary"]["estimated_usd_known"], "2.0051")
        self.assertEqual(result["summary"]["charged_usd_known"], "1.01")
        self.assertEqual(result["summary"]["estimated_usd_missing_items"], 1)
        self.assertEqual(result["summary"]["charged_usd_missing_items"], 1)

    def test_missing_or_unfinished_actor_disables_complete_efficiency_metric(self):
        for mutation in ("missing", "unfinished"):
            value = ledger()
            if mutation == "missing":
                value["actors"].append({"id": "absent-worker", "role": "worker", "complete": True})
            else:
                value["actors"][1]["complete"] = False
            result = summarize(value)
            self.assertFalse(result["accounting_complete"])
            self.assertIsNone(result["summary"]["tokens_per_verified_task"])
            self.assertEqual(result["summary"]["observed_tokens_per_verified_task"], "3300")
            self.assertIsNone(result["summary"]["estimated_usd"])
            self.assertIsNone(result["summary"]["charged_usd"])
            self.assertEqual(result["summary"]["observed_estimated_usd"], "2.00774")

    def test_proxy_counts_are_explicit_estimates(self):
        value = ledger()
        value["usage"][1]["source"] = "proxy"
        result = summarize(value)
        self.assertEqual(result["token_basis"], "proxy-present")
        self.assertIsNone(result["summary"]["tokens_per_verified_task"])

    def test_retries_and_failed_work_stay_in_whole_project_numerator(self):
        value = ledger()
        failed = copy.deepcopy(value["tasks"][0])
        failed.update(id="failed-task", verification=None)
        value["tasks"].append(failed)
        retry = copy.deepcopy(value["usage"][1])
        retry.update(id="request-3", task="failed-task", attempt=2, receipt_sha256="2" * 64,
                     started_at=11, ended_at=12, charge=None)
        value["usage"].append(retry)
        result = summarize(value)
        self.assertEqual(result["summary"]["verified_task_count"], 1)
        self.assertEqual(result["summary"]["task_count"], 2)
        self.assertEqual(result["summary"]["tokens_per_verified_task"], "5500")
        value["tasks"][0]["verification"] = None
        self.assertIsNone(summarize(value)["summary"]["tokens_per_verified_task"])

    def test_source_bound_verification_and_duplicate_billing_fail_closed(self):
        for mutation in ("changed-source", "duplicate-id", "duplicate-receipt", "duplicate-charge"):
            value = ledger()
            if mutation == "changed-source":
                value["tasks"][0]["source_sha256"] = "3" * 64
            elif mutation == "duplicate-id":
                value["usage"][1]["id"] = value["usage"][0]["id"]
            elif mutation == "duplicate-receipt":
                value["usage"][1]["receipt_sha256"] = value["usage"][0]["receipt_sha256"]
            else:
                value["overheads"][0]["charge"]["receipt_sha256"] = value["usage"][0]["charge"]["receipt_sha256"]
            with self.subTest(mutation=mutation), self.assertRaises(EconomicsError):
                summarize(value)

    def test_duplicate_completed_task_cannot_inflate_verified_denominator(self):
        value = ledger()
        duplicate = copy.deepcopy(value["tasks"][0])
        duplicate["id"] = "aliased-task"
        value["tasks"].append(duplicate)
        with self.assertRaises(EconomicsError):
            summarize(value)

    def test_invalid_numbers_timestamps_roles_and_references_are_rejected(self):
        mutations = [lambda v: v["usage"][0].update(input_tokens=True),
                     lambda v: v["usage"][0].update(cached_input_tokens=1001),
                     lambda v: v["usage"][0].update(output_tokens=-1),
                     lambda v: v["usage"][0].update(ended_at=-1),
                     lambda v: v["usage"][0].update(ended_at=float("nan")),
                     lambda v: v["usage"][0].update(task="nonexistent"),
                     lambda v: v["usage"][0].update(actor="nonexistent"),
                     lambda v: v["actors"][0].update(role="worker"),
                     lambda v: v["actors"][0].update(complete=1),
                     lambda v: v["usage"][0]["pricing"].update(input_per_million_usd="Infinity"),
                     lambda v: v["usage"][0]["charge"].update(amount_usd="-1"),
                     lambda v: v["usage"][0].update(attempt=0)]
        for mutate in mutations:
            value = ledger()
            mutate(value)
            with self.subTest(mutate=mutate), self.assertRaises(EconomicsError):
                summarize(value)

    def test_no_network_no_mutation_deterministic_and_input_bounded(self):
        value = ledger()
        before = copy.deepcopy(value)
        with mock.patch("socket.socket", side_effect=AssertionError("offline only")):
            one, two = summarize(value), summarize(value)
        self.assertEqual(one, two)
        self.assertEqual(value, before)
        self.assertEqual(one["provider_calls"], 0)
        value["usage"] = [{}] * 10001
        with self.assertRaises(EconomicsError):
            summarize(value)

    def test_unknown_fields_cannot_carry_prompts_or_customer_data(self):
        value = ledger()
        value["usage"][0]["prompt"] = "synthetic-sensitive-content"
        with self.assertRaises(EconomicsError):
            summarize(value)
        value = ledger()
        value["project"] = "sk-" + "a" * 32
        with self.assertRaises(EconomicsError):
            summarize(value)

    def test_model_recommendation_uses_existing_router_and_does_not_invoke(self):
        with mock.patch("engineering_os.economics.select_model", return_value={"decision": "blocked", "provider_calls": 0}) as selector:
            result = recommend_model({"schema_version": 1}, {"task": "coding"}, None, environ={}, now=123)
        selector.assert_called_once_with({"schema_version": 1}, {"task": "coding"}, None, environ={}, now=123)
        self.assertEqual(result["decision"], "blocked")


if __name__ == "__main__":
    unittest.main()
