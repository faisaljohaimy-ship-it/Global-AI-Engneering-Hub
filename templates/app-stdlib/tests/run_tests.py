"""Run the unit and API integration tests and optionally write a JSON report."""
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class _Result(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.outcomes = {}

    def addSuccess(self, test):
        super().addSuccess(test)
        self.outcomes[test.id()] = "passed"

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.outcomes[test.id()] = "failed"

    def addError(self, test, err):
        super().addError(test, err)
        self.outcomes[getattr(test, "id", lambda: str(test))()] = "error"

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.outcomes[test.id()] = "skipped"

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self.outcomes[test.id()] = "expected-failure"

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self.outcomes[test.id()] = "unexpected-success"


def main(report=None):
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT))
    runner = unittest.TextTestRunner(stream=sys.stderr, verbosity=1, resultclass=_Result)
    result = runner.run(suite)
    outcomes = result.outcomes
    summary = {"ran": result.testsRun, "passed": sum(v == "passed" for v in outcomes.values()),
               "failed": len(result.failures), "errors": len(result.errors), "skipped": len(result.skipped)}
    if report:
        data = {"schema": "app.test-report/1", "summary": summary,
                "tests": [{"id": key, "status": value} for key, value in sorted(outcomes.items())]}
        pathlib.Path(report).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return 0 if result.wasSuccessful() and summary["ran"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))
