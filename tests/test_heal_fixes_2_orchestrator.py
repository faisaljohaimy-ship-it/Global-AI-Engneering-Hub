"""Follow-up fixes recheck-w2-heal (f, g) in the orchestrator.

(f) Lifecycle.__init__ checked the review, grant and store role but not the task's paths, its
store scope or ownership, so an edited task handed straight to lifecycle() (no verify_plan) was
enqueued with a path another role owns. It now rechecks them against governance/agent-roles.json
as plan() does, and against the frozen areas the caller names. verify_plan took the frozen areas
from the plan itself, so a re-sealed plan could empty its own frozen list and move a task into
the area plan() refused; the verifier can now name the frozen areas it requires.

(g) review_assignment(roles=<dict>) used a caller's role document unchecked, so a malformed one
raised a bare KeyError or TypeError; it now raises OrchestratorError.

State lives in temporary directories only; nothing is executed.
"""

import copy
import pathlib
import tempfile
import unittest

from engineering_os import orchestrator as o
from engineering_os.orchestrator import (OrchestratorError, OwnershipConflict, ReviewIndependenceError, lifecycle, plan,
                                         review_assignment, sha256, verify_plan)

NOW = "2026-11-28T06:00:00Z"
ROLE = "master-build-engine-engineer"
DOCUMENT = o._roles_document(None, o.ROOT)[0]
OWNER = {path: role["id"] for role in DOCUMENT["roles"] for path in role["owns"]}
FOREIGN = next(path for path, rid in sorted(OWNER.items()) if rid != ROLE and "*" not in path)


def issued(paths=("workspace/x/a",), frozen=()):
    return plan({"goal": "g", "tasks": [{"id": "a", "paths": list(paths), "role": ROLE}]}, frozen=list(frozen), now=NOW)


def reseal(value):
    value["plan_sha256"] = sha256({key: item for key, item in value.items() if key != "plan_sha256"})
    return value


class LifecycleScopeTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="gaie-hf2f-")
        self.addCleanup(folder.cleanup)
        self.state = pathlib.Path(folder.name) / "state"
        self.task = issued()["tasks"][0]

    def refused(self, task, error=OrchestratorError, **kw):
        with self.assertRaises(error) as caught:
            lifecycle(task, state_dir=self.state, **kw)
        self.assertFalse(self.state.exists(), "nothing may be created for a refused task")
        return caught.exception

    def test_an_edited_task_with_a_foreign_path_is_never_enqueued(self):
        task = copy.deepcopy(self.task)
        task["paths"] = sorted(task["paths"] + [FOREIGN])
        task["store_paths"] = sorted(task["store_paths"] + [FOREIGN])
        error = self.refused(task, OwnershipConflict)
        conflict = error.conflicts[0]
        self.assertEqual((conflict["kind"], conflict["paths"]), ("foreign-owner", [FOREIGN]))
        self.assertIn(OWNER[FOREIGN], conflict["owners"])

    def test_a_store_scope_that_differs_from_the_paths_is_refused(self):
        wider = copy.deepcopy(self.task)
        wider["store_paths"] = sorted(wider["store_paths"] + [FOREIGN])
        self.assertIn("store scope", str(self.refused(wider)))
        narrower = copy.deepcopy(self.task)
        narrower["paths"] = sorted(narrower["paths"] + ["workspace/x/b"])
        self.assertIn("store scope", str(self.refused(narrower)))

    def test_paths_must_be_present_and_canonical(self):
        missing = {key: value for key, value in self.task.items() if key != "paths"}
        self.assertIn("a plan task", str(self.refused(missing)))
        for paths in (["workspace/x/b", "workspace/x/a"], ["workspace/x/a", "workspace/x/a"], ["workspace/../x"], [], "workspace/x/a"):
            with self.subTest(paths=paths):
                task = dict(copy.deepcopy(self.task), paths=paths)
                self.refused(task)

    def test_a_frozen_area_the_caller_names_is_enforced(self):
        error = self.refused(self.task, OwnershipConflict, frozen=["workspace/x"])
        self.assertEqual(error.conflicts[0]["kind"], "frozen")
        self.refused(self.task, frozen=["../x"])

    def test_a_planned_task_still_enqueues_with_its_planned_scope(self):
        run = lifecycle(self.task, state_dir=self.state, frozen=["swarm"])
        self.assertEqual(run.enqueue()["created"], True)
        self.assertEqual(run.store.tasks()[0]["paths"], ["workspace/x/a"])


class VerifyPlanFrozenTests(unittest.TestCase):
    def emptied(self):
        """The reviewer's case: frozen [] and the task moved into the area plan(frozen=...) refused."""
        value = copy.deepcopy(issued(frozen=["workspace/y"]))
        value["frozen"] = []
        value["tasks"][0]["paths"] = ["workspace/y/b"]
        value["tasks"][0]["store_paths"] = o._store_scope(["workspace/y/b"])
        value["ownership"] = {"workspace/y/b": "a"}
        return reseal(value)

    def test_plan_refuses_the_task_in_the_first_place(self):
        with self.assertRaises(OwnershipConflict):
            issued(paths=["workspace/y/b"], frozen=["workspace/y"])

    def test_a_resealed_plan_that_drops_a_required_frozen_area_is_refused(self):
        with self.assertRaises(OwnershipConflict) as caught:
            verify_plan(self.emptied(), frozen=["workspace/y"])
        self.assertEqual([(c["kind"], c["paths"]) for c in caught.exception.conflicts], [("frozen-dropped", ["workspace/y"])])

    def test_the_required_areas_also_bind_the_tasks(self):
        value = issued(frozen=["swarm"])
        with self.assertRaises(OwnershipConflict) as caught:
            verify_plan(value, frozen=["workspace/x"])  # required but not in the plan
        self.assertEqual(caught.exception.conflicts[0]["kind"], "frozen-dropped")
        value = reseal(dict(copy.deepcopy(value), frozen=["swarm", "workspace/x"]))
        with self.assertRaises(OwnershipConflict) as caught:
            verify_plan(value, frozen=["workspace/x"])
        self.assertEqual(caught.exception.conflicts[0]["kind"], "frozen")

    def test_a_plan_that_keeps_or_widens_the_frozen_areas_verifies(self):
        value = issued(frozen=["workspace/y"])
        self.assertIs(verify_plan(value, frozen=["workspace/y"]), value)
        self.assertIs(verify_plan(value, frozen=["workspace/y/deep"]), value)  # covered by the planned area
        self.assertIs(verify_plan(value), value)
        twenty = plan("gaie-20-layer", now=NOW)
        self.assertIs(verify_plan(twenty), twenty)

    def test_a_non_canonical_frozen_list_in_the_plan_is_refused(self):
        for frozen in (["workspace/z", "workspace/y"], ["../y"], "workspace/y", [7]):
            with self.subTest(frozen=frozen), self.assertRaises(OrchestratorError):
                verify_plan(reseal(dict(copy.deepcopy(issued()), frozen=frozen)))
        with self.assertRaises(OrchestratorError):
            verify_plan(issued(), frozen=["../y"])


class MalformedRoleDocumentTests(unittest.TestCase):
    TASK = {"id": "t", "role": ROLE}

    def test_a_malformed_document_raises_the_module_error(self):
        roles = DOCUMENT["roles"]
        cases = {"entry without reviewer": {"roles": [{k: v for k, v in r.items() if k != "reviewer"} for r in roles]},
                 "non-dict entry": {"roles": roles + [7]},
                 "roles is text": {"roles": "x"},
                 "roles is None": {"roles": None},
                 "entry without id": {"roles": [{"reviewer": True}] + roles},
                 "unhashable id": {"roles": [{"id": ["x"], "reviewer": True}] + roles},
                 "reviewer flag is text": {"roles": [dict(r, reviewer="no") for r in roles]},
                 "duplicate id": {"roles": roles + [roles[0]]}}
        for name, document in cases.items():
            with self.subTest(name=name):
                try:
                    review_assignment(self.TASK, roles=document)
                except OrchestratorError as error:
                    self.assertIn("malformed role document", str(error))
                else:
                    self.fail("accepted a malformed role document")

    def test_a_malformed_task_raises_the_module_error(self):
        for task in ({"id": "t", "role": [ROLE]}, {"id": "t", "role": ROLE, "reviewer": ["x"]}, {"id": "t"}, None, "t"):
            with self.subTest(task=task), self.assertRaises(OrchestratorError):
                review_assignment(task, roles=DOCUMENT)

    def test_well_formed_documents_behave_as_before(self):
        self.assertEqual(review_assignment(self.TASK, roles=DOCUMENT), review_assignment(self.TASK))
        subset = dict(DOCUMENT, roles=[r for r in DOCUMENT["roles"] if r["id"] not in o.PANEL_CANDIDATES["testing"]])
        with self.assertRaises(ReviewIndependenceError):
            review_assignment(self.TASK, roles=subset)
        with self.assertRaises(OrchestratorError):
            o.engine("review-assignment", {"task": {"id": "t", "role": "nobody"}})


if __name__ == "__main__":
    unittest.main()
