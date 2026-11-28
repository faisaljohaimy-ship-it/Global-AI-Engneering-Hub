"""Unified engineering memory (layer L14): one engine, facades, isolation and Scenario D.

Every repository, record, receipt and secret-shaped sample here is synthetic. No model,
provider or network is called; "process 2" is a real new interpreter (subprocess).
"""
import datetime
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

from engineering_os import contracts, gaie_memory, memory
from engineering_os.memory import (IntegrityError, IsolationError, MemoryError, MemoryStore, MissingMemory, SecretRefused,
                                   failure_signature)
from engineering_os.orchestration import CoordinationError, _atomic_write, sha

ROOT = pathlib.Path(__file__).resolve().parents[1]
NOW = datetime.datetime(2026, 1, 2, 3, 4, 5, tzinfo=datetime.timezone.utc)
CART = '''"""Cart aggregate. BODY_MARKER_DOCSTRING"""


class Cart:
    """Holds line items in integer cents."""

    def __init__(self):
        self.items = []

    def add_item(self, sku: str, cents: int, quantity: int = 1) -> None:
        self.items.append((sku, cents * quantity))  # BODY_MARKER_STATEMENT

    def total(self) -> int:
        return sum(cents for _, cents in self.items)
'''
PRICING = '''from .cart import Cart


def apply_discount(cart: Cart, percent: int) -> int:
    """Discount in whole percent. BODY_MARKER_DOCSTRING"""
    def clamp(value):
        return max(0, value)
    return clamp(cart.total() * (100 - percent) // 100)


async def refresh_rates(source: str = "fixture") -> dict:
    return {}
'''
REPO = {"shopcart/__init__.py": '"""Synthetic shop package (simulated)."""\n', "shopcart/cart.py": CART, "shopcart/pricing.py": PRICING}
SECRETS = ("gh" + "p_" + "a" * 36, "sk-" + "ant-" + "b" * 30, "AKIA" + "C" * 16, "-----BEGIN " + "PRIVATE KEY-----",
           "xox" + "b-" + "1" * 12, "pass" + "word: hunter2hunter2", "Bearer " + "d" * 24, "postgres://u:" + "pw12345678" + "@db/x",
           "SYNTHETIC_PRIVATE" + "_MARKER", "[pri" + "vate] client roadmap", "CONFI" + "DENTIAL pricing", "gaie:" + "private note")


def line_of(text, needle):
    return next(number for number, line in enumerate(text.splitlines(), 1) if needle in line)


class Base(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.tmp = pathlib.Path(temporary.name)
        self.state = self.tmp / "state"
        self.private = self.tmp / "private"
        self.private.mkdir(mode=0o700)
        self.repo = self.tmp / "repo"
        for relative, text in REPO.items():
            (self.repo / relative).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / relative).write_text(text)

    def store(self, project="shop"):
        return MemoryStore.for_project(self.state, project)

    @staticmethod
    def record(project="shop", **changes):
        value = {"project": project, "kind": "decision", "title": "Use integer cents", "summary": "Money is stored as integer cents.",
                 "tags": ["money"], "symbols": [], "links": [], "provenance": {"engine": "codex", "source_sha256": "a" * 64}}
        value.update(changes)
        return value

    def receipt(self, identifier, paths, status="passed", name="receipt.json"):
        value = {"schema_version": 1, "status": status, "solution_sha256": identifier,
                 "source_sha256": {path: hashlib.sha256((self.repo / path).read_bytes()).hexdigest() for path in paths}}
        path = self.private / name
        _atomic_write(path, value)
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    def disk_bytes(self, root=None):
        return b"".join(path.read_bytes() for path in sorted(pathlib.Path(root or self.tmp).rglob("*"))
                        if path.is_file() and not path.is_symlink())


class EngineFormatTests(Base):
    def test_state_is_a_header_plus_one_canonical_line_per_record(self):
        store = self.store()
        for title in ("Use integer cents", "Queue background jobs", "Pin dependency versions"):
            store.put(self.record(title=title))
        lines = store.path.read_bytes().splitlines()
        self.assertEqual(len(lines), 4)
        header = json.loads(lines[0])
        self.assertEqual((header["format"], header["schema_version"], header["records"], header["project"]),
                         ("gaie-engineering-memory", 2, 3, "shop"))
        self.assertEqual(header["state_sha256"], store.snapshot()["sha256"])
        self.assertEqual(os.stat(store.path).st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(store.directory).st_mode & 0o777, 0o700)
        self.assertEqual(os.stat(self.state).st_mode & 0o777, 0o700)

    def test_edited_removed_reordered_or_truncated_lines_are_refused(self):
        store = self.store()
        for title in ("Use integer cents", "Queue background jobs", "Pin dependency versions"):
            store.put(self.record(title=title))
        original = store.path.read_bytes()
        lines = original.splitlines()
        state = store.snapshot()
        first = next(iter(state["records"]))
        state["records"][first]["record"]["summary"] = "tampered summary"
        rehashed = dict(state, sha256=sha({key: value for key, value in state.items() if key != "sha256"}))
        header = json.loads(lines[0]) | {"state_sha256": rehashed["sha256"]}
        forged = [memory.canonical(header)] + [memory.canonical({"type": "record", "id": key, "row": row})
                                               for key, row in sorted(rehashed["records"].items(), key=lambda item: item[1]["seq"])]
        for damaged in ([lines[0], lines[2], lines[3]], [lines[0], lines[2], lines[1], lines[3]], lines[1:], lines[:3],
                        [lines[0].replace(b'"revision":3', b'"revision":4')] + lines[1:], [lines[0], lines[1] + b" "] + lines[2:],
                        forged):
            store.path.write_bytes(b"\n".join(damaged) + b"\n")
            with self.subTest(damaged=len(damaged)), self.assertRaises(IntegrityError):
                store.snapshot()
        store.path.write_bytes(original[:-1])
        with self.assertRaises(IntegrityError):
            store.snapshot()
        store.path.write_bytes(original)
        self.assertEqual(len(store.entries("shop")), 3)

    def test_schema1_store_and_checkpoint_migrate_with_identities_kept(self):
        legacy = self.tmp / "legacy"
        legacy.mkdir(mode=0o700)
        first = self.record(project="demo")
        first_id = sha({key: value for key, value in first.items() if key != "provenance"})
        second = self.record(project="demo", kind="architecture", title="Service layout", links=[first_id])
        second_id = sha({key: value for key, value in second.items() if key != "provenance"})
        records = {key: {"record": value, "provenances": [value["provenance"]], "verification": None}
                   for key, value in ((second_id, second), (first_id, first))}
        state = {"schema_version": 1, "revision": 2, "records": records}
        state["sha256"] = sha(state)
        _atomic_write(legacy / "memory.json", state)
        store = MemoryStore(legacy)
        self.assertEqual({row["id"] for row in store.entries("demo")}, {first_id, second_id})
        self.assertEqual(store.graph("demo")["edges"], [{"from": second_id, "to": first_id, "relation": "references"}])
        self.assertTrue((legacy / "memory.jsonl").is_file())
        checkpoint = self.private / "v1-checkpoint.json"
        _atomic_write(checkpoint, {"schema_version": 1, "state": state, "state_sha256": sha(state)})
        restored = MemoryStore.for_project(self.state, "demo")
        self.assertEqual(restored.restore(checkpoint)["revision"], 2)
        self.assertEqual(restored.get("demo", second_id)["record"]["links"], [first_id])
        state["revision"] = 1
        state["sha256"] = sha({key: value for key, value in state.items() if key != "sha256"})
        _atomic_write(legacy / "bad.json", state)
        broken = self.tmp / "broken"
        broken.mkdir(mode=0o700)
        _atomic_write(broken / "memory.json", dict(state, sha256="0" * 64))
        with self.assertRaises(IntegrityError):
            MemoryStore(broken)

    def test_read_only_store_refuses_writes_and_never_creates_state(self):
        missing = self.tmp / "missing"
        with self.assertRaises(MissingMemory):
            MemoryStore(missing, read_only=True)
        self.assertFalse(missing.exists())

        store = self.store()
        store.put(self.record())
        reader = MemoryStore(store.directory, project="shop", read_only=True)
        self.assertEqual(len(reader.entries("shop")), 1)
        original = store.path.read_bytes()
        destination = self.private / "never-created.json"
        for change in (lambda: reader.put(self.record(title="Unapproved decision")),
                       lambda: reader.checkpoint(destination),
                       lambda: reader.restore(missing / "checkpoint.json")):
            with self.assertRaisesRegex(MemoryError, "read-only"):
                change()
        self.assertEqual(store.path.read_bytes(), original)
        self.assertFalse(destination.exists())
        self.assertFalse(missing.exists())


class IsolationTests(Base):
    def test_a_project_store_never_reads_or_lists_another_project(self):
        alpha, beta = self.store("alpha"), self.store("beta")
        secret_title = "Beta only roadmap item"
        beta_id = beta.put(self.record("beta", title=secret_title))["id"]
        beta.index_repository("beta", self.repo)
        alpha_id = alpha.put(self.record("alpha"))["id"]
        self.assertNotEqual(alpha.directory, beta.directory)
        self.assertEqual([row["id"] for row in alpha.entries("alpha")], [alpha_id])
        self.assertEqual([hit["id"] for hit in alpha.retrieve("alpha", "roadmap beta")], [])
        self.assertEqual(alpha.where("alpha", "Cart.total"), [])
        self.assertNotIn(secret_title.encode(), alpha.path.read_bytes())
        self.assertEqual(alpha.brief("alpha")["entries"], 1)
        for action in (lambda: alpha.get("alpha", beta_id), lambda: alpha.neighbours("alpha", beta_id),
                       lambda: alpha.put(self.record("alpha", links=[beta_id]))):
            with self.assertRaises(MemoryError):
                action()
        for action in (lambda: alpha.entries("beta"), lambda: alpha.search("beta", "roadmap"), lambda: alpha.retrieve("beta", "roadmap"),
                       lambda: alpha.put(self.record("beta")), lambda: alpha.where("beta", "Cart"), lambda: alpha.brief("beta"),
                       lambda: alpha.index_repository("beta", self.repo), lambda: alpha.graph("beta")):
            with self.assertRaises(IsolationError):
                action()
        self.assertFalse(any(name.startswith("list") for name in dir(alpha)))

    def test_path_checks_refuse_traversal_symlinks_and_planted_state(self):
        beta = self.store("beta")
        beta.put(self.record("beta"))
        for bad in ("../beta", "a/../beta", "Beta", "", "/tmp", ".hidden"):
            with self.subTest(project=bad), self.assertRaises((IsolationError, CoordinationError)):
                MemoryStore.for_project(self.state, bad)
        (self.state / "gamma").symlink_to(self.state / "beta", target_is_directory=True)
        with self.assertRaises(IsolationError):
            MemoryStore.for_project(self.state, "gamma")
        with self.assertRaises(IsolationError):
            MemoryStore.for_project(str(self.state / "beta" / ".."), "alpha")
        alpha = self.store("alpha")
        shutil.copyfile(beta.path, alpha.path)
        with self.assertRaises(IsolationError):
            alpha.snapshot()
        with self.assertRaises(IsolationError):
            self.store("alpha")
        unbound = MemoryStore(self.tmp / "shared")
        unbound.put(self.record("alpha"))
        with self.assertRaises(IsolationError):
            MemoryStore(self.tmp / "shared", project="alpha")
        with self.assertRaises(MissingMemory):
            MemoryStore.for_project(self.state, "delta", create=False)
        self.assertFalse((self.state / "delta").exists())

    def test_checkpoints_cannot_cross_projects(self):
        beta = self.store("beta")
        beta.put(self.record("beta"))
        beta.checkpoint(self.private / "beta.json")
        with self.assertRaises(IsolationError):
            self.store("alpha").restore(self.private / "beta.json")
        shared = MemoryStore(self.tmp / "shared")
        shared.put(self.record("alpha"))
        shared.put(self.record("beta"))
        shared.checkpoint(self.private / "shared.json")
        with self.assertRaises(IsolationError):
            self.store("alpha").restore(self.private / "shared.json")
        only_alpha = MemoryStore(self.tmp / "only-alpha")
        only_alpha.put(self.record("alpha"))
        only_alpha.checkpoint(self.private / "only-alpha.json")
        restored = self.store("alpha").restore(self.private / "only-alpha.json")
        self.assertEqual(restored["project"], "alpha")
        self.assertEqual(self.store("alpha").snapshot()["project"], "alpha")

    def test_facade_projects_are_separate_engine_stores(self):
        env = {"GAIE_HOME": str(self.tmp / "gaie")}
        alpha, beta = gaie_memory.Memory("alpha", env), gaie_memory.Memory("beta", env)
        self.assertEqual(alpha.backend, "engine")
        stored = alpha.add("lesson", "Alpha lesson", "Only alpha may see this")
        beta.add("lesson", "Beta lesson", "Only beta may see this")
        engine = MemoryStore.for_project(self.tmp / "gaie" / "memory", "alpha")
        self.assertEqual([row["id"] for row in engine.entries("alpha")], [stored["id"]])
        self.assertEqual(alpha.path, engine.path)
        self.assertEqual([row["title"] for row in beta.search("lesson")], ["Beta lesson"])
        self.assertNotIn(b"Beta lesson", alpha.path.read_bytes())


class GraphTests(Base):
    def test_typed_edges_neighbours_paths_and_symbol_nodes(self):
        store = self.store()
        store.index_repository("shop", self.repo)
        cents = store.put(self.record(symbols=["Cart.total"]))["id"]
        api = store.put(self.record(kind="architecture", title="Checkout service", summary="Checkout composes cart and pricing.",
                                    relations=[{"relation": "depends-on", "target": cents}]))["id"]
        lone = store.put(self.record(kind="lesson", title="Unrelated lesson", summary="Keep notes short."))["id"]
        view = store.neighbours("shop", cents)
        self.assertEqual([(edge["relation"], edge["node"]["id"]) for edge in view["incoming"]], [("depends-on", api)])
        self.assertEqual([(edge["relation"], edge["node"]["qualname"]) for edge in view["outgoing"]], [("mentions", "Cart.total")])
        self.assertEqual(store.neighbours("shop", cents, direction="out", relation="depends-on")["outgoing"], [])
        module = store.neighbours("shop", "symbol:shopcart/cart.py")
        self.assertIn(("contains", "Cart"), [(edge["relation"], edge["node"]["qualname"]) for edge in module["outgoing"]])
        route = store.graph_path("shop", api, "symbol:shopcart/cart.py#Cart.total")
        self.assertTrue(route["found"])
        self.assertEqual([hop["relation"] for hop in route["hops"]], ["depends-on", "mentions"])
        self.assertEqual(route["hops"][0]["direction"], "forward")
        back = store.graph_path("shop", "symbol:shopcart/cart.py#Cart.total", api)
        self.assertEqual([hop["direction"] for hop in back["hops"]], ["backward", "backward"])
        self.assertFalse(store.graph_path("shop", api, lone)["found"])
        self.assertFalse(store.graph_path("shop", api, "symbol:shopcart/cart.py#Cart.total", max_depth=1)["found"])
        self.assertIn({"from": api, "to": cents, "relation": "depends-on"}, store.graph("shop")["edges"])
        for bad in ({"relation": "owns", "target": cents}, {"relation": "fixes", "target": "f" * 64}, {"relation": "fixes"}):
            with self.subTest(relation=bad), self.assertRaises(MemoryError):
                store.put(self.record(title="Bad edge " + str(len(bad)), relations=[bad]))
        with self.assertRaises(MemoryError):
            store.neighbours("shop", "symbol:missing.py")
        with self.assertRaises(MemoryError):
            store.graph_path("shop", api, cents, max_depth=0)


class AdrTests(Base):
    def test_lifecycle_supersession_and_why(self):
        store = self.store()
        first = store.adr_add("shop", "Use integer cents for money", "Float totals drifted by a cent in reports.",
                              "Store every amount as integer cents.", "Formatting happens only at the UI edge.", now=NOW)
        self.assertEqual((first["adr_id"], first["status"]), ("ADR-0001", "proposed"))
        self.assertEqual(store.adr_status("shop", "ADR-0001", "accepted", now=NOW)["status"], "accepted")
        with self.assertRaises(MemoryError):
            store.adr_status("shop", "ADR-0001", "accepted")
        second = store.adr_add("shop", "Use Decimal for tax", "Tax rules need fractional cents.", "Use decimal.Decimal in pricing.",
                               "Slower arithmetic; explicit rounding.", supersedes="ADR-0001")
        self.assertEqual(store.adr("shop", "ADR-0001")["status"], "accepted")
        store.adr_status("shop", "ADR-0002", "accepted")
        old = store.adr("shop", "ADR-0001")
        self.assertEqual((old["status"], old["superseded_by"]), ("superseded", "ADR-0002"))
        self.assertEqual([step["status"] for step in old["history"]], ["proposed", "accepted", "superseded"])
        self.assertEqual(store.adr("shop", "ADR-0002")["supersedes"], "ADR-0001")
        self.assertIn({"relation": "supersedes", "node": {"id": first["id"], "type": "entry", "kind": "adr",
                                                         "title": "Use integer cents for money"}},
                      store.neighbours("shop", second["id"])["outgoing"])
        for action in (lambda: store.adr_add("shop", "Third", "c", "d", "e", supersedes="ADR-0001"),
                       lambda: store.adr_add("shop", "Third", "c", "d", "e", supersedes="ADR-0099"),
                       lambda: store.adr_add("shop", "Third", "c", "d", "e", status="superseded"),
                       lambda: store.adr_status("shop", "ADR-0002", "superseded"),
                       lambda: store.adr_status("shop", "ADR-0404", "accepted"),
                       lambda: store.put(self.record(kind="adr", attributes={"adr_id": "ADR-0009", "context": "c", "consequences": "e"}))):
            with self.assertRaises(MemoryError):
                action()
        again = store.adr_add("shop", "Use Decimal for tax", "Tax rules need fractional cents.", "Use decimal.Decimal in pricing.",
                              "Slower arithmetic; explicit rounding.", supersedes="ADR-0001")
        self.assertTrue(again["deduplicated"])
        answer = store.why("shop", "why integer cents for money?")
        self.assertEqual([(item["adr_id"], item["status"], item["superseded_by"]) for item in answer["answers"]],
                         [("ADR-0001", "superseded", "ADR-0002"), ("ADR-0002", "accepted", None)])
        self.assertEqual(store.why("shop", "ADR-0001")["answers"][0]["context"], "Float totals drifted by a cent in reports.")
        hits = {hit["id"]: hit for hit in store.retrieve("shop", "integer cents money", kinds=["adr"])}
        self.assertTrue(hits[first["id"]]["superseded"])
        self.assertEqual(store.brief("shop")["adrs"]["superseded"], [{"adr_id": "ADR-0001", "title": "Use integer cents for money"}])

    def test_inconsistent_lifecycle_is_refused_even_when_rehashed(self):
        store = self.store()
        store.adr_add("shop", "Use integer cents", "c", "d", "e", status="accepted")
        state = store.snapshot()
        row = next(iter(state["records"].values()))
        row["lifecycle"]["status"] = "superseded"
        with self.assertRaises(IntegrityError):
            memory._seal(state)
        row["lifecycle"] = None
        with self.assertRaises(IntegrityError):
            memory._seal(state)


class SolutionAndFailureTests(Base):
    def test_registry_marks_unverified_and_binds_receipts_to_source(self):
        store = self.store()
        solution = store.put(self.record(kind="solution", title="Batch cart writes", summary="One write per checkout."))["id"]
        rows = store.solutions("shop")
        self.assertEqual((rows[0]["status"], rows[0]["verified"]), ("unverified", False))
        self.assertTrue(rows[0]["label"].startswith("UNVERIFIED"))
        path, digest = self.receipt(solution, ["shopcart/cart.py"])
        store.verify("shop", solution, self.repo, path, digest)
        self.assertEqual(store.solutions("shop")[0]["status"], "evidence-recorded")
        self.assertEqual(store.solutions("shop", self.repo)[0]["receipt_sha256"], digest)
        self.assertEqual(store.solutions("shop", self.repo)[0]["status"], "source-matches-recorded-test")
        (self.repo / "shopcart/cart.py").write_text(CART + "\n# changed\n")
        stale = store.solutions("shop", self.repo)[0]
        self.assertEqual((stale["status"], stale["verified"]), ("stale", False))
        for paths, status, target in ((["shopcart/cart.py"], "failed", solution), (["shopcart/cart.py"], "passed", "e" * 64)):
            path, digest = self.receipt(target, paths, status=status, name="bad.json")
            with self.assertRaises(MemoryError):
                store.verify("shop", solution, self.repo, path, digest)
        decision = store.put(self.record())["id"]
        path, digest = self.receipt(decision, ["shopcart/cart.py"], name="decision.json")
        with self.assertRaises(MemoryError):
            store.verify("shop", decision, self.repo, path, digest)

    def test_failure_signature_root_cause_fix_and_verified_recovery(self):
        store = self.store()
        signature = "TypeError: unsupported operand type(s) for +: 'int' and 'str' at /srv/app/shopcart/cart.py:14 (0x7f3a2b10)"
        self.assertEqual(failure_signature(signature), "typeerror: unsupported operand type(s) for +: 'int' and 'str' at cart.py:# (<addr>)")
        self.assertEqual(failure_signature(failure_signature(signature)), failure_signature(signature))
        first = store.record_failure("shop", signature, "Cart.total crashed on a string price.",
                                     root_cause="Prices arrived as strings from the CSV import.",
                                     fix="Cast cents to int in Cart.add_item.", symbols=["Cart.add_item"])
        self.assertTrue(first["root_cause"] and first["fix"])
        variant = "TypeError: unsupported operand type(s) for +: 'int' and 'str' at /home/ci/shopcart/cart.py:99 (0x55aa)"
        recalled = store.recall_failure("shop", variant)
        self.assertEqual((recalled[0]["match"], recalled[0]["status"]), ("exact", "unverified-fix"))
        self.assertEqual(recalled[0]["root_causes"][0]["summary"], "Prices arrived as strings from the CSV import.")
        self.assertEqual(store.recall_failure("shop", "TypeError: unsupported operand type(s) for -: 'int' and 'str'")[0]["match"], "similar")
        self.assertEqual(store.recall_failure("shop", "KeyError: 'sku'"), [])
        path, digest = self.receipt(first["fix"], ["shopcart/cart.py"])
        store.verify("shop", first["fix"], self.repo, path, digest)
        self.assertEqual(store.recall_failure("shop", variant, source_root=self.repo)[0]["status"], "verified-fix")
        repeat = store.record_failure("shop", variant, "Seen again in CI.", title=store.get("shop", first["failure"])["record"]["title"],
                                      symbols=["Cart.add_item"])
        self.assertEqual((repeat["failure"], repeat["merged"]), (first["failure"], True))
        self.assertEqual(store.recall_failure("shop", variant)[0]["occurrences"], 2)
        later = store.record_failure("shop", "ZeroDivisionError: division by zero", "Empty cart average.")
        self.assertEqual(store.recall_failure("shop", "ZeroDivisionError: division by zero")[0]["status"], "unresolved")
        store.record_recovery("shop", later["failure"], root_cause="Average over zero items.")
        self.assertEqual(store.recall_failure("shop", "ZeroDivisionError: division by zero")[0]["status"], "root-cause-only")
        with self.assertRaises(MemoryError):
            store.record_recovery("shop", first["root_cause"], fix="not a failure")


class CheckpointTests(Base):
    def test_sealed_checkpoint_round_trip_and_tamper_refusal(self):
        store = self.store()
        store.put(self.record())
        store.task_progress("shop", "checkout", "Checkout", ["design"], ["build"])
        receipt = store.checkpoint(self.private / "one.json")
        self.assertEqual(receipt["checkpoint_sha256"], hashlib.sha256((self.private / "one.json").read_bytes()).hexdigest())
        restored = MemoryStore.for_project(self.tmp / "other-state", "shop")
        self.assertEqual(restored.restore(self.private / "one.json", expected_sha256=receipt["checkpoint_sha256"]), receipt)
        self.assertEqual(restored.snapshot(), store.snapshot())
        with self.assertRaises(MemoryError):
            restored.restore(self.private / "one.json")
        with self.assertRaises(MemoryError):
            store.checkpoint(self.private / "one.json")
        with self.assertRaises(IntegrityError):
            MemoryStore.for_project(self.tmp / "s2", "shop").restore(self.private / "one.json", expected_sha256="0" * 64)
        value = json.loads((self.private / "one.json").read_text())
        key = next(iter(value["state"]["records"]))
        cases = []
        changed = json.loads(json.dumps(value))
        changed["state"]["records"][key]["record"]["summary"] = "tampered"
        cases.append(changed)
        rehashed = json.loads(json.dumps(changed))
        rehashed["state_sha256"] = sha(rehashed["state"])
        cases.append(rehashed)
        sealed = json.loads(json.dumps(changed))
        sealed["state"]["sha256"] = sha({k: v for k, v in sealed["state"].items() if k != "sha256"})
        sealed["state_sha256"] = sha(sealed["state"])
        cases.append(sealed)
        cases.append(dict(value, project="beta"))
        for number, case in enumerate(cases):
            path = self.private / f"tampered-{number}.json"
            _atomic_write(path, case)
            with self.subTest(case=number), self.assertRaises(MemoryError):
                MemoryStore.for_project(self.tmp / f"fresh-{number}", "shop").restore(path)
        git = self.tmp / "checkout"
        (git / ".git").mkdir(parents=True)
        (git / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
        with self.assertRaises(CoordinationError):
            store.checkpoint(git / "memory.json")


class SymbolIndexTests(Base):
    def test_index_modules_classes_functions_signatures_and_lines_without_bodies(self):
        store = self.store()
        (self.repo / "shopcart/broken.py").write_text("def broken(:\n")
        (self.repo / "shopcart/settings.py").write_text('API_TOKEN = "' + "ghp_" + "Q" * 36 + '"\n')
        (self.repo / "shopcart/linked.py").symlink_to(self.repo / "shopcart/cart.py")
        (self.repo / ".venv").mkdir()
        (self.repo / ".venv/hidden.py").write_text("def hidden(): pass\n")
        result = store.index_repository("shop", self.repo, engine="codex")
        self.assertEqual(result["files"], 3)
        self.assertEqual(sorted((row["path"], row["reason"]) for row in result["skipped"]),
                         [("shopcart/broken.py", "syntax-error"), ("shopcart/linked.py", "unsafe-missing-or-invalid"),
                          ("shopcart/settings.py", "credential-shaped-content")])
        total = store.where("shop", "Cart.total")[0]
        self.assertEqual((total["path"], total["module"], total["kind"], total["line"], total["signature"], total["match"]),
                         ("shopcart/cart.py", "shopcart.cart", "method", line_of(CART, "def total"), "def total(self) -> int", "exact"))
        self.assertEqual(store.where("shop", "shopcart.pricing.apply_discount")[0]["signature"],
                         "def apply_discount(cart: Cart, percent: int) -> int")
        self.assertEqual(store.where("shop", "clamp")[0]["qualname"], "apply_discount.clamp")
        self.assertEqual(store.where("shop", "refresh_rates")[0]["kind"], "async-function")
        self.assertEqual(store.where("shop", "add_item")[0]["signature"], "def add_item(self, sku: str, cents: int, quantity: int=1) -> None")
        self.assertEqual(store.where("shop", "shopcart")[0]["kind"], "module")
        self.assertEqual(store.where("shop", "hidden"), [])
        (self.repo / ("gh" + "p_" + "R" * 36 + ".py")).write_text("X = 1\n")
        with self.assertRaises((SecretRefused, CoordinationError)):
            store.index_python("shop", "gh" + "p_" + "R" * 36 + ".py", self.repo, "codex")
        self.assertNotIn(b"p_RRRR", store.path.read_bytes())
        (self.repo / ("gh" + "p_" + "R" * 36 + ".py")).unlink()
        data = store.path.read_bytes()
        for marker in (b"BODY_MARKER", b"Holds line items", b"self.items.append", b"ghp_"):
            self.assertNotIn(marker, data)
        self.assertEqual(store.symbol_status("shop", self.repo), {path: "fresh" for path in REPO})
        (self.repo / "shopcart/cart.py").write_text(CART.replace("def total(self) -> int:", "def total(self) -> float:"))
        (self.repo / "shopcart/pricing.py").unlink()
        self.assertEqual(store.symbol_status("shop", self.repo)["shopcart/cart.py"], "stale")
        self.assertEqual(store.symbol_status("shop", self.repo)["shopcart/pricing.py"], "missing")
        self.assertEqual(store.where("shop", "total", source_root=self.repo)[0]["source_status"], "stale")
        store.index_repository("shop", self.repo, paths=["shopcart/cart.py", "shopcart/pricing.py"])
        self.assertEqual(store.where("shop", "Cart.total")[0]["signature"], "def total(self) -> float")
        self.assertEqual(store.where("shop", "apply_discount"), [])
        self.assertEqual(store.symbol_status("shop", self.repo), {"shopcart/__init__.py": "fresh", "shopcart/cart.py": "fresh"})
        for bad in (lambda: store.index_repository("shop", self.repo, paths=["../x.py"]),
                    lambda: store.index_repository("shop", self.tmp / "missing"),
                    lambda: store.index_repository("shop", self.repo, engine="robot")):
            with self.assertRaises(MemoryError):
                bad()


class RetrievalDedupEvidenceTests(Base):
    def test_ranked_concept_retrieval_over_entries_and_symbols(self):
        store = self.store()
        store.index_repository("shop", self.repo)
        store.put(self.record(title="Use integer cents", summary="Money totals are integer cents.", symbols=["Cart.total"]))
        store.put(self.record(kind="lesson", title="Slow dashboard", summary="Missing index on orders.created_at.", tags=["performance"]))
        store.put(self.record(kind="lesson", title="اعتماد قاعدة البيانات", summary="قرار بنقل الطلبات إلى قاعدة بيانات واحدة", tags=[]))
        hits = store.retrieve("shop", "Cart.total")
        self.assertEqual((hits[0]["type"], hits[0]["qualname"]), ("symbol", "Cart.total"))
        self.assertEqual(hits[1]["title"], "Use integer cents")
        self.assertEqual(store.retrieve("shop", "latency")[0]["title"], "Slow dashboard")
        self.assertEqual(store.retrieve("shop", "أعتماد")[0]["title"], "اعتماد قاعدة البيانات")
        self.assertEqual(store.retrieve("shop", "Cart.total"), hits)
        self.assertEqual([hit["type"] for hit in store.retrieve("shop", "Cart.total", include_symbols=False)], ["entry"])
        self.assertEqual([hit["title"] for hit in store.retrieve("shop", tags=["performance"])], ["Slow dashboard"])
        self.assertEqual([hit["title"] for hit in store.retrieve("shop")][0], "اعتماد قاعدة البيانات")
        self.assertEqual(store.retrieve("shop", "nothing-matches-here"), [])
        with self.assertRaises(MemoryError):
            store.retrieve("shop", "x", kinds=["unknown"])

    def test_content_and_near_duplicate_title_dedup_with_provenance(self):
        store = self.store()
        first = store.put(self.record())
        again = store.put(self.record(provenance={"engine": "claude-code", "source_sha256": "b" * 64}))
        self.assertEqual((again["id"], again["deduplicated"], again["merged"]), (first["id"], True, False))
        near = store.put(self.record(title="  cents: use INTEGER!", summary="Store integer cents everywhere.",
                                     provenance={"engine": "claude-code", "source_sha256": "c" * 64}))
        self.assertEqual((near["id"], near["merged"]), (first["id"], True))
        row = store.get("shop", first["id"])
        self.assertEqual(len(row["provenances"]), 2)
        self.assertEqual(row["merged"][0]["title"], "  cents: use INTEGER!")
        self.assertEqual(row["merged"][0]["provenance"]["source_sha256"], "c" * 64)
        self.assertEqual(store.put(self.record(title="cents: use INTEGER!", summary="x",
                                               provenance={"engine": "claude-code", "source_sha256": "c" * 64}))["id"], first["id"])
        distinct = [store.put(self.record(kind="lesson"))["id"],
                    store.put(self.record(evidence=[{"kind": "unit-tests", "sha256": "d" * 64}]))["id"],
                    store.put(self.record(kind="symbol", title="Use integer cents"))["id"]]
        self.assertEqual(len({first["id"], *distinct}), 4)
        self.assertEqual({hit["id"]: hit for hit in store.retrieve("shop", "integer")}[first["id"]]["merged_variants"], 2)

    def test_source_bound_evidence_goes_stale_or_missing(self):
        store = self.store()
        adr = store.adr_add("shop", "Integer cents in Cart", "Totals drifted.", "Cart keeps integer cents.", "UI formats.",
                            sources=["shopcart/cart.py", "shopcart/pricing.py"], source_root=self.repo, status="accepted")
        self.assertEqual(store.evidence_status("shop", adr["id"])["status"], "unchecked")
        self.assertEqual(store.evidence_status("shop", adr["id"], self.repo)["status"], "fresh")
        (self.repo / "shopcart/pricing.py").write_text(PRICING + "\n")
        status = store.evidence_status("shop", adr["id"], self.repo)
        self.assertEqual(status["status"], "stale")
        self.assertEqual({row["path"]: row["status"] for row in status["files"]}, {"shopcart/cart.py": "fresh", "shopcart/pricing.py": "stale"})
        (self.repo / "shopcart/cart.py").unlink()
        self.assertEqual(store.adr("shop", "ADR-0001", self.repo)["evidence"]["status"], "stale")
        (self.repo / "shopcart/pricing.py").write_text(PRICING)
        self.assertEqual(store.evidence_status("shop", adr["id"], self.repo)["status"], "missing")
        self.assertEqual(store.retrieve("shop", "integer cents", source_root=self.repo)[0]["evidence_status"], "missing")
        self.assertEqual(store.evidence_status("shop", store.put(self.record(title="No sources"))["id"])["status"], "none")
        with self.assertRaises(MemoryError):
            store.adr_add("shop", "x", "c", "d", "e", sources=["shopcart/cart.py"])
        with self.assertRaises(MemoryError):
            store.adr_add("shop", "x", "c", "d", "e", sources=["../outside.py"], source_root=self.repo)


class SecretGuardTests(Base):
    def test_secret_and_private_marked_values_never_reach_disk(self):
        store = self.store()
        store.put(self.record())
        before = store.snapshot()
        for sample in SECRETS:
            attempts = (lambda: store.put(self.record(summary=f"note {sample}")), lambda: store.put(self.record(title=sample[:150])),
                        lambda: store.put(self.record(tags=[sample[:70]])),
                        lambda: store.adr_add("shop", "Decision", f"context {sample}", "d", "e"),
                        lambda: store.task_progress("shop", "t", "Task", [f"done {sample}"], []),
                        lambda: store.record_failure("shop", f"Error {sample}", "s"),
                        lambda: store.record_failure("shop", "Error", "s", fix=f"rotate {sample}"),
                        lambda: store.retrieve("shop", sample[:150]))
            for number, attempt in enumerate(attempts):
                with self.subTest(sample=sample[:12], attempt=number), self.assertRaises((SecretRefused, CoordinationError)):
                    attempt()
        self.assertEqual(store.snapshot(), before)
        disk = self.disk_bytes(self.state)
        for sample in SECRETS:
            self.assertNotIn(sample.encode(), disk)
        for prose in ("Private state stays in a 0700 directory.", "Token-based auth replaced cookies.", "The secret guard is best-effort."):
            store.put(self.record(kind="lesson", title=prose[:40], summary=prose))
        with self.assertRaises(SecretRefused):
            store.put(self.record(summary="gh" + "p_" + "a" * 18 + "\n" + "a" * 18))

    def test_restore_and_import_paths_are_guarded_too(self):
        store = self.store()
        store.put(self.record())
        value = json.loads(json.dumps({"schema_version": 2, "format": "gaie-memory-checkpoint", "project": "shop",
                                       "state": store.snapshot(), "state_sha256": ""}))
        key = next(iter(value["state"]["records"]))
        row = value["state"]["records"].pop(key)
        row["record"]["summary"] = "leaked " + SECRETS[0]
        new_key = sha({k: v for k, v in row["record"].items() if k != "provenance"})
        value["state"]["records"][new_key] = row
        value["state"]["sha256"] = sha({k: v for k, v in value["state"].items() if k != "sha256"})
        value["state_sha256"] = sha(value["state"])
        _atomic_write(self.private / "planted.json", value)
        target = MemoryStore.for_project(self.tmp / "target", "shop")
        with self.assertRaises(SecretRefused):
            target.restore(self.private / "planted.json")
        self.assertNotIn(SECRETS[0].encode(), target.path.read_bytes())
        result = store.import_batch("shop", [{"key": "x", "record": self.record(title="Leak", summary=SECRETS[1]), "refs": [], "now": None},
                                             {"key": "y", "record": self.record(title="Clean import"), "refs": [{"relation": "references", "key": "x"}],
                                              "now": None}])
        self.assertEqual((sorted(result["ids"]), result["refused"]), (["y"], ["x"]))
        self.assertNotIn(SECRETS[1].encode(), store.path.read_bytes())


class FacadeAndVendoringTests(Base):
    def setUp(self):
        super().setUp()
        self.env = {"GAIE_HOME": str(self.tmp / "gaie")}

    def vendored(self, with_engine):
        engine = self.tmp / ("engine-full" if with_engine else "engine-legacy")
        engine.mkdir()
        files = {"engineering_os/gaie_memory.py": "gaie_memory.py", "engineering_os/gaie_router.py": "gaie_router.py",
                 "governance/policies/gaie-routes.json": "gaie-routes.json", "projects/registry.json": "projects.json",
                 "projects/aliases.json": "aliases.json"}
        if with_engine:
            files.update({"engineering_os/memory.py": "memory.py", "engineering_os/orchestration.py": "orchestration.py",
                          "scripts/security_scan.py": "security_scan.py"})
        for source, name in files.items():
            shutil.copyfile(ROOT / source, engine / name)
        return engine / "gaie_memory.py"

    def run_cli(self, script, *args):
        run = subprocess.run([sys.executable, str(script), "--project", "demo", *args], capture_output=True, text=True,
                             cwd=self.tmp, env={**os.environ, **self.env}, timeout=60)
        return run.returncode, json.loads(run.stdout)

    def test_engine_entries_are_visible_through_the_legacy_api(self):
        facade = gaie_memory.Memory("demo", self.env)
        self.assertEqual((facade.entries(), facade.search(), facade.backend), ([], [], "engine"))
        self.assertFalse((self.tmp / "gaie" / "memory" / "demo").exists())
        cause = facade.add("root-cause", "N+1 query", "Loop issued one query per row", now=NOW)["id"]
        fix = facade.add("repair", "Batch the query", "Single joined query", links=[{"relation": "fixes", "target": cause}])["id"]
        self.assertEqual(facade.add("repair", "batch  the QUERY", "Joined query", links=[{"relation": "fixes", "target": cause}])["status"], "merged")
        engine = facade.store()
        adr = engine.adr_add("demo", "Prefer joins", "N+1 hurt latency.", "Join in SQL.", "Bigger queries.", status="accepted")
        self.assertEqual([row["kind"] for row in facade.search(kind="adr")], ["adr"])
        self.assertEqual(facade.related(cause)["incoming"][0]["from"]["id"], fix)
        rows = facade.entries()
        self.assertEqual([row["previous"] for row in rows], [None, cause, fix])
        self.assertEqual(rows[0]["created"], "2026-01-02T03:04:05Z")
        self.assertEqual(facade.call("adr", "ADR-0001")["id"], adr["id"])
        with self.assertRaises(gaie_memory.MemoryError_):
            facade.add("lesson", "note", "value " + SECRETS[8])
        with self.assertRaises(gaie_memory.MemoryError_):
            facade.call("adr_status", "ADR-0001", "accepted")

    def test_legacy_journal_is_verified_and_imported_once(self):
        legacy = gaie_memory.Memory("demo", self.env)
        first = gaie_memory._journal_add(legacy, "root-cause", "Slow query", "Missing index", ["db"], [], [], NOW)
        second = gaie_memory._journal_add(legacy, "repair", "Add index", "Index on created_at", [],
                                          [{"kind": "unit-tests", "sha256": "a" * 64}], [{"relation": "fixes", "target": first["id"]}], NOW)
        self.assertEqual(second["status"], "stored")
        rows = legacy.entries()
        self.assertEqual([row["title"] for row in rows], ["Slow query", "Add index"])
        self.assertEqual(legacy.import_report, {"imported": 2, "refused": 0})
        self.assertEqual(rows[1]["links"][0]["target"], rows[0]["id"])
        self.assertEqual(rows[1]["evidence"], [{"kind": "unit-tests", "sha256": "a" * 64}])
        again = gaie_memory.Memory("demo", self.env)
        self.assertEqual(len(again.entries()), 2)
        self.assertIsNone(again.import_report)
        journal = legacy.journal.read_text()
        legacy.journal.write_text(journal.replace("Missing index", "Missing indexes"))
        with self.assertRaises(gaie_memory.MemoryError_):
            gaie_memory.Memory("demo", self.env).entries()

    def test_vendored_copies_use_the_engine_or_refuse_to_split_memory(self):
        portable = self.vendored(with_engine=False)
        code, result = self.run_cli(portable, "add", "--kind", "lesson", "--title", "t", "--body", "b")
        self.assertEqual((code, result["status"]), (0, "stored"))
        self.assertTrue((self.tmp / "gaie/memory/demo/entries.jsonl").is_file())
        code, result = self.run_cli(portable, "brief")
        self.assertEqual(code, 1)
        self.assertIn("unified engine", result["error"])
        hub = gaie_memory.Memory("demo", self.env)
        self.assertEqual([row["title"] for row in hub.entries()], ["t"])
        code, result = self.run_cli(portable, "search")
        self.assertEqual(code, 1)
        self.assertIn("managed by the unified engine", result["error"])
        full = self.vendored(with_engine=True)
        code, result = self.run_cli(full, "add", "--kind", "lesson", "--title", "second", "--body", "b")
        self.assertEqual((code, result["status"]), (0, "stored"))
        code, result = self.run_cli(full, "brief")
        self.assertEqual((code, result["entries"]), (0, 2))

    def test_cli_resume_commands(self):
        module = ROOT / "engineering_os" / "gaie_memory.py"
        steps = [("adr", "--title", "Queue jobs", "--context", "Requests timed out.", "--decision", "Use a durable queue.",
                  "--consequences", "Operate a broker.", "--status", "accepted"),
                 ("task", "--id", "jobs", "--title", "Background jobs", "--done", "design", "--remaining", "worker",
                  "--remaining", "tests", "--decision", "ADR-0001"),
                 ("failure", "--signature", "TimeoutError: job 42 exceeded 30s", "--summary", "Worker stalled.", "--fix", "Add heartbeat."),
                 ("index", "--root", str(self.repo))]
        for step in steps:
            code, result = self.run_cli(module, *step)
            self.assertEqual(code, 0, result)
        self.assertEqual(self.run_cli(module, "next")[1][0]["next"], "worker")
        self.assertEqual(self.run_cli(module, "where", "Cart.total")[1][0]["line"], line_of(CART, "def total"))
        self.assertEqual(self.run_cli(module, "why", "ADR-0001")[1]["answers"][0]["decision"], "Use a durable queue.")
        self.assertEqual(self.run_cli(module, "recall", "TimeoutError: job 7 exceeded 30s")[1][0]["status"], "unverified-fix")
        self.assertEqual(self.run_cli(module, "solutions")[1][0]["status"], "unverified")
        self.assertEqual(self.run_cli(module, "status", "--root", str(self.repo))[1], {path: "fresh" for path in REPO})
        brief = self.run_cli(module, "brief")[1]
        self.assertEqual((brief["open_tasks"][0]["task_id"], brief["symbol_index"]["files"]), ("jobs", 3))
        code, sealed = self.run_cli(module, "checkpoint", "--to", str(self.private / "cli.json"))
        self.assertEqual(code, 0)
        self.env = {"GAIE_HOME": str(self.tmp / "gaie2")}
        self.assertEqual(self.run_cli(module, "restore", "--from", str(self.private / "cli.json"), "--sha256", "0" * 64)[0], 1)
        code, restored = self.run_cli(module, "restore", "--from", str(self.private / "cli.json"), "--sha256", sealed["checkpoint_sha256"])
        self.assertEqual((code, restored["revision"]), (0, sealed["revision"]))
        self.assertEqual(self.run_cli(module, "next", "--task", "jobs")[1][0]["remaining"], ["worker", "tests"])


class ContractTests(Base):
    def test_engine_record_entrypoint_and_health(self):
        contracts.validate_engine(memory.ENGINE_RECORD, check_imports=True)
        self.assertEqual(memory.ENGINE_RECORD["layer"], "L14")
        for name, spec in memory.ENGINE_RECORD["actions"].items():
            self.assertIn("secrets:none", spec["permissions"], name)
            self.assertEqual(spec["side_effect"] == "none", "write:state" not in spec["permissions"], name)
        listing = sorted(os.listdir(self.tmp))
        self.assertTrue(memory.health()["ok"])
        self.assertEqual(sorted(os.listdir(self.tmp)), listing)
        ctx = {"state_dir": str(self.state), "source_root": str(self.repo)}
        # A read on a store that was never written answers empty and still creates nothing (pr30-authz F2).
        self.assertEqual(memory.invoke("retrieve", {"project": "shop", "query": "cents"}, ctx), {"items": []})
        self.assertFalse(self.state.exists())
        stored = memory.invoke("put", {"project": "shop", "record": self.record()}, ctx)
        self.assertEqual(memory.invoke("retrieve", {"project": "shop", "query": "cents"}, ctx)["items"][0]["id"], stored["id"])
        self.assertEqual(memory.invoke("index", {"project": "shop"}, ctx)["files"], 3)
        self.assertEqual(memory.invoke("where", {"project": "shop", "name": "Cart.total"}, ctx)["items"][0]["source_status"], "fresh")
        memory.invoke("task-progress", {"project": "shop", "task_id": "t1", "title": "Task", "done": [], "remaining": ["a"]}, ctx)
        self.assertEqual(memory.invoke("next-steps", {"project": "shop"}, ctx)["items"][0]["next"], "a")
        sealed = memory.invoke("checkpoint", {"project": "shop", "destination": str(self.private / "c.json")}, ctx)
        other = {"state_dir": str(self.tmp / "other")}
        self.assertEqual(memory.invoke("restore", {"project": "shop", "checkpoint": str(self.private / "c.json"),
                                                   "expected_sha256": sealed["checkpoint_sha256"]}, other), sealed)
        for action, payload, context in (("explode", {"project": "shop"}, ctx), ("put", {"project": "shop"}, ctx),
                                         ("put", {"project": "shop", "record": self.record("beta")}, ctx),
                                         ("retrieve", {"project": "shop", "query": "x", "extra": 1}, ctx),
                                         ("index", {"project": "shop"}, {"state_dir": str(self.state)}),
                                         ("retrieve", {"query": "x"}, ctx), ("retrieve", {"project": "shop"}, {}),
                                         ("retrieve", {"project": "../shop", "query": "x"}, ctx)):
            with self.subTest(action=action, payload=sorted(payload)), self.assertRaises((MemoryError, CoordinationError)):
                memory.invoke(action, payload, context)


PROCESS_TWO = r'''
import json, os, sys
args = json.loads(sys.argv[1])
touched = []

def audit(event, details):
    if event in ("open", "os.listdir", "os.scandir") and details and isinstance(details[0], (str, bytes, os.PathLike)):
        path = os.path.abspath(os.fsdecode(details[0]))
        if any(path == root or path.startswith(root + os.sep) for root in args["forbidden"]):
            touched.append(path)

sys.addaudithook(audit)
from engineering_os.memory import MemoryStore

store = MemoryStore.for_project(args["state"], args["project"])
restored = store.restore(args["checkpoint"], expected_sha256=args["sha256"])
step = store.next_steps(args["project"], "checkout")[0]
where = store.where(args["project"], "Cart.total")
why = store.why(args["project"], "why do we keep money as integer cents?")
brief = store.brief(args["project"])
progress = store.task_progress(args["project"], "checkout", step["title"], step["done"] + [step["next"]], step["remaining"][1:],
                               engine="codex", decisions=["ADR-0001"])
sealed = store.checkpoint(args["next_checkpoint"])
work = list(touched)
try:  # positive control: the hook does see a read attempt under the old repository path
    open(os.path.join(args["forbidden"][0], "shopcart", "cart.py"), "rb")
except OSError:
    pass
print(json.dumps({"restored": restored, "next": step["next"], "where": where, "why": why, "brief_open": brief["open_tasks"],
                  "progress": progress, "sealed": sealed, "touched": work, "control": touched[len(work):], "pid": os.getpid()}))
'''


class ScenarioDTests(Base):
    """Acceptance Scenario D: a new interpreter resumes from a checkpoint without the repository."""

    def test_new_interpreter_resumes_without_reading_the_repository(self):
        project = "synthetic-shop"
        first = MemoryStore.for_project(self.state, project)
        indexed = first.index_repository(project, self.repo)
        self.assertEqual((indexed["files"], indexed["skipped"]), (3, []))
        adr = first.adr_add(project, "Keep money as integer cents", "Float totals drifted by one cent in nightly reports.",
                            "Cart and pricing keep every amount as integer cents.", "Formatting to currency happens only in the UI.",
                            status="accepted", symbols=["Cart.total", "apply_discount"], sources=["shopcart/cart.py"],
                            source_root=self.repo)
        first.task_progress(project, "checkout", "Checkout flow", ["index the repository", "record ADR-0001"],
                            ["apply discounts inside Cart.total", "write checkout tests"], decisions=["ADR-0001"],
                            symbols=["Cart.total"])
        sealed = first.checkpoint(self.private / "session-1.json")
        checkpoint_text = (self.private / "session-1.json").read_text()
        for marker in ("BODY_MARKER", "Holds line items", "return sum("):
            self.assertNotIn(marker, checkpoint_text)
        moved = self.tmp / "repo-moved-away"
        self.repo.rename(moved)
        shutil.rmtree(moved)
        self.assertFalse(self.repo.exists() or moved.exists())
        args = {"state": str(self.tmp / "session-2-state"), "project": project, "checkpoint": str(self.private / "session-1.json"),
                "sha256": sealed["checkpoint_sha256"], "next_checkpoint": str(self.private / "session-2.json"),
                "forbidden": [str(self.repo), str(moved)]}
        run = subprocess.run([sys.executable, "-c", PROCESS_TWO, json.dumps(args)], cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(run.returncode, 0, run.stderr)
        second = json.loads(run.stdout)
        self.assertNotEqual(second["pid"], os.getpid())
        self.assertEqual(second["touched"], [])
        self.assertEqual(second["control"], [str(self.repo / "shopcart" / "cart.py")])
        self.assertEqual(second["restored"], sealed)
        self.assertEqual(second["next"], "apply discounts inside Cart.total")
        self.assertEqual((second["where"][0]["path"], second["where"][0]["line"], second["where"][0]["signature"],
                          second["where"][0]["source_status"]),
                         ("shopcart/cart.py", line_of(CART, "def total"), "def total(self) -> int", "unchecked"))
        answer = second["why"]["answers"][0]
        self.assertEqual((answer["adr_id"], answer["status"], answer["context"]),
                         ("ADR-0001", "accepted", "Float totals drifted by one cent in nightly reports."))
        self.assertEqual(answer["evidence"]["status"], "unchecked")
        self.assertEqual(second["brief_open"][0]["decisions"], [{"adr_id": "ADR-0001", "title": "Keep money as integer cents",
                                                                  "status": "accepted"}])
        self.assertEqual((second["progress"]["version"], second["progress"]["next"]), (2, "write checkout tests"))
        self.assertNotEqual(second["sealed"]["checkpoint_sha256"], sealed["checkpoint_sha256"])
        third = MemoryStore.for_project(self.tmp / "session-3-state", project)
        third.restore(self.private / "session-2.json", expected_sha256=second["sealed"]["checkpoint_sha256"])
        task = third.next_steps(project, "checkout")[0]
        self.assertEqual((task["version"], task["done"][-1], task["remaining"]),
                         (2, "apply discounts inside Cart.total", ["write checkout tests"]))
        self.assertEqual(third.adr(project, "ADR-0001")["id"], adr["id"])
        versions = [hit for hit in third.retrieve(project, "checkout flow", kinds=["task"])]
        self.assertEqual([hit["superseded"] for hit in versions], [False, True])
        engines = {provenance["engine"] for row in third.entries(project) if row["record"]["kind"] == "task"
                   for provenance in row["provenances"]}
        self.assertEqual(engines, {"claude-code", "codex"})


if __name__ == "__main__":
    unittest.main()
