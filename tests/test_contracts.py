import copy
import unittest

from engineering_os import contracts as c


def layer(lid, deps=()):
    return {"id": lid, "name": {"en": "Layer", "ar": "طبقة"}, "responsibilities": ["Do one thing."],
            "interfaces": ["engineering_os.contracts:canonical"], "inputs": ["request"], "outputs": ["result"],
            "depends_on": list(deps), "permissions": ["read:repo"], "skills": [], "tools": ["python3"],
            "agents": ["chief-engineering-architect"], "tests": ["tests/test_contracts.py"], "scenarios": ["A"],
            "evidence": {"rule": "tests-pass"}}


def engine():
    return {"id": "master-build", "layer": "L16", "title": {"en": "Build", "ar": "البناء"},
            "entrypoint": "engineering_os.contracts:canonical", "health": "engineering_os.contracts:canonical",
            "actions": {"plan": {"side_effect": "none", "permissions": ["read:registry"], "summary": "Plan."}},
            "supersedes": []}


def grant():
    return {"grant_id": "g-test-1", "role": "master-build-engine-engineer", "engines": {"master-build": ["plan"]},
            "paths": ["workspace/demo"], "max_side_effect": "workspace-write", "expires_at": "2099-01-01T00:00:00Z",
            "approvals": []}


class ContractTests(unittest.TestCase):
    def test_layers_positive_twenty_in_order_acyclic(self):
        rows = [layer(lid, deps=[c.LAYER_IDS[i - 1]] if i else []) for i, lid in enumerate(c.LAYER_IDS)]
        self.assertEqual(len(c.validate_layers(rows, check_imports=True)), 20)

    def test_layers_negative(self):
        rows = [layer(lid) for lid in c.LAYER_IDS]
        with self.assertRaises(c.ContractError):
            c.validate_layers(rows[:19])                      # not twenty
        bad = copy.deepcopy(rows); bad[2]["depends_on"] = ["L04"]; bad[3]["depends_on"] = ["L03"]
        with self.assertRaises(c.ContractError):
            c.validate_layers(bad)                            # cycle
        bad = copy.deepcopy(rows); bad[0]["permissions"] = ["root:everything"]
        with self.assertRaises(c.ContractError):
            c.validate_layers(bad)                            # unknown permission
        bad = copy.deepcopy(rows); bad[0]["interfaces"] = ["engineering_os.contracts:does_not_exist"]
        with self.assertRaises(c.ContractError):
            c.validate_layers(bad, check_imports=True)        # interface must resolve
        bad = copy.deepcopy(rows); bad[0]["name"] = {"en": "only english"}
        with self.assertRaises(c.ContractError):
            c.validate_layers(bad)                            # bilingual names

    def test_engine_and_grant(self):
        self.assertTrue(c.validate_engines([engine()], check_imports=True))
        bad = engine(); bad["actions"]["plan"]["side_effect"] = "anything-goes"
        with self.assertRaises(c.ContractError):
            c.validate_engine(bad)
        self.assertTrue(c.validate_grant(grant()))
        g = grant(); g["approvals"] = [{"side_effect": "workspace-write", "engine": "master-build", "action": "plan",
                                        "approved_by": "owner", "token_sha256": "0" * 64}]
        with self.assertRaises(c.ContractError):
            c.validate_grant(g)                               # approvals only for gated classes

    def test_side_effect_order_and_digest(self):
        self.assertLess(c.side_effect_rank("workspace-write"), c.side_effect_rank("production"))
        self.assertEqual(c.sha256({"b": 1, "a": 2}), c.sha256({"a": 2, "b": 1}))
        with self.assertRaises(c.ContractError):
            c.side_effect_rank("root")
        with self.assertRaises(ValueError):
            c.sha256({"x": float("nan")})                     # not JSON: never hashed


def binding(sid="A", test="tests/test_contracts.py", case="ScenarioContractTests"):
    return {"id": sid, "test": test, "case": case}


class ScenarioContractTests(unittest.TestCase):
    """`scenarios` entries: a bare letter (participation, unbound) or a binding to a test case of the layer."""

    def rows(self):
        return [layer(lid) for lid in c.LAYER_IDS]

    def test_bare_letters_and_bindings_validate(self):
        rows = self.rows()
        rows[0]["scenarios"] = ["B", binding("A"), binding("A", case="ScenarioContractTests.test_bare_letters_and_bindings_validate")]
        self.assertEqual(len(c.validate_layers(rows)), 20)
        self.assertEqual(set(c.SCENARIO_TITLES), c.SCENARIOS)

    def test_bad_bindings_are_refused(self):
        cases = [
            (binding("J"), "unknown scenario"),
            ({"id": ["A"], "test": "tests/test_contracts.py", "case": "X"}, "unknown scenario"),
            (binding(test="tests/test_layers.py"), "not one of the layer's Python tests"),
            (binding(test="tests/test_demo.mjs"), "not one of the layer's Python tests"),
            (binding(test=None), "not one of the layer's Python tests"),
            (binding(case="Scenario A"), "Class or Class.test_method"),
            (binding(case="A.b.c"), "Class or Class.test_method"),
            (binding(case=""), "Class or Class.test_method"),
            ({"id": "A", "test": "tests/test_contracts.py"}, "needs exactly"),
            (dict(binding(), proven=True), "needs exactly"),
            (7, "needs exactly"),
            ("a", "unknown scenario"),
        ]
        for entry, message in cases:
            rows = self.rows()
            rows[0]["tests"].append("tests/test_demo.mjs")
            rows[0]["scenarios"] = [entry]
            with self.subTest(entry=entry), self.assertRaisesRegex(c.ContractError, message):
                c.validate_layers(rows)

    def test_duplicates_and_letter_plus_binding_are_refused(self):
        for scenarios, message in (([binding(), binding()], "duplicates"), (["A", "A"], "duplicates"),
                                   (["A", binding("A")], "both as a bare letter and as a binding")):
            rows = self.rows()
            rows[3]["scenarios"] = scenarios
            with self.subTest(scenarios=scenarios), self.assertRaisesRegex(c.ContractError, message):
                c.validate_layers(rows)

    def test_report_never_turns_an_unbound_scenario_into_a_verified_one(self):
        rows = self.rows()
        for row in rows:
            row["scenarios"] = []
        rows[15]["scenarios"] = [binding("A")]
        rows[1]["scenarios"] = ["G"]                          # participation without a binding
        report = c.scenario_report(rows)
        self.assertEqual(sorted(report), sorted(c.SCENARIOS))
        self.assertEqual(report["A"]["status"], "BOUND")
        self.assertEqual(report["A"]["bindings"], [{"layer": "L16", "test": "tests/test_contracts.py",
                                                    "case": "ScenarioContractTests"}])
        self.assertEqual((report["G"]["status"], report["G"]["participating"]), ("UNBOUND", ["L02"]))
        everything_verified = {lid: "VERIFIED" for lid in c.LAYER_IDS}
        verified = c.scenario_report(rows, everything_verified)
        self.assertEqual(verified["A"]["status"], "VERIFIED")
        for letter in sorted(c.SCENARIOS - {"A"}):
            self.assertEqual(verified[letter]["status"], "UNBOUND", letter)

    def test_report_takes_the_weakest_binding_layer(self):
        rows = self.rows()
        for row in rows:
            row["scenarios"] = []
        rows[0]["scenarios"] = [binding("E")]
        rows[8]["scenarios"] = [binding("E")]
        statuses = {lid: "VERIFIED" for lid in c.LAYER_IDS}
        for weaker in ("INCOMPLETE", "UNVERIFIED", "FAILED"):
            with self.subTest(weaker=weaker):
                self.assertEqual(c.scenario_report(rows, dict(statuses, L09=weaker))["E"]["status"], weaker)
        self.assertEqual(c.scenario_report(rows, dict(statuses, L09="FAILED", L01="UNVERIFIED"))["E"]["status"], "FAILED")
        missing = {lid: status for lid, status in statuses.items() if lid != "L09"}
        self.assertEqual(c.scenario_report(rows, missing)["E"]["status"], "UNVERIFIED")
        for bad in ({"L01": "PASSED"}, ["VERIFIED"]):
            with self.subTest(bad=bad), self.assertRaises(c.ContractError):
                c.scenario_report(rows, bad)
        rows[0]["scenarios"] = [binding("Z")]
        with self.assertRaises(c.ContractError):
            c.scenario_report(rows)


if __name__ == "__main__":
    unittest.main()
