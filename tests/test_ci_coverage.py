"""CI coverage guard: every test file runs in CI, and every workflow keeps least privilege.

- Every node test file (tests/*.mjs, packages/*/test/*.mjs, motion-library/*/*.test.mjs) is run by an
  unconditional step of a workflow that runs on every pull request and every push to main, or it is
  listed in EXEMPT_NODE_TESTS with a reason.
- Every tests/test_*.py is reachable by an unfiltered `python3 -m unittest discover -s tests` step of a
  job that scripts/verify_release.py requires.
- Every action is pinned to a full commit SHA with its version comment; every workflow and job grants
  read access only; checkouts do not keep the token; no workflow uses pull_request_target or
  continue-on-error.

The workflows are read with a small strict parser for the YAML subset they use (CI has no PyYAML).
Anything outside that subset is an error, never a silent pass.
"""
import fnmatch
import pathlib
import posixpath
import re
import shlex
import unittest
from unittest.loader import VALID_MODULE_NAME

from scripts.verify_release import WORKFLOWS as RELEASE_WORKFLOWS

ROOT = pathlib.Path(__file__).resolve().parents[1]

# Node test files that no workflow runs, each with the reason. A file leaves this list when it runs.
EXEMPT_NODE_TESTS = {
    "tests/test_native_motions_browser.mjs": (
        "Host-bound: it compares pixel hashes with frame signatures recorded on the development host "
        "(Playwright 1.63.0, Chromium 158.0.8127.36, that host's system fonts; the DOM sample draws text). "
        "The locked CI Playwright 1.65.1 installs Chromium 159.0.8154.6 on a runner with other fonts, so "
        "the hashes are not expected to match there. It passes on the recording host. Wire it in once the "
        "evidence is recorded with the locked Playwright on the runner."),
    "tests/test_ported_motions_browser.mjs": (
        "Host-bound browser proof of the 60 ported motions: with --write it records frame signatures and "
        "docs/evidence/ported-motions-chromium.json on the development host (Playwright 1.63.0, Chromium "
        "158.0.8127.36; the reviewed pin 1.65.1 was not installed there, as the receipt records). "
        "tests/test_ported_motions.py checks in every CI run that the receipt passed and is bound to the "
        "module bytes. Wire it in once the receipt is recorded with the locked Playwright on the runner."),
}

NODE_TEST_GLOBS = ("tests/*.mjs", "packages/*/test/*.mjs", "motion-library/*/*.test.mjs")
FULL_SUITE = ["python3", "-m", "unittest", "discover", "-s", "tests"]
# Measured on GitHub: the full suite took up to 514 s (job 140911615512); keep at least double that.
MIN_FULL_SUITE_TIMEOUT_MINUTES = 20


# --------------------------------------------------------------------------- strict YAML subset

_KEY = re.compile(r"""(?P<key>[A-Za-z0-9_][A-Za-z0-9_.-]*|"[^"\\]*"|'[^']*'):(?:[ ]+(?P<rest>.*))?$""")
_INT = re.compile(r"-?[0-9]+$")


def _unquote(text):
    if text[0] == "'":
        return text[1:-1].replace("''", "'")
    body = text[1:-1]
    if re.search(r'\\[^\\"nt]', body):
        raise ValueError(f"unsupported escape in {text!r}")
    return body.replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"').replace("\\\\", "\\")


def _quoted_end(text, start):
    """Index just past the quoted scalar that begins at text[start]."""
    quote, index = text[start], start + 1
    while index < len(text):
        if text[index] == quote:
            if quote == "'" and text[index + 1:index + 2] == "'":
                index += 2
                continue
            return index + 1
        index += 2 if quote == '"' and text[index] == "\\" else 1
    raise ValueError(f"unterminated quote in {text!r}")


def _no_trailer(text, rest):
    if rest.strip() and not re.match(r"\s+#", rest):
        raise ValueError(f"unexpected text after a value: {text!r}")


def _scalar(text):
    if text[0] in "\"'":
        end = _quoted_end(text, 0)
        _no_trailer(text, text[end:])
        return _unquote(text[:end])
    if text[0] == "[":
        return _flow_sequence(text)
    if text[0] in "{&*!%@`|>":
        raise ValueError(f"unsupported YAML construct: {text!r}")
    text = re.split(r"\s#", text, maxsplit=1)[0].rstrip()
    if text in ("true", "false"):
        return text == "true"
    if text in ("null", "~"):
        return None
    return int(text) if _INT.match(text) else text


def _flow_sequence(text):
    items, index = [], 1
    while True:
        while index < len(text) and text[index] == " ":
            index += 1
        if index < len(text) and text[index] == "]" and not items:
            _no_trailer(text, text[index + 1:])
            return items
        if index >= len(text):
            raise ValueError(f"unterminated flow sequence: {text!r}")
        if text[index] in "\"'":
            end = _quoted_end(text, index)
            items.append(_unquote(text[index:end]))
            index = end
        else:
            end = index
            while end < len(text) and text[end] not in ",]":
                end += 1
            item = text[index:end].strip()
            if not item or item[0] in "[{&*!|>#":
                raise ValueError(f"unsupported flow item in {text!r}")
            items.append(_scalar(item))
            index = end
        while index < len(text) and text[index] == " ":
            index += 1
        if index < len(text) and text[index] == ",":
            index += 1
            continue
        if index < len(text) and text[index] == "]":
            _no_trailer(text, text[index + 1:])
            return items
        raise ValueError(f"malformed flow sequence: {text!r}")


class _Parser:
    def __init__(self, text):
        self.lines = text.split("\n")
        self.i = 0

    def peek(self):
        """(indent, content) of the next line that is neither blank nor a comment, or None."""
        while self.i < len(self.lines):
            raw = self.lines[self.i].rstrip()
            content = raw.lstrip(" ")
            if not content or content.startswith("#"):
                self.i += 1
                continue
            if content[0] == "\t" or raw.startswith("---") or raw.startswith("..."):
                raise ValueError(f"line {self.i + 1}: tabs and documents markers are not supported")
            return len(raw) - len(content), content
        return None

    def block(self, indent):
        content = self.peek()[1]
        return self.sequence(indent) if content == "-" or content.startswith("- ") else self.mapping(indent)

    def mapping(self, indent):
        result = {}
        while True:
            line = self.peek()
            if line is None or line[0] < indent:
                return result
            if line[0] > indent:
                raise ValueError(f"line {self.i + 1}: unexpected indentation")
            match = _KEY.match(line[1])
            if not match:
                raise ValueError(f"line {self.i + 1}: expected 'key: value', got {line[1]!r}")
            key = match["key"]
            key = _unquote(key) if key[0] in "\"'" else key
            if key in result:
                raise ValueError(f"line {self.i + 1}: duplicate key {key!r}")
            self.i += 1
            result[key] = self.value(match["rest"], indent)

    def sequence(self, indent):
        items = []
        while True:
            line = self.peek()
            if line is None or line[0] < indent:
                return items
            if line[0] > indent:
                raise ValueError(f"line {self.i + 1}: unexpected indentation")
            content = line[1]
            if not (content == "-" or content.startswith("- ")):
                raise ValueError(f"line {self.i + 1}: a mapping key cannot follow a sequence at its indentation")
            body = content[1:].lstrip(" ")
            if not body:
                self.i += 1
                following = self.peek()
                if following is None or following[0] <= indent:
                    raise ValueError(f"line {self.i}: empty sequence item")
                items.append(self.block(following[0]))
            elif _KEY.match(body):
                column = indent + len(content) - len(body)
                self.lines[self.i] = " " * column + body
                items.append(self.mapping(column))
            else:
                self.i += 1
                items.append(_scalar(body))

    def value(self, rest, indent):
        if rest is None or rest.startswith("#"):
            line = self.peek()
            return self.block(line[0]) if line is not None and line[0] > indent else None
        indicator = re.match(r"[|>][-+]?(?=\s|$)", rest)
        if indicator:
            _no_trailer(rest, rest[indicator.end():])
            return self.literal(indent, indicator.group())
        return _scalar(rest)

    def literal(self, indent, indicator):
        if indicator not in ("|", "|-"):
            raise ValueError(f"only literal block scalars are supported, not {indicator!r}")
        lines, content_indent = [], None
        while self.i < len(self.lines):
            raw = self.lines[self.i]
            if not raw.strip():
                lines.append("")
                self.i += 1
                continue
            current = len(raw) - len(raw.lstrip(" "))
            if current <= indent:
                break
            content_indent = current if content_indent is None else content_indent
            if current < content_indent:
                raise ValueError(f"line {self.i + 1}: block scalar line is indented less than its first line")
            lines.append(raw[content_indent:])
            self.i += 1
        while lines and lines[-1] == "":
            lines.pop()
        return "\n".join(lines) + ("\n" if lines and indicator == "|" else "")


def parse_yaml(text):
    """Parse the block-style YAML subset used by the workflows: mappings, sequences, literal block
    scalars, flow sequences and plain or quoted scalars. Anything else raises ValueError."""
    parser = _Parser(text)
    if parser.peek() is None:
        raise ValueError("empty document")
    document = parser.mapping(0)
    if parser.peek() is not None:
        raise ValueError(f"line {parser.i + 1}: content after the document")
    return document


# --------------------------------------------------------------------------- workflow facts

def load_workflows(root=ROOT):
    return {path.relative_to(root).as_posix(): path.read_text(encoding="utf-8")
            for path in sorted((root / ".github/workflows").glob("*.y*ml"))}


def runs_on_every_change(workflow):
    """True when the workflow runs, unfiltered, on every pull request and every push to main."""
    on = workflow.get("on")
    if not isinstance(on, dict) or "pull_request" not in on or on["pull_request"] is not None:
        return False
    push = on.get("push")
    return isinstance(push, dict) and set(push) == {"branches"} and "main" in push["branches"]


def _jobs(workflow):
    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        raise ValueError("workflow has no jobs")
    return jobs


def unconditional_steps(workflow):
    """(job_id, job, step) for steps that always run in a gating workflow: no job or step `if`
    (except always()), and no continue-on-error."""
    if not runs_on_every_change(workflow):
        return
    for job_id, job in _jobs(workflow).items():
        if "if" in job or "continue-on-error" in job:
            continue
        for step in job.get("steps", []):
            condition = step.get("if")
            if (condition is None or "always()" in str(condition)) and "continue-on-error" not in step:
                yield job_id, job, step


def logical_lines(script):
    """Shell lines with backslash continuations joined and here-document bodies left out."""
    lines, pending, heredoc = [], "", None
    for raw in script.split("\n"):
        if heredoc is not None:
            if raw.strip() == heredoc:
                heredoc = None
            continue
        line = pending + raw
        if line.endswith("\\"):
            pending = line[:-1] + " "
            continue
        pending = ""
        marker = re.search(r"<<-?\s*(['\"]?)(\w+)\1", line)
        if marker:
            heredoc = marker.group(2)
        lines.append(line)
    if pending or heredoc is not None:
        raise ValueError("unterminated continuation or here-document")
    return lines


def commands(script):
    """Each simple command of a run script as a token list (operators split commands)."""
    for line in logical_lines(script):
        lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        lexer.commenters = "#"
        current = []
        for token in lexer:
            if token and set(token) <= set("();<>|&"):
                if current:
                    yield current
                current = []
            else:
                current.append(token)
        if current:
            yield current


_NODE_VALUE_OPTIONS = {"-r", "--require", "--import", "--loader", "--experimental-loader", "--input-type",
                       "--test-reporter", "--test-reporter-destination", "--test-concurrency", "--test-timeout",
                       "-C", "--conditions", "--test-name-pattern", "--test-skip-pattern", "--test-shard"}
_NODE_EVAL = {"-e", "--eval", "-p", "--print"}
_NODE_FILTERS = ("--test-name-pattern", "--test-skip-pattern", "--test-only", "--test-shard")


def node_files(tokens):
    """The files a node command runs in full: every positional with --test, else the script."""
    while tokens and re.match(r"[A-Za-z_][A-Za-z0-9_]*=", tokens[0]):
        tokens = tokens[1:]
    if not tokens or posixpath.basename(tokens[0]) != "node":
        return []
    options, positionals, rest = [], [], iter(tokens[1:])
    for token in rest:
        if positionals and "--test" not in options:
            break  # arguments of the script itself
        if token.startswith("-"):
            options.append(token)
            if token in _NODE_VALUE_OPTIONS or token in _NODE_EVAL:
                next(rest, None)
        else:
            positionals.append(token)
    if any(option in _NODE_EVAL for option in options):
        return []
    if any(option.split("=")[0] in _NODE_FILTERS for option in options):
        return []
    return positionals if "--test" in options else positionals[:1]


def executed_node_files(workflows):
    """{file: [where]} for every file a gating workflow's unconditional step runs with node."""
    found = {}
    for path, text in workflows.items():
        for job_id, _, step in unconditional_steps(parse_yaml(text)):
            script = step.get("run")
            if not isinstance(script, str):
                continue
            base = step.get("working-directory", "")
            for tokens in commands(script):
                for name in node_files(tokens):
                    found.setdefault(posixpath.normpath(posixpath.join(base, name)), []).append(f"{path}:{job_id}")
    return found


def full_suite_jobs(workflows):
    """(path, job name, timeout) of each job whose unconditional step runs the unfiltered suite."""
    jobs = []
    for path, text in workflows.items():
        for job_id, job, step in unconditional_steps(parse_yaml(text)):
            script = step.get("run")
            if not isinstance(script, str) or step.get("working-directory"):
                continue
            if any(tokens in (FULL_SUITE, FULL_SUITE + ["-v"]) for tokens in commands(script)):
                jobs.append((path, job.get("name", job_id), job.get("timeout-minutes")))
    return jobs


_PIN = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_./-]+)?@[0-9a-f]{40}")
_USES = re.compile(r"^\s*(?:-\s+)?uses:\s*(?P<value>.*)$")


def _read_only(permissions, where, top_level):
    if not isinstance(permissions, dict):
        return [f"{where}: permissions must be a mapping of scopes, not {permissions!r}"]
    problems = [f"{where}: {scope} is {level!r}" for scope, level in permissions.items()
                if level not in ("read", "none")]
    if top_level and permissions.get("contents") != "read":
        problems.append(f"{where}: top-level permissions must set contents: read")
    return problems


def workflow_problems(path, text):
    """Pinning and least-privilege problems of one workflow file (an empty list when it is clean)."""
    problems, data = [], parse_yaml(text)
    if "pull_request_target" in text:
        problems.append(f"{path}: uses pull_request_target")
    if "continue-on-error" in text:
        problems.append(f"{path}: uses continue-on-error")
    pins = [_USES.match(line)["value"] for line in text.split("\n") if _USES.match(line)]
    for value in pins:
        match = re.fullmatch(r"(?P<ref>\S+)\s+#\s*v\d+(?:\.\d+)*\s*", value)
        if not match or not _PIN.fullmatch(match["ref"]):
            problems.append(f"{path}: action not pinned to a full commit SHA with its version comment: {value!r}")
    if "permissions" not in data:
        problems.append(f"{path}: no top-level permissions")
    else:
        problems += _read_only(data["permissions"], path, top_level=True)
    steps = 0
    for job_id, job in _jobs(data).items():
        where = f"{path}:{job_id}"
        if "permissions" in job:
            problems += _read_only(job["permissions"], where, top_level=False)
        if "timeout-minutes" not in job:
            problems.append(f"{where}: no timeout-minutes")
        for step in job.get("steps", []):
            uses = step.get("uses")
            if uses is None:
                continue
            steps += 1
            keeps_token = (step.get("with") or {}).get("persist-credentials") is not False
            if str(uses).startswith("actions/checkout@") and keeps_token:
                problems.append(f"{where}: actions/checkout must set persist-credentials: false")
    if steps != len(pins):
        problems.append(f"{path}: {len(pins)} uses lines but {steps} action steps were parsed")
    return problems


def node_test_files(root=ROOT):
    return sorted({path.relative_to(root).as_posix() for pattern in NODE_TEST_GLOBS for path in root.glob(pattern)})


# --------------------------------------------------------------------------- tests

class RepositoryCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflows = load_workflows()
        cls.executed = executed_node_files(cls.workflows)

    def test_every_node_test_file_runs_in_a_gating_workflow_or_is_exempt(self):
        files = node_test_files()
        self.assertGreaterEqual(len(files), 10)
        unrun = [name for name in files if name not in self.executed and name not in EXEMPT_NODE_TESTS]
        self.assertEqual(unrun, [], "add a workflow step for each file, or exempt it here with a reason")

    def test_exemptions_name_unrun_files_with_a_reason(self):
        files = set(node_test_files())
        for name, reason in EXEMPT_NODE_TESTS.items():
            with self.subTest(name=name):
                self.assertIn(name, files)
                self.assertNotIn(name, self.executed, "a file that runs needs no exemption")
                self.assertGreater(len(reason.split()), 3)

    def test_every_executed_node_file_exists(self):
        missing = sorted(name for name in self.executed
                         if name.endswith((".mjs", ".js")) and not (ROOT / name).is_file())
        self.assertEqual(missing, [])

    def test_every_python_test_module_is_reachable_by_an_unfiltered_discover_in_a_required_job(self):
        jobs = full_suite_jobs(self.workflows)
        required = [(path, name) for path, name, _ in jobs if name in RELEASE_WORKFLOWS.get(path, ())]
        self.assertTrue(required, f"no release-required job runs the full suite: {jobs}")
        for path, name, timeout in jobs:
            with self.subTest(job=f"{path}:{name}"):
                self.assertIsInstance(timeout, int)
                self.assertGreaterEqual(timeout, MIN_FULL_SUITE_TIMEOUT_MINUTES)
        modules = sorted(ROOT.glob("tests/test_*.py"))
        self.assertGreater(len(modules), 50)
        for module in modules:
            with self.subTest(module=module.name):
                self.assertTrue(VALID_MODULE_NAME.match(module.name) and fnmatch.fnmatch(module.name, "test*.py"))
        self.assertTrue(pathlib.Path(__file__).name in {module.name for module in modules})

    def test_every_workflow_pins_actions_and_keeps_least_privilege(self):
        self.assertGreaterEqual(len(self.workflows), 9)
        sources = dict(self.workflows)
        sources["templates/hub-link.yml"] = (ROOT / "templates/hub-link.yml").read_text(encoding="utf-8")
        problems = [problem for path, text in sources.items() for problem in workflow_problems(path, text)]
        self.assertEqual(problems, [])

    def test_release_required_jobs_exist_in_gating_workflows(self):
        for path, names in RELEASE_WORKFLOWS.items():
            with self.subTest(path=path):
                data = parse_yaml(self.workflows[path])
                self.assertTrue(runs_on_every_change(data))
                declared = {job.get("name", job_id) for job_id, job in _jobs(data).items()}
                for job in _jobs(data).values():
                    for browser in ((job.get("strategy") or {}).get("matrix") or {}).get("browser", []):
                        declared.add(job["name"].replace("${{ matrix.browser }}", browser))
                self.assertLessEqual(set(names), declared)


GATING = """\
name: fixture
on:
  pull_request:
  push:
    branches: [main]
permissions:
  contents: read
jobs:
  unit:
    name: unit
    runs-on: ubuntu-24.04
    timeout-minutes: 25
    steps:
      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2
        with:
          persist-credentials: false
{steps}"""


def gating(steps):
    return GATING.replace("{steps}", steps)


class ParserTests(unittest.TestCase):
    def test_supported_subset_is_read_like_yaml(self):
        document = parse_yaml(
            "name: 'It''s \"x\"'  # comment\n"
            "on:\n  pull_request:\n  push:\n    branches: [main, \"release\"]\n"
            "jobs:\n  a:\n    timeout-minutes: 10\n    flag: false\n"
            "    steps:\n      - run: |\n          echo one  # kept: shell text\n\n          # also kept\n"
            "          echo two\n      - name: plain value # comment\n        run: echo \"a: b\"\n"
            "      -\n        uses: x/y@" + "a" * 40 + "\n")
        self.assertEqual(document["name"], "It's \"x\"")
        self.assertEqual(document["on"], {"pull_request": None, "push": {"branches": ["main", "release"]}})
        job = document["jobs"]["a"]
        self.assertEqual((job["timeout-minutes"], job["flag"]), (10, False))
        self.assertEqual(job["steps"][0]["run"], "echo one  # kept: shell text\n\n# also kept\necho two\n")
        self.assertEqual(job["steps"][1], {"name": "plain value", "run": 'echo "a: b"'})
        self.assertEqual(job["steps"][2], {"uses": "x/y@" + "a" * 40})

    def test_everything_outside_the_subset_is_refused(self):
        for text in ("a: {b: c}\n", "a: &anchor 1\n", "a: *alias\n", "a: >\n  folded\n", "a:\n\tb: 1\n",
                     "a: 1\na: 2\n", "a: 1\n  b: 2\n", "a:\n- b\n", "a: 'open\n", "a: [b, {c: d}]\n",
                     "a: \"x\" y\n", "- a\n", "---\na: 1\n", "a: [b\n", "", "a: \"\\u0041\"\n"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_yaml(text)

    def test_the_real_workflows_parse(self):
        for path, text in load_workflows().items():
            with self.subTest(path=path):
                self.assertIn("jobs", parse_yaml(text))


class GuardTests(unittest.TestCase):
    def executed(self, steps):
        return executed_node_files({"w.yml": gating(steps)})

    def test_node_commands_count_their_test_files_and_scripts(self):
        found = self.executed(
            "      - run: node --test --test-reporter=tap tests/a.mjs tests/b.mjs | tee out.tap\n"
            "      - run: |\n          set -euo pipefail\n          FOO=1 node tests/c.mjs --out \"$RUNNER_TEMP/x\"\n"
            "          node --input-type=module <<'JS'\n          import 'tests/heredoc.mjs';\n          JS\n"
            "          node --input-type=module -e \"console.log(1)\" tests/eval-argument.mjs\n"
            "          python3 scripts/x.py \\\n            tests/not-node.mjs\n"
            "      - working-directory: packages/p\n        run: node --test test/d.test.mjs\n")
        self.assertEqual(sorted(found), ["packages/p/test/d.test.mjs", "tests/a.mjs", "tests/b.mjs", "tests/c.mjs"])

    def test_conditional_filtered_or_non_gating_runs_do_not_count(self):
        self.assertEqual(self.executed(
            "      - if: github.event_name == 'push'\n        run: node tests/a.mjs\n"
            "      - run: node --test --test-name-pattern=one tests/b.mjs\n"
            "      - run: node --test --test-skip-pattern two tests/c.mjs\n"
            "      - run: echo node tests/d.mjs\n"), {})
        always = self.executed("      - if: ${{ always() }}\n        run: node tests/e.mjs\n")
        self.assertEqual(list(always), ["tests/e.mjs"])
        for trigger in ("on:\n  schedule:\n    - cron: '1 1 * * 1'\n",
                        "on:\n  push:\n    branches: [main]\n",
                        "on:\n  pull_request:\n    paths: [docs/**]\n  push:\n    branches: [main]\n",
                        "on:\n  pull_request:\n  push:\n    branches: [main]\n    paths: [docs/**]\n"):
            with self.subTest(trigger=trigger):
                text = gating("      - run: node tests/a.mjs\n").replace(
                    "on:\n  pull_request:\n  push:\n    branches: [main]\n", trigger)
                self.assertEqual(executed_node_files({"w.yml": text}), {})

    def test_only_the_unfiltered_discover_counts_as_the_full_suite(self):
        def jobs(command):
            return full_suite_jobs({"w.yml": gating(f"      - run: {command}\n")})
        self.assertEqual(jobs("python3 -m unittest discover -s tests -v"), [("w.yml", "unit", 25)])
        self.assertEqual(jobs("python3 -m unittest discover -s tests"), [("w.yml", "unit", 25)])
        for command in ("python3 -m unittest discover -s tests -p test_a.py -v",
                        "python3 -m unittest discover -s tests -k fast", "python3 -m unittest tests.test_a"):
            with self.subTest(command=command):
                self.assertEqual(jobs(command), [])

    def test_unpinned_actions_write_tokens_and_risky_options_are_reported(self):
        self.assertEqual(workflow_problems("w.yml", gating("      - run: true\n")), [])
        cases = {
            "action not pinned": ("actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2",
                                  "actions/checkout@v4"),
            "version comment": ("@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2",
                                "@11bd71901bbe5b1630ceea73d27597364c9af683"),
            "contents is 'write'": ("  contents: read\njobs", "  contents: write\njobs"),
            "permissions must be a mapping": ("permissions:\n  contents: read\n", "permissions: write-all\n"),
            "persist-credentials": ("persist-credentials: false", "persist-credentials: true"),
            "pull_request_target": ("  pull_request:\n", "  pull_request_target:\n"),
            "no timeout-minutes": ("    timeout-minutes: 25\n", ""),
        }
        def reported(expected, text):
            return any(expected in problem for problem in workflow_problems("w.yml", text))

        clean = gating("      - run: true\n")
        for expected, (before, after) in cases.items():
            self.assertIn(before, clean)
            with self.subTest(expected=expected):
                self.assertTrue(reported(expected, clean.replace(before, after)))
        job_write = clean.replace("    timeout-minutes: 25\n",
                                  "    timeout-minutes: 25\n    permissions:\n      issues: write\n")
        self.assertTrue(reported("issues is 'write'", job_write))
        self.assertTrue(reported("continue-on-error", gating("      - run: true\n        continue-on-error: true\n")))


if __name__ == "__main__":
    unittest.main()
