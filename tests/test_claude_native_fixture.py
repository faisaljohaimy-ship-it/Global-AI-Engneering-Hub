"""Verify the native smoke verifier distinguishes discovery from execution."""
import json
import pathlib
import tempfile
import unittest

from scripts import verify_claude_master_mcp as smoke


class ClaudeNativeFixtureTests(unittest.TestCase):
    def test_native_result_must_match_tool_id_name_arguments_and_expected_scope(self):
        request = {"command": smoke.BUILD_COMMAND}
        step = smoke.Step("gaie_master_route", request,
                          smoke.verify_route("MASTER_BUILD", "a" * 40))
        valid = {"engine": "MASTER_BUILD", "status": "routed",
                 "master_approval": {"revision": "a" * 40}}
        initial = {"role": "user", "content": smoke.BUILD_COMMAND}
        tools = [{"name": step.wire_name}]
        assistant = {"type": "tool_use", "name": step.wire_name, "id": "toolu_gaie_fixture_0",
                     "input": {"request": request}}
        result = {"type": "tool_result", "tool_use_id": "toolu_gaie_fixture_0",
                  "content": [{"type": "text", "text": json.dumps(valid)}]}
        for bad_use, bad_result in (
            ({**assistant, "name": "mcp__gaie__gaie_architecture"}, result),
            ({**assistant, "input": {"request": {}}}, result),
            (assistant, {**result, "tool_use_id": "toolu_other"}),
            (assistant, {**result, "is_error": True}),
            (assistant, {**result, "content": [{"type": "text", "text": json.dumps(
                {**valid, "master_approval": {"revision": "b" * 40}})}]}),
            (assistant, result),
        ):
            script = smoke.Script(smoke.BUILD_COMMAND, [step])
            self.assertIn(b"event: content_block_delta", script.turn({
                "stream": True, "model": smoke.MODEL, "tools": tools, "messages": [initial],
            }))
            payload = {"stream": True, "model": smoke.MODEL, "tools": tools,
                       "messages": [initial, {"role": "assistant", "content": [bad_use]},
                                    {"role": "user", "content": [bad_result]}]}
            if bad_use != assistant or bad_result != result:
                with self.assertRaises(smoke.FixtureError):
                    script.turn(payload)
                self.assertEqual(script.observations, [])
            else:
                self.assertIn(smoke.RESULT_TEXT.encode(), script.turn(payload))
                self.assertEqual(script.observations, [{
                    "tool": "gaie_master_route", "result_sha256": smoke.value_sha256(valid),
                    "verified": {"engine": "MASTER_BUILD", "fixture_revision": "a" * 40},
                }])

    def test_unapproved_session_refuses_a_discovered_master_execution_tool(self):
        script = smoke.Script(smoke.BUILD_COMMAND, [smoke.Step(
            "gaie_master_status", {}, smoke.verify_blocked,
        )], forbidden_tools=("mcp__gaie__gaie_master_execute",))
        request = {"stream": True, "model": smoke.MODEL,
                   "tools": [{"name": "mcp__gaie__gaie_master_status"},
                             {"name": "mcp__gaie__gaie_master_execute"}],
                   "messages": [{"role": "user", "content": smoke.BUILD_COMMAND}]}
        with self.assertRaises(smoke.FixtureError):
            script.turn(request)
        self.assertEqual(script.requests, 0)
        with self.assertRaises(smoke.FixtureError):
            smoke.verify_blocked({"status": "approved", "master_tools_enabled": True})

    def test_isolated_env_uses_only_private_state_and_loopback_fixture(self):
        with tempfile.TemporaryDirectory() as folder:
            state = pathlib.Path(folder)
            url = "http://127.0.0.1:8123"
            env = smoke.isolated_env(state, url)
            for path in ("HOME", "CLAUDE_CONFIG_DIR", "XDG_CACHE_HOME", "TMPDIR"):
                home = pathlib.Path(env[path])
                self.assertEqual(home.parent, state)
                self.assertEqual(home.stat().st_mode & 0o777, 0o700)
            self.assertEqual(env["ANTHROPIC_BASE_URL"], url)
            self.assertEqual(env["ANTHROPIC_API_KEY"], smoke.FIXTURE_PLACEHOLDER)
            self.assertEqual(env["HTTPS_PROXY"], url)
            self.assertEqual(env["NO_PROXY"], "127.0.0.1")
