"""Acceptance scenarios A-I in the layer registry, and the test files the registry leaves out.

Proves: every scenario the registry binds names a test file of that layer which exists and
defines the bound test class or method; a scenario with no binding is UNBOUND, never VERIFIED,
whatever the layers' status; the scenario tables in docs/specs/gaie-20-layers/LAYERS.md equal
the registry; and every tests/test_*.py and tests/test_*.mjs file is either listed by a layer or
named in LAYERS.md with the reason it is left out. Test files are parsed with ast; nothing is
imported or executed, so this stays fast on every host.
"""
import ast
import fnmatch
import json
import pathlib
import re
import tempfile
import unittest

from engineering_os import contracts, layers

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = ROOT / "docs/specs/gaie-20-layers/LAYERS.md"

BINDING_ROW = re.compile(r"^\| ([A-I]) \| ([^|]+?) \| (L\d{2}) \| `(tests/[^`]+)` \| `([^`]+)` \|", re.MULTILINE)
PENDING_ROW = re.compile(r"^\| ([^|`]+?) \| not yet bound \| ([a-z0-9-]+) \| (.+) \|$", re.MULTILINE)
OUTSIDE_ROW = re.compile(r"^\| `(tests/[^`]+)` \| (unbound|announced) \| (.+) \|$", re.MULTILINE)
ASSURANCE_ITEM = "L20 assurance module"
ASSURANCE_TEST = "tests/test_assurance.py"


def registry():
    return json.loads((ROOT / layers.LAYERS_FILE).read_text(encoding="utf-8"))


def section(text, title):
    """The body of the Markdown section headed `title` (any level), up to the next heading of that level or above."""
    match = re.search(rf"^(#+) {re.escape(title)}\s*$", text, re.MULTILINE)
    if not match:
        raise AssertionError(f"LAYERS.md has no section {title!r}")
    level = len(match.group(1))
    end = re.compile(rf"^#{{1,{level}}} ", re.MULTILINE).search(text, match.end())
    return text[match.end():end.start() if end else len(text)]


def spec_text():
    return SPEC.read_text(encoding="utf-8")


def test_classes(source):
    """{class name: set of test_* methods, own and inherited from classes in the same file} for unittest classes."""
    tree = ast.parse(source)
    classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}

    def base_names(node):
        names = []
        for base in node.bases:
            if isinstance(base, ast.Name):
                names.append(base.id)
            elif isinstance(base, ast.Attribute):
                names.append(base.attr)
        return names

    def is_case(name, seen=()):
        node = classes.get(name)
        if node is None or name in seen:
            return False
        return any(base == "TestCase" or is_case(base, seen + (name,)) for base in base_names(node))

    def methods(name, seen=()):
        node = classes.get(name)
        if node is None or name in seen:
            return set()
        own = {item.name for item in node.body
               if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name.startswith("test")}
        for base in base_names(node):
            own |= methods(base, seen + (name,))
        return own

    return {name: methods(name) for name in classes if is_case(name)}


def case_problem(source, case):
    """None when `case` (Class or Class.test_method) is a unittest case with tests in `source`, else the reason."""
    name, _, method = case.partition(".")
    found = test_classes(source)
    if name not in found:
        return f"no unittest.TestCase class {name}"
    if not found[name]:
        return f"class {name} defines no test method"
    if method and method not in found[name]:
        return f"class {name} has no test method {method}"
    return None


def test_files():
    return sorted(f"tests/{p.name}" for p in (ROOT / "tests").iterdir()
                  if p.is_file() and p.name.startswith("test_") and p.suffix in {".py", ".mjs"})


class CaseLookupTests(unittest.TestCase):
    """The checker itself, on synthetic sources: it refuses what does not exist."""

    SOURCE = ("import unittest\n\nclass Base(unittest.TestCase):\n    def test_shared(self):\n        pass\n\n"
              "class ScenarioX(Base):\n    def test_one(self):\n        pass\n\n"
              "class Plain:\n    def test_not_a_case(self):\n        pass\n\n"
              "class Empty(unittest.TestCase):\n    def helper(self):\n        pass\n")

    def test_existing_classes_and_methods_are_found(self):
        for case in ("ScenarioX", "ScenarioX.test_one", "ScenarioX.test_shared", "Base"):
            self.assertIsNone(case_problem(self.SOURCE, case), case)

    def test_missing_or_non_test_cases_are_refused(self):
        for case, reason in (("ScenarioY", "no unittest.TestCase class"), ("Plain", "no unittest.TestCase class"),
                             ("Empty", "defines no test method"), ("ScenarioX.test_two", "no test method"),
                             ("ScenarioX.helper", "no test method")):
            self.assertIn(reason, case_problem(self.SOURCE, case), case)


class ScenarioBindingTests(unittest.TestCase):
    def setUp(self):
        self.records = registry()
        self.report = contracts.scenario_report(self.records)

    def bindings(self):
        return [(r["id"], e) for r in self.records for e in r["scenarios"] if isinstance(e, dict)]

    def test_every_binding_names_an_existing_test_case_of_its_layer(self):
        self.assertTrue(self.bindings())
        for lid, entry in self.bindings():
            with self.subTest(layer=lid, scenario=entry["id"], case=entry["case"]):
                record = next(r for r in self.records if r["id"] == lid)
                self.assertIn(entry["test"], record["tests"])
                path = ROOT / entry["test"]
                self.assertTrue(path.is_file() and not path.is_symlink(), entry["test"])
                self.assertIsNone(case_problem(path.read_text(encoding="utf-8"), entry["case"]))

    def test_the_registry_claims_scenarios_only_through_bindings(self):
        for record in self.records:
            bare = [e for e in record["scenarios"] if not isinstance(e, dict)]
            self.assertEqual(bare, [], f"{record['id']}: a bare letter claims a scenario without a test case")

    def test_bindings_table_equals_the_registry(self):
        rows = BINDING_ROW.findall(section(spec_text(), "Scenario bindings"))
        documented = sorted((letter, lid, test, case) for letter, _, lid, test, case in rows)
        actual = sorted((e["id"], lid, e["test"], e["case"]) for lid, e in self.bindings())
        self.assertEqual(documented, actual)
        for letter, title, *_ in rows:
            self.assertEqual(title.strip(), contracts.SCENARIO_TITLES[letter])

    def test_each_layer_section_names_its_bound_cases(self):
        text = spec_text()
        for record in self.records:
            body = section(text, f"{record['id']} {record['name']['en']} — {record['name']['ar']}")
            for entry in record["scenarios"]:
                self.assertIn(f"`{entry['case']}`", body, (record["id"], entry))

    def test_unbound_scenarios_are_exactly_the_documented_ones_and_never_verified(self):
        pending = PENDING_ROW.findall(section(spec_text(), "Not yet bound"))
        letters = set()
        for item, _, addition in pending:
            match = re.match(r"^Scenario ([A-I]) ", item)
            self.assertTrue(match or item == ASSURANCE_ITEM, f"unknown not-yet-bound item {item!r}")
            self.assertGreater(len(addition), 40, item)
            if match:
                letters.add(match.group(1))
                self.assertIn(contracts.SCENARIO_TITLES[match.group(1)], item)
        unbound = {letter for letter, row in self.report.items() if row["status"] == "UNBOUND"}
        self.assertEqual(unbound, letters)
        self.assertEqual({row["status"] for letter, row in self.report.items() if letter not in letters}, {"BOUND"})
        # even with every layer VERIFIED, an unbound scenario is never VERIFIED
        verified = contracts.scenario_report(self.records, {lid: "VERIFIED" for lid in contracts.LAYER_IDS})
        for letter in contracts.SCENARIOS:
            self.assertEqual(verified[letter]["status"], "UNBOUND" if letter in letters else "VERIFIED", letter)

    def test_without_receipts_bound_scenarios_are_unverified(self):
        with tempfile.TemporaryDirectory(prefix="gaie-scn-") as temp:
            state = pathlib.Path(temp) / "none"
            statuses = {row["id"]: row["status"] for row in layers.status(state_dir=state)}
            self.assertFalse(state.exists())
        report = contracts.scenario_report(self.records, statuses)
        self.assertEqual({row["status"] for row in report.values()}, {"UNVERIFIED", "UNBOUND"})

    def test_assurance_module_state_is_explicit(self):
        pending = {item for item, _, _ in PENDING_ROW.findall(section(spec_text(), "Not yet bound"))}
        interfaces = [ref for r in self.records for ref in r["interfaces"] if ref.startswith("engineering_os.assurance:")]
        listed = [r["id"] for r in self.records if ASSURANCE_TEST in r["tests"]]
        if ASSURANCE_ITEM in pending:
            self.assertEqual((interfaces, listed), ([], []), "bound: remove the not-yet-bound row")
        else:
            l20 = next(r for r in self.records if r["id"] == "L20")
            self.assertTrue(any(ref.startswith("engineering_os.assurance:") for ref in l20["interfaces"]))
            self.assertIn(ASSURANCE_TEST, l20["tests"])

    def test_scenarios_are_defined_in_the_spec(self):
        body = section(spec_text(), "Acceptance scenarios A–I")
        for letter, title in contracts.SCENARIO_TITLES.items():
            self.assertIn(f"{letter} {title}", body)


class TestFileCoverageTests(unittest.TestCase):
    def setUp(self):
        self.records = registry()
        self.bound = {test for record in self.records for test in record["tests"]}
        self.rows = OUTSIDE_ROW.findall(section(spec_text(), "Test files outside the registry"))
        self.files = test_files()

    def test_every_test_file_is_listed_by_a_layer_or_left_out_with_a_reason(self):
        silent = [path for path in self.files if path not in self.bound
                  and not any(fnmatch.fnmatchcase(path, pattern) for pattern, _, _ in self.rows)]
        self.assertEqual(silent, [], "bind these files to a layer or list them in LAYERS.md with a reason")

    def test_outside_rows_are_exact_reasoned_and_not_stale(self):
        patterns = [pattern for pattern, _, _ in self.rows]
        self.assertEqual(len(patterns), len(set(patterns)), "duplicate rows")
        self.assertTrue(self.rows)
        for pattern, kind, reason in self.rows:
            with self.subTest(pattern=pattern):
                self.assertGreater(len(reason.strip()), 20)
                matched = [path for path in self.files if fnmatch.fnmatchcase(path, pattern)]
                if any(ch in pattern for ch in "*?["):
                    self.assertEqual(kind, "unbound")
                    self.assertTrue([p for p in matched if p not in self.bound], "a glob row must cover an unbound file")
                    continue
                self.assertNotIn(pattern, self.bound, "listed by a layer: remove the row")
                if kind == "unbound":
                    self.assertEqual(matched, [pattern], "an unbound row names a file in this tree")

    def test_reserved_files_of_the_earlier_session_are_bound_or_listed(self):
        for reserved in ("tests/test_video_pipeline.py", "tests/test_digital_show.py"):
            self.assertIn(reserved, self.bound)
        self.assertIn("tests/test_digital_show_scenes.mjs", [pattern for pattern, _, _ in self.rows])


if __name__ == "__main__":
    unittest.main()
