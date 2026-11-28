"""Measured L19 inputs: real numbers read from the swarm evidence files of this tree.

Nothing here runs an agent or a model. The figures are those recorded by the swarm
phases; the tests check that engineering_os.economics reads, cites and recomputes
them correctly, and that docs/evidence/gaie-20-layers/economics-baseline.json is
bound to its sources and public-safe.
"""
import contextlib
import io
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from engineering_os import economics
from engineering_os.economics import (EconomicsError, SOURCES, baseline_document, context_footprint, engine,
                                      estimate_scope, measured_baseline, read_results_table, recommend_concurrency,
                                      waves_from_evidence)
from engineering_os.orchestration import SECRET

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "docs" / "evidence" / "gaie-20-layers" / "economics-baseline.json"


def load(key):
    return json.loads((ROOT / SOURCES[key]).read_text(encoding="utf-8"))


class MeasuredInputs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = measured_baseline(ROOT)

    def test_every_source_exists_and_the_1000_agent_run_is_pending(self):
        for path in SOURCES.values():
            self.assertTrue((ROOT / path).is_file(), path)
        pending = self.baseline["pending"]["phase3_1000_agent_run"]
        self.assertEqual(pending["status"], "pending (owned by swarm session)")

    def test_headline_figures_are_cited_with_their_sources(self):
        head = self.baseline["headline_comparisons"]
        context = head["first_request_context_tokens"]
        self.assertEqual((context["before"]["value"], context["after"]["value"]), (222067, 5486))
        self.assertEqual(context["before"]["source"], "swarm/evidence/tool-audit.json")
        self.assertEqual(context["status"], "cited, not reproduced")
        per_task = head["input_tokens_per_verified_small_task_20_agents"]
        self.assertEqual((per_task["before"]["value"], per_task["after"]["value"]), (801572, 50307))
        self.assertEqual((per_task["recomputed"]["before"], per_task["recomputed"]["after"]), (801572, 50307))
        self.assertEqual(per_task["before"]["source"], "swarm/evidence/ladder.json")
        speed = head["tasks_per_minute_20_agents"]
        self.assertEqual((speed["before"]["value"], speed["after"]["value"]), (29.64, 76.57))
        self.assertAlmostEqual(speed["recomputed"]["before"], 29.64, delta=0.011)
        self.assertAlmostEqual(speed["recomputed"]["after"], 76.57, delta=0.011)
        self.assertEqual(speed["ratio"], 2.58)
        for item in head.values():
            self.assertIn("not", item["status"])  # never claimed as re-measured

    def test_results_markdown_agrees_with_stages_json(self):
        rows = read_results_table((ROOT / SOURCES["phase2_results"]).read_text(encoding="utf-8"))
        self.assertEqual(len(rows), 20)
        s20 = next(row for row in rows if row["Stage"] == "s20")
        self.assertEqual((s20["Per verified task"], s20["Tasks/min"], s20["Verified"]),
                         (50307, 76.57, {"verified": 20, "of": 20}))
        checks = self.baseline["results_table_cross_check"]["rows"]
        self.assertEqual(len(checks), 20)
        self.assertTrue(all(row["agrees_with_stages_json"] for row in checks), checks)

    def test_coordinator_worker_cache_split_per_stage(self):
        split = self.baseline["consumption_by_stage"]["stages"]
        s20 = split["s20"]
        self.assertEqual(s20["worker"], {"input": 1006148, "cache_read": 671350, "cache_write": 334656, "output": 18899})
        self.assertEqual(s20["coordinator"]["input"], 386649)
        self.assertEqual(s20["coordinator_share_of_all_tokens"], 0.276)
        self.assertEqual(s20["reviewer"], "unknown")
        self.assertEqual(s20["retries"], "unknown")
        self.assertEqual(s20["cost_units_per_verified_task"], 29005)
        self.assertEqual(split["l5r"]["not_verified"], 2)
        self.assertEqual(split["g10"]["worker_tokens_per_verified_task"], round((4700793 + 13976) / 10))

    def test_development_waves_conflicts_and_rework_from_phase3(self):
        team, team2 = self.baseline["development_waves"]
        self.assertEqual((team["agents"], team["tasks_verified"], team["conflicts"], team["failures"]), (20, 20, 0, 0))
        self.assertEqual(team["tokens"], 3896199 + 128555)
        self.assertEqual((team2["agents"], team2["tasks_verified"], team2["conflicts"], team2["failures"]), (16, 13, 1, 2))
        rework = self.baseline["rework_measured"]
        self.assertEqual(rework["lanes_needing_repair_by_the_setting_session"], 3)
        self.assertEqual(rework["rework_tokens"], "unknown")
        self.assertFalse(rework["suite_after_joining_passed"])
        lanes = self.baseline["development_lanes"]["phase3_team"]["tokens_per_lane"]
        self.assertEqual((lanes["min"], lanes["max"]), (68019, 505643))

    def test_recommender_on_measured_waves(self):
        demos = self.baseline["recommender_on_measured_waves"]
        grow = demos["phase2_c1_then_s10"]
        self.assertEqual((grow["agents"], grow["rule"]), (20, "grow-efficiency-improved"))
        self.assertGreater(float(grow["last_wave"]["verified_tasks_per_million_tokens"]),
                           float(grow["previous_wave"]["verified_tasks_per_million_tokens"]))
        self.assertEqual(demos["phase2_s20_then_s25"]["agents"], 20)  # the host ceiling, measured in phase 2
        shrink = demos["phase3_team_then_team2"]
        self.assertEqual((shrink["agents"], shrink["rule"]), (8, "conflict-shrink"))
        self.assertIn("conflicts", demos["phase2_s10_then_s20"]["unknown_inputs"])

    def test_measured_phase2_ladder_never_grows_past_its_efficiency(self):
        waves = [w for w in waves_from_evidence(load("phase2_stages"), SOURCES["phase2_stages"])
                 if w["label"] in ("s10", "s20", "s25", "s50", "s75", "s100")]
        for before, after in zip(waves, waves[1:]):
            result = recommend_concurrency([before, after], {"start": 4, "max_agents": 1000, "max_batch": 8})
            if result["agents"] > after["agents"]:
                self.assertEqual(result["rule"], "grow-efficiency-improved")
                self.assertGreater(float(result["last_wave"]["verified_tasks_per_million_tokens"]),
                                   float(result["previous_wave"]["verified_tasks_per_million_tokens"]))

    def test_estimates_from_measured_rows_are_labelled(self):
        evidence = load("phase2_stages")
        for scope in ("feature", "mvp", "enterprise"):
            result = estimate_scope(scope, evidence)
            self.assertEqual((result["kind"], result["measured"]), ("ESTIMATE", False))
            self.assertIn("stand-ins", result["assumptions"]["validity"])
            self.assertEqual(result["money"], {"low": "unknown", "high": "unknown"})
            self.assertLess(result["tokens"]["input"]["low"]["value"], result["tokens"]["input"]["high"]["value"])
        self.assertEqual(engine("estimate-scope", {"scope": "mvp"}), estimate_scope("mvp", evidence))
        self.assertEqual(engine("estimate-rework", {"scope": "mvp"})["assumptions"]["rework_share"], ["0", "0.4"])


class ContextFootprint(unittest.TestCase):
    def test_this_tree_is_measured_by_a_stated_method(self):
        result = context_footprint(ROOT)
        self.assertIn("characters / 4", result["method"]["tokens"])
        self.assertIn("approximate", result["method"]["tokens"])
        always = result["always_loaded"]
        files = [row["file"] for row in always["instruction_files"]]
        self.assertEqual(files[:2], ["CLAUDE.md", "AGENTS.md"])
        self.assertEqual(always["chars"], sum(r["chars"] for r in always["instruction_files"])
                         + sum(r["listing_chars"] for r in always["skill_listing"] + always["agent_listing"]))
        self.assertEqual(always["tokens_approx"], always["chars"] // 4)
        self.assertGreater(len(always["skill_listing"]), 0)
        self.assertEqual(result["host_controlled_context"], "unknown")
        self.assertIn("swarm-light", result["lean_worker_definitions"])

    def test_synthetic_tree_counts_imports_once_and_listings_only(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / ".claude" / "skills" / "demo").mkdir(parents=True)
            (root / ".claude" / "agents").mkdir()
            (root / "CLAUDE.md").write_text("@AGENTS.md\nabcd\n", encoding="utf-8")
            (root / "AGENTS.md").write_text("x" * 40, encoding="utf-8")
            (root / ".claude" / "skills" / "demo" / "SKILL.md").write_text(
                "---\nname: demo\ndescription: twelve chars\n---\n" + "body " * 100, encoding="utf-8")
            (root / ".claude" / "agents" / "swarm-light.md").write_text(
                "---\nname: swarm-light\ndescription: lean\ntools: Bash\n---\nrun\n", encoding="utf-8")
            result = context_footprint(root)
        always = result["always_loaded"]
        self.assertEqual([(r["file"], r["chars"]) for r in always["instruction_files"]], [("CLAUDE.md", 16), ("AGENTS.md", 40)])
        self.assertEqual(always["skill_listing"][0]["listing_chars"], len("demo") + len("twelve chars"))
        self.assertEqual(always["chars"], 16 + 40 + 16 + len("swarm-light") + len("lean"))
        self.assertGreater(result["on_demand"]["chars"], always["chars"])


class BaselineEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = BASELINE.read_text(encoding="utf-8")
        cls.document = json.loads(cls.text)

    def test_public_safe_and_labelled(self):
        self.assertIsNone(SECRET.search(self.text))
        self.assertNotRegex(self.text, r"/home/|/root/|/Users/|[A-Za-z]:\\\\")
        doc = self.document
        self.assertEqual((doc["kind"], doc["layer"]), ("economics-baseline", "L19"))
        self.assertRegex(doc["measured_on"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertEqual(doc["method"]["provider_calls"], 0)
        self.assertEqual(doc["method"]["agents_run"], 0)
        self.assertIn("characters / 4", doc["method"]["context_tokens"]["tokens"])
        for estimate in doc["estimates"].values():
            self.assertEqual(estimate["kind"], "ESTIMATE")
            self.assertFalse(estimate["measured"])

    def test_bound_to_its_sources_and_reproducible(self):
        doc = self.document
        self.assertEqual({key: value["path"] for key, value in doc["sources"].items()}, SOURCES)
        unchanged = all(economics._file_sha(ROOT / value["path"]) == value["sha256"] for value in doc["sources"].values())
        fresh = baseline_document(ROOT, date=doc["measured_on"])
        if unchanged:  # the swarm evidence is fixed; a changed source means the baseline must be regenerated
            self.assertEqual(fresh["measured"], doc["measured"])
            self.assertEqual(fresh["estimates"], doc["estimates"])
        context = doc["context_footprint"]

        def files(footprint):
            rows = (footprint["always_loaded"]["instruction_files"] + footprint["on_demand"]["skill_bodies"]
                    + footprint["on_demand"]["agent_definitions"])
            return sorted((row["file"], row["sha256"]) for row in rows)
        if files(fresh["context_footprint"]) == files(context):  # other branches may change these files later
            self.assertEqual(fresh["context_footprint"]["always_loaded"], context["always_loaded"])
            self.assertEqual(fresh["context_footprint"]["on_demand"], context["on_demand"])
        always = context["always_loaded"]
        self.assertEqual(always["tokens_approx"], always["chars"] // 4)
        self.assertEqual(doc["context_comparison"]["repository_always_loaded_tokens_approx"], always["tokens_approx"])

    def test_missing_evidence_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for key in ("phase1_ladder", "phase1_tool_audit"):
                target = root / SOURCES[key]
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(ROOT / SOURCES[key], target)
            with self.assertRaises(EconomicsError):
                measured_baseline(root)
        with self.assertRaises(EconomicsError):
            baseline_document(ROOT, date="28/11/2026")

    def test_a_changed_results_table_is_caught(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for path in SOURCES.values():
                (root / path).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(ROOT / path, root / path)
            results = root / SOURCES["phase2_results"]
            text = results.read_text(encoding="utf-8")
            self.assertIn("| 76.57 |", text)
            results.write_text(text.replace("| 76.57 |", "| 77.57 |"), encoding="utf-8")
            rows = measured_baseline(root)["results_table_cross_check"]["rows"]
        bad = [row for row in rows if not row["agrees_with_stages_json"]]
        self.assertEqual(bad, [{"stage": "s20", "agrees_with_stages_json": False, "mismatched": ["Tasks/min"]}])

    def test_check_mode_reports_a_stale_file(self):
        with tempfile.TemporaryDirectory() as folder:
            stale = Path(folder) / "baseline.json"
            stale.write_text("{}\n", encoding="utf-8")
            command = ["baseline", "--date", "2026-11-28", "--out", str(stale)]
            with contextlib.redirect_stdout(io.StringIO()) as printed:
                self.assertEqual(economics.main(command + ["--check"]), 1)
                self.assertEqual(economics.main(command), 0)
                self.assertEqual(economics.main(command + ["--check"]), 0)
            self.assertIn("stale", printed.getvalue())
            self.assertTrue(re.search(r'"layer": "L19"', stale.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
