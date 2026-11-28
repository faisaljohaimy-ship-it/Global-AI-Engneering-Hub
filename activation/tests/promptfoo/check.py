"""Check a Promptfoo result file: one assertion passed, one failed as written, none errored."""
import json
import sys

stats = json.load(open(sys.argv[1]))["results"]["stats"]
expected = {"successes": 1, "failures": 1, "errors": 0}
found = {key: stats[key] for key in expected}
print(json.dumps({"expected": expected, "found": found}))
sys.exit(0 if found == expected else 1)
