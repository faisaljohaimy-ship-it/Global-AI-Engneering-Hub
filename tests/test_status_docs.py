"""The status documents state what the tree shows: the scenario matrix of the final report is checked.

docs/specs/gaie-20-layers/FINAL_REPORT.md carries one acceptance-scenario matrix per language,
between `<!-- scenario-matrix:ar -->` / `<!-- scenario-matrix:en -->` and `<!-- /scenario-matrix -->`.
Each row is: letter | subject | state (`passing`, `partial` or `open` in backticks) | test file in
backticks | test classes in backticks | what was measured. A row marked `passing` must name a test
file that exists and defines every named class, and docs/specs/gaie-20-layers/RESUME.md must not
list that scenario as partial or open. Negative cases run the same checker on synthetic documents
in a temporary directory; no repository file is written.
"""
import json
import pathlib
import re
import tempfile
import unittest

from engineering_os.contracts import SCENARIOS

ROOT = pathlib.Path(__file__).resolve().parents[1]
REPORT = "docs/specs/gaie-20-layers/FINAL_REPORT.md"
RESUME = "docs/specs/gaie-20-layers/RESUME.md"
STATUS = "docs/OPERATING_SYSTEM_STATUS.md"
STATES = ("passing", "partial", "open")
END = "<!-- /scenario-matrix -->"


def _cells(line):
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def matrix(text, lang):
    """Return ({letter: (state, test_file, classes)}, problems) for one language's matrix."""
    start = f"<!-- scenario-matrix:{lang} -->"
    if text.count(start) != 1:
        return {}, [f"{lang}: expected exactly one '{start}' marker, found {text.count(start)}"]
    body = text.split(start, 1)[1]
    if END not in body:
        return {}, [f"{lang}: matrix has no closing '{END}'"]
    lines = [line for line in body.split(END, 1)[0].splitlines() if line.strip()]
    problems, rows = [], {}
    if len(lines) < 2 or not re.fullmatch(r"\|[-| :]+\|", lines[1].strip()):
        return {}, [f"{lang}: matrix needs a header row and a separator row"]
    for line in lines[2:]:
        cells = _cells(line)
        if len(cells) != 6:
            problems.append(f"{lang}: row needs 6 cells, has {len(cells)}: {line.strip()[:60]}")
            continue
        letter = cells[0]
        if not re.fullmatch(r"[A-Z]", letter):
            problems.append(f"{lang}: first cell must be one scenario letter: {letter!r}")
            continue
        if letter in rows:
            problems.append(f"{lang}: scenario {letter} appears twice")
            continue
        states = re.findall(r"`(%s)`" % "|".join(STATES), cells[2])
        if len(states) != 1:
            problems.append(f"{lang}: scenario {letter} must have exactly one state of {STATES}")
            continue
        tests = re.findall(r"`(tests/[\w./-]+\.(?:py|mjs))`", cells[3])
        if len(tests) > 1:
            problems.append(f"{lang}: scenario {letter} names more than one test file")
            continue
        classes = tuple(re.findall(r"`([A-Za-z_]\w*)`", cells[4]))
        rows[letter] = (states[0], tests[0] if tests else None, classes)
    if set(rows) != set(SCENARIOS):
        missing, extra = sorted(set(SCENARIOS) - set(rows)), sorted(set(rows) - set(SCENARIOS))
        problems.append(f"{lang}: matrix must list exactly scenarios A-I (missing {missing}, extra {extra})")
    return rows, problems


def _section(text, heading):
    """The text under a '## heading' line up to the next level-2 heading, or None."""
    match = re.search(r"^## %s\s*$" % re.escape(heading), text, re.M)
    if not match:
        return None
    rest = text[match.end():]
    following = re.search(r"^## ", rest, re.M)
    return rest[:following.start()] if following else rest


def resume_open(text):
    """Return (letters RESUME.md lists as partial or open, problems)."""
    problems, letters = [], set()
    scenarios = _section(text, "Acceptance scenarios")
    if scenarios is None:
        return set(), ["RESUME.md has no '## Acceptance scenarios' section"]
    rows = 0
    for line in scenarios.splitlines():
        if not line.startswith("|"):
            continue
        cells = _cells(line)
        if len(cells) >= 3 and re.fullmatch(r"[A-Z]", cells[0]):
            rows += 1
            if not cells[2].strip("*` ").lower().startswith("passing"):
                letters.add(cells[0])
    if not rows:
        problems.append("RESUME.md 'Acceptance scenarios' has no scenario rows")
    items = _section(text, "Open items") or ""
    for line in items.splitlines():
        if not line.startswith("|"):
            continue
        cells = _cells(line)
        match = re.fullmatch(r"`?scenario-([a-z])`?", cells[0]) if cells else None
        if match and not cells[-1].strip("*` ").lower().startswith("done"):
            letters.add(match.group(1).upper())
    return letters, problems


def check(report_text, resume_text, root):
    """Every problem that makes the report's scenario matrix dishonest; empty when it holds."""
    ar, problems = matrix(report_text, "ar")
    en, more = matrix(report_text, "en")
    problems += more
    for letter in sorted(set(ar) & set(en)):
        if ar[letter] != en[letter]:
            problems.append(f"scenario {letter}: Arabic and English rows disagree: {ar[letter]} != {en[letter]}")
    for letter, (state, test, classes) in sorted(en.items()):
        if state == "passing" and (not test or not classes):
            problems.append(f"scenario {letter} is passing but names no test file or no test class")
        if not test:
            continue
        path = pathlib.Path(root) / test
        if not path.is_file():
            problems.append(f"scenario {letter}: test file {test} does not exist")
            continue
        source = path.read_text(encoding="utf-8")
        for name in classes:
            if not re.search(r"^class %s\b" % re.escape(name), source, re.M):
                problems.append(f"scenario {letter}: {test} defines no class {name}")
    open_letters, more = resume_open(resume_text)
    problems += more
    for letter in sorted(open_letters):
        if en.get(letter, ("",))[0] == "passing":
            problems.append(f"scenario {letter} is marked passing but RESUME.md lists it as partial or open")
    return problems


def _read(relative):
    return (ROOT / relative).read_text(encoding="utf-8")


class RealDocumentTests(unittest.TestCase):
    def test_final_report_scenario_matrix_is_honest(self):
        self.assertEqual(check(_read(REPORT), _read(RESUME), ROOT), [])

    def test_report_is_arabic_first_then_english_with_the_same_sections(self):
        text = _read(REPORT)
        arabic, english = text.find("\n## العربية\n"), text.find("\n## English\n")
        self.assertTrue(0 < arabic < english, (arabic, english))
        numbers = lambda part: re.findall(r"^### (\d+)\. ", part, re.M)
        self.assertEqual(numbers(text[arabic:english]), [str(n) for n in range(1, 13)])
        self.assertEqual(numbers(text[english:]), [str(n) for n in range(1, 13)])

    def test_both_layer_tables_and_the_status_table_name_all_twenty_layers(self):
        layers = json.loads(_read("governance/layers.json"))
        text = _read(REPORT)
        english = text[text.find("\n## English\n"):]
        arabic = text[:text.find("\n## English\n")]
        status = _read(STATUS)
        for record in layers:
            lid, name = record["id"], record["name"]
            self.assertIn(f"| {lid} {name['en']} |", english, lid)
            self.assertIn(f"| {lid} {name['ar']} |", arabic, lid)
            self.assertIn(f"|{lid} {name['en']}|", status, lid)


class CheckerTests(unittest.TestCase):
    """The checker refuses each kind of dishonest matrix (synthetic documents only)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="sd-")
        self.root = pathlib.Path(self.tmp.name)
        (self.root / "tests").mkdir()
        (self.root / "tests/test_x.py").write_text(
            "import unittest\nclass ScenarioXTests(unittest.TestCase):\n    pass\n# class Mentioned\n", encoding="utf-8")
        self.rows = {letter: ("`passing`", "`tests/test_x.py`", "`ScenarioXTests`") for letter in sorted(SCENARIOS)}
        self.rows["G"] = ("`partial`", "`tests/test_x.py`", "")
        self.resume = ("# Resume\n\n## Acceptance scenarios\n\n| Scenario | Subject | State | Test |\n|---|---|---|---|\n"
                       + "".join(f"| {l} | s | {'**Partial**: no test' if l == 'G' else 'Passing'} | t |\n"
                                 for l in sorted(SCENARIOS))
                       + "\n## Open items\n\n| Id | Item | Status |\n|---|---|---|\n| scenario-g | release | open |\n"
                       + "| scenario-b | upgrade | done (`abc1234`) |\n")

    def tearDown(self):
        self.tmp.cleanup()

    def report(self, en=None, ar=None):
        def block(lang, rows):
            lines = [f"<!-- scenario-matrix:{lang} -->", "| S | Subject | State | Test file | Classes | Measured |",
                     "|---|---|---|---|---|---|"]
            lines += [f"| {letter} | subject | {state} | {test} | {classes} | measured |"
                      for letter, (state, test, classes) in rows.items()]
            return "\n".join(lines + [END])
        return "\n\n".join(["# Report", block("ar", ar or self.rows), block("en", en or self.rows)])

    def problems(self, report=None, resume=None):
        return check(report if report is not None else self.report(), resume if resume is not None else self.resume, self.root)

    def test_a_consistent_synthetic_matrix_has_no_problems(self):
        self.assertEqual(self.problems(), [])

    def test_passing_row_with_a_missing_test_file_is_refused(self):
        rows = dict(self.rows, A=("`passing`", "`tests/test_missing.py`", "`ScenarioXTests`"))
        self.assertTrue(any("test_missing.py does not exist" in p for p in self.problems(self.report(rows, rows))))

    def test_passing_row_whose_class_is_not_defined_is_refused(self):
        for absent in ("ScenarioYTests", "Mentioned", "ScenarioX"):
            rows = dict(self.rows, B=("`passing`", "`tests/test_x.py`", f"`{absent}`"))
            self.assertTrue(any(f"defines no class {absent}" in p for p in self.problems(self.report(rows, rows))), absent)

    def test_passing_row_without_a_test_or_class_is_refused(self):
        for cells in (("`passing`", "—", "`ScenarioXTests`"), ("`passing`", "`tests/test_x.py`", "—")):
            rows = dict(self.rows, C=cells)
            self.assertTrue(any("names no test file or no test class" in p for p in self.problems(self.report(rows, rows))))

    def test_passing_scenario_that_resume_lists_as_partial_is_refused(self):
        rows = dict(self.rows, G=("`passing`", "`tests/test_x.py`", "`ScenarioXTests`"))
        found = self.problems(self.report(rows, rows))
        self.assertTrue(any("scenario G is marked passing" in p for p in found), found)

    def test_passing_scenario_with_an_open_item_in_resume_is_refused(self):
        resume = self.resume + "| scenario-i | install | in progress |\n"
        self.assertTrue(any("scenario I is marked passing" in p for p in self.problems(resume=resume)))
        resume = self.resume.replace("| scenario-g | release | open |", "| scenario-g | release | done (`abc`) |")
        resume = resume.replace("**Partial**: no test", "Passing")
        rows = dict(self.rows, G=("`passing`", "`tests/test_x.py`", "`ScenarioXTests`"))
        self.assertEqual(self.problems(self.report(rows, rows), resume), [])

    def test_arabic_and_english_rows_must_agree(self):
        ar = dict(self.rows, D=("`partial`", "`tests/test_x.py`", "`ScenarioXTests`"))
        self.assertTrue(any("scenario D: Arabic and English rows disagree" in p for p in self.problems(self.report(ar=ar))))

    def test_missing_duplicated_or_unknown_scenarios_are_refused(self):
        rows = {k: v for k, v in self.rows.items() if k != "H"}
        self.assertTrue(any("missing ['H']" in p for p in self.problems(self.report(rows, rows))))
        text = self.report().replace("| A | subject", "| J | subject", 1)
        self.assertTrue(any("extra ['J']" in p for p in self.problems(text)))
        text = self.report().replace("| B | subject", "| A | subject")
        self.assertTrue(any("scenario A appears twice" in p for p in self.problems(text)))

    def test_unknown_state_or_missing_markers_are_refused(self):
        rows = dict(self.rows, E=("`verified`", "`tests/test_x.py`", "`ScenarioXTests`"))
        self.assertTrue(any("scenario E must have exactly one state" in p for p in self.problems(self.report(rows, rows))))
        text = self.report().replace("<!-- scenario-matrix:ar -->", "")
        self.assertTrue(any("ar: expected exactly one" in p for p in self.problems(text)))
        text = self.report().replace(END, "", 1)
        self.assertTrue(self.problems(text))

    def test_resume_without_its_scenario_table_is_refused(self):
        self.assertTrue(any("no '## Acceptance scenarios'" in p for p in self.problems(resume="# Resume\n")))


if __name__ == "__main__":
    unittest.main()
