"""Review fix w2-memory-heal-orch M3: a task's reviewer is never anyone who held or worked it.

Before the fix ``TaskStore.review`` compared the reviewer only with the current owner:
alice could claim, work and hand a task over to bob, then approve bob's submission as the
testing reviewer and the task reached ``done``; the same after fail -> recover -> claim
by another actor. Independence is now checked against every claim, renew, handover,
submit and fail actor in the task's audit history, at review time and in verify_state.
"""

import pathlib
import tempfile
import unittest

from engineering_os.orchestration import CoordinationError, TaskStore, producers, sha, verify_state

ORCH = {"id": "orch", "engine": "codex", "role": "orchestrator"}
ALICE = {"id": "alice", "engine": "codex", "role": "development"}
BOB = {"id": "bob", "engine": "claude-code", "role": "development"}
R = [{"kind": "test", "sha256": "a" * 64}]


def reviewer(name, role):
    return {"id": name, "engine": "codex", "role": role}


class ReviewerHistoryTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="gaie-m3-")
        self.addCleanup(self.folder.cleanup)
        self.clock = [1000.0]
        self.store = TaskStore(pathlib.Path(self.folder.name) / "state", clock=lambda: self.clock[0])
        self.task = self.store.create_task({"id": "feat", "project": "p", "branch": "codex/feat", "paths": ["src/feat.py"],
                                            "title": "feature", "priority": 1}, ORCH, 0)

    def handed_over_and_submitted(self):
        t = self.store.claim("feat", ALICE, self.task["version"])
        t = self.store.renew("feat", ALICE, t["version"], t["lease"]["id"])
        t = self.store.handover("feat", ALICE, t["version"], t["lease"]["id"], "alice wrote all of src/feat.py", R)
        t = self.store.claim("feat", BOB, t["version"])
        return self.store.submit("feat", BOB, t["version"], t["lease"]["id"], R)

    def assert_refused(self, task, actor):
        before = self.store.snapshot()["revision"]
        with self.assertRaises(CoordinationError) as caught:
            self.store.review("feat", actor, task["version"], "approved", R)
        self.assertIn("held or worked", str(caught.exception))
        self.assertEqual(self.store.snapshot()["revision"], before)
        self.assertEqual(self.store.snapshot()["tasks"]["feat"]["approvals"], {})

    def test_producer_cannot_review_after_a_handover(self):
        task = self.handed_over_and_submitted()
        for role in ("testing", "security", "release"):
            with self.subTest(role=role):
                self.assert_refused(task, reviewer("alice", role))
        self.assertEqual(producers(self.store.snapshot(), "feat"), {"alice", "bob"})
        for role, name in (("testing", "carol"), ("security", "dave"), ("release", "erin")):
            task = self.store.review("feat", reviewer(name, role), task["version"], "approved", R)
        self.assertEqual(task["status"], "done")
        self.assertTrue(verify_state(self.store.snapshot()))

    def test_failed_producer_cannot_review_after_recovery(self):
        t = self.store.claim("feat", ALICE, self.task["version"])
        t = self.store.fail("feat", ALICE, t["version"], t["lease"]["id"], R)
        t = self.store.recover("feat", ORCH, t["version"], R)
        t = self.store.claim("feat", BOB, t["version"])
        task = self.store.submit("feat", BOB, t["version"], t["lease"]["id"], R)
        self.assertIsNone(task["handover"])
        self.assert_refused(task, reviewer("alice", "testing"))
        with self.assertRaises(CoordinationError):  # the current owner, refused as before
            self.store.review("feat", reviewer("bob", "testing"), task["version"], "approved", R)

    def test_expired_holder_cannot_review_after_recovery(self):
        t = self.store.claim("feat", ALICE, self.task["version"], ttl=10)
        self.clock[0] += 11
        t = self.store.recover("feat", ORCH, t["version"], R)
        t = self.store.claim("feat", BOB, t["version"])
        task = self.store.submit("feat", BOB, t["version"], t["lease"]["id"], R)
        self.assert_refused(task, reviewer("alice", "security"))

    def test_creator_and_unrelated_reviewers_stay_allowed(self):
        t = self.store.claim("feat", BOB, self.task["version"])
        task = self.store.submit("feat", BOB, t["version"], t["lease"]["id"], R)
        task = self.store.review("feat", reviewer("orch", "testing"), task["version"], "approved", R)
        self.assertEqual(task["approvals"]["testing"]["actor"]["id"], "orch")

    def test_verify_state_refuses_a_resealed_producer_approval(self):
        task = self.handed_over_and_submitted()
        for role, name in (("testing", "carol"), ("security", "dave"), ("release", "erin")):
            task = self.store.review("feat", reviewer(name, role), task["version"], "approved", R)
        state = self.store.snapshot()
        state["tasks"]["feat"]["approvals"]["testing"]["actor"] = reviewer("alice", "testing")
        last = state["events"][-1]
        last["tasks_sha256"] = sha(state["tasks"])
        last["sha256"] = sha({key: value for key, value in last.items() if key != "sha256"})
        with self.assertRaises(CoordinationError) as caught:
            verify_state(state)
        self.assertIn("held or worked", str(caught.exception))
        state["tasks"]["feat"]["approvals"]["testing"]["actor"] = reviewer("carol", "testing")
        last["tasks_sha256"] = sha(state["tasks"])
        last["sha256"] = sha({key: value for key, value in last.items() if key != "sha256"})
        self.assertTrue(verify_state(state))


if __name__ == "__main__":
    unittest.main()
