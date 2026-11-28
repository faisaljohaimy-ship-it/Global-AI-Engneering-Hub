"""Synthetic ledger tests; no real billing, subscription or provider evidence."""
import copy
import pickle
import re
import sys
import unittest
from decimal import Decimal
from unittest import mock

from engineering_os.economics import EconomicsError, recommend_model, summarize
from engineering_os import economics
from engineering_os.economics import (Money, Quota, Seconds, Tokens, UnitError, Unknown, assess, as_json,
                                      engine, estimate_infrastructure, estimate_maintenance, estimate_rework,
                                      estimate_scope, health, is_unknown, measured, per_million_tokens, price,
                                      read_results_table, recommend_concurrency, total, waves_from_evidence)


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


# ---------------------------------------------------------------- L19 extension (GAIE 20 layers)
# Synthetic ledgers, waves and evidence only; the measured inputs are tested in
# tests/test_economics_measured.py.

def one_sentence(test, reason):
    test.assertIsInstance(reason, str)
    test.assertTrue(reason.endswith("."), reason)
    test.assertEqual(len(re.findall(r"[.!?](?:\s|$)", reason)), 1, reason)


class UnitTests(unittest.TestCase):
    def test_same_unit_arithmetic_and_explicit_conversion(self):
        self.assertEqual(Tokens(2) + Tokens(3), Tokens(5))
        self.assertEqual(Money("1.25") + Money("0.75"), Money(2))
        self.assertEqual(Tokens(10) * 3, Tokens(30))
        self.assertEqual(Tokens(10) / Tokens(4), Decimal("2.5"))
        self.assertEqual((Tokens(10) / 4).to_json(), {"unit": "tokens", "value": "2.5"})
        self.assertTrue(Seconds(5) < Seconds(6))
        self.assertEqual(price(Tokens(2_000_000), Money("3")), Money(6))
        self.assertEqual(per_million_tokens(4, Tokens(500_000)), Decimal(8))
        self.assertEqual(total([Tokens(1), 2, Tokens(3)], Tokens), Tokens(6))
        self.assertEqual(Quota(3, "weekly-percent") + Quota(2, "weekly-percent"), Quota(5, "weekly-percent"))

    def test_any_implicit_mixing_raises(self):
        mixes = [lambda: Tokens(1) + Money(1), lambda: Money(1) + Tokens(1), lambda: Tokens(1) + 1,
                 lambda: 1 + Tokens(1), lambda: Money(1) - Quota(1, "weekly-percent"),
                 lambda: Quota(1, "weekly-percent") + Quota(1, "five-hour-window"),
                 lambda: Tokens(1) * Tokens(2), lambda: Tokens(1) / Money(1), lambda: Money(5) / Tokens(1),
                 lambda: 3 / Tokens(1), lambda: Tokens(1) < Money(1), lambda: Tokens(1) == 1,
                 lambda: Tokens(1) == Money(1), lambda: Seconds(1) + Tokens(1), lambda: bool(Tokens(1)),
                 lambda: sum([Tokens(1), Tokens(2)]), lambda: Tokens(1) * True,
                 lambda: price(Money(1), Money(1)), lambda: price(Tokens(1), Tokens(1)),
                 lambda: per_million_tokens(1, Money(1)), lambda: measured(Money(1), Tokens),
                 lambda: total([Tokens(1), Money(1)], Tokens), lambda: Unknown("tokens") + Money(1),
                 lambda: Tokens(1) + Unknown("USD")]
        for mix in mixes:
            with self.subTest(mix=mix), self.assertRaises(UnitError):
                mix()
        self.assertTrue(issubclass(UnitError, EconomicsError) and issubclass(UnitError, TypeError))

    def test_constructors_reject_imprecise_or_negative_measurements(self):
        for bad in (lambda: Tokens(1.5), lambda: Tokens(-1), lambda: Tokens(True), lambda: Money(0.1),
                    lambda: Money("-1"), lambda: Money("NaN"), lambda: Money("abc"), lambda: Seconds(-1),
                    lambda: Seconds(float("inf")), lambda: Quota(1, "Bad Name"), lambda: measured(1.5, Tokens)):
            with self.subTest(bad=bad), self.assertRaises(UnitError):
                bad()

    def test_unknown_is_never_zero_and_propagates(self):
        unknown = measured(None, Tokens)
        self.assertTrue(is_unknown(unknown))
        self.assertEqual(unknown.to_json(), "unknown")
        self.assertEqual(measured("unknown", Money), Unknown("USD"))
        self.assertTrue(is_unknown(Tokens(5) + unknown))
        self.assertTrue(is_unknown(total([Tokens(1), None], Tokens)))
        self.assertTrue(is_unknown(Tokens(5) / 0))
        self.assertTrue(is_unknown(Tokens(5) / Tokens(0)))
        self.assertTrue(is_unknown(price(None, Money(1))))
        self.assertTrue(is_unknown(per_million_tokens(None, Tokens(1))))
        self.assertTrue(is_unknown(per_million_tokens(1, Tokens(0))))
        self.assertNotEqual(unknown, Tokens(0))
        for misuse in (lambda: bool(unknown), lambda: unknown < Tokens(1), lambda: Tokens(1) >= unknown):
            with self.assertRaises(UnitError):
                misuse()
        self.assertEqual(as_json({"a": [unknown, Decimal("0.5"), Money("1.10")]}),
                         {"a": ["unknown", "0.5", {"unit": "USD", "value": "1.1"}]})

    def test_quantities_are_immutable_and_copy_safely(self):
        value = Tokens(7)
        with self.assertRaises(AttributeError):
            value.value = 8
        with self.assertRaises(AttributeError):
            Unknown("tokens").unit = "USD"
        self.assertEqual(copy.deepcopy(value), value)
        self.assertEqual(pickle.loads(pickle.dumps(Quota(2, "weekly-percent"))), Quota(2, "weekly-percent"))
        self.assertEqual(copy.deepcopy(Unknown("USD")), Unknown("USD"))
        self.assertEqual(len({Tokens(1), Tokens(1), Money(1)}), 2)


def ledger_v2():
    pricing = {"input_per_million_usd": "2", "cached_input_per_million_usd": "0.2",
               "cache_write_per_million_usd": "2.5", "output_per_million_usd": "10"}
    scope = {"feature": "checkout", "mvp": "store", "enterprise": None}

    def task(identity, digit, verified, defects):
        source = digit * 64
        return {"id": identity, "source_sha256": source, "scope": dict(scope), "defects": defects,
                "verification": None if not verified else
                {"status": "passed", "source_sha256": source, "receipt_sha256": chr(ord(digit) + 1) * 64}}

    def use(identity, actor, task_id, attempt, purpose, receipt, start, end, tokens):
        inp, cached, written, out = tokens
        return {"id": identity, "actor": actor, "task": task_id, "attempt": attempt, "purpose": purpose,
                "model": "synthetic-model", "tool": "tool", "source": "provider-reported",
                "receipt_sha256": receipt * 64, "started_at": start, "ended_at": end, "input_tokens": inp,
                "cached_input_tokens": cached, "cache_write_tokens": written, "output_tokens": out,
                "pricing": dict(pricing), "charge": None}
    return {
        "schema_version": 2, "project": "synthetic-project", "period": {"started_at": 0, "ended_at": 3600},
        "actors": [{"id": "coord", "role": "coordinator", "complete": True},
                   {"id": "w1", "role": "worker", "complete": True},
                   {"id": "rev", "role": "reviewer", "complete": True}],
        "tasks": [task("t1", "1", True, 0), task("t2", "3", True, 1), task("t3", "5", False, None)],
        "usage": [use("u1", "coord", None, 1, "coordination", "a", 0, 10, (1000, 400, 100, 50)),
                  use("u2", "w1", "t1", 1, "work", "b", 0, 20, (2000, 500, 300, 200)),
                  use("u3", "w1", "t2", 1, "work", "c", 20, 30, (2000, 0, 0, 100)),
                  use("u4", "w1", "t2", 2, "work", "d", 30, 40, (1500, 1000, 0, 100)),
                  use("u5", "rev", "t1", 1, "review", "e", 40, 45, (800, 0, 0, 40)),
                  use("u6", "w1", "t2", 1, "rework", "f", 45, 50, (500, 0, 0, 60))],
        "overheads": [{"id": "fix", "task": "t2", "category": "rework", "seconds": 120,
                       "estimate_usd": "1", "charge": None}]}


class LedgerV2Tests(unittest.TestCase):
    def test_every_metric_of_a_complete_schema2_ledger(self):
        result = assess(ledger_v2())
        self.assertEqual(result["kind"], "measured")
        self.assertEqual((result["verified_tasks"], result["tasks"]), (2, 3))
        self.assertEqual(result["tokens_per_verified_task"], {"unit": "tokens", "value": 4175})
        self.assertEqual(result["verified_tasks_per_million_tokens"], "239.520958")
        roles = result["consumption_by_role"]
        self.assertEqual([roles[r]["total"]["value"] for r in ("coordinator", "worker", "reviewer")], [1050, 6460, 840])
        self.assertEqual(roles["coordinator"]["cache_write"], {"unit": "tokens", "value": 100})
        self.assertEqual(roles["reviewer"]["call_seconds"], {"unit": "seconds", "value": 5})
        self.assertEqual(roles["worker"]["share_of_all_tokens"], "0.773653")
        self.assertEqual(result["cache"]["reads"]["value"], 1900)
        self.assertEqual(result["cache"]["writes"]["value"], 400)
        self.assertEqual(result["retries"]["requests"], 1)
        self.assertEqual(result["retries"]["total"]["value"], 1600)
        self.assertEqual(result["retries"]["estimated_cost"], {"unit": "USD", "value": "0.0022"})
        self.assertEqual(result["rework"]["usage"]["total"]["value"], 560)
        self.assertEqual(result["rework"]["usage"]["estimated_cost"]["value"], "0.0016")
        self.assertEqual(result["rework"]["overhead_seconds"]["value"], 120)
        self.assertEqual(result["waste"]["tokens"]["value"], 2160)
        self.assertEqual(result["waste"]["share_of_all_tokens"], "0.258683")
        self.assertEqual(result["defects"]["defect_rate"], "0.5")
        self.assertEqual(result["time"]["development"]["value"], 3600)
        self.assertEqual(result["time"]["observed_call_wall_span"]["value"], 50)
        productivity = result["productivity"]
        self.assertEqual(productivity["verified_per_development_hour"], "2")
        self.assertEqual(productivity["verified_per_call_span_hour_upper_bound"], "144")
        self.assertEqual(productivity["quality_adjusted_per_development_hour"], "0.741317")
        self.assertEqual(result["money"]["estimated"], {"unit": "USD", "value": "1.01788"})
        self.assertEqual(result["money"]["charged"], "unknown")
        self.assertEqual(result["subscription_quota"], "unknown")
        self.assertEqual(result["provider_calls"], 0)

    def test_quality_adjustment_only_discounts(self):
        value = ledger_v2()
        clean = copy.deepcopy(value)
        clean["tasks"][1]["defects"] = 0
        clean["usage"] = [row for row in clean["usage"] if row["attempt"] == 1 and row["purpose"] != "rework"]
        better = assess(clean)["productivity"]
        self.assertEqual(better["quality_adjusted_per_development_hour"], better["verified_per_development_hour"])
        worse = assess(value)["productivity"]
        self.assertLess(Decimal(worse["quality_adjusted_per_development_hour"]),
                        Decimal(worse["verified_per_development_hour"]))

    def test_missing_measurements_are_unknown_never_zero(self):
        value = ledger_v2()
        value["period"] = None
        value["usage"][1]["cache_write_tokens"] = None
        value["tasks"][0]["defects"] = None
        result = assess(value)
        self.assertEqual(result["time"]["development"], "unknown")
        self.assertEqual(result["productivity"]["verified_per_development_hour"], "unknown")
        self.assertEqual(result["productivity"]["quality_adjusted_per_development_hour"], "unknown")
        self.assertEqual(result["defects"]["defect_rate"], "unknown")
        self.assertEqual(result["cache"]["writes"], "unknown")
        self.assertEqual(result["money"]["estimated"], "unknown")
        self.assertNotEqual(result["productivity"]["verified_per_call_span_hour_upper_bound"], "unknown")
        raw = summarize(value)
        self.assertIsNone(raw["summary"]["cache_write_tokens"])
        self.assertEqual(raw["summary"]["cache_write_tokens_known"], 100)

    def test_incomplete_or_proxy_accounting_keeps_exact_metrics_unknown(self):
        value = ledger_v2()
        value["actors"][2]["complete"] = False
        result = assess(value)
        self.assertEqual(result["kind"], "partial")
        self.assertEqual(result["tokens_per_verified_task"], "unknown")
        self.assertEqual(result["observed_tokens_per_verified_task"]["value"], 4175)
        value = ledger_v2()
        value["usage"][0]["source"] = "proxy"
        self.assertEqual(assess(value)["verified_tasks_per_million_tokens"], "unknown")

    def test_schema1_ledgers_report_what_they_cannot_record_as_unknown(self):
        result = assess(ledger())
        self.assertEqual(result["kind"], "measured")
        self.assertEqual(result["tokens_per_verified_task"]["value"], 3300)
        self.assertEqual(result["consumption_by_role"]["reviewer"]["total"], "unknown")
        self.assertEqual(result["rework"]["usage"]["total"], "unknown")
        self.assertEqual(result["waste"]["share_of_all_tokens"], "unknown")
        self.assertEqual(result["cache"]["writes"], "unknown")
        self.assertEqual(result["productivity"]["quality_adjusted_per_development_hour"], "unknown")
        self.assertEqual(result["retries"]["requests"], 0)
        self.assertEqual(result["money"]["charged"], {"unit": "USD", "value": "1.03"})

    def test_schema2_rejects_malformed_records(self):
        mutations = [lambda v: v["usage"][0].update(purpose="shopping"),
                     lambda v: v["usage"][0].update(cache_write_tokens=601),
                     lambda v: v["usage"][0].update(cache_write_tokens=-1),
                     lambda v: v.update(period={"started_at": 10, "ended_at": 5}),
                     lambda v: v.update(period={"started_at": 0}),
                     lambda v: v["tasks"][0].update(defects=-1),
                     lambda v: v["tasks"][0].update(defects=True),
                     lambda v: v["usage"][0]["pricing"].pop("cache_write_per_million_usd"),
                     lambda v: v["usage"][0].pop("purpose"),
                     lambda v: v.pop("period"),
                     lambda v: v["actors"][2].update(role="auditor")]
        for mutate in mutations:
            value = ledger_v2()
            mutate(value)
            with self.subTest(mutate=mutate), self.assertRaises(EconomicsError):
                summarize(value)
        value = ledger()
        value["actors"].append({"id": "rev", "role": "reviewer", "complete": True})
        with self.assertRaises(EconomicsError):
            summarize(value)
        value = ledger()
        value["schema_version"] = 3
        with self.assertRaises(EconomicsError):
            assess(value)


def wave(agents=4, seconds=60, verified=4, tokens=400_000, conflicts=0, failures=0, **more):
    return {"agents": agents, "duration_seconds": seconds, "tasks_verified": verified, "tokens": tokens,
            "conflicts": conflicts, "failures": failures, **more}


LIMITS = {"start": 4, "max_agents": 64, "max_batch": 8}


class RecommenderTests(unittest.TestCase):
    def test_starts_from_next_wave_without_history(self):
        result = recommend_concurrency([], LIMITS)
        self.assertEqual((result["agents"], result["batch"], result["rule"]), (4, 1, "start"))
        one_sentence(self, result["reason"])

    def test_grows_only_when_verified_throughput_per_token_improves(self):
        improved = recommend_concurrency([wave(), wave(agents=8, verified=8, tokens=600_000)], LIMITS)
        self.assertEqual((improved["agents"], improved["rule"]), (16, "grow-efficiency-improved"))
        self.assertEqual(improved["last_wave"]["verified_tasks_per_million_tokens"], "13.333333")
        self.assertIn("improved from 10.00 to 13.33", improved["reason"])
        worse = recommend_concurrency([wave(), wave(agents=8, verified=8, tokens=1_000_000)], LIMITS)
        self.assertEqual((worse["agents"], worse["rule"]), (8, "hold-efficiency-not-improved"))
        self.assertEqual(worse["next_wave_base"]["agents"], 16)
        equal = recommend_concurrency([wave(), wave(agents=8, verified=8, tokens=800_000)], LIMITS)
        self.assertEqual(equal["agents"], 8)
        for result in (improved, worse, equal):
            one_sentence(self, result["reason"])

    def test_one_wave_cannot_prove_an_improvement(self):
        result = recommend_concurrency([wave()], LIMITS)
        self.assertEqual(result["next_wave_base"]["agents"], 8)
        self.assertEqual((result["agents"], result["rule"]), (4, "hold-efficiency-not-improved"))
        self.assertIn("no earlier wave", result["reason"])

    def test_minimum_efficiency_gain_is_respected(self):
        waves = [wave(), wave(agents=8, verified=8, tokens=760_000)]  # 10.00 -> 10.53 per million tokens
        self.assertEqual(recommend_concurrency(waves, LIMITS)["agents"], 16)
        strict = dict(LIMITS, min_efficiency_gain="0.1")
        self.assertEqual(recommend_concurrency(waves, strict)["agents"], 8)

    def test_shrinks_on_conflicts_even_when_efficiency_improves(self):
        result = recommend_concurrency([wave(), wave(agents=8, verified=8, tokens=600_000, conflicts=2)], LIMITS)
        self.assertEqual((result["agents"], result["batch"], result["rule"]), (4, 1, "conflict-shrink"))
        self.assertTrue(result["reason"].startswith("2 conflicts"))
        single = recommend_concurrency([wave(agents=1, verified=1, conflicts=1)], LIMITS)
        self.assertEqual(single["agents"], 1)
        self.assertIn("1 conflict in", single["reason"])
        one_sentence(self, result["reason"])

    def test_limit_errors_stop_and_budgets_cap(self):
        stop = recommend_concurrency([wave(), wave(agents=8, verified=8, tokens=600_000, limit_errors=3)], LIMITS)
        self.assertEqual((stop["agents"], stop["stop"], stop["rule"]), (0, True, "limit-stop"))
        capped = recommend_concurrency([wave(), wave(agents=8, verified=8, tokens=600_000)],
                                       dict(LIMITS, tokens_left=Tokens(900_000)))
        self.assertEqual(capped["agents"], 12)
        tasks = recommend_concurrency([wave(), wave(agents=8, verified=8, tokens=1_000_000)], dict(LIMITS, tasks_left=5))
        self.assertEqual(tasks["agents"], 5)
        self.assertIn("only 5 tasks are left", tasks["reason"])
        ceiling = recommend_concurrency([wave(agents=20, verified=20, tokens=1_000_000, seconds=15),
                                         wave(agents=25, verified=25, tokens=1_200_000, seconds=33,
                                              peak_concurrent_agents=20)], dict(LIMITS, max_agents=20))
        self.assertEqual((ceiling["agents"], ceiling["batch"]), (20, 2))
        self.assertTrue(ceiling["rule"].endswith("+max-agents-cap"))
        for result in (stop, capped, tasks, ceiling):
            one_sentence(self, result["reason"])

    def test_inherited_next_wave_rules_still_apply(self):
        halved = recommend_concurrency([wave(agents=10, verified=5, failures=5)], LIMITS)
        self.assertEqual(halved["agents"], 5)
        peak = recommend_concurrency([wave(agents=10, verified=10, peak_concurrent_agents=6)], LIMITS)
        self.assertEqual(peak["agents"], 6)
        batch = recommend_concurrency([wave(agents=8, verified=8), wave(agents=8, verified=8)], LIMITS)
        self.assertEqual((batch["agents"], batch["batch"]), (8, 2))

    def test_unknown_inputs_are_listed_and_never_used_as_zero(self):
        result = recommend_concurrency([wave(), wave(agents=8, verified=8, tokens=None)], LIMITS)
        self.assertEqual(result["agents"], 8)
        self.assertIn("tokens", result["unknown_inputs"])
        self.assertEqual(result["last_wave"]["verified_tasks_per_million_tokens"], "unknown")
        open_conflicts = recommend_concurrency([wave(), wave(agents=8, verified=8, tokens=600_000, conflicts=None)], LIMITS)
        self.assertEqual(open_conflicts["agents"], 16)
        self.assertIn("conflicts", open_conflicts["unknown_inputs"])
        no_time = recommend_concurrency([wave(seconds=None)], LIMITS)
        self.assertEqual(no_time["last_wave"]["tasks_per_minute"], "unknown")

    def test_growth_property_over_a_grid(self):
        for tokens in (400_000, 600_000, 800_000, 1_000_000, None):
            for conflicts in (0, 1, None):
                for errors in (0, 1):
                    for seconds in (30, 60, 120):
                        first = wave()
                        last = wave(agents=8, verified=8, tokens=tokens, conflicts=conflicts,
                                    limit_errors=errors, seconds=seconds)
                        result = recommend_concurrency([first, last], LIMITS)
                        one_sentence(self, result["reason"])
                        if result["agents"] > 8:
                            self.assertIsNotNone(tokens)
                            self.assertLess(tokens, 800_000)
                            self.assertNotEqual(conflicts, 1)
                            self.assertEqual(errors, 0)
                        if conflicts == 1 or errors:
                            self.assertLess(result["agents"], 8)

    def test_units_and_fields_are_checked(self):
        for bad in (lambda: recommend_concurrency([wave(tokens=Money(5))], LIMITS),
                    lambda: recommend_concurrency([wave(tokens=1.5)], LIMITS),
                    lambda: recommend_concurrency([wave(seconds=Tokens(5))], LIMITS),
                    lambda: recommend_concurrency([wave()], dict(LIMITS, tokens_left=Money(1)))):
            with self.assertRaises(UnitError):
                bad()
        for bad_wave, limits in ((wave(agents=0), LIMITS), (wave(prompt="x"), LIMITS), ({"agents": 1}, LIMITS),
                                 (wave(conflicts=-1), LIMITS), (wave(verified=True), LIMITS),
                                 (wave(), {"max_agents": 3}), (wave(), dict(LIMITS, extra=1)),
                                 (wave(), dict(LIMITS, min_efficiency_gain="-1"))):
            with self.subTest(bad_wave=bad_wave, limits=limits), self.assertRaises(EconomicsError):
                recommend_concurrency([bad_wave], limits)
        with self.assertRaises(EconomicsError):
            recommend_concurrency("waves", LIMITS)

    def test_deterministic_offline_and_restores_import_path(self):
        waves = [wave(), wave(agents=8, verified=8, tokens=600_000)]
        before_path, before_waves = list(sys.path), copy.deepcopy(waves)
        with mock.patch("socket.socket", side_effect=AssertionError("offline only")):
            one, two = recommend_concurrency(waves, LIMITS), recommend_concurrency(waves, LIMITS)
        self.assertEqual(one, two)
        self.assertEqual(sys.path, before_path)
        self.assertEqual(waves, before_waves)

    def test_waves_from_evidence_documents(self):
        stages = {"stages": [{"label": "p", "kind": "probe", "actual_agents": 2},
                             {"label": "a", "kind": "task", "actual_agents": 4, "tasks": 8, "verified_tasks": 7,
                              "wall_seconds": 30.0, "peak_concurrent_agents": 4, "agents_with_limit_error": 0,
                              "agent_tokens": {"input_total": 900, "output": 100},
                              "orchestrator_tokens": {"input_total": 50, "output": 5}},
                             {"label": "k", "kind": "task", "skipped": "cap reached"}]}
        self.assertEqual(waves_from_evidence(stages, "synthetic.json"), [
            {"label": "a", "source": "synthetic.json", "agents": 4, "batch": 2, "peak_concurrent_agents": 4,
             "duration_seconds": 30.0, "tokens": 1055, "tasks_verified": 7, "failures": 1, "conflicts": None,
             "limit_errors": 0}])
        team = {"totals": {"agents_started": 3, "ran_at_once": 3, "wall_seconds": 10.0, "input_tokens": 10,
                           "output_tokens": 2, "agents_that_met_a_limit": 0},
                "lanes": [{"state": "joined"}, {"state": "rejected: it changed paths outside its lane"},
                          {"state": "not joined: its own tests fail here"}]}
        [result] = waves_from_evidence(team, "team.json")
        self.assertEqual((result["tasks_verified"], result["conflicts"], result["failures"], result["tokens"]), (1, 1, 1, 12))
        team["lanes"].append({"state": "something new"})
        self.assertIsNone(waves_from_evidence(team, "team.json")[0]["conflicts"])
        with self.assertRaises(EconomicsError):
            waves_from_evidence({"nothing": []}, "x.json")


def stage_row(label, size, agents, tasks, verified, cost, input_total, output, seconds, tpm, share):
    return {"label": label, "kind": "task", "size": size, "agent_type": "lean", "model": "synthetic",
            "actual_agents": agents, "tasks": tasks, "verified_tasks": verified, "cost_units": cost,
            "sum_of_agent_seconds": seconds, "tasks_per_minute": tpm,
            "agent_tokens": {"input_total": input_total, "cache_read": 0, "output": output},
            "orchestrator_share_of_all_tokens": share}


EVIDENCE = {"stages": [stage_row("s", "small", 10, 10, 10, 1000, 10000, 100, 60.0, 60.0, 0.2),
                       stage_row("m", "medium", 10, 10, 10, 2000, 20000, 200, 120.0, 30.0, 0.5),
                       stage_row("l", "large", 10, 10, 9, 9000, 90000, 900, 180.0, 10.0, 0.3),
                       stage_row("l-bad", "large", 5, 5, 3, 3000, 30000, 300, 90.0, 5.0, 0.9)]}
RATES = {"input_per_million_usd": "1", "output_per_million_usd": "5"}


class EstimateTests(unittest.TestCase):
    def test_feature_estimate_is_labelled_with_assumptions_and_range(self):
        result = estimate_scope("feature", EVIDENCE, {"rates": RATES})
        self.assertEqual((result["kind"], result["measured"]), ("ESTIMATE", False))
        self.assertIn("not a measurement", result["label"])
        self.assertEqual(result["recipe"], {"small": 3, "medium": 1})
        self.assertEqual(result["tokens"]["input"], {"low": {"unit": "tokens", "value": 3125},
                                                     "high": {"unit": "tokens", "value": 20000}})
        self.assertEqual(result["tokens"]["output"]["low"]["value"], 31)
        self.assertEqual(result["money"], {"low": {"unit": "USD", "value": "0.00328"},
                                           "high": {"unit": "USD", "value": "0.021"}})
        self.assertEqual(result["agent_time"]["low"]["value"], 15)
        self.assertEqual(result["wall_time"]["high"]["value"], "9.6")
        self.assertEqual(result["assumptions"]["coordinator_share_of_all_tokens"], ["0.2", "0.5"])
        self.assertEqual(result["assumptions"]["second_attempt_share"], ["0", "0"])

    def test_mvp_and_enterprise_use_measured_failure_rates_and_stay_ordered(self):
        mvp = estimate_scope("mvp", EVIDENCE)
        self.assertEqual(mvp["recipe"], {"small": 40, "medium": 12, "large": 3})
        self.assertEqual(mvp["assumptions"]["second_attempt_share"], ["0.0055", "0.4"])
        self.assertEqual(mvp["basis"]["configurations"]["large"]["label"], "l")
        self.assertEqual(mvp["money"], {"low": "unknown", "high": "unknown"})
        enterprise = estimate_scope("enterprise", EVIDENCE)
        self.assertEqual(enterprise["recipe"], {"small": 400, "medium": 120, "large": 30})
        for result in (mvp, enterprise):
            for kind in ("input", "output"):
                self.assertLessEqual(result["tokens"][kind]["low"]["value"], result["tokens"][kind]["high"]["value"])
        self.assertGreater(enterprise["tokens"]["input"]["high"]["value"], mvp["tokens"]["input"]["high"]["value"])

    def test_missing_size_makes_the_estimate_unknown(self):
        evidence = {"stages": EVIDENCE["stages"][:2]}
        result = estimate_scope("mvp", evidence, {"rates": RATES})
        self.assertEqual(result["basis"]["sizes_without_a_figure"], ["large"])
        self.assertEqual(result["tokens"]["input"]["low"], "unknown")
        self.assertEqual(result["money"]["high"], "unknown")
        self.assertEqual(result["wall_time"]["low"], "unknown")

    def test_estimate_inputs_are_validated(self):
        for call in (lambda: estimate_scope("galaxy", EVIDENCE), lambda: estimate_scope("feature", []),
                     lambda: estimate_scope("feature", EVIDENCE, {"guess": 1}),
                     lambda: estimate_scope("feature", EVIDENCE, {"task_multiplier": ["2", "1"]}),
                     lambda: estimate_scope("feature", EVIDENCE, {"coordinator_share": ["0", "1"]}),
                     lambda: estimate_scope("feature", EVIDENCE, {"rates": {"input_per_million_usd": "1"}}),
                     lambda: estimate_infrastructure({"months": 0, "components": []}),
                     lambda: estimate_infrastructure({"months": 1, "components": [
                         {"name": "db", "monthly_usd_low": "5", "monthly_usd_high": "1"}]}),
                     lambda: estimate_maintenance({"kind": "measurement"}),
                     lambda: estimate_rework(estimate_scope("feature", EVIDENCE), {"rework_share": ["0.5", "0.1"]})):
            with self.subTest(call=call), self.assertRaises(EconomicsError):
                call()
        with self.assertRaises(UnitError):
            estimate_scope("feature", EVIDENCE, {"rates": {"input_per_million_usd": 1.5, "output_per_million_usd": "1"}})

    def test_infrastructure_maintenance_and_rework_models(self):
        infra = estimate_infrastructure({"months": 12, "components": [
            {"name": "db", "monthly_usd_low": "10", "monthly_usd_high": "25"},
            {"name": "cdn", "monthly_usd_low": 0, "monthly_usd_high": "5.5"}]})
        self.assertEqual(infra["money"], {"low": {"unit": "USD", "value": "120"}, "high": {"unit": "USD", "value": "366"}})
        self.assertEqual(infra["kind"], "ESTIMATE")
        unknown = estimate_infrastructure({"months": 1, "components": [
            {"name": "db", "monthly_usd_low": None, "monthly_usd_high": None}]})
        self.assertEqual(unknown["money"]["high"], "unknown")
        self.assertEqual(unknown["components_with_unknown_cost"], ["db"])
        build = estimate_scope("feature", EVIDENCE, {"rates": RATES})
        upkeep = estimate_maintenance(build, {"share_per_year": ["0.1", "0.2"], "years": 2})
        self.assertEqual(upkeep["tokens"]["low"]["value"], round((3125 + 31) * 0.2))
        self.assertEqual(upkeep["money"]["high"]["value"], "0.0084")
        rework = estimate_rework(build, measured_waste_share="0.25")
        self.assertEqual(rework["assumptions"]["rework_share"], ["0.25", "0.25"])
        self.assertEqual(rework["tokens"]["high"]["value"], 5050)
        self.assertEqual(estimate_rework(estimate_scope("mvp", EVIDENCE))["assumptions"]["rework_share"], ["0.0055", "0.4"])
        self.assertEqual(estimate_maintenance(estimate_scope("mvp", EVIDENCE))["money"]["low"], "unknown")


class ContractTests(unittest.TestCase):
    def test_engine_dispatches_and_refuses_unknown_actions(self):
        self.assertEqual(engine("summarize", {"ledger": ledger()}), summarize(ledger()))
        self.assertEqual(engine("assess", {"ledger": ledger_v2()}), assess(ledger_v2()))
        self.assertEqual(engine("recommend-concurrency", {"waves": [], "limits": LIMITS})["agents"], 4)
        self.assertEqual(engine("estimate-infrastructure", {"assumptions": {"months": 1, "components": [
            {"name": "db", "monthly_usd_low": "1", "monthly_usd_high": "2"}]}})["money"]["low"]["value"], "1")
        for action, payload, ctx in (("deploy", {}, None), ("assess", [], None), ("assess", {}, "ctx")):
            with self.assertRaises(EconomicsError):
                engine(action, payload, ctx)
        self.assertEqual(set(economics.ACTIONS), {"summarize", "assess", "recommend-concurrency", "estimate-scope",
                                                 "estimate-infrastructure", "estimate-maintenance", "estimate-rework",
                                                 "context-footprint", "measured-baseline"})

    def test_health_is_side_effect_free(self):
        path, modules = list(sys.path), set(sys.modules)
        self.assertEqual(health()["ok"], True)
        self.assertEqual(sys.path, path)
        self.assertEqual(set(sys.modules) - modules, set())
        with mock.patch.dict(economics._SWARM, {"adaptive": ("swarm/phase3/missing.py", "next_wave")}):
            self.assertFalse(health()["ok"])

    def test_results_table_parser(self):
        rows = read_results_table("| Stage | Verified | Tasks/min | Input tokens |\n|---|---|---|---|\n"
                                  "| c1 | 1/1 | 7.77 | 63,754 |\n")
        self.assertEqual(rows, [{"Stage": "c1", "Verified": {"verified": 1, "of": 1}, "Tasks/min": 7.77,
                                 "Input tokens": 63754}])
        with self.assertRaises(EconomicsError):
            read_results_table("no table")
        with self.assertRaises(EconomicsError):
            read_results_table("| a | b |\n|---|---|\n| 1 |\n")

if __name__ == "__main__":
    unittest.main()
