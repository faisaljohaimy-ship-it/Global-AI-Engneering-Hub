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


if __name__ == "__main__":
    unittest.main()
