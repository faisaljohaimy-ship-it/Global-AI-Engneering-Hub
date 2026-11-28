"""Tests for swarm/phase3/schema.py: a sound document passes, each broken rule is reported once."""
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "swarm" / "phase3"))
import schema  # noqa: E402

STAGE = {"label": "t1", "kind": "task", "actual_agents": 4, "agents_with_limit_error": 0,
         "agent_tokens": {"input_uncached": 2, "cache_write": 10, "cache_read": 20, "input_total": 32, "output": 8, "total": 40},
         "wall_seconds": 5.0, "model": "haiku", "cost_units": 100, "swk_calls": 3, "refused_calls": 0, "foreign_calls": 0,
         "tasks": 4, "verified_tasks": 3, "verified_success_rate": 75.0, "security_findings": 0, "peak_concurrent_agents": 3}
PROBE = {"label": "p1", "kind": "probe", "actual_agents": 1, "agents_with_limit_error": 0,
         "agent_tokens": dict(STAGE["agent_tokens"]), "wall_seconds": 1, "model": "sonnet", "cost_units": 1, "swk_calls": 1,
         "refused_calls": 1, "foreign_calls": 0, "guard_enforced": True, "allowed_command_ran": True}


def doc(*stages):
    return {"about": "x", "plan_sha256": "ab", "caps": {}, "figures": {}, "stages": list(stages)}


class SchemaTest(unittest.TestCase):
    def broken(self, change, stage=STAGE):
        s = copy.deepcopy(stage)
        change(s)
        return schema.validate(doc(s))

    def test_sound(self):
        self.assertEqual(schema.validate(doc(STAGE, PROBE, {"label": "s", "skipped": "why"})), [])

    def test_top_key(self):
        d = doc(STAGE)
        del d["caps"]
        self.assertEqual(len(schema.validate(d)), 1)

    def test_kinds(self):
        self.assertEqual(len(self.broken(lambda s: s.update(kind="x"))), 1)
        self.assertEqual(len(self.broken(lambda s: s.update(extra=1), {"label": "s", "skipped": "w"})), 1)
        self.assertEqual(len(self.broken(lambda s: s.pop("guard_enforced"), PROBE)), 1)
        self.assertEqual(len(self.broken(lambda s: s.update(tasks="4"))), 1)

    def test_arithmetic(self):
        self.assertEqual(len(self.broken(lambda s: s["agent_tokens"].update(input_total=31, total=39))), 1)
        self.assertEqual(len(self.broken(lambda s: s["agent_tokens"].update(total=41))), 1)
        self.assertEqual(len(self.broken(lambda s: s.update(verified_tasks=5, verified_success_rate=125.0))), 1)
        self.assertEqual(len(self.broken(lambda s: s.update(peak_concurrent_agents=5))), 1)
        self.assertEqual(len(self.broken(lambda s: s.update(verified_success_rate=70.0))), 1)

    def test_text(self):
        self.assertEqual(len(self.broken(lambda s: s.update(label="/home/a"))), 1)
        self.assertEqual(len(self.broken(lambda s: s.update(label="session_0abc"))), 1)
        self.assertEqual(len(self.broken(lambda s: s.update(model="claude-sonnet-4-5"))), 1)

    def test_preflight(self):
        data = json.loads((ROOT / "swarm/phase2/evidence/preflight.json").read_text())
        self.assertEqual(schema.validate(doc(data["stage"])), [])


FIXTURE = ROOT / "tests" / "fixtures" / "p3-stand-in-stages.json"


class ThirdPhaseTest(unittest.TestCase):
    def fixture(self):
        return json.loads(FIXTURE.read_text())

    def once(self, change):
        d = self.fixture()
        change(d)
        found = schema.validate(d)
        self.assertEqual(len(found), 1, found)

    def test_fixture_and_real_documents(self):
        self.assertEqual(schema.validate(self.fixture()), [])
        real = json.loads((ROOT / "swarm/phase2/evidence/stages.json").read_text())
        self.assertEqual(schema.validate(real), [])

    def test_counted_total(self):
        self.once(lambda d: d["counted_before_this_run"].update(total=1))

    def test_ledger_sum(self):
        self.once(lambda d: d["stages"][0]["ledger"].update(tool_calls=4))

    def test_ledger_clean(self):
        def change(d):
            s = d["stages"][0]
            s["ledger"]["calls_outside_the_contract_that_ran"] = {"Bash": 1}
            s["guard_enforced"] = False
        self.once(change)

    def test_gate_passed_needs_held(self):
        self.once(lambda d: d["stages"][0]["security_gate"]["probes"][1].update(held=False))

    def test_refused_probe_ran_outside(self):
        self.once(lambda d: d["stages"][0]["security_gate"]["probes"][0].update(calls_outside_the_contract_that_ran=1))

    def test_task_before_gate(self):
        self.once(lambda d: d["stages"][0]["security_gate"].update(passed=False, probes=[]))

    def test_guard_enforced(self):
        self.once(lambda d: d["stages"][0]["ledger"]["gate"].update(reconciled=False))

    def test_queue(self):
        def change(d):
            d["stages"][1]["queue"] = {"tasks": 4, "handed_in": 2, "given_up": 1, "left_waiting": 0,
                                       "claimed_and_not_handed_in": 1, "agent_calls_per_message": 20}
        change(d := self.fixture())
        self.assertEqual(schema.validate(d), [])
        self.once(lambda d: (change(d), d["stages"][1]["queue"].update(handed_in=3)))
        self.once(lambda d: (change(d), d["stages"][1]["queue"].update(agent_calls_per_message=21)))

    def test_verified_and_limit(self):
        self.once(lambda d: d["stages"][1].update(verified_tasks=5, verified_success_rate=125.0))
        self.once(lambda d: d["figures"].update(input_tokens_counted=d["caps"]["cumulative_input_tokens"] + 1))


if __name__ == "__main__":
    unittest.main()
