"""Twenty-layer registry, role registry and source-bound layer verification.

Negative cases run on synthetic trees in temporary directories; no repository file is edited.
Receipts go to temporary private state directories, never to the owner's ~/.gaie.
"""
import copy
import json
import os
import pathlib
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

from engineering_os import adapters, contracts, control, control_plane, layers

ROOT = pathlib.Path(__file__).resolve().parents[1]
NAMES = [
    "Owner, Policy & Governance", "AI Intelligence & Model Routing", "Adaptive Agent Orchestration",
    "Engineering Control Plane", "Universal Integration Intelligence", "Software Engineering",
    "Data & Knowledge Intelligence", "Cinematic, Motion & GPU", "Security & Quality Intelligence",
    "Independent Product Ecosystem", "Cloud & Deployment Intelligence", "Continuous Technology Intelligence",
    "Advanced Engineering Reasoning", "Persistent Engineering Memory", "Requirements & Specification Intelligence",
    "Autonomous Software Factory", "Self-Healing & Recovery Intelligence", "Advanced Cinematic Intelligence",
    "Engineering Economics & Resource Intelligence", "Independent Engineering Assurance",
]
DEMO_MODULE = "def answer(x):\n    if x < 0:\n        raise ValueError('negative')\n    return x * 2\n"
DEMO_TEST = ("import unittest\nfrom pkgdemo import core\n\n\nclass Demo(unittest.TestCase):\n"
             "    def test_answer(self):\n        self.assertEqual(core.answer(2), 4)\n\n"
             "    def test_negative(self):\n        with self.assertRaises(ValueError):\n            core.answer(-1)\n")
FAILING_TEST = ("import unittest\nfrom pkgdemo import core\n\n\nclass Demo(unittest.TestCase):\n"
                "    def test_answer(self):\n        self.assertEqual(core.answer(2), 5)\n")
DEMO_MJS = ("import test from 'node:test';\nimport assert from 'node:assert/strict';\n"
            "import {double} from '../pkgdemo/core.mjs';\ntest('double', () => assert.equal(double(2), 4));\n")


def real_layers():
    return json.loads((ROOT / "governance/layers.json").read_text(encoding="utf-8"))


def real_roles():
    return json.loads((ROOT / "governance/agent-roles.json").read_text(encoding="utf-8"))


def real_engines():
    return json.loads((ROOT / "governance/engines.json").read_text(encoding="utf-8"))


def demo_record(lid, tests=("tests/test_pkgdemo.py",), interfaces=("pkgdemo.core:answer",), agents=None):
    return {"id": lid, "name": {"en": f"Demo {lid}", "ar": "طبقة تجريبية"}, "responsibilities": ["Double numbers."],
            "interfaces": list(interfaces), "inputs": ["number"], "outputs": ["number"], "depends_on": [],
            "permissions": ["read:repo"], "skills": [], "tools": ["python3"],
            "agents": list(agents or ["twenty-layer-architecture-engineer"]), "tests": list(tests), "scenarios": [],
            "evidence": {"rule": "tests-pass"}}


class Synthetic:
    """A minimal tree with twenty demo layers: L02 lists a failing test, L03 adds an .mjs test."""

    def __init__(self, base):
        self.root = pathlib.Path(base) / "tree"
        self.state = pathlib.Path(base) / "state"
        files = {"pkgdemo/__init__.py": "", "pkgdemo/core.py": DEMO_MODULE,
                 "pkgdemo/core.mjs": "export const double = (x) => x * 2;\n",
                 "tests/test_pkgdemo.py": DEMO_TEST, "tests/test_pkgdemo_fail.py": FAILING_TEST,
                 "tests/test_pkgdemo.mjs": DEMO_MJS}
        for relative, text in files.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        records = [demo_record(lid) for lid in contracts.LAYER_IDS]
        records[1]["tests"] = ["tests/test_pkgdemo_fail.py"]
        records[2]["tests"] = ["tests/test_pkgdemo.py", "tests/test_pkgdemo.mjs"]
        self.write_layers(records)

    def write_layers(self, records):
        (self.root / "governance").mkdir(exist_ok=True)
        (self.root / "governance/layers.json").write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")

    def records(self):
        return json.loads((self.root / "governance/layers.json").read_text(encoding="utf-8"))

    def verify(self, ids, **kwargs):
        return layers.verify(ids, state_dir=self.state, root=self.root, **kwargs)

    def status(self, lid):
        return layers.status([lid], state_dir=self.state, root=self.root)[0]

    def receipt(self, lid):
        return json.loads((self.state / f"{lid}.json").read_text(encoding="utf-8"))


class TempCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="gaie-layers-test-")
        self.addCleanup(self.tmp.cleanup)
        self.base = pathlib.Path(self.tmp.name)


class LayerRegistryTests(TempCase):
    def test_twenty_records_validate_under_the_contract_with_imports(self):
        records = real_layers()
        self.assertEqual(len(contracts.validate_layers(records, check_imports=True)), 20)
        self.assertEqual([r["id"] for r in records], list(contracts.LAYER_IDS))
        self.assertEqual([r["name"]["en"] for r in records], NAMES)
        for record in records:
            self.assertTrue(any("؀" <= ch <= "ۿ" for ch in record["name"]["ar"]), record["id"])
            self.assertTrue(all(dep < record["id"] for dep in record["depends_on"]), record["id"])
            self.assertEqual(record["evidence"], {"rule": "tests-pass"})

    def test_repository_checks_and_fresh_interpreter_imports(self):
        self.assertEqual(layers.validate(), {"layers": 20, "roles": 20, "ok": True})
        for record in layers.load_layers():
            self.assertEqual(layers._exercised(ROOT, record), [], record["id"])

    def test_wave_two_layers_point_at_existing_callables_until_their_modules_land(self):
        by_id = {r["id"]: r for r in real_layers()}
        for lid in ("L15", "L20"):
            for ref in by_id[lid]["interfaces"]:
                self.assertTrue(callable(contracts.resolve(ref)), ref)
        self.assertIn("engineering_os.gaie_router:route", by_id["L15"]["interfaces"])
        self.assertIn("engineering_os.layers:verify", by_id["L20"]["interfaces"])

    def test_missing_test_file_is_refused_before_anything_runs(self):
        tree = Synthetic(self.base)
        records = tree.records()
        records[4]["tests"] = ["tests/test_missing.py"]
        tree.write_layers(records)
        with self.assertRaisesRegex(layers.LayerError, "L05: missing test file tests/test_missing.py"):
            layers.load_layers(tree.root)
        with self.assertRaises(layers.LayerError):
            tree.verify(["L01"])
        self.assertFalse(tree.state.exists())

    def test_unknown_layer_ids_are_refused(self):
        tree = Synthetic(self.base)
        for bad in (["L21"], ["L00"], ["l01"], ["L01", "L99"], [], "L01"):
            with self.assertRaises(layers.LayerError, msg=bad):
                layers.select(tree.records(), bad)
        with self.assertRaisesRegex(layers.LayerError, "unknown layer id"):
            tree.verify(["L21"])
        with self.assertRaisesRegex(layers.LayerError, "unknown layer id"):
            layers.status(["L00"], state_dir=tree.state, root=tree.root)

    def test_unexercised_foreign_or_unresolvable_interfaces_are_refused(self):
        tree = Synthetic(self.base)
        (tree.root / "pkgdemo/core.py").write_text(DEMO_MODULE + "\n\ndef unused():\n    return 0\n", encoding="utf-8")
        cases = [(("pkgdemo.core:answer", "pkgdemo.core:unused"), "no listed Python test names"),
                 (("json:dumps",), "not a module in this tree")]
        for interfaces, message in cases:
            records = tree.records()
            records[0]["interfaces"] = list(interfaces)
            tree.write_layers(records)
            with self.assertRaisesRegex(layers.LayerError, message):
                layers.load_layers(tree.root)
        # named by the test text but absent from the module: only the fresh-interpreter import catches it
        (tree.root / "tests/test_pkgdemo.py").write_text(DEMO_TEST + "# core.missing_fn is planned\n", encoding="utf-8")
        records = tree.records()
        records[0]["interfaces"] = ["pkgdemo.core:answer", "pkgdemo.core:missing_fn"]
        tree.write_layers(records)
        layers.load_layers(tree.root)
        with self.assertRaisesRegex(layers.LayerError, "missing_fn"):
            layers.load_layers(tree.root, check_imports=True)

    def test_unknown_agent_and_contract_violations_are_refused(self):
        tree = Synthetic(self.base)
        original = tree.records()
        for mutate, message in ((lambda r: r[0].update(agents=["rogue-engineer"]), "unknown role"),
                                (lambda r: r[0].update(permissions=["root:everything"]), "unknown permission"),
                                (lambda r: r[0].update(skills=["skills/none/SKILL.md"]), "missing skill"),
                                (lambda r: r.pop(), "exactly L01..L20")):
            records = copy.deepcopy(original)
            mutate(records)
            tree.write_layers(records)
            with self.assertRaisesRegex(layers.LayerError, message):
                layers.load_layers(tree.root)


class VerificationTests(TempCase):
    def test_verified_receipt_is_bound_to_sources_and_tampering_invalidates_it(self):
        tree = Synthetic(self.base)
        report = tree.verify(["L01"])
        self.assertTrue(report["ok"])
        self.assertEqual(report["layers"][0]["status"], "VERIFIED")
        path = tree.state / "L01.json"
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        receipt = tree.receipt("L01")
        for source in ("pkgdemo/__init__.py", "pkgdemo/core.py", "tests/test_pkgdemo.py"):
            self.assertIn(source, receipt["sources"])
        self.assertEqual(receipt["tests"][0]["status"], "passed")
        self.assertEqual((receipt["tests"][0]["ran"], receipt["tests"][0]["passed"]), (2, 2))
        # SEC-12: the receipt states how the tests ran; the governor sandbox where this host has its full tier.
        full = layers.governor.isolation_probe()["tier"] == "full"
        execution = receipt["execution"]
        self.assertEqual((execution["simulated"], execution["model_calls"], execution["environment"]), (False, 0, "scrubbed"))
        self.assertEqual((execution["mode"], execution["sandboxed"]), ("governor-sandbox", True) if full else ("subprocess", False))
        self.assertEqual(receipt["tests"][0]["isolation"]["profile"], "strict" if full else "process-only")
        contracts.validate_receipt(receipt["contract_receipt"])
        self.assertEqual(tree.status("L01")["status"], "VERIFIED")

        source = tree.root / "pkgdemo/core.py"
        original = source.read_bytes()
        source.write_bytes(original + b"# edited\n")
        current = tree.status("L01")
        self.assertEqual(current["status"], "UNVERIFIED")
        self.assertIn("stale", current["reason"])
        self.assertEqual(current["changed"], ["pkgdemo/core.py"])
        source.write_bytes(original)                      # bound to bytes, not to time
        self.assertEqual(tree.status("L01")["status"], "VERIFIED")

        test_file = tree.root / "tests/test_pkgdemo.py"
        test_file.write_text(DEMO_TEST + "\n", encoding="utf-8")
        self.assertEqual(tree.status("L01")["changed"], ["tests/test_pkgdemo.py"])
        test_file.write_text(DEMO_TEST, encoding="utf-8")

        records = tree.records()
        records[0]["responsibilities"] = ["Double numbers, now with a different record."]
        tree.write_layers(records)
        self.assertIn("record changed", tree.status("L01")["reason"])

    def test_failing_test_fails_the_layer(self):
        tree = Synthetic(self.base)
        report = tree.verify(["L02"])
        self.assertFalse(report["ok"])
        self.assertEqual(report["layers"][0]["status"], "FAILED")
        row = tree.receipt("L02")["tests"][0]
        self.assertEqual((row["status"], row["failed"]), ("failed", 1))
        self.assertTrue(row["output_tail"])
        self.assertEqual(tree.status("L02")["status"], "FAILED")

    def test_node_tests_are_skipped_honestly_without_node(self):
        tree = Synthetic(self.base)
        report = tree.verify(["L03"], node=None)
        self.assertEqual(report["layers"][0]["status"], "INCOMPLETE")
        rows = {row["path"]: row for row in tree.receipt("L03")["tests"]}
        self.assertEqual(rows["tests/test_pkgdemo.mjs"]["status"], "skipped")
        self.assertIn("node", rows["tests/test_pkgdemo.mjs"]["reason"])
        self.assertIn("pkgdemo/core.mjs", tree.receipt("L03")["sources"])
        self.assertEqual(tree.status("L03")["status"], "INCOMPLETE")

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_node_tests_run_with_node(self):
        tree = Synthetic(self.base)
        self.assertEqual(tree.verify(["L03"])["layers"][0]["status"], "VERIFIED")
        rows = {row["path"]: row for row in tree.receipt("L03")["tests"]}
        self.assertEqual(rows["tests/test_pkgdemo.mjs"]["status"], "passed")
        (tree.root / "pkgdemo/core.mjs").write_text("export const double = (x) => x * 3;\n", encoding="utf-8")
        self.assertEqual(tree.status("L03")["changed"], ["pkgdemo/core.mjs"])

    def test_a_test_file_runs_once_per_call(self):
        tree = Synthetic(self.base)
        tree.verify(["L04", "L05"])
        self.assertEqual(tree.receipt("L04")["tests"], tree.receipt("L05")["tests"])

    def test_forged_corrupt_or_foreign_receipts_are_unverified(self):
        tree = Synthetic(self.base)
        tree.verify(["L01", "L02"])
        record = tree.records()[0]
        good = tree.receipt("L01")
        self.assertEqual(layers.receipt_status(record, good, root=tree.root)["status"], "VERIFIED")
        failed = tree.receipt("L02")

        edited = copy.deepcopy(failed); edited["status"] = "VERIFIED"
        self.assertIn("digest mismatch", layers.receipt_status(tree.records()[1], edited, root=tree.root)["reason"])

        forged = copy.deepcopy(failed); forged["status"] = "VERIFIED"
        forged["receipt_sha256"] = contracts.sha256({k: v for k, v in forged.items() if k != "receipt_sha256"})
        self.assertIn("without every test passing", layers.receipt_status(tree.records()[1], forged, root=tree.root)["reason"])

        self.assertIn("another kind or layer", layers.receipt_status(tree.records()[1], good, root=tree.root)["reason"])
        extra = copy.deepcopy(good); extra["note"] = "trust me"
        self.assertEqual(layers.receipt_status(record, extra, root=tree.root)["status"], "UNVERIFIED")
        hidden = copy.deepcopy(good); hidden["sources"].pop("pkgdemo/core.py")
        hidden["source_sha256"] = contracts.sha256(hidden["sources"])
        hidden["contract_receipt"]["source_sha256"] = hidden["source_sha256"]
        hidden["receipt_sha256"] = contracts.sha256({k: v for k, v in hidden.items() if k != "receipt_sha256"})
        self.assertIn("does not bind", layers.receipt_status(record, hidden, root=tree.root)["reason"])

        (tree.state / "L01.json").write_text("{not json", encoding="utf-8")
        os.chmod(tree.state / "L01.json", 0o600)
        self.assertIn("unreadable", tree.status("L01")["reason"])
        self.assertEqual(tree.status("L06")["reason"], "no receipt")

    def test_state_directory_inside_git_is_refused(self):
        state = ROOT / ".gaie-layers-test-state"
        with self.assertRaisesRegex(layers.LayerError, "state directory refused"):
            layers.verify(["L13"], state_dir=state)
        self.assertFalse(state.exists())

    def test_real_small_layer_verifies_with_its_imported_sources(self):
        state = self.base / "state"
        report = layers.verify(["L13"], state_dir=state)
        self.assertTrue(report["ok"], report)
        receipt = json.loads((state / "L13.json").read_text(encoding="utf-8"))
        for source in ("engineering_os/__init__.py", "engineering_os/reasoning.py",
                       "engineering_os/orchestration.py", "tests/test_reasoning.py"):
            self.assertIn(source, receipt["sources"])
        self.assertGreater(receipt["tests"][0]["passed"], 10)
        self.assertEqual(layers.status(["L13"], state_dir=state)[0]["status"], "VERIFIED")
        self.assertEqual(layers.status(["L14"], state_dir=state)[0]["status"], "UNVERIFIED")


class RoleTests(unittest.TestCase):
    def setUp(self):
        self.layers = real_layers()
        self.document = real_roles()
        self.engines = real_engines()

    def check(self, document, engines=None):
        """Validate against the layers and the real engine registry unless another registry is given."""
        return layers.validate_roles(document, layers=self.layers, engines=self.engines if engines is None else engines)

    def mutated(self, rid, **changes):
        document = copy.deepcopy(self.document)
        role = next(r for r in document["roles"] if r["id"] == rid)
        for key, value in changes.items():
            if key in {"engines", "paths", "max_side_effect"}:
                role["default_grant"][key] = value
            else:
                role[key] = value
        return document

    def test_owner_roles_validate_and_instantiate_contract_grants(self):
        document = layers.load_roles()
        self.assertEqual(tuple(r["id"] for r in document["roles"]), layers.ROLE_IDS)
        self.assertEqual({r["team"] for r in document["roles"]}, set("ABCDEFGH"))
        for role in document["roles"]:
            grant = layers.instantiate_grant(role, "g-test-0001", "2099-01-01T00:00:00Z")
            self.assertEqual(contracts.validate_grant(grant)["role"], role["id"])
            self.assertNotIn(grant["max_side_effect"], contracts.GATED)
            if role["reviewer"]:
                self.assertLessEqual(contracts.side_effect_rank(grant["max_side_effect"]),
                                     contracts.side_effect_rank("state-write"))
        mine = next(r for r in document["roles"] if r["id"] == "twenty-layer-architecture-engineer")
        self.assertIn("engineering_os/layers.py", mine["owns"])
        self.assertTrue(self.check(self.document))
        registered = {e["id"]: {a: spec["side_effect"] for a, spec in e["actions"].items()} for e in self.engines}
        for role in self.document["roles"]:
            for engine, granted in role["default_grant"]["engines"].items():
                self.assertTrue(set(granted) <= set(registered[engine]), (role["id"], engine))
        self.assertEqual(registered["layers"], {"status": "none", "verify": "state-write"})

    def test_unknown_missing_and_duplicate_roles_are_rejected(self):
        unknown = copy.deepcopy(self.document); unknown["roles"][0]["id"] = "rogue-engineer"
        missing = copy.deepcopy(self.document); missing["roles"].pop()
        duplicate = copy.deepcopy(self.document); duplicate["roles"][1] = copy.deepcopy(duplicate["roles"][0])
        for document, message in ((unknown, "unknown role"), (missing, "exactly the owner's twenty roles"),
                                  (duplicate, "duplicate role ids")):
            with self.assertRaisesRegex(layers.LayerError, message):
                self.check(document)
        bad_layer = copy.deepcopy(self.layers); bad_layer[0]["agents"].append("rogue-engineer")
        with self.assertRaisesRegex(layers.LayerError, "unknown role"):
            layers.check_layers(bad_layer)

    def test_privilege_escalation_in_grant_templates_is_rejected(self):
        cases = [
            (self.mutated("chief-engineering-architect", max_side_effect="production"), "privilege escalation"),
            (self.mutated("chief-engineering-architect", max_side_effect="external-write"), "privilege escalation"),
            (self.mutated("chief-engineering-architect", max_side_effect="network"), "privilege escalation"),
            (self.mutated("independent-assurance-engineer", max_side_effect="workspace-write", paths=["workspace/*"]),
             "reviewer is limited"),
            (self.mutated("twenty-layer-architecture-engineer", max_side_effect="repo-write", paths=["hub.py"]),
             "not owned by the role"),
            (self.mutated("testing-self-healing-engineer", paths=["engineering_os/*"]), "stay under workspace/"),
            (self.mutated("testing-self-healing-engineer", paths=["workspace/../../etc"]), "unsafe path"),
            (self.mutated("testing-self-healing-engineer", paths=[]), "need scoped paths"),
            (self.mutated("chief-engineering-architect", paths=["workspace/*"]), "need scoped paths"),
            (self.mutated("chief-engineering-architect", max_side_effect="root"), "unknown side-effect"),
            (self.mutated("chief-engineering-architect", owns=["../outside"]), "unsafe pattern"),
            # a ceiling above what the granted actions need is refused too (least privilege)
            (self.mutated("master-build-engine-engineer", max_side_effect="state-write"), "over-broad ceiling"),
            # templates may only name registered engines and actions
            (self.mutated("chief-engineering-architect", engines={"inventory": ["scan"]}),
             "unknown engine action inventory.scan"),
            (self.mutated("engineering-reasoning-engineer", engines={"reasoning": ["deploy"]}),
             "unknown engine action reasoning.deploy"),
        ]
        for document, message in cases:
            with self.assertRaisesRegex(layers.LayerError, message):
                self.check(document)

    def test_engine_registry_bounds_every_granted_action(self):
        registry = self.engines
        self.assertTrue(self.check(self.document, engines=registry))
        layers.load_roles()                                       # the on-disk registry is the one checked

        def changed(engine, action, effect):
            mutated = copy.deepcopy(registry)
            next(e for e in mutated if e["id"] == engine)["actions"][action]["side_effect"] = effect
            return mutated

        with self.assertRaisesRegex(layers.LayerError, "reasoning.plan is repo-write above none"):
            self.check(self.document, engines=changed("reasoning", "plan", "repo-write"))
        with self.assertRaisesRegex(layers.LayerError, "privilege escalation"):
            self.check(self.document, engines=changed("master-release", "eligibility", "external-write"))
        with self.assertRaisesRegex(layers.LayerError, "privilege escalation"):
            self.check(self.document, engines=changed("layers", "verify", "production"))
        with self.assertRaisesRegex(layers.LayerError, "over-broad ceiling"):
            self.check(self.document, engines=changed("layers", "verify", "none"))
        with self.assertRaisesRegex(layers.LayerError, "unknown engine action"):
            self.check(self.document, engines=[e for e in registry if e["id"] != "memory"])
        with self.assertRaisesRegex(layers.LayerError, "engines:"):
            self.check(self.document, engines=[{"id": "not a record"}])

    def test_roles_and_layer_agents_must_agree(self):
        document = self.mutated("persistent-memory-engineer", layers=["L07", "L14"])
        with self.assertRaisesRegex(layers.LayerError, "differ from the layers that list it"):
            self.check(document)


class GovernedEngineTests(TempCase):
    """The layers engine (L04) through control_plane.invoke, the real Security Governor and the role templates."""

    def setUp(self):
        super().setUp()
        if control_plane.governor is None:
            self.skipTest("engineering_os.governor is not installed")
        self.ctx = {"state_dir": str(self.base / "state")}
        self.roles = {role["id"]: role for role in layers.load_roles()["roles"]}

    def grant(self, rid):
        return layers.instantiate_grant(self.roles[rid], "g-layers-engine-test", "2099-01-01T00:00:00Z")

    def test_role_templates_verify_and_report_through_the_control_plane(self):
        out = control_plane.invoke("layers", "verify", {"layers": ["L13"]},
                                   grant=self.grant("twenty-layer-architecture-engineer"), ctx=self.ctx)
        contracts.validate_receipt(out["receipt"])
        self.assertEqual(out["receipt"]["side_effect"], "state-write")
        self.assertTrue(out["result"]["ok"], out["result"])
        self.assertTrue((self.base / "state/layers/L13.json").is_file())
        status = control_plane.invoke("layers", "status", {"layers": ["L13", "L14"]},
                                      grant=self.grant("independent-assurance-engineer"), ctx=self.ctx)
        self.assertEqual({row["id"]: row["status"] for row in status["result"]["rows"]},
                         {"L13": "VERIFIED", "L14": "UNVERIFIED"})
        self.assertEqual(status["receipt"]["side_effect"], "none")

    def test_templates_without_verify_are_denied_and_bad_payloads_refused(self):
        for rid in ("testing-self-healing-engineer", "chief-engineering-architect", "master-build-engine-engineer"):
            with self.subTest(role=rid), self.assertRaises(control_plane.governor.GovernorDenied):
                control_plane.invoke("layers", "verify", {}, grant=self.grant(rid), ctx=self.ctx)
        self.assertFalse((self.base / "state/layers").exists())
        for payload in ({"layers": "L13"}, {"layers": ["L21"]}, {"layers": []}, {"unexpected": True}):
            with self.subTest(payload=payload), self.assertRaises(control_plane.EngineFailure):
                control_plane.invoke("layers", "status", payload, grant=self.grant("testing-self-healing-engineer"),
                                     ctx=self.ctx)
        with self.assertRaisesRegex(adapters.AdapterError, "has no action"):
            adapters.layers("delete", {}, {"state_dir": str(self.base / "state")})
        self.assertIs(adapters.layers_health()["ok"], True)
        self.assertFalse((self.base / "state/layers").exists())


class HubCommandTests(TempCase):
    def hub(self, *args):
        return subprocess.run([sys.executable, str(ROOT / "hub.py"), *args], capture_output=True, text=True,
                              cwd=ROOT, timeout=600)

    def test_layers_table_and_json_without_receipts(self):
        state = self.base / "empty"
        table = self.hub("layers", "--state", str(state))
        self.assertEqual(table.returncode, 0, table.stderr)
        for lid, name in zip(contracts.LAYER_IDS, NAMES):
            self.assertRegex(table.stdout, rf"{lid}\s+UNVERIFIED\s+{name}")
        self.assertIn("الضمان الهندسي المستقل", table.stdout)
        rows = json.loads(self.hub("layers", "--state", str(state), "--json").stdout)
        self.assertEqual([r["status"] for r in rows], ["UNVERIFIED"] * 20)
        self.assertFalse(state.exists())

    def test_verify_one_layer_then_report_it(self):
        state = self.base / "state"
        result = self.hub("layers", "--verify", "--layer", "L13", "--state", str(state))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertRegex(result.stdout, r"L13\s+VERIFIED")
        rows = {r["id"]: r for r in json.loads(self.hub("layers", "--state", str(state), "--json").stdout)}
        self.assertEqual(rows["L13"]["status"], "VERIFIED")
        self.assertEqual(rows["L14"]["status"], "UNVERIFIED")
        architecture = layers.architecture(state_dir=state)
        self.assertEqual({r["id"]: r["status"] for r in architecture["layers"]}["L13"], "VERIFIED")

    def test_unknown_layer_exits_with_an_error(self):
        result = self.hub("layers", "--layer", "L21", "--state", str(self.base / "state"))
        self.assertEqual(result.returncode, 2)
        self.assertIn("unknown layer id", json.loads(result.stdout)["error"])

    def test_architecture_reports_twenty_layers_and_keeps_the_twelve(self):
        result = self.hub("architecture")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        legacy = control.architecture()
        self.assertEqual(report["layer_count"], 20)
        self.assertEqual([r["id"] for r in report["layers"]], list(contracts.LAYER_IDS))
        self.assertFalse(report["runtime_dependency_on_hub"])
        for key in ("schema_version", "name", "standard"):
            self.assertEqual(report[key], legacy[key])
        for old, new in zip(legacy["layers"], report["layers"]):
            for key in ("id", "target", "available_source", "missing_source", "operational_proof"):
                self.assertEqual(new[key], old[key], (old["id"], key))
            self.assertEqual(new["legacy_name"], old["name"])
        for row in report["layers"]:
            self.assertTrue(row["target"])
            self.assertEqual(row["evidence_boundary"], layers.EVIDENCE_BOUNDARY[row["id"]])
            self.assertIn(row["status"], layers.STATUSES)


class DocumentationTests(unittest.TestCase):
    def test_architecture_and_layer_spec_cover_all_twenty_layers(self):
        architecture = (ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")
        spec = (ROOT / "docs/specs/gaie-20-layers/LAYERS.md").read_text(encoding="utf-8")
        for record in real_layers():
            lid = record["id"]
            self.assertIn(f"{lid} {record['name']['en']}", architecture)
            self.assertIn(layers.EVIDENCE_BOUNDARY[lid], architecture)
            self.assertIn(f"{lid} {record['name']['en']}", spec)
            self.assertIn(record["name"]["ar"], spec)
            for ref in record["interfaces"] + record["tests"]:
                self.assertIn(ref, spec, (lid, ref))
        for planned in ("engineering_os/requirements.py", "engineering_os/assurance.py"):
            self.assertIn(planned, spec)
        self.assertIn("python3 hub.py layers --verify", architecture)


if __name__ == "__main__":
    unittest.main()
