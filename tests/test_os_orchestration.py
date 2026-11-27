import copy
import json
import os
import pathlib
import subprocess
import tempfile
import time
import unittest

from engineering_os.orchestration import CoordinationError, TaskStore, canonical, sha, verify_state

ROOT = pathlib.Path(__file__).resolve().parents[1]
LEAD = {"id": "lead", "engine": "codex", "role": "orchestrator"}
CODER = {"id": "coder", "engine": "codex", "role": "development"}
CLAUDE = {"id": "designer", "engine": "claude-code", "role": "development"}
RECEIPTS = [{"kind": "unit-tests", "sha256": "a" * 64}]


class OrchestrationTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = pathlib.Path(self.folder.name)
        self.clock = [1000.0]
        self.store = TaskStore(self.root / "state", clock=lambda: self.clock[0])

    def spec(self, identifier="task-one", branch="codex/task-one", priority=0):
        return {"id": identifier, "project": "opaque-project", "branch": branch,
                "paths": ["src/module.py"], "title": "Synthetic test task", "priority": priority}

    def create(self, specification=None):
        return self.store.create_task(self.spec() if specification is None else specification,
                                      LEAD, self.store.snapshot()["revision"])

    def claim(self, task=None, actor=CODER, ttl=100):
        task = self.create() if task is None else task
        return self.store.claim(task["id"], actor, task["version"], ttl)

    def test_task_persists_and_is_private(self):
        task = self.create()
        resumed = TaskStore(self.store.directory)
        self.assertEqual(resumed.tasks()[0], task)
        self.assertEqual(self.store.directory.stat().st_mode & 0o777, 0o700)
        for path in self.store.directory.iterdir():
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertTrue(verify_state(resumed.snapshot()))

    def test_handover_between_engines_fences_old_worker(self):
        active = self.claim()
        handed = self.store.handover(active["id"], CODER, active["version"], active["lease"]["id"],
                                     "Continue the interface review.", RECEIPTS)
        self.assertIsNone(handed["lease"])
        next_owner = self.claim(handed, CLAUDE)
        with self.assertRaises(CoordinationError):
            self.store.renew(active["id"], CODER, next_owner["version"], active["lease"]["id"])
        self.assertEqual(next_owner["owner"]["engine"], "claude-code")
        self.assertEqual(next_owner["handover"]["from"], CODER)

    def test_three_independent_reviews_are_required(self):
        active = self.claim()
        task = self.store.submit(active["id"], CODER, active["version"], active["lease"]["id"], RECEIPTS)
        self.assertEqual(task["status"], "review")
        for index, role in enumerate(["testing", "security", "release"]):
            reviewer = {"id": "reviewer-" + role, "engine": "codex", "role": role}
            task = self.store.review(task["id"], reviewer, task["version"], "approved", RECEIPTS)
            self.assertEqual(task["status"], "done" if index == 2 else "review")
        self.assertEqual(len(task["approvals"]), 3)
        self.assertTrue(verify_state(self.store.snapshot()))

    def test_self_review_and_one_actor_in_multiple_review_roles_fail(self):
        active = self.claim()
        task = self.store.submit(active["id"], CODER, active["version"], active["lease"]["id"], RECEIPTS)
        with self.assertRaises(CoordinationError):
            self.store.review(task["id"], {**CODER, "role": "testing"}, task["version"], "approved", RECEIPTS)
        reviewer = {"id": "reviewer-one", "engine": "codex", "role": "testing"}
        task = self.store.review(task["id"], reviewer, task["version"], "approved", RECEIPTS)
        with self.assertRaises(CoordinationError):
            self.store.review(task["id"], {**reviewer, "role": "security"}, task["version"], "approved", RECEIPTS)

    def test_rejected_review_requires_recovery_and_fresh_receipts(self):
        active = self.claim()
        task = self.store.submit(active["id"], CODER, active["version"], active["lease"]["id"], RECEIPTS)
        task = self.store.review(task["id"], {"id": "qa", "engine": "codex", "role": "testing"}, task["version"], "rejected", RECEIPTS)
        self.assertEqual(task["status"], "blocked")
        with self.assertRaises(CoordinationError):
            self.store.claim(task["id"], CLAUDE, task["version"])
        recovered = self.store.recover(task["id"], LEAD, task["version"], RECEIPTS)
        self.assertEqual((recovered["status"], recovered["receipts"], recovered["approvals"]), ("pending", [], {}))

    def test_cas_versions_lease_expiry_and_explicit_recovery(self):
        task = self.claim(ttl=10)
        with self.assertRaises(CoordinationError):
            self.store.renew(task["id"], CODER, task["version"]-1, task["lease"]["id"])
        self.clock[0] += 10
        with self.assertRaises(CoordinationError):
            self.store.submit(task["id"], CODER, task["version"], task["lease"]["id"], RECEIPTS)
        recovered = self.store.recover(task["id"], LEAD, task["version"], RECEIPTS)
        new = self.claim(recovered, CLAUDE)
        self.assertNotEqual(new["lease"]["id"], task["lease"]["id"])
        with self.assertRaises(CoordinationError):
            self.store.fail(task["id"], CODER, new["version"], task["lease"]["id"], RECEIPTS)

    def test_branch_ownership_prevents_parallel_git_collisions(self):
        one = self.create()
        two = self.create(self.spec("task-two", branch=one["branch"]))
        self.claim(one)
        with self.assertRaises(CoordinationError):
            self.claim(two, CLAUDE)
        isolated = self.create(self.spec("task-three", branch="claude/isolated"))
        self.assertEqual(self.claim(isolated, CLAUDE)["status"], "active")

    def test_two_processes_cannot_claim_same_branch_tasks(self):
        one = self.create()
        two = self.create(self.spec("task-two", branch=one["branch"]))
        code = """
import json,sys,time,pathlib
from engineering_os.orchestration import TaskStore,CoordinationError
root=pathlib.Path(sys.argv[1]);task=sys.argv[2]
(root/('ready-'+task)).write_text('ready')
for attempt in range(200):
 if (root/'go').exists():break
 time.sleep(.01)
else:raise RuntimeError('start barrier timed out')
try:
 store=TaskStore(root/'state');store.claim(task,{'id':task,'engine':'codex','role':'development'},1)
 print('claimed')
except CoordinationError:print('blocked')
"""
        workers = [subprocess.Popen(["python3", "-c", code, str(self.root), task["id"]], cwd=ROOT,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for task in [one, two]]
        try:
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and len(list(self.root.glob("ready-*"))) != 2:
                time.sleep(.01)
            (self.root/"go").write_text("go")
            outputs = [worker.communicate(timeout=5) for worker in workers]
            self.assertEqual(sorted(out.strip() for out, _ in outputs), ["blocked", "claimed"])
            self.assertTrue(all(worker.returncode == 0 for worker in workers), outputs)
            self.assertEqual(sum(row["status"] == "active" for row in self.store.tasks()), 1)
            self.assertEqual(self.store.snapshot()["revision"], 3)
        finally:
            for worker in workers:
                if worker.poll() is None:
                    worker.kill()
                    worker.wait()

    def test_fail_recover_priority_and_wrong_actor(self):
        low = self.create(self.spec("later", priority=3))
        urgent = self.create(self.spec("urgent", branch="codex/urgent", priority=0))
        self.assertEqual(self.store.tasks()[0]["id"], urgent["id"])
        active = self.claim(low)
        with self.assertRaises(CoordinationError):
            self.store.fail(active["id"], CLAUDE, active["version"], active["lease"]["id"], RECEIPTS)
        failed = self.store.fail(active["id"], CODER, active["version"], active["lease"]["id"], RECEIPTS)
        self.assertEqual(failed["failures"], 1)
        with self.assertRaises(CoordinationError):
            self.store.recover(failed["id"], CODER, failed["version"], RECEIPTS)
        self.assertEqual(self.store.recover(failed["id"], LEAD, failed["version"], RECEIPTS)["status"], "pending")

    def test_checkpoint_restore_persists_current_owner_and_audit(self):
        active = self.claim()
        destination = self.root / "checkpoint.json"
        receipt = self.store.checkpoint(destination)
        resumed = TaskStore(self.root/"resumed", clock=lambda:self.clock[0])
        self.assertEqual(resumed.restore(destination)["state_sha256"], receipt["state_sha256"])
        self.assertEqual(resumed.snapshot(), self.store.snapshot())
        with self.assertRaises(CoordinationError):
            resumed.restore(destination)
        with self.assertRaises(CoordinationError):
            self.store.checkpoint(destination)
        self.assertEqual(resumed.tasks()[0]["lease"]["id"], active["lease"]["id"])

    def test_audit_detects_modified_tasks_and_events(self):
        self.create()
        original = self.store.snapshot()
        for change in [lambda d:d["tasks"]["task-one"].update(priority=2),
                       lambda d:d["events"][0].update(operation="claim")]:
            tampered = copy.deepcopy(original)
            change(tampered)
            with self.assertRaises(CoordinationError):
                verify_state(tampered)

    def test_rehashed_checkpoint_still_rejects_unsafe_scope(self):
        self.create()
        state = self.store.snapshot()
        state["tasks"]["task-one"]["paths"] = ["../secrets"]
        state["events"][-1]["tasks_sha256"] = sha(state["tasks"])
        event = state["events"][-1]
        event["sha256"] = sha({k:v for k,v in event.items() if k != "sha256"})
        destination = self.root/"unsafe.json"
        destination.write_bytes(canonical({"schema_version":1,"state":state,"state_sha256":sha(state)}))
        destination.chmod(0o600)
        resumed = TaskStore(self.root/"resumed")
        with self.assertRaises(CoordinationError):
            resumed.restore(destination)

    def test_unknown_fields_credential_shapes_and_unsafe_paths_refused(self):
        for path in ["../secret", "/etc/passwd", ".git/config", "src/../../secret", "src\\secret", "src/*", "src/\nsecret"]:
            with self.subTest(path=path), self.assertRaises(CoordinationError):
                self.create({**self.spec(), "paths":[path]})
        for branch in ["main", "master", "codex/../main", "claude/a.lock", "codex/a//b"]:
            with self.subTest(branch=branch), self.assertRaises(CoordinationError):
                self.create({**self.spec(), "branch":branch})
        for field in ["api_key", "password", "production_token"]:
            with self.assertRaises(CoordinationError):
                self.create({**self.spec(), field:"must-not-persist"})
        key = "gh" + "p_" + "a"*36
        with self.assertRaises(CoordinationError):
            self.create({**self.spec(), "title":key})
        self.assertEqual(self.store.snapshot()["revision"], 0)

    def test_private_directory_and_file_guards(self):
        exposed = self.root/"exposed"
        exposed.mkdir(mode=0o755)
        exposed.chmod(0o755)
        with self.assertRaises(CoordinationError):
            TaskStore(exposed)
        linked = self.root/"linked"
        linked.symlink_to(self.store.directory, target_is_directory=True)
        with self.assertRaises(CoordinationError):
            TaskStore(linked)
        repo = self.root/"repository"
        (repo/".git").mkdir(parents=True)
        (repo/".git/HEAD").write_text("ref: refs/heads/main\n")
        with self.assertRaises(CoordinationError):
            TaskStore(repo/"private-state")
        self.store.path.unlink()
        outside = self.root/"outside.json"
        outside.write_text("{}")
        outside.chmod(0o600)
        self.store.path.symlink_to(outside)
        with self.assertRaises((CoordinationError,OSError)):
            self.store.snapshot()

    def test_nonfinite_ttl_and_stale_revision_fail_without_mutation(self):
        task = self.create()
        with self.assertRaises(CoordinationError):
            self.store.create_task(self.spec("new", branch="codex/new"), LEAD, 0)
        for ttl in [float("nan"),float("inf"),True,0,3601,10**1000]:
            with self.subTest(ttl=ttl), self.assertRaises(CoordinationError):
                self.store.claim(task["id"], CODER, task["version"], ttl)
        self.assertEqual(self.store.snapshot()["revision"], 1)

    def test_cli_status_is_readable_and_does_not_start_agents(self):
        result = subprocess.run(["python3","-m","engineering_os.orchestration","--state-dir",str(self.store.directory),"status"],cwd=ROOT,capture_output=True,text=True,check=True)
        self.assertEqual(json.loads(result.stdout)["runtime"], "manual local coordination; no daemon")
        self.assertEqual(result.stderr, "")

    def test_router_respects_role_engine_priority_and_occupied_branch(self):
        first = self.create(self.spec("later", priority=3))
        urgent = self.create({**self.spec("urgent", branch="claude/urgent", priority=0), "engine":"claude-code"})
        security = self.create({**self.spec("security", branch="codex/security", priority=0), "role":"security"})
        self.assertEqual(self.store.route(CLAUDE)["id"], urgent["id"])
        self.assertEqual(self.store.route(CODER)["id"], first["id"])
        with self.assertRaises(CoordinationError):
            self.claim(urgent, CODER)
        active = self.claim(first)
        blocked = self.create(self.spec("same-branch", branch=active["branch"], priority=0))
        self.assertIsNone(self.store.route(CODER))
        self.assertEqual(self.store.route({**CODER,"role":"security"})["id"],security["id"])
