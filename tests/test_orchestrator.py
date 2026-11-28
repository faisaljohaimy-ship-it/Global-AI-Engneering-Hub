"""Tests for the L03 Adaptive Agent Orchestration engine (engineering_os/orchestrator.py)."""
import copy
import datetime
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

from engineering_os import governor, orchestrator
from engineering_os.contracts import sha256, side_effect_rank, validate_grant
from engineering_os.economics import recommend_concurrency
from engineering_os.layers import load_roles
from engineering_os.orchestrator import (
    GrantEscalation, LifecycleError, OrchestratorError, OwnershipConflict, ReviewIndependenceError, covers,
    detect_conflicts, grant_within_default, host_cap, lifecycle, overlaps, plan, registry_conflicts,
    review_assignment, scenario_h, schedule, verify_plan, worktree_plan)

ROOT = pathlib.Path(__file__).resolve().parents[1]
NOW = "2026-11-28T06:36:23Z"
EVIDENCE = ROOT / "docs/evidence/gaie-20-layers/scenario-h.json"
DIGEST = {"kind": "unit-tests", "sha256": "a" * 64}
ROLES = load_roles(ROOT)
BY_ID = {role["id"]: role for role in ROLES["roles"]}
TWENTY = plan("gaie-20-layer", now=NOW)


def wave(agents=4, seconds=600, verified=4, tokens=400_000, conflicts=0, failures=0, **more):
    return {"agents": agents, "duration_seconds": seconds, "tasks_verified": verified, "tokens": tokens,
            "conflicts": conflicts, "failures": failures, **more}


def goal(*tasks):
    return {"goal": "synthetic-goal", "tasks": list(tasks)}


def static(path):
    return path.split("*")[0].rstrip("/") if "*" in path else path


class PlanTests(unittest.TestCase):
    def test_twenty_role_plan_has_no_path_overlap_and_independent_reviewers(self):
        tasks = TWENTY["tasks"]
        self.assertEqual(len(tasks), 20)
        self.assertEqual(sorted(t["role"] for t in tasks), sorted(BY_ID))
        self.assertEqual(len(TWENTY["agents"]), 20)
        self.assertEqual([len(w) for w in TWENTY["waves"]], [3, 13, 2, 2])
        # Independent check, not the module's helper: no path is a prefix directory of another's.
        scopes = [(t["id"], static(p)) for t in tasks for p in t["paths"]]
        for i, (first, a) in enumerate(scopes):
            for second, b in scopes[i + 1:]:
                self.assertFalse(a == b or a.startswith(b + "/") or b.startswith(a + "/"), (first, a, second, b))
        self.assertEqual(len(TWENTY["ownership"]), sum(len(t["paths"]) for t in tasks))
        for task in tasks:
            review = task["review"]
            self.assertNotEqual(review["reviewer"], task["role"])
            self.assertNotIn(task["role"], review["panel"].values())
            self.assertEqual(sorted(review["panel"]), ["release", "security", "testing"])
            self.assertEqual(len(set(review["panel"].values())), 3)
        self.assertTrue(all(TWENTY["checks"].values()))
        self.assertEqual(TWENTY["provider_calls"], 0)
        verify_plan(TWENTY)

    def test_plan_is_hierarchical_deterministic_and_dependency_ordered(self):
        self.assertEqual(plan("gaie-20-layer", now=NOW)["plan_sha256"], TWENTY["plan_sha256"])
        self.assertEqual([m["id"] for m in TWENTY["hierarchy"]["milestones"]],
                         ["team-a", "team-b", "team-c", "team-d", "team-e", "team-f", "team-g", "team-h"])
        self.assertEqual(TWENTY["hierarchy"]["milestone_waves"][0], ["team-a"])
        wave_of = {t["id"]: t["wave"] for t in TWENTY["tasks"]}
        for task in TWENTY["tasks"]:
            for dependency in task["depends_on"]:
                self.assertLess(wave_of[dependency], wave_of[task["id"]])
        assurance = next(t for t in TWENTY["tasks"] if t["id"] == "independent-assurance-engineer")
        self.assertIn("master-build-engine-engineer", assurance["depends_on"])
        self.assertEqual(TWENTY["receipts"]["decompose"]["mode"], "deterministic")
        self.assertTrue(TWENTY["critical_path"][0] == "chief-engineering-architect")

    def test_roles_are_assigned_by_owned_paths_then_layers(self):
        result = plan(goal({"id": "reasoning-fix", "paths": ["engineering_os/reasoning.py"]},
                           {"id": "workspace-tests", "paths": ["workspace/demo/tests"], "layers": ["L17"]},
                           {"id": "cinema", "paths": ["skills/gaie-cinematic/SKILL.md"]}), now=NOW)
        rows = {t["id"]: t for t in result["tasks"]}
        self.assertEqual(rows["reasoning-fix"]["role"], "engineering-reasoning-engineer")
        self.assertEqual(rows["reasoning-fix"]["assignment"]["rule"], "owned-paths")
        self.assertEqual(rows["workspace-tests"]["role"], "testing-self-healing-engineer")
        self.assertEqual(rows["workspace-tests"]["assignment"]["rule"], "layers")
        self.assertEqual(rows["cinema"]["role"], "cinematic-production-engineer")
        with self.assertRaises(OrchestratorError):  # nobody owns it and no layer is given
            plan(goal({"id": "orphan", "paths": ["workspace/demo/x.py"]}), now=NOW)
        with self.assertRaises(OrchestratorError):  # a declared role outside the plan's roles
            plan(goal({"id": "x", "paths": ["workspace/x"], "role": "master-build-engine-engineer"}),
                 roles=["testing-self-healing-engineer"], now=NOW)

    def test_role_subset_skips_absent_teams_but_keeps_order(self):
        result = plan("subset", roles=["chief-engineering-architect", "independent-assurance-engineer",
                                       "github-integration-release-engineer"], now=NOW)
        self.assertEqual([[p["task"] for p in w] for w in result["waves"]],
                         [["chief-engineering-architect"], ["independent-assurance-engineer"],
                          ["github-integration-release-engineer"]])
        with self.assertRaises(OrchestratorError):
            plan("subset", roles=["not-a-role"], now=NOW)

    def test_max_agents_caps_every_wave_and_per_role_adds_instances(self):
        small = plan("gaie-20-layer", max_agents=5, now=NOW)
        self.assertTrue(all(len(w) <= 5 for w in small["waves"]))
        self.assertEqual(sum(len(w) for w in small["waves"]), 20)
        self.assertGreater(len(small["waves"]), 4)
        for bad in (0, 21, True, 2.5):
            with self.subTest(max_agents=bad), self.assertRaises(OrchestratorError):
                plan("gaie-20-layer", max_agents=bad, now=NOW)
        tasks = [{"id": f"part-{n}", "paths": [f"workspace/demo/part-{n}"], "role": "master-build-engine-engineer"}
                 for n in range(4)]
        one = plan(goal(*tasks), now=NOW)
        two = plan(goal(*tasks), per_role=2, now=NOW)
        self.assertEqual([len(w) for w in one["waves"]], [1, 1, 1, 1])
        self.assertEqual([len(w) for w in two["waves"]], [2, 2])
        self.assertEqual(sorted(a["id"] for a in two["agents"]),
                         ["master-build-engine-engineer-1", "master-build-engine-engineer-2"])
        self.assertEqual(len({a["branch"] for a in two["agents"]}), 2)

    def test_requirement_spec_becomes_build_work_in_its_workspace(self):
        from engineering_os.requirements import parse
        spec = parse("Build a new project management system with tasks and projects", language="en")
        result = plan(spec, per_role=2, max_agents=8, now=NOW)
        rows = {t["id"]: t for t in result["tasks"]}
        features = [t for t in result["tasks"] if t["id"].startswith("feature-")]
        self.assertEqual(len(features), len(spec["features"]))
        self.assertTrue(all(t["role"] == "master-build-engine-engineer" for t in features))
        self.assertTrue(all(p.startswith("workspace/project-management/") for t in result["tasks"] for p in t["paths"]))
        self.assertEqual(result["waves"][0][0]["task"], "architecture")
        self.assertEqual(result["waves"][-1][0]["task"], "release")
        self.assertTrue(all("data-model" in t["depends_on"] for t in features))
        self.assertEqual(rows["tests"]["grant"]["paths"], ["workspace/project-management/tests"])
        self.assertEqual(rows["tests"]["grant"]["max_side_effect"], "workspace-write")
        broken = copy.deepcopy(spec)
        broken["features"] = "not a list"
        with self.assertRaises(OrchestratorError):
            plan(broken, now=NOW)

    def test_cycles_unknown_dependencies_and_bad_paths_are_refused(self):
        cases = [
            goal({"id": "a", "paths": ["workspace/a"], "role": "master-build-engine-engineer", "depends_on": ["b"]},
                 {"id": "b", "paths": ["workspace/b"], "role": "master-build-engine-engineer", "depends_on": ["a"]}),
            goal({"id": "a", "paths": ["workspace/a"], "role": "master-build-engine-engineer", "depends_on": ["ghost"]}),
            goal({"id": "a", "paths": ["../outside"], "role": "master-build-engine-engineer"}),
            goal({"id": "a", "paths": ["/etc/passwd"], "role": "master-build-engine-engineer"}),
            goal({"id": "a", "paths": [".git/config"], "role": "master-build-engine-engineer"}),
            goal({"id": "a", "paths": ["*"], "role": "master-build-engine-engineer"}),
            goal({"id": "a", "paths": [], "role": "master-build-engine-engineer"}),
            goal({"id": "A", "paths": ["workspace/a"], "role": "master-build-engine-engineer"}),
            goal({"id": "a", "paths": ["workspace/a"], "role": "master-build-engine-engineer", "shell": "rm"}),
            {"goal": "g"},
        ]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(OrchestratorError):
                plan(case, now=NOW)

    def test_changed_plans_are_refused(self):
        changed = copy.deepcopy(TWENTY)
        changed["tasks"][0]["paths"].append("engineering_os/orchestrator.py")
        with self.assertRaises(OrchestratorError):
            verify_plan(changed)
        resealed = copy.deepcopy(TWENTY)
        resealed["tasks"][3]["review"]["reviewer"] = resealed["tasks"][3]["role"]
        resealed["plan_sha256"] = sha256({k: v for k, v in resealed.items() if k != "plan_sha256"})
        with self.assertRaises(ReviewIndependenceError):
            verify_plan(resealed)
        with self.assertRaises(OrchestratorError):
            schedule(changed, [])


class ConflictTests(unittest.TestCase):
    def test_overlap_rules(self):
        positive = [("a/b.py", "a/b.py"), ("a", "a/b.py"), ("skills/x/*", "skills/x/SKILL.md"), ("docs/*", "docs/a/b.md"),
                    ("skills/x/*", "skills/x"), ("a/*.py", "a/b/c.py"), ("pkg/m*", "pkg/mo*"), ("tests", "tests/x/*")]
        negative = [("a/b.py", "a/b.pyc"), ("a/b", "a/bc"), ("skills/x/*", "skills/y/*"), ("tests/x.py", "tests/fixtures/*"),
                    ("AGENTS.md", ".claude/*"), ("workspace/p/tests", "workspace/p/docs/SECURITY.md")]
        for a, b in positive:
            with self.subTest(a=a, b=b):
                self.assertTrue(overlaps(a, b) and overlaps(b, a))
        for a, b in negative:
            with self.subTest(a=a, b=b):
                self.assertFalse(overlaps(a, b) or overlaps(b, a))
        self.assertTrue(covers("workspace/*", "workspace/p/tests"))
        self.assertTrue(covers("skills/x/*", "skills/x"))
        self.assertFalse(covers("engineering_os/healing.py", "engineering_os"))

    def test_conflicting_ownership_between_tasks_is_detected(self):
        cases = {
            "same file": (["workspace/app/main.py"], ["workspace/app/main.py"]),
            "directory and file": (["workspace/app"], ["workspace/app/main.py"]),
            "pattern and file": (["workspace/app/*"], ["workspace/app/lib/x.py"]),
        }
        for name, (first, second) in cases.items():
            with self.subTest(name), self.assertRaises(OwnershipConflict) as caught:
                plan(goal({"id": "one", "paths": first, "role": "master-build-engine-engineer"},
                          {"id": "two", "paths": second, "role": "master-upgrade-engine-engineer"}), now=NOW)
            self.assertEqual(caught.exception.conflicts[0]["kind"], "task-overlap")
            self.assertEqual(caught.exception.conflicts[0]["tasks"], ["one", "two"])

    def test_task_writing_another_roles_owned_path_is_a_conflict(self):
        with self.assertRaises(OwnershipConflict) as caught:
            plan(goal({"id": "steal", "paths": ["engineering_os/governor.py"], "role": "master-build-engine-engineer"}),
                 now=NOW)
        conflict = caught.exception.conflicts[0]
        self.assertEqual(conflict["kind"], "foreign-owner")
        self.assertEqual(conflict["owners"], ["agent-isolation-security-engineer"])
        with self.assertRaises(OwnershipConflict):  # a directory that contains another role's files
            plan(goal({"id": "wide", "paths": ["engineering_os"], "role": "engineering-reasoning-engineer"}), now=NOW)

    def test_frozen_areas_of_another_session_are_conflicts(self):
        with self.assertRaises(OwnershipConflict) as caught:
            plan("gaie-20-layer", frozen=["swarm", ".claude/settings.json"], now=NOW)
        kinds = {(c["kind"], c["tasks"][0]) for c in caught.exception.conflicts}
        self.assertIn(("frozen", "adaptive-agent-orchestration-engineer"), kinds)  # owns swarm/scheduler.py
        self.assertIn(("frozen", "agent-isolation-security-engineer"), kinds)      # owns swarm/phase3/cage.py
        self.assertIn(("frozen", "claude-code-integration-engineer"), kinds)       # owns .claude/*
        unaffected = plan(goal({"id": "ok", "paths": ["workspace/ok"], "role": "master-build-engine-engineer"}),
                          frozen=["swarm"], now=NOW)
        self.assertEqual(unaffected["frozen"], ["swarm"])

    def test_registry_with_overlapping_owned_paths_is_detected(self):
        self.assertEqual(registry_conflicts(ROLES), [])
        changed = copy.deepcopy(ROLES)
        BY = {role["id"]: role for role in changed["roles"]}
        BY["master-build-engine-engineer"]["owns"].append("engineering_os/reasoning.py")
        found = registry_conflicts(changed)
        self.assertEqual(found[0]["roles"], ["engineering-reasoning-engineer", "master-build-engine-engineer"])
        with self.assertRaises(OwnershipConflict) as caught:
            plan("gaie-20-layer", roles=changed, now=NOW)
        self.assertIn("foreign-owner", {c["kind"] for c in caught.exception.conflicts})

    def test_detect_conflicts_returns_every_conflict(self):
        tasks = [{"id": "a", "role": "master-build-engine-engineer", "paths": ["workspace/x", "engineering_os/memory.py"]},
                 {"id": "b", "role": "master-upgrade-engine-engineer", "paths": ["workspace/x/y"]}]
        kinds = sorted(c["kind"] for c in detect_conflicts(tasks, document=ROLES, frozen=["workspace/x/y/z"]))
        self.assertEqual(kinds, ["foreign-owner", "frozen", "frozen", "task-overlap"])


class GrantTests(unittest.TestCase):
    def test_grants_never_exceed_role_defaults(self):
        for task in TWENTY["tasks"]:
            role, grant = BY_ID[task["role"]], task["grant"]
            with self.subTest(task=task["id"]):
                validate_grant(grant)
                self.assertTrue(grant_within_default(grant, role))
                template = role["default_grant"]
                self.assertLessEqual(set(grant["engines"]), set(template["engines"]))
                for engine, actions in grant["engines"].items():
                    self.assertLessEqual(set(actions), set(template["engines"][engine]))
                self.assertLessEqual(side_effect_rank(grant["max_side_effect"]), side_effect_rank(template["max_side_effect"]))
                self.assertEqual(grant["approvals"], [])
                self.assertEqual(grant["expires_at"], "2026-11-28T10:36:23Z")

    def test_governor_enforces_the_task_grants(self):
        actions = orchestrator._actions(orchestrator._engines(ROOT))
        at = "2026-11-28T07:00:00Z"
        for task in TWENTY["tasks"]:
            grant = task["grant"]
            for engine, granted in grant["engines"].items():
                for action in granted:
                    allowed = governor.check(grant, engine, action, actions[engine][action], now=at)
                    self.assertTrue(allowed["allowed"])
            foreign = next(e for e in sorted(actions) if e not in grant["engines"])
            action = sorted(actions[foreign])[0]
            with self.assertRaises(governor.GovernorDenied):
                governor.check(grant, foreign, action, actions[foreign][action], now=at)
        grant = TWENTY["tasks"][0]["grant"]
        engine, action = next((e, a[0]) for e, a in grant["engines"].items())
        with self.assertRaises(governor.GovernorDenied) as expired:
            governor.check(grant, engine, action, actions[engine][action], now="2026-11-29T00:00:00Z")
        self.assertEqual(expired.exception.reason, "grant-expired")

    def test_requests_above_the_role_default_are_refused(self):
        cases = [
            {"engines": {"memory": ["put"]}},                     # engine not in the build role's default
            {"engines": {"master-build": ["create-repository"]}},  # action not in the default
        ]
        for extra in cases:
            with self.subTest(extra=extra), self.assertRaises(GrantEscalation):
                plan(goal(dict({"id": "x", "paths": ["workspace/x"], "role": "master-build-engine-engineer"}, **extra)),
                     now=NOW)
        with self.assertRaises(GrantEscalation):  # a write action with no writable task path
            plan(goal({"id": "x", "paths": ["engineering_os/healing.py"], "role": "testing-self-healing-engineer",
                       "engines": {"self-healing": ["verify-repair"]}}), now=NOW)
        widened = copy.deepcopy(TWENTY["tasks"][0]["grant"])
        widened["max_side_effect"] = "repo-write"
        with self.assertRaises(GrantEscalation):
            grant_within_default(widened, BY_ID[TWENTY["tasks"][0]["role"]])
        wrong_path = copy.deepcopy(plan(goal({"id": "t", "paths": ["workspace/t"], "role": "testing-self-healing-engineer"}),
                                        now=NOW)["tasks"][0]["grant"])
        wrong_path["paths"] = ["engineering_os"]
        with self.assertRaises(GrantEscalation):
            grant_within_default(wrong_path, BY_ID["testing-self-healing-engineer"])

    def test_least_privilege_narrows_paths_actions_and_ceiling(self):
        result = plan(goal({"id": "repair", "paths": ["workspace/demo/src"], "role": "testing-self-healing-engineer"},
                           {"id": "look", "paths": ["workspace/demo/notes"], "role": "engineering-reasoning-engineer"},
                           {"id": "read-only", "paths": ["workspace/demo/report"], "role": "independent-assurance-engineer",
                            "engines": {"layers": ["status"]}}), now=NOW)
        rows = {t["id"]: t["grant"] for t in result["tasks"]}
        self.assertEqual(rows["repair"]["paths"], ["workspace/demo/src"])       # not the whole workspace/*
        self.assertEqual(rows["repair"]["max_side_effect"], "workspace-write")
        self.assertEqual(rows["read-only"]["engines"], {"layers": ["status"]})
        self.assertEqual(rows["read-only"]["max_side_effect"], "none")          # below the role's state-write
        healing = next(t for t in TWENTY["tasks"] if t["role"] == "testing-self-healing-engineer")
        self.assertEqual(healing["grant"]["max_side_effect"], "none")           # no workspace path in this task
        self.assertEqual(len(healing["grant_notes"]), 2)


class ReviewTests(unittest.TestCase):
    def test_reviewer_is_never_the_implementer_for_any_role(self):
        for role in BY_ID:
            result = review_assignment({"id": "t", "role": role})
            with self.subTest(role=role):
                self.assertNotEqual(result["reviewer"], role)
                self.assertNotIn(role, result["panel"].values())
                self.assertTrue(result["independent"])
        self.assertEqual(review_assignment({"id": "t", "role": "independent-assurance-engineer"})["reviewer"],
                         "testing-self-healing-engineer")
        self.assertEqual(review_assignment({"id": "t", "role": "github-integration-release-engineer"})["panel"]["release"],
                         "chief-engineering-architect")

    def test_a_reviewer_equal_to_the_implementer_is_refused(self):
        with self.assertRaises(ReviewIndependenceError):
            review_assignment({"id": "t", "role": "master-build-engine-engineer", "reviewer": "master-build-engine-engineer"})
        with self.assertRaises(ReviewIndependenceError):
            plan(goal({"id": "t", "paths": ["workspace/t"], "role": "master-build-engine-engineer",
                       "reviewer": "master-build-engine-engineer"}), now=NOW)
        chosen = review_assignment({"id": "t", "role": "master-build-engine-engineer",
                                    "reviewer": "chief-engineering-architect"})
        self.assertEqual(chosen["reviewer"], "chief-engineering-architect")
        with self.assertRaises(OrchestratorError):
            review_assignment({"id": "t", "role": "nobody"})


class ScheduleTests(unittest.TestCase):
    def test_start_and_host_cap(self):
        first = schedule(TWENTY, [], cpus=4)
        self.assertEqual((first["recommended_agents"], first["rule"]), (4, "start"))
        self.assertEqual(first["wave"], ["chief-engineering-architect", "control-plane-integration-engineer",
                                         "twenty-layer-architecture-engineer"])  # only team A is ready
        self.assertEqual(first["agents"], 3)
        self.assertEqual(host_cap(4)["cap"], 8)
        self.assertEqual(host_cap(64)["cap"], 20)
        self.assertEqual(schedule(TWENTY, [], cpus=1)["recommended_agents"], 2)
        for bad in (0, -1, True, 1.5):
            with self.subTest(cpus=bad), self.assertRaises(OrchestratorError):
                host_cap(bad)

    def test_grows_only_when_verified_throughput_per_token_improves(self):
        done = ["chief-engineering-architect", "control-plane-integration-engineer", "twenty-layer-architecture-engineer"]
        better = [wave(), wave(agents=8, verified=8, tokens=600_000)]
        grown = schedule(TWENTY, better, done=done, cpus=16)
        self.assertEqual((grown["recommended_agents"], grown["rule"]), (16, "grow-efficiency-improved"))
        self.assertEqual(grown["agents"], 13)  # 13 ready tasks, one per agent
        capped = schedule(TWENTY, better, done=done, cpus=4)
        self.assertEqual((capped["recommended_agents"], capped["limits"]["max_agents"]), (8, 8))  # 4 CPUs x 2
        self.assertEqual(capped["host"]["cap"], 8)
        worse = schedule(TWENTY, [wave(), wave(agents=8, verified=8, tokens=1_000_000)], done=done, cpus=16)
        self.assertEqual((worse["recommended_agents"], worse["rule"]), (8, "hold-efficiency-not-improved"))

    def test_shrinks_on_conflicts_and_stops_on_limits(self):
        done = ["chief-engineering-architect", "control-plane-integration-engineer", "twenty-layer-architecture-engineer"]
        shrunk = schedule(TWENTY, [wave(), wave(agents=8, verified=8, tokens=600_000, conflicts=2)], done=done, cpus=16)
        self.assertEqual((shrunk["agents"], shrunk["rule"]), (4, "conflict-shrink"))
        stopped = schedule(TWENTY, [wave(), wave(agents=8, verified=8, tokens=600_000, limit_errors=1)], done=done, cpus=16)
        self.assertEqual((stopped["agents"], stopped["stop"], stopped["rule"]), (0, True, "limit-stop"))
        halved = schedule(TWENTY, [wave(agents=8, verified=4, failures=4)], done=done, cpus=16)
        self.assertEqual(halved["recommended_agents"], 4)

    def test_done_tasks_advance_and_completion_stops(self):
        everything = [t["id"] for t in TWENTY["tasks"]]
        finished = schedule(TWENTY, [wave()], done=everything, cpus=4)
        self.assertEqual((finished["agents"], finished["complete"], finished["stop"]), (0, True, True))
        last = schedule(TWENTY, [wave()], done=everything[:-2], cpus=4)
        self.assertEqual(sorted(last["wave"]), sorted(everything[-2:]))
        with self.assertRaises(OrchestratorError):
            schedule(TWENTY, [], done=["ghost"])
        with self.assertRaises(OrchestratorError):
            schedule(TWENTY, [{"agents": "many"}])


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = pathlib.Path(folder.name)
        self.state = self.root / "state"
        self.clock = [1000.0]
        self.task = next(t for t in TWENTY["tasks"] if t["id"] == "master-build-engine-engineer")

    def make(self, task=None):
        return lifecycle(task or self.task, state_dir=self.state, clock=lambda: self.clock[0])

    def approve_all(self, run):
        for role in self.task["review"]["panel"].values():
            run.review(role, "approved", [DIGEST])

    def test_states_in_order_with_memory_checkpoints(self):
        run = self.make()
        self.assertIsNone(run.state())
        seen = [run.enqueue()["state"]]
        lease = run.lease(ttl=600)
        seen.append(lease["state"])
        self.assertEqual(lease["grant"], self.task["grant"])
        seen.append(run.start(lease["lease_id"])["state"])
        seen.append(run.checkpoint(lease["lease_id"], ["plan the change"], ["write it"])["state"])
        seen.append(run.submit(lease["lease_id"], [DIGEST])["state"])
        self.approve_all(run)
        seen.append(run.state())
        seen.append(run.merge([{"kind": "merge-commit", "sha256": "c" * 64}])["state"])
        self.assertEqual(seen, ["queued", "leased", "running", "running", "submitted", "reviewed", "merged"])
        self.assertEqual(run.enqueue(), {"state": "merged", "created": False})
        from engineering_os.memory import MemoryStore
        rows = MemoryStore.for_project(self.state / "memory", TWENTY["project"]).entries(TWENTY["project"])
        notes = sorted(tag for row in rows for tag in row["record"]["tags"] if tag.startswith("lifecycle-"))
        self.assertIn("lifecycle-merged", notes)
        self.assertEqual(run.status()["approvals"], {"release": "approved", "security": "approved", "testing": "approved"})

    def test_illegal_transitions_and_reviewers_are_refused(self):
        run = self.make()
        with self.assertRaises(LifecycleError):
            run.lease()                                   # not queued yet
        run.enqueue()
        with self.assertRaises(LifecycleError):
            run.merge([DIGEST])                           # not reviewed
        lease = run.lease()
        with self.assertRaises(LifecycleError):
            run.lease()                                   # already leased
        with self.assertRaises(LifecycleError):
            run.resume()                                  # lease still live
        with self.assertRaises(LifecycleError):
            run.submit("0" * 32, [DIGEST])                # foreign lease
        with self.assertRaises(OrchestratorError):
            run.submit(lease["lease_id"], [{"kind": "diff", "sha256": "not-a-digest"}])
        run.submit(lease["lease_id"], [DIGEST])
        with self.assertRaises(ReviewIndependenceError):
            run.review(self.task["role"], "approved", [DIGEST])       # the implementer
        with self.assertRaises(ReviewIndependenceError):
            run.review("nl-router-project-registry-engineer", "approved", [DIGEST])  # not on the panel
        with self.assertRaises(LifecycleError):
            run.merge([DIGEST])                           # approvals missing
        self.assertEqual(run.state(), "submitted")

    def test_rejected_review_fails_and_failed_work_resumes(self):
        run = self.make()
        run.enqueue()
        lease = run.lease()
        run.checkpoint(lease["lease_id"], ["step one"], ["step two"])
        run.submit(lease["lease_id"], [DIGEST])
        self.assertEqual(run.review(self.task["review"]["panel"]["security"], "rejected", [DIGEST])["state"], "failed")
        resumed = run.resume()
        self.assertEqual(resumed["state"], "resumed")
        self.assertEqual(resumed["progress"]["done"], ["step one"])
        lease = run.lease()
        run.fail(lease["lease_id"], [DIGEST])
        self.assertEqual(run.state(), "failed")
        self.assertEqual(run.resume()["state"], "resumed")
        lease = run.lease()
        self.assertEqual(run.handover(lease["lease_id"], "context window full; continue from memory", [DIGEST])["state"],
                         "resumed")
        self.assertEqual(run.status()["failures"], 1)

    def test_changed_tasks_are_refused(self):
        reviewer = copy.deepcopy(self.task)
        reviewer["review"]["panel"]["testing"] = reviewer["role"]
        with self.assertRaises(ReviewIndependenceError):
            self.make(reviewer)
        wider = copy.deepcopy(self.task)
        wider["grant"]["engines"]["memory"] = ["put"]
        with self.assertRaises(GrantEscalation):
            self.make(wider)
        with self.assertRaises(OrchestratorError):
            lifecycle(self.task, state_dir=ROOT / "never-inside-git")

    def test_resume_from_checkpoint_in_a_fresh_process(self):
        task_file = self.root / "task.json"
        task_file.write_text(json.dumps(self.task))
        common = ("import json, sys\nsys.path.insert(0, sys.argv[1])\n"
                  "from engineering_os.orchestrator import lifecycle\n"
                  "task = json.load(open(sys.argv[2]))\n")
        crash = common + (
            "run = lifecycle(task, state_dir=sys.argv[3], clock=lambda: 1000.0)\n"
            "run.enqueue()\nlease = run.lease(ttl=60)\nrun.start(lease['lease_id'], ttl=60)\n"
            "run.checkpoint(lease['lease_id'], ['read the contract', 'write the module'],"
            " ['write the tests', 'update the spec'], ttl=60)\n"
            "print(json.dumps(run.status()))\n")  # the process ends here: no submit, the lease will expire
        resume = common + (
            "run = lifecycle(task, state_dir=sys.argv[3], clock=lambda: 2000.0)\n"
            "before = run.status()\nresumed = run.resume()\nlease = run.lease()\n"
            "plan = lease['progress']\n"
            "run.checkpoint(lease['lease_id'], plan['done'] + plan['remaining'], [])\n"
            "run.submit(lease['lease_id'], [{'kind': 'unit-tests', 'sha256': 'a' * 64}])\n"
            "print(json.dumps({'before': before, 'resumed': resumed, 'plan': plan, 'after': run.status()}))\n")
        environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        outputs = []
        for script in (crash, resume):
            done = subprocess.run([sys.executable, "-c", script, str(ROOT), str(task_file), str(self.state)],
                                  capture_output=True, text=True, timeout=120, cwd=self.root, env=environment)
            self.assertEqual(done.returncode, 0, done.stderr)
            outputs.append(json.loads(done.stdout))
        first, second = outputs
        self.assertEqual((first["state"], first["progress"]["next"]), ("running", "write the tests"))
        self.assertEqual((second["before"]["state"], second["before"]["lease_expired"]), ("running", True))
        self.assertEqual(second["resumed"]["state"], "resumed")
        self.assertEqual(second["plan"]["done"], ["read the contract", "write the module"])
        self.assertEqual(second["plan"]["next"], "write the tests")
        self.assertEqual(second["after"]["state"], "submitted")
        self.assertEqual(second["after"]["progress"]["version"], 2)
        run = self.make()  # a third owner (this process) finishes review and merge
        self.clock[0] = 3000.0
        self.approve_all(run)
        self.assertEqual(run.merge([{"kind": "merge-commit", "sha256": "d" * 64}])["state"], "merged")
        snapshot = run.store.snapshot()
        self.assertEqual([e["operation"] for e in snapshot["events"]],
                         ["create", "claim", "renew", "renew", "recover", "claim", "renew", "submit",
                          "review", "review", "review"])


class WorktreeTests(unittest.TestCase):
    def git(self, *argv, cwd=None):
        env = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, HOME=self.home)
        return subprocess.run(list(argv), capture_output=True, text=True, timeout=60, check=True, cwd=cwd, env=env)

    def test_one_worktree_and_branch_per_agent_on_a_temporary_repository(self):
        with tempfile.TemporaryDirectory() as folder:
            self.home = folder
            repo, base = os.path.join(folder, "repo"), os.path.join(folder, "worktrees")
            os.mkdir(repo)
            git = ["git", "-c", "user.name=test", "-c", "user.email=test@example.invalid", "-c", "core.hooksPath=/dev/null"]
            self.git(*git, "init", "-q", "-b", "main", cwd=repo)
            pathlib.Path(repo, "README.md").write_text("temporary repository\n")
            self.git(*git, "add", "README.md", cwd=repo)
            self.git(*git, "commit", "-q", "-m", "init", cwd=repo)
            commands = worktree_plan(TWENTY, repo=repo, base_dir=base, base_ref="main")
            self.assertFalse(commands["executed"])
            self.assertEqual(len(commands["agents"]), 20)
            self.assertEqual(len({row["branch"] for row in commands["agents"]}), 20)
            for row in commands["agents"]:
                for argv in row["create"]:
                    self.git(*argv)
            listing = self.git("git", "-C", repo, "worktree", "list", "--porcelain").stdout
            for row in commands["agents"]:
                self.assertIn(f"worktree {os.path.realpath(row['path'])}", listing)
                self.assertIn(f"branch refs/heads/{row['branch']}", listing)
            self.assertEqual(listing.count("worktree "), 21)
            for row in commands["agents"]:
                for argv in row["remove"]:
                    self.git(*argv)
            self.assertEqual(self.git("git", "-C", repo, "worktree", "list", "--porcelain").stdout.count("worktree "), 1)
            self.assertEqual(self.git("git", "-C", repo, "branch", "--list", "claude/*").stdout.strip(), "")

    def test_unsafe_locations_and_refs_are_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            cases = [dict(repo=folder, base_dir=os.path.join(folder, "inside")),
                     dict(repo="relative/repo", base_dir="/tmp/x"),
                     dict(repo=folder, base_dir=folder + "-wt", base_ref="--upload-pack=evil"),
                     dict(repo=folder, base_dir=folder + "-wt", base_ref="main..other")]
            for case in cases:
                with self.subTest(case=case), self.assertRaises(OrchestratorError):
                    worktree_plan(TWENTY, **case)


class ScenarioHTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        cls.snapshot = cls.doc["source"]["snapshot"]

    def test_numbers_are_recomputed_from_the_metrics_snapshot(self):
        self.assertEqual(self.doc["source"]["snapshot_sha256"], sha256(self.snapshot))
        commits = self.doc["git_source"]["commits"]
        recomputed = scenario_h(self.snapshot, commits=commits, cpus=4, source=self.doc["source"]["path"])
        self.assertEqual(json.loads(json.dumps(recomputed)), self.doc["results"])

    def test_figures_match_independent_arithmetic(self):
        agents = [a for w in self.snapshot["waves"] for a in w["agents"]]
        running = [r for w in self.snapshot["waves"] for r in w["still_running"]]
        merged = [a for a in agents if a["merged"]]
        tokens = sum(max(a["tokens"], a.get("followup", {}).get("tokens", 0)) for a in agents)
        span = max(max(a["duration_s"] for a in agents),
                   max(a["duration_s"] + a.get("followup", {}).get("duration_s", 0) for a in agents))
        results = self.doc["results"]
        self.assertEqual(results["tokens"]["total"], tokens)
        self.assertAlmostEqual(results["tokens"]["per_merged_task"], tokens / len(merged), places=2)
        self.assertAlmostEqual(results["throughput"]["merged_tasks_per_hour"], len(merged) * 3600 / span, places=3)
        entries = sum(len(a["conflicts"]) for a in agents)
        self.assertEqual(results["conflicts"]["entries"], entries)
        self.assertAlmostEqual(results["conflicts"]["rate_agents_with_conflicts"],
                               sum(1 for a in agents if a["conflicts"]) / len(agents), places=4)
        fixed = sum(1 for a in merged if any("fixed by integrator" in c for c in a["conflicts"]))
        self.assertAlmostEqual(results["rework"]["integrator_rework_rate"], fixed / len(merged), places=4)
        self.assertEqual(results["concurrency"]["peak"], len(agents) + len(running))
        self.assertLessEqual(results["concurrency"]["peak"], 11)
        cohort = {"agents": len(agents), "duration_seconds": round(span), "tasks_verified": len(merged), "tokens": tokens,
                  "conflicts": entries, "failures": len(agents) - len(merged)}
        decision = recommend_concurrency([cohort], {"start": 4, "max_agents": 8, "max_batch": 1})
        self.assertEqual(results["next_wave"]["agents"], decision["agents"])
        self.assertEqual(results["next_wave"]["host"]["cpus"], 4)
        git = results["git"]
        self.assertEqual(git["agent_merges"], sum(1 for c in self.doc["git_source"]["commits"]
                                                  if orchestrator._AGENT_MERGE.match(c["subject"])))

    def test_live_metrics_file_when_present(self):
        path = pathlib.Path(self.doc["source"]["path"])
        if not path.is_file():
            self.skipTest("the metrics file lives outside the repository and is absent here")
        data = path.read_bytes()
        if sha256(data) != self.doc["source"]["sha256"]:
            self.skipTest("the metrics file changed after the evidence was generated; regenerate it")
        self.assertEqual(json.loads(data), self.snapshot)

    def test_labels_and_claims_are_honest(self):
        self.assertEqual((self.doc["kind"], self.doc["simulated"]), ("measured", False))
        simulated = self.doc["simulated_20_agent_schedule"]
        self.assertEqual((simulated["simulated"], simulated["kind"]), (True, "simulated"))
        self.assertEqual(simulated["plan_sha256"], plan("gaie-20-layer", now=NOW)["plan_sha256"])
        self.assertEqual(self.doc["swarm_1000_agent_run"]["status"], "pending")
        self.assertTrue(any("No 20-agent concurrent run" in claim for claim in self.doc["claims_not_made"]))
        self.assertEqual(self.doc["provider_calls"], 0)
        self.assertTrue(self.doc["host_pressure"])
        for name in self.doc["swarm_1000_agent_run"]["evidence_files_in_tree"]:
            self.assertTrue((ROOT / name).is_file(), name)

    def test_malformed_metrics_are_refused(self):
        bad = [None, {}, {"waves": []}, {"waves": [{"agents": [{"id": "x"}]}]},
               {"waves": [{"agents": [dict(self.snapshot["waves"][0]["agents"][0], tokens=-1)]}]},
               {"waves": [{"agents": [dict(self.snapshot["waves"][0]["agents"][0], merged=False)], "still_running": []}]}]
        for value in bad:
            with self.subTest(value=str(value)[:60]), self.assertRaises(OrchestratorError):
                scenario_h(value)


class EngineTests(unittest.TestCase):
    def test_contract_entrypoint_and_health(self):
        made = orchestrator.engine("plan", {"goal": "engine-goal", "now": NOW, "max_agents": 6}, {})
        self.assertTrue(all(len(w) <= 6 for w in made["waves"]))
        review = orchestrator.engine("review-assignment", {"task": made["tasks"][0]}, {})
        self.assertNotEqual(review["reviewer"], made["tasks"][0]["role"])
        nxt = orchestrator.engine("schedule", {"plan": made, "history": [], "cpus": 4}, {})
        self.assertEqual(nxt["rule"], "start")
        for action, payload in (("deploy", {}), ("plan", {"goal": "x", "shell": "rm"}), ("plan", [])):
            with self.subTest(action=action), self.assertRaises(OrchestratorError):
                orchestrator.engine(action, payload, {})
        health = orchestrator.health()
        self.assertTrue(health["ok"], health["detail"])

    def test_now_forms(self):
        moment = datetime.datetime(2026, 11, 28, 6, 36, 23, tzinfo=datetime.timezone.utc)
        self.assertEqual(plan("gaie-20-layer", now=moment)["plan_sha256"], TWENTY["plan_sha256"])
        self.assertEqual(plan("gaie-20-layer", now=moment.timestamp())["plan_sha256"], TWENTY["plan_sha256"])
        for bad in ("yesterday", datetime.datetime(2026, 1, 1), True):
            with self.subTest(now=bad), self.assertRaises(OrchestratorError):
                plan("gaie-20-layer", now=bad)


if __name__ == "__main__":
    unittest.main()
