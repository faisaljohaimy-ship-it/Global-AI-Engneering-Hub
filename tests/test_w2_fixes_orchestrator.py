"""Review fixes w2-memory-heal-orch L3 (verify_plan rechecks role ownership) and L5.

L3: verify_plan checked only task-to-task overlaps and the plain SHA-256 digest, which
anyone can recompute. An issued plan edited to add another role's path to a task (and
its store scope), then re-sealed, was accepted and its task enqueued with that scope.
verify_plan now rechecks ownership against the role registry the same way plan() does
and requires the store scope to match the task's paths.
"""

import copy
import pathlib
import tempfile
import unittest

from engineering_os import orchestrator as o
from engineering_os.contracts import sha256
from engineering_os.orchestrator import OrchestratorError, OwnershipConflict, plan, verify_plan

NOW = "2026-11-28T06:00:00Z"
ROLE = "master-build-engine-engineer"
DOCUMENT = o._roles_document(None, o.ROOT)[0]
OWNER = {path: role["id"] for role in DOCUMENT["roles"] for path in role["owns"]}
FOREIGN = next(path for path, rid in sorted(OWNER.items()) if rid != ROLE and "*" not in path)


def issued():
    return plan({"goal": "g", "tasks": [{"id": "a", "paths": ["workspace/x/a"], "role": ROLE}]}, now=NOW)


def reseal(value):
    value["plan_sha256"] = sha256({key: item for key, item in value.items() if key != "plan_sha256"})
    return value


class VerifyPlanOwnershipTests(unittest.TestCase):
    def test_plan_refuses_the_foreign_path_in_the_first_place(self):
        with self.assertRaises(OwnershipConflict):
            plan({"goal": "g", "tasks": [{"id": "a", "paths": ["workspace/x/a", FOREIGN], "role": ROLE}]}, now=NOW)

    def test_a_resealed_plan_with_a_foreign_path_is_refused_and_never_enqueued(self):
        edited = copy.deepcopy(issued())
        edited["tasks"][0]["paths"] = sorted(edited["tasks"][0]["paths"] + [FOREIGN])
        edited["tasks"][0]["store_paths"] = sorted(edited["tasks"][0]["store_paths"] + [FOREIGN])
        reseal(edited)
        with self.assertRaises(OwnershipConflict) as caught:
            verify_plan(edited)
        conflict = caught.exception.conflicts[0]
        self.assertEqual((conflict["kind"], conflict["paths"]), ("foreign-owner", [FOREIGN]))
        self.assertIn(OWNER[FOREIGN], conflict["owners"])

    def test_a_store_scope_wider_than_the_paths_is_refused(self):
        edited = copy.deepcopy(issued())
        edited["tasks"][0]["store_paths"] = sorted(edited["tasks"][0]["store_paths"] + [FOREIGN])
        reseal(edited)
        with self.assertRaises(OrchestratorError) as caught:
            verify_plan(edited)
        self.assertIn("store scope", str(caught.exception))

    def test_valid_plans_still_verify_unchanged(self):
        for value in (issued(), plan("gaie-20-layer", now=NOW)):
            before = copy.deepcopy(value)
            self.assertIs(verify_plan(value), value)
            self.assertEqual(value, before)
        with tempfile.TemporaryDirectory(prefix="gaie-l3-") as scratch:
            state = pathlib.Path(scratch) / "state"
            state.mkdir(mode=0o700)
            value = verify_plan(issued())
            run = o.lifecycle(value["tasks"][0], state_dir=state)
            run.enqueue()
            self.assertEqual(run.store.tasks()[0]["paths"], ["workspace/x/a"])


if __name__ == "__main__":
    unittest.main()
