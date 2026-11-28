"""Tests for the central agent-team policy (governance/policies/agent-team.json) and its loader
engineering_os/agent_team.py: schema, roster equals the registry, numbers equal the cited evidence,
drift guards against the orchestrator and the router, staffing checks that fail closed, the
declared-versus-enforced section and the role-parameterised specialist agent definition."""
import ast
import contextlib
import copy
import io
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from engineering_os import agent_team, orchestrator
from engineering_os.agent_team import (AgentTeamError, NoStandingTeam, PolicyNotInstalled, check_staffing, concurrency,
                                       digest, evidence_status, load_policy, load_registry, reviewer_for, role_card,
                                       team_for, validate)
from engineering_os.layers import ROLE_IDS

ROOT = pathlib.Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "governance/policies/agent-team.json"
POLICY = load_policy()
REGISTRY = load_registry()
NOW = "2026-11-28T06:36:23Z"
SCENARIO_H = json.loads((ROOT / "docs/evidence/gaie-20-layers/scenario-h.json").read_text(encoding="utf-8"))
HOST_LIMITS = json.loads((ROOT / "swarm/evidence/host-limits.json").read_text(encoding="utf-8"))
SPEC = json.loads((ROOT / "tests/fixtures/upgrade/taskapp/gaie-spec.json").read_text(encoding="utf-8"))
SPECIALIST = "agents/gaie-specialist.md"


def mutated(**changes):
    policy = copy.deepcopy(POLICY)
    for dotted, value in changes.items():
        *parents, last = dotted.split("__")
        target = policy
        for key in parents:
            target = target[key]
        if value is KeyError:
            del target[last]
        else:
            target[last] = value
    return policy


def front_matter(text):
    return dict(line.split(": ", 1) for line in text.split("---\n")[1].strip().splitlines())


class LoadTests(unittest.TestCase):
    def write(self, folder, text):
        path = pathlib.Path(folder) / "agent-team.json"
        path.write_text(text, encoding="utf-8")
        return path

    def test_duplicate_keys_and_bad_json_are_refused(self):
        text = POLICY_PATH.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as folder:
            duplicate = self.write(folder, text.replace('"session_limit": 20,', '"session_limit": 20, "session_limit": 20,', 1))
            with self.assertRaisesRegex(AgentTeamError, "duplicate JSON key"):
                load_policy(duplicate)
            nested = self.write(folder, text.replace('"start": 4,', '"start": 4, "start": 8,', 1))
            with self.assertRaisesRegex(AgentTeamError, "duplicate JSON key"):
                load_policy(nested)
            for bad in (text.replace('"session_limit": 20', '"session_limit": NaN', 1), text[:-10], ""):
                with self.subTest(bad=bad[-40:]), self.assertRaises(AgentTeamError):
                    load_policy(self.write(folder, bad))
            with self.assertRaises(AgentTeamError) as caught:
                load_policy(pathlib.Path(folder) / "absent.json")
            self.assertNotIsInstance(caught.exception, PolicyNotInstalled)  # a named file that is missing is an error

    def test_schema_and_bounds(self):
        self.assertEqual(list(POLICY)[:3], ["schema_version", "policy_version", "implementation"])
        self.assertEqual(POLICY["schema_version"], 1)
        self.assertRegex(POLICY["policy_version"], r"^\d+\.\d+\.\d+$")
        self.assertEqual(POLICY["implementation"], "engineering_os/agent_team.py")
        self.assertTrue((ROOT / POLICY["implementation"]).is_file())
        self.assertEqual(POLICY["registry"], "governance/agent-roles.json")
        self.assertLessEqual(POLICY["session_limit"], agent_team.HARD_SESSION_LIMIT)
        self.assertEqual(agent_team.HARD_SESSION_LIMIT, 20)
        self.assertIs(validate(POLICY, REGISTRY), POLICY)
        self.assertEqual(load_policy(POLICY_PATH), POLICY)
        self.assertEqual(digest(POLICY), team_for("build")["policy_sha256"])


class PolicyTests(unittest.TestCase):
    def test_roles_equal_the_registry(self):
        self.assertEqual(POLICY["roles"], [role["id"] for role in REGISTRY["roles"]])
        self.assertEqual(tuple(POLICY["roles"]), ROLE_IDS)
        self.assertEqual(len(POLICY["roles"]), 20)
        flagged = [role["id"] for role in REGISTRY["roles"] if role["reviewer"]]
        self.assertEqual(flagged, ["independent-assurance-engineer"])
        self.assertEqual(POLICY["mandatory_roles"], flagged)

    def test_build_and_upgrade_staff_all_twenty(self):
        # Owner decision of 2026-11-28: the standing team of a build and of an upgrade is the full roster.
        # Trimming a roster is a later owner decision; change the policy and this assertion together.
        for intent in ("build", "upgrade"):
            team = team_for(intent, 4)
            with self.subTest(intent=intent):
                self.assertEqual(team["roles"], list(ROLE_IDS))
                self.assertEqual((team["size"], team["omitted"]), (20, []))
                self.assertEqual(team["policy_version"], POLICY["policy_version"])
                self.assertEqual(set(team["concurrency"]), {"session_limit", "effective", "start", "workflow_runner",
                                                            "host_cap", "cpus", "agents_per_cpu", "runner", "rule", "basis"})
        self.assertEqual(set(POLICY["intents_without_roster"]), {"audit", "accelerate", "repair", "cinematic", "release"})
        for intent in POLICY["intents_without_roster"]:
            with self.subTest(intent=intent), self.assertRaisesRegex(NoStandingTeam, "no standing team"):
                team_for(intent)
        with self.assertRaisesRegex(AgentTeamError, "not in the agent-team policy") as caught:
            team_for("deploy")
        self.assertNotIsInstance(caught.exception, NoStandingTeam)

    def test_a_trimmed_roster_lists_the_rest_as_omitted_with_reasons(self):
        roster = [rid for rid in ROLE_IDS if not rid.startswith(("cinematic", "motion", "gpu"))]
        team = team_for("upgrade", 4, policy=mutated(rosters__upgrade=roster))
        self.assertEqual(team["size"], 17)
        self.assertEqual([row["role"] for row in team["omitted"]],
                         ["cinematic-production-engineer", "motion-sdk-animation-engineer", "gpu-3d-digital-twin-engineer"])
        self.assertTrue(all("not in the upgrade roster" in row["reason"] for row in team["omitted"]))


class NegativeTests(unittest.TestCase):
    def test_policies_that_break_the_bounds_are_refused(self):
        twenty = list(ROLE_IDS)
        cases = {
            "21 roles": mutated(roles=twenty + ["extra-engineer"]),
            "session limit 25": mutated(session_limit=25),
            "session limit 0": mutated(session_limit=0),
            "session limit true": mutated(session_limit=True),
            "roster above a lowered session limit": mutated(session_limit=10),
            "unknown roster role": mutated(rosters__build=twenty[:19] + ["unknown-engineer"]),
            "duplicate roster role": mutated(rosters__build=twenty[:19] + [twenty[0]]),
            "roster out of registry order": mutated(rosters__build=list(reversed(twenty))),
            "roster without the reviewer": mutated(rosters__build=[r for r in twenty if r != "independent-assurance-engineer"]),
            "empty roster": mutated(rosters__build=[]),
            "unknown field": mutated(extra=1),
            "missing field": mutated(declared_vs_enforced=KeyError),
            "schema 2": mutated(schema_version=2),
            "schema true": mutated(schema_version=True),
            "short version": mutated(policy_version="1.0"),
            "other implementation": mutated(implementation="engineering_os/other.py"),
            "start 0": mutated(concurrency__start=0),
            "start above the limit": mutated(concurrency__start=21),
            "agents per CPU 0": mutated(concurrency__agents_per_cpu=0),
            "agents per CPU 1.5": mutated(concurrency__agents_per_cpu=1.5),
            "runner cap 0": mutated(concurrency__workflow_runner__cap=0),
            "intent with roster and reason": mutated(intents_without_roster__build="no"),
            "one testing reviewer": mutated(review__testing_reviewers=["independent-assurance-engineer"]),
            "approvals changed": mutated(review__approvals=["testing"]),
            "bad test name": mutated(declared_vs_enforced__enforced_in_ci=[{"claim": "x", "tests": ["test_agent_team"]}]),
            "no declared-only claims": mutated(declared_vs_enforced__declared_only=[]),
            "consumer reads unknown key": mutated(consumers=[{"file": "engineering_os/orchestrator.py", "reads": ["x"]}]),
        }
        evidence = POLICY["concurrency"]["evidence"]
        cases["evidence with value and contains"] = mutated(concurrency__evidence=[dict(evidence[0], contains="20")] + evidence[1:])
        cases["evidence outside the tree"] = mutated(concurrency__evidence=[dict(evidence[0], file="../x.json")] + evidence[1:])
        cases["no measured session limit"] = mutated(concurrency__evidence=[
            row for row in evidence if not (row["supports"] == "session_limit" and row["kind"] == "measured")])
        cases["nothing supports start"] = mutated(concurrency__evidence=[row for row in evidence if row["supports"] != "start"])
        for name, policy in cases.items():
            with self.subTest(name), self.assertRaises(AgentTeamError):
                validate(policy, REGISTRY)

    def test_a_policy_that_differs_from_the_registry_is_refused(self):
        nineteen = list(ROLE_IDS[:19])
        for name, policy in (("19 roles", mutated(roles=nineteen, rosters__build=nineteen, rosters__upgrade=nineteen)),
                             ("reordered", mutated(roles=[ROLE_IDS[1], ROLE_IDS[0], *ROLE_IDS[2:]]))):
            with self.subTest(name), self.assertRaises(AgentTeamError):
                validate(policy, REGISTRY)
        registry = copy.deepcopy(REGISTRY)
        registry["roles"][0]["reviewer"] = True
        with self.assertRaisesRegex(AgentTeamError, "reviewer role"):
            validate(POLICY, registry)
        with self.assertRaises(AgentTeamError):
            team_for("build", policy=mutated(roles=nineteen, rosters__build=nineteen, rosters__upgrade=nineteen))


class EvidenceTests(unittest.TestCase):
    def test_numbers_equal_the_cited_evidence(self):
        rows = evidence_status(POLICY, ROOT)
        self.assertEqual(len(rows), len(POLICY["concurrency"]["evidence"]))
        self.assertEqual([row for row in rows if row["status"] != "ok"], [])
        cited = {(row["supports"], row["file"]) for row in POLICY["concurrency"]["evidence"]}
        for name in ("session_limit", "agents_per_cpu", "start", "workflow_runner"):
            self.assertTrue(any(s == name for s, _ in cited), name)
        # the policy numbers are the numbers in those files
        self.assertEqual(POLICY["session_limit"], HOST_LIMITS["agent_tool"]["peak_concurrent_measured"])
        self.assertEqual(POLICY["session_limit"], SCENARIO_H["host_cap_policy"]["session_limit"])
        self.assertEqual(POLICY["concurrency"]["agents_per_cpu"], SCENARIO_H["host_cap_policy"]["agents_per_cpu"])
        self.assertEqual(POLICY["concurrency"]["start"], SCENARIO_H["results"]["next_wave"]["limits"]["start"])
        cap, reserved = map(int, re.search(r"min\((\d+), cores - (\d+)\)", HOST_LIMITS["workflow_tool"]["documented_cap"]).groups())
        self.assertEqual(POLICY["concurrency"]["workflow_runner"], {"cap": cap, "reserved_cpus": reserved})
        cores = HOST_LIMITS["machine"]["cores"]
        self.assertEqual(concurrency(cores)["workflow_runner"], HOST_LIMITS["workflow_tool"]["peak_concurrent_measured"])
        self.assertEqual(concurrency(SCENARIO_H["host_cap_policy"]["cpus"])["effective"], SCENARIO_H["host_cap_policy"]["cap"])
        stages = json.loads((ROOT / "swarm/phase2/evidence/stages.json").read_text(encoding="utf-8"))["stages"]
        self.assertEqual(max(stage.get("peak_concurrent_agents") or 0 for stage in stages), POLICY["session_limit"])

    def test_a_changed_number_is_reported_as_a_mismatch(self):
        evidence = copy.deepcopy(POLICY["concurrency"]["evidence"])
        evidence[0]["value"] = 21
        evidence[1]["contains"] = "at most 21 agents"
        evidence[2]["pointer"] = ["totals", "no-such-key"]
        rows = evidence_status(mutated(concurrency__evidence=evidence), ROOT)
        self.assertEqual([row["status"] for row in rows[:3]], ["mismatch"] * 3)
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual({row["status"] for row in evidence_status(POLICY, folder)}, {"absent"})


class ConcurrencyTests(unittest.TestCase):
    def test_effective_start_and_runner(self):
        four = concurrency(4)
        self.assertEqual((four["session_limit"], four["effective"], four["start"], four["workflow_runner"]), (20, 8, 4, 2))
        self.assertEqual((concurrency(4, runner="workflow")["effective"], concurrency(4, runner="workflow")["start"]), (2, 2))
        self.assertEqual((concurrency(64)["effective"], concurrency(64)["start"], concurrency(64)["workflow_runner"]), (20, 4, 16))
        self.assertEqual((concurrency(1)["effective"], concurrency(1)["start"], concurrency(1)["workflow_runner"]), (2, 2, None))
        for cpus in (1, 2, 3, 4, 8, 10, 64, 4096):
            with self.subTest(cpus=cpus):
                self.assertEqual(concurrency(cpus)["effective"], orchestrator.host_cap(cpus)["cap"])
                self.assertLessEqual(concurrency(cpus)["effective"], 20)
        with self.assertRaisesRegex(AgentTeamError, "workflow runner"):
            concurrency(2, runner="workflow")
        for bad in (0, -1, True, 1.5, "4"):
            with self.subTest(cpus=bad), self.assertRaises(AgentTeamError):
                concurrency(bad)
        with self.assertRaises(AgentTeamError):
            concurrency(4, runner="threads")

    def test_a_policy_edit_changes_the_cap(self):
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / "agent-team.json"
            path.write_text(json.dumps(mutated(concurrency__agents_per_cpu=1)), encoding="utf-8")
            edited = load_policy(path)
        self.assertEqual(concurrency(4, policy=edited)["effective"], 4)
        self.assertEqual(orchestrator.host_cap(4, edited["concurrency"]["agents_per_cpu"])["cap"], 4)


class DriftTests(unittest.TestCase):
    def test_orchestrator_constants_come_from_the_policy(self):
        self.assertEqual(orchestrator.MAX_AGENTS, POLICY["session_limit"])
        self.assertEqual(orchestrator.AGENTS_PER_CPU, POLICY["concurrency"]["agents_per_cpu"])
        self.assertEqual(orchestrator.START_AGENTS, POLICY["concurrency"]["start"])
        source = (ROOT / "engineering_os/orchestrator.py").read_text(encoding="utf-8")
        self.assertNotRegex(source, re.compile(r"^(?:MAX_AGENTS|AGENTS_PER_CPU|START_AGENTS) = \d", re.M))
        self.assertIn("agent_team.load_policy", source)
        # reading the policy added no key to the plan body: the pinned twenty-role plan digest still holds
        self.assertEqual(orchestrator.plan("gaie-20-layer", now=NOW)["plan_sha256"],
                         SCENARIO_H["simulated_20_agent_schedule"]["plan_sha256"])

    def test_router_maximum_equals_the_session_limit(self):
        routes = json.loads((ROOT / "governance/policies/gaie-routes.json").read_text(encoding="utf-8"))
        self.assertEqual(routes["max_agents"], POLICY["session_limit"])

    def test_reviewer_rule_matches_the_orchestrator(self):
        self.assertEqual(POLICY["review"]["testing_reviewers"], list(orchestrator.PANEL_CANDIDATES["testing"]))
        self.assertEqual(POLICY["review"]["approvals"], list(orchestrator.CAPACITIES))
        for rid in ROLE_IDS:
            with self.subTest(role=rid):
                expected = orchestrator.review_assignment({"id": "t", "role": rid})["reviewer"]
                self.assertEqual(reviewer_for(rid), expected)
                self.assertNotEqual(reviewer_for(rid), rid)
        with self.assertRaises(AgentTeamError):
            reviewer_for("nobody")

    def test_consumers_read_the_policy(self):
        self.assertTrue(POLICY["consumers"])
        for row in POLICY["consumers"]:
            with self.subTest(file=row["file"]):
                self.assertIn("agent_team", (ROOT / row["file"]).read_text(encoding="utf-8"))


class StaffingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.twenty = orchestrator.plan("gaie-20-layer", now=NOW)
        cls.spec = orchestrator.plan(SPEC, now=NOW)

    def test_twenty_role_plan_staffs_everyone(self):
        result = check_staffing(self.twenty, "build")
        self.assertEqual([row["role"] for row in result["staffed"]], list(ROLE_IDS))
        self.assertEqual((result["omitted"], result["agents"], result["counts"]["staffed"]), ([], 20, 20))
        self.assertEqual(check_staffing(dict(self.twenty, intent="upgrade"))["counts"]["staffed"], 20)

    def test_spec_plan_lists_omitted_roles_with_reasons(self):
        result = check_staffing(self.spec, "build")
        staffed = [row["role"] for row in result["staffed"]]
        self.assertEqual(staffed, ["chief-engineering-architect", "master-build-engine-engineer",
                                   "enterprise-security-privacy-engineer", "testing-self-healing-engineer",
                                   "github-integration-release-engineer"])
        self.assertEqual((len(result["staffed"]), len(result["omitted"])), (5, 15))
        self.assertEqual(sorted(staffed + [row["role"] for row in result["omitted"]]), sorted(ROLE_IDS))
        self.assertTrue(all(isinstance(row["reason"], str) and row["reason"].strip() for row in result["omitted"]))
        reasons = {row["role"]: row["reason"] for row in result["omitted"]}
        self.assertIn("independent reviewer", reasons["independent-assurance-engineer"])
        self.assertEqual(reasons["cinematic-production-engineer"], POLICY["omission"]["default_reason"])
        declared = check_staffing(dict(self.spec, omitted=[{"role": "cinematic-production-engineer",
                                                            "reason": "the specification has no media work"}]), "build")
        self.assertIn({"role": "cinematic-production-engineer", "reason": "the specification has no media work"},
                      declared["omitted"])
        record = check_staffing({"intent": "upgrade", "roles": ["master-upgrade-engine-engineer", "independent-assurance-engineer"]})
        self.assertEqual((record["counts"]["staffed"], record["counts"]["omitted"]), (2, 18))

    def test_staffing_fails_closed(self):
        task = self.twenty["tasks"][0]
        self_review = dict(task, review=dict(task["review"], reviewer=task["role"]))
        nineteen = list(ROLE_IDS[:19])
        trimmed = mutated(rosters__build=[r for r in ROLE_IDS if r != "gpu-3d-digital-twin-engineer"])
        cases = {
            "21 agents": (dict(self.twenty, agents=self.twenty["agents"] + [dict(self.twenty["agents"][0], id="extra")]), {}),
            "unknown task role": (dict(self.spec, tasks=self.spec["tasks"] + [dict(self.spec["tasks"][0], role="nobody")]), {}),
            "unknown listed role": ({"roles": ["nobody", "independent-assurance-engineer"]}, {}),
            "self review": (dict(self.twenty, tasks=[self_review] + self.twenty["tasks"][1:]), {}),
            "no intent": (self.spec, {"intent": None}),
            "intent without roster": (self.spec, {"intent": "release"}),
            "role outside the roster": (self.twenty, {"policy": trimmed}),
            "omitted role that works": (dict(self.spec, omitted=[{"role": "chief-engineering-architect", "reason": "x"}]), {}),
            "omitted without reason": (dict(self.spec, omitted=[{"role": "cinematic-production-engineer", "reason": " "}]), {}),
            "omitted twice": (dict(self.spec, omitted=[{"role": "cinematic-production-engineer", "reason": "a"}] * 2), {}),
            "no reviewer at all": ({"roles": ["chief-engineering-architect"]}, {}),
            "policy differs from the registry": (self.spec, {"policy": mutated(roles=nineteen, rosters__build=nineteen,
                                                                              rosters__upgrade=nineteen)}),
            "not a plan": ([], {}),
        }
        for name, (plan, options) in cases.items():
            options = dict({"intent": "build"}, **options)
            with self.subTest(name), self.assertRaises(AgentTeamError):
                check_staffing(plan, options.pop("intent"), **options)


class DeclaredTests(unittest.TestCase):
    def test_declared_versus_enforced_names_real_tests(self):
        section = POLICY["declared_vs_enforced"]
        names = [name for row in section["enforced_in_ci"] for name in row["tests"]]
        self.assertTrue(names)
        trees = {}
        for name in names:
            _, module, cls, method = name.split(".")
            path = ROOT / "tests" / f"{module}.py"
            with self.subTest(test=name):
                self.assertTrue(path.is_file())
                tree = trees.setdefault(path, ast.parse(path.read_text(encoding="utf-8")))
                classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
                self.assertIn(cls, classes)
                self.assertIn(method, {node.name for node in classes[cls].body if isinstance(node, ast.FunctionDef)})

    def test_declared_only_states_what_is_not_enforced(self):
        declared = " ".join(row["claim"] + " " + row["why"] for row in POLICY["declared_vs_enforced"]["declared_only"])
        for phrase in ("live session starts the team", "the role it claims", "Live concurrency", ".claude/settings.json",
                       "frozen", "inside its work item's paths"):
            self.assertIn(phrase, declared)


class SpecialistTests(unittest.TestCase):
    def test_definition_and_mirror(self):
        source, mirror = ROOT / SPECIALIST, ROOT / ".claude" / SPECIALIST
        self.assertEqual(source.read_bytes(), mirror.read_bytes())
        self.assertNotRegex(source.name, r"^swarm-")
        text = source.read_text(encoding="utf-8")
        config = front_matter(text)
        self.assertEqual(set(config), {"name", "description", "tools", "disallowedTools"})
        self.assertEqual(config["name"], "gaie-specialist")
        self.assertEqual(config["tools"].split(", "), ["Read", "Grep", "Glob", "Edit", "Write", "Bash"])
        self.assertTrue({"Agent", "Skill", "WebFetch", "WebSearch", "mcp__*"} <= set(config["disallowedTools"].split(", ")))
        self.assertLessEqual(len(text), 2600, "keep the definition lean: every session pays its tokens")
        for phrase in ("governance/policies/agent-team.json", "agent_team role", "reviewer", "owns"):
            self.assertIn(phrase, text)
        card = role_card("master-build-engine-engineer")
        self.assertEqual(card["reviewer"], "independent-assurance-engineer")
        self.assertEqual(card["owns"], next(r["owns"] for r in REGISTRY["roles"] if r["id"] == "master-build-engine-engineer"))
        self.assertEqual(card["rosters"], ["build", "upgrade"])
        self.assertEqual(role_card("independent-assurance-engineer")["reviewer"], "testing-self-healing-engineer")
        with self.assertRaises(AgentTeamError):
            role_card("nobody")


class StandaloneTests(unittest.TestCase):
    def test_module_imports_only_the_standard_library(self):
        tree = ast.parse((ROOT / "engineering_os/agent_team.py").read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                self.assertEqual(node.level, 0, "no relative import: the file is vendored alone")
                imported.add(node.module.split(".")[0])
            elif isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
        self.assertLessEqual(imported, {"argparse", "hashlib", "json", "os", "pathlib", "re", "sys"})

    def test_an_install_without_the_files_raises_not_installed(self):
        with tempfile.TemporaryDirectory() as folder:
            engine = pathlib.Path(folder) / "engine"
            engine.mkdir()
            shutil.copyfile(ROOT / "engineering_os/agent_team.py", engine / "agent_team.py")
            code = ("import sys; sys.path.insert(0, sys.argv[1]); import agent_team\n"
                    "try:\n    agent_team.load_policy()\nexcept agent_team.PolicyNotInstalled as error:\n    print('not-installed', error)")
            run = subprocess.run([sys.executable, "-I", "-c", code, str(engine)], capture_output=True, text=True, timeout=60)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn("not-installed agent-team.json is not installed", run.stdout)

    def test_vendored_copy_finds_its_policy_beside_itself(self):
        with tempfile.TemporaryDirectory() as folder:
            engine = pathlib.Path(folder) / "engine"
            engine.mkdir()
            for source, name in (("engineering_os/agent_team.py", "agent_team.py"),
                                 ("governance/policies/agent-team.json", "agent-team.json"),
                                 ("governance/agent-roles.json", "agent-roles.json")):
                shutil.copyfile(ROOT / source, engine / name)
            command = [sys.executable, "-I", str(engine / "agent_team.py"), "show", "--intent", "upgrade", "--cpus", "4", "--json"]
            run = subprocess.run(command, capture_output=True, text=True, cwd=folder, timeout=60)
            self.assertEqual(run.returncode, 0, run.stderr)
            team = json.loads(run.stdout)
            self.assertEqual((team["size"], team["concurrency"]["effective"], team["concurrency"]["start"]), (20, 8, 4))
            self.assertEqual(team["policy_sha256"], digest(POLICY))
            (engine / "agent-roles.json").unlink()
            missing = subprocess.run(command, capture_output=True, text=True, cwd=folder, timeout=60)
            self.assertEqual(missing.returncode, 2)
            self.assertIn("agent-roles.json is not installed", missing.stderr)


class CliTests(unittest.TestCase):
    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = agent_team.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_show_check_role_and_evidence(self):
        code, out, _ = self.run_main("show", "--intent", "build", "--cpus", "4")
        self.assertEqual(code, 0)
        self.assertIn("20 roles, 0 omitted", out)
        self.assertIn("session limit 20, effective 8, start 4, workflow runner 2", out)
        code, out, _ = self.run_main("show", "--cpus", "4", "--runner", "workflow", "--json")
        self.assertEqual((code, json.loads(out)["concurrency"]["effective"]), (0, 2))
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / "plan.json"
            path.write_text(json.dumps(orchestrator.plan(SPEC, now=NOW)), encoding="utf-8")
            code, out, _ = self.run_main("check", str(path), "--intent", "build", "--json")
            self.assertEqual((code, json.loads(out)["counts"]["staffed"]), (0, 5))
            code, _, err = self.run_main("check", str(path))
            self.assertEqual(code, 2)
            self.assertIn("name the intent", err)
        code, out, _ = self.run_main("role", "adaptive-agent-orchestration-engineer")
        self.assertEqual(code, 0)
        self.assertIn("reviewer independent-assurance-engineer", out)
        self.assertEqual(self.run_main("role", "nobody")[0], 2)
        self.assertEqual(self.run_main("evidence")[0], 0)
        self.assertEqual(self.run_main("show", "--intent", "release")[0], 2)


if __name__ == "__main__":
    unittest.main()
