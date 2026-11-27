import copy
import json
import pathlib
import unittest
from unittest import mock

from engineering_os.model_router import RoutingError, select_model, validate_registry

ROOT = pathlib.Path(__file__).resolve().parents[1]
NOW = 1800000000


class ModelRouterTests(unittest.TestCase):
    """All operational/model/pricing fixtures here are synthetic, never live calls."""
    def setUp(self):
        self.model = {"id":"synthetic-local","provider":"local","status":"PROJECT_VERIFIED",
                      "model_id":"synthetic-snapshot-20260101","revision":"a"*40,
                      "reviews":{"license":"approved","security":"approved","commercial":"approved"},
                      "tasks":["coding"],"max_complexity":5,"context_tokens":4096,
                      "runtime_sha256":"b"*64,
                      "pricing":{"input_per_million_usd":"0","output_per_million_usd":"0","verified_at":NOW}}
        self.registry = {"schema_version":1,"evidence_max_age_seconds":3600,"models":[self.model]}
        self.request = {"project":"opaque-project","task":"coding","complexity":3,
                        "input_tokens":1000,"output_tokens":100,"privacy":"confidential",
                        "permissions":["source:read"],"max_cost_usd":"0","min_quality":.8,"max_latency_ms":1000}
        self.receipt = {"revision":"a"*40,"operational":True,"tested":True,"project_verified":True,
                        "at":NOW,"receipt_sha256":"c"*64,"quality":.9,"latency_ms":100,
                        "remaining_requests":10,"remaining_tokens":10000,"permissions":["source:read"],
                        "privacy":["public","confidential"],"runtime_sha256":"b"*64,
                        "cost_approved":True,"free_allowance_verified":False}
        self.evidence = {"schema_version":1,"project":"opaque-project","models":{"synthetic-local":self.receipt}}

    def choose(self, **options):
        return select_model(self.registry,self.request,self.evidence,environ=options.pop("environ",{}),now=NOW,**options)

    def rejected(self, reason):
        result = self.choose()
        self.assertEqual(result["decision"], "blocked", result)
        self.assertIn(reason,result["rejected"][self.model["id"]])

    def remote(self):
        self.model["provider"] = "openai"
        self.model["credential_env"] = "SYNTHETIC_TEST_KEY"
        self.receipt["free_allowance_verified"] = True

    def test_default_registry_contains_zero_available_model_versions(self):
        registry = json.loads((ROOT/"catalog/models/registry.json").read_text())
        self.assertTrue(validate_registry(registry))
        result = select_model(registry,self.request,now=NOW,environ={})
        self.assertIsNone(result["selected"])
        self.assertEqual(len(result["rejected"]),5)
        self.assertTrue(all(row==["not_project_verified"] for row in result["rejected"].values()))

    def test_synthetic_local_fixture_is_deterministic_and_offline(self):
        with mock.patch("socket.socket",side_effect=AssertionError("must not access network")):
            one,two = self.choose(),self.choose()
        self.assertEqual(one,two)
        self.assertEqual(one["selected"]["id"],"synthetic-local")
        self.assertEqual(one["selected"]["estimated_cost_usd"],"0")
        self.assertEqual(one["provider_calls"],0)
        self.assertFalse(one["quota_reserved"])

    def test_remote_credential_is_required_but_never_returned(self):
        self.remote()
        self.rejected("credential_unavailable")
        result = self.choose(environ={"SYNTHETIC_TEST_KEY":"synthetic-not-a-provider-key"})
        self.assertEqual(result["decision"],"eligible")
        self.assertNotIn("synthetic-not-a-provider-key",json.dumps(result))

    def test_cost_is_decimal_and_must_fit_explicit_authority(self):
        self.model["pricing"].update(input_per_million_usd="2",output_per_million_usd="10")
        self.request["max_cost_usd"] = ".0029"
        self.rejected("cost_budget")
        self.request["max_cost_usd"] = ".003"
        self.assertEqual(self.choose()["selected"]["estimated_cost_usd"],"0.003")
        self.receipt["cost_approved"] = False
        self.rejected("pricing_or_cost_authority_expired")

    def test_free_remote_price_needs_verified_free_allowance(self):
        self.remote()
        self.receipt["free_allowance_verified"] = False
        result = self.choose(environ={"SYNTHETIC_TEST_KEY":"synthetic"})
        self.assertIn("free_allowance_unverified",result["rejected"]["synthetic-local"])

    def test_project_privacy_permissions_usage_and_context_fail_closed(self):
        cases=[("privacy",["public"],"privacy_denied"),
               ("permissions",[],"permission_denied"),
               ("remaining_requests",0,"usage_limit"),
               ("remaining_tokens",1099,"usage_limit")]
        for field,value,reason in cases:
            original=copy.deepcopy(self.receipt[field]);self.receipt[field]=value
            with self.subTest(field=field):self.rejected(reason)
            self.receipt[field]=original
        self.request["input_tokens"] = 5000
        self.rejected("context_capacity")
        self.evidence["project"] = "another-project"
        with self.assertRaises(RoutingError):self.choose()

    def test_stale_future_or_mismatched_runtime_evidence_is_not_operational(self):
        for at in [NOW-3601,NOW+1]:
            self.receipt["at"] = at
            self.rejected("stale_or_invalid_evidence")
        self.receipt["at"] = NOW
        self.receipt["runtime_sha256"] = "d"*64
        self.rejected("local_runtime_unverified")
        self.receipt["revision"] = "e"*40
        self.rejected("runtime_not_verified_at_pin")

    def test_pinned_reviewed_exact_model_and_fresh_pricing_are_required(self):
        for field,value,reason in [("revision","main","unreviewed_or_unpinned"),
                                   ("model_id","provider/model-latest","missing_exact_model_identifier"),
                                   ("reviews",{},"unreviewed_or_unpinned")]:
            original=self.model[field];self.model[field]=value
            with self.subTest(field=field):self.rejected(reason)
            self.model[field]=original
        self.model["pricing"]["verified_at"] = NOW-3601
        self.rejected("pricing_or_cost_authority_expired")

    def test_quality_speed_task_and_complexity_filters_precede_ranking(self):
        for field,value,reason in [("quality",.7,"quality_floor"),("latency_ms",1001,"latency_budget")]:
            original=self.receipt[field];self.receipt[field]=value
            self.rejected(reason);self.receipt[field]=original
        self.model["max_complexity"] = 2
        self.rejected("task_or_complexity_mismatch")
        self.model["max_complexity"] = 5
        self.model["tasks"] = ["vision"]
        self.rejected("task_or_complexity_mismatch")

    def test_ranking_ties_are_stable_and_weights_are_explicit(self):
        other=copy.deepcopy(self.model);other["id"]="another-synthetic"
        self.registry["models"].append(other)
        self.evidence["models"][other["id"]]=copy.deepcopy(self.receipt)
        self.assertEqual(self.choose()["selected"]["id"],"another-synthetic")
        self.evidence["models"][other["id"]]["latency_ms"]=900
        self.request["weights"]={"quality":0,"speed":1,"cost":0}
        self.assertEqual(self.choose()["selected"]["id"],"synthetic-local")

    def test_nonfinite_boolean_and_bad_constraints_are_refused(self):
        for field in ["max_cost_usd","min_quality","max_latency_ms"]:
            for value in [True,float("nan"),float("inf"),-1]:
                original=self.request[field];self.request[field]=value
                with self.subTest(field=field,value=value),self.assertRaises(RoutingError):self.choose()
                self.request[field]=original
        for value in [True,1.5,-1]:
            self.request["input_tokens"]=value
            with self.assertRaises(RoutingError):self.choose()

    def test_raw_prompts_secrets_and_malformed_evidence_are_not_metadata(self):
        for field in ["prompt","api_key","password"]:
            with self.assertRaises(RoutingError):
                select_model(self.registry,{**self.request,field:"synthetic"},self.evidence,environ={},now=NOW)
        self.receipt["api_key"]="synthetic"
        self.rejected("missing_or_malformed_operational_evidence")
        del self.receipt["api_key"]
        self.model["api_key"]="synthetic"
        with self.assertRaises(RoutingError):self.choose()

    def test_absent_evidence_does_not_assume_credentials_are_sufficient(self):
        self.remote()
        result=select_model(self.registry,self.request,environ={"SYNTHETIC_TEST_KEY":"synthetic"},now=NOW)
        self.assertIsNone(result["selected"])
        self.assertIn("missing_or_malformed_operational_evidence",result["rejected"]["synthetic-local"])

    def test_malformed_permissions_and_duplicate_registry_are_refused(self):
        self.request["permissions"]=[{}]
        with self.assertRaises(RoutingError):self.choose()
        self.request["permissions"]=["source:read"]
        self.registry["models"].append(copy.deepcopy(self.model))
        with self.assertRaises(RoutingError):self.choose()
