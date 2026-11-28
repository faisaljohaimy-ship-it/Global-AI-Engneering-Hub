"""Wave-2 engines through the one governed entry, control_plane.invoke, with the real Security Governor.

Every action registered by the wave-2 integration runs once with a real minimal payload in a private
temporary workspace and must return a contract-valid receipt bound to its request, result and sources,
plus one usage row. Unknown actions are rejected before the governor; malformed payloads fail inside the
adapter after an audited allow, never with "has no action" (the rules of tests/test_control_plane.py).
Every path-bearing wave-2 action refuses a location outside its grant (governor) and a location reached
through a symbolic link (adapter, before the governor), and its adapter never runs.
No network, model or provider is used. The media actions need ffmpeg, node and headless Chromium; they
skip with a message where those are absent. All data is synthetic.
"""
import contextlib
import io
import json
import os
import pathlib
import shutil
import sys
import tempfile
import unittest
from unittest import mock

from engineering_os import adapters, contracts, control_plane as cp

ROOT = pathlib.Path(__file__).resolve().parents[1]
NOW = "2026-11-28T06:36:23Z"
GOVERNOR = cp.governor is not None
NEW_ENGINES = {"orchestrator": "L03", "security-audit": "L09", "requirements": "L15", "cinematic-production": "L18"}
# Actions added to engines that existed before wave 2, by the same integration.
NEW_ACTIONS = {}
HAVE_MEDIA_TOOLS = bool(shutil.which("ffmpeg") and shutil.which("ffprobe") and shutil.which("node"))
STORYBOARD = {"schema": "gaie.storyboard/1", "id": "registry-clip", "title": {"en": "Registry clip"}, "languages": ["en"],
              "format": {"width": 320, "height": 180, "fps": 24},
              "audio": {"bpm": 120, "music": True, "sound_design": False, "voiceover": None},
              "scenes": [{"id": "one", "duration_ms": 2000, "motion": {"source": "reference", "id": "os-networks-b01"},
                          "text": {"en": "It works."}}]}
SCENARIO_H = ROOT / "docs/evidence/gaie-20-layers/scenario-h.json"


def registered():
    return {record["id"]: record for record in cp.load_registry()}


def wave2_actions():
    """Every (engine, action) this integration registered."""
    records = registered()
    pairs = {(engine, action) for engine in NEW_ENGINES for action in records[engine]["actions"]}
    return pairs | {(engine, action) for engine, actions in NEW_ACTIONS.items() for action in actions}


def grant(engines, *, max_side_effect="none", paths=()):
    return {"grant_id": "g-test-w2-registry", "role": "control-plane-integration-engineer", "engines": engines,
            "paths": [str(p) for p in paths], "max_side_effect": max_side_effect,
            "expires_at": "2099-01-01T00:00:00Z", "approvals": []}


def adapter_name(engine):
    return registered()[engine]["entrypoint"].split(":")[1]


@unittest.skipUnless(GOVERNOR, "engineering_os/governor.py is not installed; every invoke is refused")
class _Governed(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="gaie-w2-", dir="/tmp")
        self.addCleanup(temporary.cleanup)
        self.base = pathlib.Path(temporary.name)
        os.chmod(self.base, 0o700)
        self.state = self.base / "state"
        self.work = self.base / "work"
        self.work.mkdir(mode=0o700)
        self.ctx = {"state_dir": str(self.state)}

    def ledger(self):
        path = self.state / "economics" / "ledger.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def invoke(self, engine, action, payload, *, paths=()):
        """Invoke under a grant of exactly this action at its registered side effect; check the receipt."""
        spec = registered()[engine]["actions"][action]
        rows = len(self.ledger())
        out = cp.invoke(engine, action, payload, grant=grant({engine: [action]}, max_side_effect=spec["side_effect"],
                                                             paths=paths), ctx=self.ctx)
        self.assertEqual(set(out), {"ok", "engine", "action", "result", "receipt"})
        self.assertTrue(out["ok"])
        receipt = contracts.validate_receipt(out["receipt"])
        self.assertEqual(receipt["request_sha256"], contracts.sha256({"engine": engine, "action": action, "payload": payload}))
        self.assertEqual(receipt["result_sha256"], contracts.sha256(out["result"]))
        self.assertEqual(receipt["source_sha256"], cp.describe(engine)["source_sha256"])
        self.assertEqual((receipt["grant_id"], receipt["side_effect"]), ("g-test-w2-registry", spec["side_effect"]))
        ledger = self.ledger()
        self.assertEqual(len(ledger), rows + 1)
        self.assertEqual((ledger[-1]["engine"], ledger[-1]["action"], ledger[-1]["status"]), (engine, action, "ok"))
        return out["result"]


class RegistryTests(unittest.TestCase):
    def test_new_engines_are_registered_on_their_layers_with_sources(self):
        records = registered()
        layers = cp.layers()
        for engine, layer in NEW_ENGINES.items():
            with self.subTest(engine=engine):
                self.assertEqual(records[engine]["layer"], layer)
                self.assertIn(engine, layers[layer])
                described = cp.describe(engine)
                self.assertTrue(all(value and len(value) == 64 for value in described["sources"].values()), described["sources"])
        for engine, actions in NEW_ACTIONS.items():
            self.assertLessEqual(set(actions), set(records[engine]["actions"]), engine)

    def test_registered_actions_stay_at_or_below_workspace_write_and_publish_is_not_registered(self):
        for engine, action in wave2_actions():
            effect = registered()[engine]["actions"][action]["side_effect"]
            self.assertLessEqual(contracts.side_effect_rank(effect), contracts.side_effect_rank("workspace-write"),
                                 (engine, action))
        self.assertNotIn("publish", registered()["master-build"]["actions"])

    def test_every_path_bearing_wave2_action_is_canonical_and_governed(self):
        for (engine, action), fields in adapters.CANONICAL_PATH_FIELDS.items():
            with self.subTest(engine=engine, action=action):
                self.assertIn((engine, action), wave2_actions())
                self.assertEqual(tuple(adapters.PATH_FIELDS[(engine, action)]), tuple(fields))
                self.assertEqual(cp.describe(engine)["path_fields"][action], list(fields))

    def test_unknown_actions_are_adapter_errors_and_bad_payloads_never_say_no_action(self):
        with tempfile.TemporaryDirectory(prefix="gaie-w2-", dir="/tmp") as state:
            os.chmod(state, 0o700)
            ctx = {"state_dir": pathlib.Path(state), "environ": {}, "root": ROOT}
            for engine, action in sorted(wave2_actions()):
                entry = contracts.resolve(registered()[engine]["entrypoint"])
                with self.subTest(engine=engine, action=action):
                    with self.assertRaises(Exception) as caught:
                        entry(action, {"unexpected_field": 1}, ctx)
                    self.assertNotIn("has no action", str(caught.exception))
            for engine in NEW_ENGINES:
                with self.subTest(engine=engine), self.assertRaises(adapters.AdapterError):
                    contracts.resolve(registered()[engine]["entrypoint"])("not-an-action", {}, ctx)

    def test_new_engines_report_healthy_without_side_effects(self):
        with tempfile.TemporaryDirectory(prefix="gaie-w2-", dir="/tmp") as home, mock.patch.dict(os.environ, {"GAIE_HOME": home}):
            rows = {engine: cp.health(engine) for engine in NEW_ENGINES}
            self.assertEqual(os.listdir(home), [])
        for engine, row in rows.items():
            with self.subTest(engine=engine):
                self.assertIs(row["ok"], True, row["detail"])


class RefusalTests(_Governed):
    def test_unknown_action_is_rejected_before_the_governor(self):
        for engine in NEW_ENGINES:
            with self.subTest(engine=engine), mock.patch.object(cp.governor, "check") as check:
                with self.assertRaisesRegex(cp.ControlPlaneError, "unknown action"):
                    cp.invoke(engine, "drop-everything", {}, grant=grant({engine: ["drop-everything"]}), ctx=self.ctx)
                check.assert_not_called()
        self.assertEqual(self.ledger(), [])

    def test_bad_payloads_fail_inside_the_adapter_and_are_accounted(self):
        for engine, action in sorted(wave2_actions()):
            spec = registered()[engine]["actions"][action]
            with self.subTest(engine=engine, action=action):
                with self.assertRaises(cp.EngineFailure) as caught:
                    cp.invoke(engine, action, {"unexpected_field": 1}, ctx=self.ctx,
                              grant=grant({engine: [action]}, max_side_effect=spec["side_effect"], paths=[self.work, ROOT]))
                self.assertNotIn("has no action", str(caught.exception))
                self.assertEqual(self.ledger()[-1]["status"], "failed")

    def test_ungranted_action_is_denied_and_runs_nothing(self):
        with mock.patch.object(adapters, "requirements") as adapter, self.assertRaises(cp.governor.GovernorDenied) as caught:
            cp.invoke("requirements", "parse", {"command": "Build a system"}, grant=grant({"requirements": ["validate"]}),
                      ctx=self.ctx)
        adapter.assert_not_called()
        self.assertEqual(caught.exception.reason, "action-not-granted")
        self.assertEqual(self.ledger(), [])

    def assert_path_refused(self, engine, action, payload, field, error):
        spec = registered()[engine]["actions"][action]
        with mock.patch.object(adapters, adapter_name(engine)) as adapter:
            with self.assertRaises(error) as caught:
                cp.invoke(engine, action, payload, ctx=self.ctx,
                          grant=grant({engine: [action]}, max_side_effect=spec["side_effect"], paths=[self.work]))
            adapter.assert_not_called()
        self.assertEqual(self.ledger(), [])
        return caught.exception

    def test_escaping_and_symlinked_locations_are_refused_for_every_path_bearing_action(self):
        outside = self.base / "outside"
        outside.mkdir(mode=0o700)
        (outside / "clip.mp4").write_bytes(b"\0" * 16)
        link = self.work / "link"
        link.symlink_to(outside, target_is_directory=True)
        for (engine, action), fields in sorted(adapters.CANONICAL_PATH_FIELDS.items()):
            for field in fields:
                inside = {name: str(self.work / name) for name in fields}
                with self.subTest(engine=engine, action=action, field=field, case="outside the grant"):
                    denial = self.assert_path_refused(engine, action, {**inside, field: str(outside / "clip.mp4")}, field,
                                                      cp.governor.GovernorDenied)
                    self.assertEqual(denial.reason, "path-outside-grant")
                with self.subTest(engine=engine, action=action, field=field, case="through a symlink"):
                    error = self.assert_path_refused(engine, action, {**inside, field: str(link / "clip.mp4")}, field,
                                                     cp.ControlPlaneError)
                    self.assertIn("symbolic link", str(error))
                with self.subTest(engine=engine, action=action, field=field, case="non-canonical"):
                    error = self.assert_path_refused(engine, action, {**inside, field: str(self.work) + "/../outside"},
                                                     field, cp.ControlPlaneError)
                    self.assertIn("canonical", str(error))
        self.assertEqual(sorted(p.name for p in outside.iterdir()), ["clip.mp4"])


class OrchestratorTests(_Governed):
    def test_plan_schedule_review_worktrees_and_scenario_h(self):
        made = self.invoke("orchestrator", "plan", {"goal": "w2-registry-goal", "now": NOW, "max_agents": 4})
        self.assertEqual(made["schema"], "gaie.orchestration-plan/1")
        self.assertTrue(all(len(wave) <= 4 for wave in made["waves"]))
        self.assertTrue(all(made["checks"].values()))
        nxt = self.invoke("orchestrator", "schedule", {"plan": made, "history": [], "cpus": 4})
        self.assertEqual((nxt["rule"], nxt["plan_sha256"]), ("start", made["plan_sha256"]))
        review = self.invoke("orchestrator", "review-assignment", {"task": made["tasks"][0]})
        self.assertNotEqual(review["reviewer"], made["tasks"][0]["role"])
        repo = self.work / "repo"
        repo.mkdir()
        trees = self.invoke("orchestrator", "worktree-plan", {"plan": made, "repo": str(repo), "base_dir": str(self.work / "trees")},
                            paths=[self.work])
        self.assertIs(trees["executed"], False)
        self.assertEqual(len(trees["agents"]), len(made["agents"]))
        self.assertFalse((self.work / "trees").exists())
        from engineering_os import orchestrator
        metrics = json.loads(SCENARIO_H.read_text(encoding="utf-8"))["source"]["snapshot"]
        figures = self.invoke("orchestrator", "scenario-h", {"metrics": metrics, "cpus": 4})
        self.assertEqual(figures, json.loads(json.dumps(orchestrator.scenario_h(metrics, cpus=4))))


class SecurityAuditTests(_Governed):
    def test_static_scan_full_audit_and_audit_log_anchor(self):
        scan = self.invoke("security-audit", "scan", {})
        self.assertEqual((scan["tool"], scan["probes_run"], scan["network"]), ("engineering_os.security_audit", False, False))
        audit = self.invoke("security-audit", "audit", {}, paths=[ROOT])
        self.assertTrue(audit["probes_run"])
        self.assertTrue(any(row["kind"] == "registered" for row in audit["findings"]))
        anchor = self.invoke("security-audit", "anchor", {})
        self.assertGreaterEqual(anchor["records"], 3)
        intact = self.invoke("security-audit", "verify-anchor", {"anchor": anchor})
        self.assertEqual(intact, {"intact": True, "records": anchor["records"] + 1})
        ahead = {"records": anchor["records"] + 50, "record_sha256": anchor["record_sha256"]}
        self.assertEqual(self.invoke("security-audit", "verify-anchor", {"anchor": ahead}),
                         {"intact": False, "reason": "audit-tampered"})

    def test_full_audit_needs_the_hub_checkout_in_its_grant(self):
        with mock.patch.object(adapters, "security_audit") as adapter, self.assertRaises(cp.governor.GovernorDenied) as caught:
            cp.invoke("security-audit", "audit", {}, grant=grant({"security-audit": ["audit"]}, max_side_effect="workspace-write",
                                                                 paths=[self.work]), ctx=self.ctx)
        adapter.assert_not_called()
        self.assertEqual(caught.exception.reason, "path-outside-grant")


class RequirementsTests(_Governed):
    def test_parse_refine_validate_diff_acceptance_and_packs(self):
        parsed = self.invoke("requirements", "parse", {"command": "Build a system", "language": "en"})["result"]["spec"]
        self.assertEqual([q["id"] for q in parsed["open_questions"]], ["domain"])
        refined = self.invoke("requirements", "refine", {"spec": parsed, "answers": {"domain": "project-management"}})
        spec = refined["result"]["spec"]
        self.assertEqual((spec["domain"], spec["open_questions"]), ("project-management", []))
        self.assertTrue(self.invoke("requirements", "validate", {"spec": spec})["ok"])
        diff = self.invoke("requirements", "diff", {"old": spec, "new": spec})["result"]["diff"]
        self.assertEqual(diff["breaking"], [])
        checks = self.invoke("requirements", "acceptance", {"spec": spec})["result"]["acceptance"]
        self.assertTrue(checks)
        packs = self.invoke("requirements", "packs", {})["result"]["packs"]
        self.assertIn("project-management", json.dumps(packs))

    def test_hub_cli_invokes_under_a_grant_and_exits_3_when_denied(self):
        path = self.base / "grant.json"
        path.write_text(json.dumps(grant({"requirements": ["parse"]})))
        code, text = self.run_hub("invoke", "requirements", "parse", "--payload", json.dumps({"command": "Build a system"}),
                                  "--grant", str(path), "--state", str(self.state))
        self.assertEqual(code, 0, text)
        contracts.validate_receipt(json.loads(text)["receipt"])
        code, text = self.run_hub("invoke", "requirements", "packs", "--payload", "{}", "--grant", str(path),
                                  "--state", str(self.state))
        self.assertEqual((code, json.loads(text)["status"]), (3, "denied"))

    def run_hub(self, *argv):
        out = io.StringIO()
        code = 0
        with mock.patch.object(sys, "argv", ["hub.py", *argv]), contextlib.redirect_stdout(out):
            import hub
            try:
                hub.main()
            except SystemExit as stop:
                code = stop.code
        return code, out.getvalue()


class CinematicProductionTests(_Governed):
    def test_inventory_validate_direct_and_subtitles(self):
        from engineering_os import video_pipeline
        inventory = self.invoke("cinematic-production", "inventory", {})
        self.assertEqual(inventory, json.loads(json.dumps(video_pipeline.inventory())))
        self.assertEqual(inventory["native_total"], inventory["native_engine_motions"]["count"]
                         + inventory["nextgen_camera_motions"]["count"])
        self.assertEqual(inventory["native_engine_motions"]["source_bound_to_registry"],
                         inventory["native_engine_motions"]["count"])
        valid = self.invoke("cinematic-production", "validate", {"storyboard": STORYBOARD})
        self.assertEqual((valid["valid"], valid["frames"]), (True, 48))
        self.assertTrue(self.invoke("cinematic-production", "direct", {"storyboard": STORYBOARD})["passed"])
        subtitles = self.invoke("cinematic-production", "subtitles", {"storyboard": STORYBOARD})
        self.assertIn("It works.", subtitles["en"]["vtt"])

    @unittest.skipUnless(HAVE_MEDIA_TOOLS, "ffmpeg, ffprobe or node is not installed")
    def test_render_into_a_granted_directory_then_measure_it(self):
        media = self.work / "media"
        try:
            rendered = self.invoke("cinematic-production", "render", {"storyboard": STORYBOARD, "out_dir": str(media),
                                                                      "name": "registry-clip"}, paths=[self.work])
        except cp.EngineFailure as failure:
            if "ToolMissing" in str(failure):
                self.skipTest(f"headless Chromium is not available here: {failure}")
            raise
        self.assertTrue(rendered["qa_passed"], rendered["qa"])
        main = next(row for row in rendered["outputs"] if row["variant"] == "main")
        self.assertEqual(pathlib.Path(main["path"]).parent, media)
        measured = self.invoke("cinematic-production", "qa", {"path": main["path"], "expect": {
            "width": 320, "height": 180, "fps": 24, "frames": 48}}, paths=[self.work])
        self.assertTrue(measured["passed"], measured["checks"])
        self.assertTrue(all(pathlib.Path(row["path"]).parent == media for row in rendered["outputs"]))

    @unittest.skipUnless(HAVE_MEDIA_TOOLS, "ffmpeg, ffprobe or node is not installed")
    def test_probe_reports_browser_and_voice_capability(self):
        try:
            probe = self.invoke("cinematic-production", "probe", {})
        except cp.EngineFailure as failure:
            if "ToolMissing" in str(failure):
                self.skipTest(f"headless Chromium is not available here: {failure}")
            raise
        self.assertIn("webgl2_executed", probe["browser"])
        self.assertIs(probe["voiceover"]["paid_or_network_tts_used"], False)


class CoverageTests(unittest.TestCase):
    """Order-independent: every registered wave-2 action is named in an invoke call of this module."""

    def test_every_wave2_action_has_an_invoke_case_in_this_module(self):
        source = pathlib.Path(__file__).read_text(encoding="utf-8")
        for engine, action in sorted(wave2_actions()):
            with self.subTest(engine=engine, action=action):
                self.assertIn(f'"{engine}", "{action}"', source)


if __name__ == "__main__":
    unittest.main()
