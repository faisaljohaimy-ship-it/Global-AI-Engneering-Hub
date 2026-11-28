"""API integration tests: the real HTTP server on a free loopback port, generated per entity."""
import pathlib
import tempfile
import time
import unittest

from tests.support import SCHEMA, Running, sample
from app import db, seed as seeding

PARENT_OF = {ref["field"]: ref for entity in SCHEMA.entities for ref in entity.references}


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = Running()

    @classmethod
    def tearDownClass(cls):
        cls.server.close()

    def call(self, *args, **kwargs):
        return self.server.request(*args, **kwargs)

    def path(self, entity, record_id=None):
        base = f"/api/{entity.collection}"
        return base if record_id is None else f"{base}/{record_id}"

    def parents(self, entity, n=1):
        refs = {}
        for ref in entity.references:
            refs[ref["field"]] = self.server.create(SCHEMA.by_name[ref["entity"]], n)["id"]
        return refs

    # -- per-entity checks -----------------------------------------------------
    def _create(self, entity):
        body = sample(entity, 3, self.parents(entity))
        status, headers, record = self.call("POST", self.path(entity), body)
        self.assertEqual(status, 201, record)
        self.assertEqual(headers["location"], self.path(entity, record["id"]))
        for key, value in body.items():
            self.assertEqual(record[key], value, key)
        self.assertRegex(record["created_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def _list(self, entity):
        created = [self.server.create(entity, n, self.parents(entity))["id"] for n in (4, 5)]
        status, _, page = self.call("GET", self.path(entity) + "?limit=500")
        self.assertEqual(status, 200)
        self.assertTrue(set(created) <= {item["id"] for item in page["items"]})
        self.assertGreaterEqual(page["total"], 2)
        status, _, page = self.call("GET", self.path(entity) + "?limit=1&offset=0")
        self.assertEqual((status, len(page["items"]), page["limit"]), (200, 1, 1))

    def _get(self, entity):
        record = self.server.create(entity, 6, self.parents(entity))
        status, _, fetched = self.call("GET", self.path(entity, record["id"]))
        self.assertEqual((status, fetched), (200, record))

    def _update(self, entity):
        record = self.server.create(entity, 7, self.parents(entity))
        body = sample(entity, 8, {ref["field"]: record[ref["field"]] for ref in entity.references})
        status, _, updated = self.call("PUT", self.path(entity, record["id"]), body)
        self.assertEqual(status, 200, updated)
        for key, value in body.items():
            self.assertEqual(updated[key], value, key)
        status, _, error = self.call("PUT", self.path(entity, record["id"]), {"__unknown__": 1})
        self.assertEqual((status, error["error"]["code"]), (400, "validation_failed"))
        status, _, _ = self.call("PUT", self.path(entity, 999999999), body)
        self.assertEqual(status, 404)

    def _delete(self, entity):
        record = self.server.create(entity, 9, self.parents(entity))
        status, _, body = self.call("DELETE", self.path(entity, record["id"]))
        self.assertEqual((status, body), (204, b""))
        self.assertEqual(self.call("GET", self.path(entity, record["id"]))[0], 404)
        self.assertEqual(self.call("DELETE", self.path(entity, record["id"]))[0], 404)

    def _validation(self, entity):
        status, _, error = self.call("POST", self.path(entity), {"__unknown__": "x"})
        self.assertEqual(status, 400)
        self.assertEqual(error["error"]["code"], "validation_failed")
        self.assertEqual(error["error"]["fields"]["__unknown__"], "unknown_field")
        required = [f["name"] for f in entity.fields if f.get("required") and "default" not in f]
        required += [ref["field"] for ref in entity.references if ref.get("required")]
        for name in required:
            self.assertEqual(error["error"]["fields"].get(name), "required", name)
        before = self.call("GET", self.path(entity) + "?limit=1")[2]["total"]
        for field in entity.fields:
            body = sample(entity, 1, self.parents(entity))
            body[field["name"]] = [] if field["type"] != "text" else "x" * (field.get("max", SCHEMA.limits["max_text"]) + 1)
            status, _, error = self.call("POST", self.path(entity), body)
            self.assertEqual(status, 400, field["name"])
            self.assertIn(field["name"], error["error"]["fields"])
        self.assertEqual(self.call("GET", self.path(entity) + "?limit=1")[2]["total"], before)

    def _not_found(self, entity):
        for path in (self.path(entity, 999999999), self.path(entity) + "/0", self.path(entity) + "/abc",
                     self.path(entity) + "/1/extra"):
            status, _, error = self.call("GET", path)
            self.assertEqual(status, 404, path)
            self.assertIn(error["error"]["code"], ("not_found",))

    # -- relations -------------------------------------------------------------
    def _reference_missing(self, entity, ref):
        refs = self.parents(entity)
        refs[ref["field"]] = 999999999
        status, _, error = self.call("POST", self.path(entity), sample(entity, 2, refs))
        self.assertEqual(status, 409, error)
        self.assertEqual(error["error"]["code"], "reference_not_found")
        self.assertEqual(error["error"]["fields"], {ref["field"]: "not_found"})

    def _reference_delete_parent(self, entity, ref):
        parent_entity = SCHEMA.by_name[ref["entity"]]
        child = self.server.create(entity, 2, self.parents(entity))
        parent_id = child[ref["field"]]
        status, _, body = self.call("DELETE", self.path(parent_entity, parent_id))
        if ref.get("required"):
            self.assertEqual(status, 409, body)
            self.assertEqual(body["error"]["code"], "has_dependents")
            self.assertGreaterEqual(body["error"]["dependents"][entity.name], 1)
            self.assertEqual(self.call("DELETE", self.path(entity, child["id"]))[0], 204)
            self.assertEqual(self.call("DELETE", self.path(parent_entity, parent_id))[0], 204)
        else:
            self.assertEqual(status, 204, body)
            self.assertIsNone(self.call("GET", self.path(entity, child["id"]))[2][ref["field"]])

    def _links(self, entity, link):
        targets = [self.server.create(SCHEMA.by_name[link["entity"]], n)["id"] for n in (1, 2)]
        body = sample(entity, 2, self.parents(entity))
        body[link["field"]] = targets
        status, _, record = self.call("POST", self.path(entity), body)
        self.assertEqual((status, record[link["field"]]), (201, sorted(targets)))
        body[link["field"]] = [999999999]
        self.assertEqual(self.call("POST", self.path(entity), body)[0], 409)
        body[link["field"]] = [targets[0], targets[0]]
        self.assertEqual(self.call("POST", self.path(entity), body)[0], 400)

    # -- boundary and security -------------------------------------------------
    def test_health(self):
        self.assertEqual(self.call("GET", "/api/health")[:3:2], (200, {"ok": True}))
        status, _, schema = self.call("GET", "/api/schema")
        self.assertEqual((status, [e["name"] for e in schema["entities"]]), (200, [e.name for e in SCHEMA.entities]))

    def test_security_headers(self):
        for path in ("/", "/static/app.js", "/api/health", "/api/nope"):
            _, headers, _ = self.call("GET", path)
            policy = headers["content-security-policy"]
            self.assertIn("frame-ancestors 'none'", policy, path)
            self.assertIn("default-src 'self'", policy, path)
            self.assertNotIn("unsafe-inline", policy)
            self.assertNotIn("unsafe-eval", policy)
            self.assertEqual(headers["x-content-type-options"], "nosniff")
            self.assertEqual(headers["x-frame-options"], "DENY")
            self.assertEqual(headers["referrer-policy"], "no-referrer")
            self.assertNotIn("access-control-allow-origin", headers)
            self.assertNotIn("python", headers.get("server", "").lower())

    def test_cross_origin_write_refused(self):
        entity = SCHEMA.entities[0]
        body = sample(entity, 1, self.parents(entity))
        for headers in ({"Origin": "https://attacker.example"}, {"Origin": "null"},
                        {"Sec-Fetch-Site": "cross-site"}, {"Sec-Fetch-Site": "same-site"}):
            status, _, error = self.call("POST", self.path(entity), body, headers=headers)
            self.assertEqual((status, error["error"]["code"]), (403, "cross_origin"), headers)
        record = self.server.create(entity, 1, self.parents(entity))
        status, _, _ = self.call("DELETE", self.path(entity, record["id"]), headers={"Origin": "https://attacker.example"})
        self.assertEqual(status, 403)
        same = {"Origin": f"http://127.0.0.1:{self.server.port}", "Sec-Fetch-Site": "same-origin"}
        self.assertEqual(self.call("POST", self.path(entity), body, headers=same)[0], 201)

    def test_wrong_content_type_refused(self):
        entity = SCHEMA.entities[0]
        for content_type in ("text/plain", "application/x-www-form-urlencoded", "multipart/form-data"):
            status, _, error = self.call("POST", self.path(entity), raw=b"{}", headers={"Content-Type": content_type})
            self.assertEqual((status, error["error"]["code"]), (415, "unsupported_media_type"))

    def test_oversized_body_refused(self):
        entity = SCHEMA.entities[0]
        raw = b'{"x": "' + b"a" * (SCHEMA.limits["max_body_bytes"] + 10) + b'"}'
        status, _, error = self.call("POST", self.path(entity), raw=raw)
        self.assertEqual((status, error["error"]["code"]), (413, "payload_too_large"))

    def test_invalid_json_refused(self):
        entity = SCHEMA.entities[0]
        for raw in (b"{", b"[1, 2]", b'{"a": 1, "a": 2}', b'{"a": NaN}', b"\xff\xfe"):
            status, _, error = self.call("POST", self.path(entity), raw=raw)
            self.assertEqual((status, error["error"]["code"]), (400, "invalid_json"), raw)

    def test_unknown_collection_404(self):
        for path in ("/api/does-not-exist", "/api/schema_migrations", "/api/sqlite_master", "/nowhere"):
            self.assertEqual(self.call("GET", path)[0], 404, path)

    def test_method_not_allowed(self):
        entity = SCHEMA.entities[0]
        for method, path in (("PATCH", self.path(entity, 1)), ("DELETE", self.path(entity)),
                             ("OPTIONS", self.path(entity)), ("POST", "/api/health"), ("PUT", "/")):
            status, headers, _ = self.call(method, path)
            self.assertEqual(status, 405, (method, path))
            self.assertIn("allow", headers)
            self.assertNotIn("access-control-allow-methods", headers)

    def test_bad_query_refused(self):
        entity = SCHEMA.entities[0]
        for query in ("?limit=0", "?limit=100000", "?offset=-1", "?unknown=1", "?limit=1&limit=2", "?limit=abc"):
            self.assertEqual(self.call("GET", self.path(entity) + query)[0], 400, query)

    def test_static_traversal_refused(self):
        for path in ("/static/../app/server.py", "/static/%2e%2e/app/db.py", "/static/../../etc/passwd",
                     "/static/", "/static/schema.json", "/app/schema.json", "/.git/config", "/data/app.sqlite3"):
            self.assertEqual(self.call("GET", path)[0], 404, path)

    def test_sql_injection_is_inert(self):
        entity = next((e for e in SCHEMA.entities if any(f["type"] == "text" for f in e.fields)), None)
        self.assertIsNotNone(entity, "the schema has at least one text field")
        field = next(f for f in entity.fields if f["type"] == "text")
        body = sample(entity, 1, self.parents(entity))
        payload = ("x'); DROP TABLE " + entity.table + "; --")[: field.get("max", 200)]
        body[field["name"]] = payload
        status, _, record = self.call("POST", self.path(entity), body)
        self.assertEqual((status, record[field["name"]]), (201, payload))
        self.assertEqual(self.call("GET", self.path(entity, record["id"]))[2][field["name"]], payload)
        query = "?" + (entity.references[0]["field"] + "=1%20OR%201=1" if entity.references else "limit=1%3B")
        self.assertEqual(self.call("GET", self.path(entity) + query)[0], 400)
        self.assertEqual(self.call("GET", self.path(entity))[0], 200)

    def test_list_latency_budget(self):
        budget = SCHEMA.nfr.get("p95_ms", 200)
        entity = SCHEMA.entities[0]
        for n in range(20):
            self.server.create(entity, n, self.parents(entity))
        samples = []
        for _ in range(60):
            start = time.perf_counter()
            self.assertEqual(self.call("GET", self.path(entity) + "?limit=100")[0], 200)
            samples.append((time.perf_counter() - start) * 1000)
        p95 = sorted(samples)[int(len(samples) * 0.95) - 1]
        self.assertLess(p95, budget, f"p95 {p95:.1f} ms over the {budget} ms local budget")

    def test_seed_is_synthetic(self):
        data = seeding.load()
        self.assertEqual(data["label"], "synthetic")
        with tempfile.TemporaryDirectory() as tmp:
            counts = seeding.seed(pathlib.Path(tmp) / "seed.sqlite3")
            self.assertEqual(counts, {e.name: len(data["records"].get(e.name, [])) for e in SCHEMA.entities})
            connection = db.connect(pathlib.Path(tmp) / "seed.sqlite3")
            try:
                for entity in SCHEMA.entities:
                    total = connection.execute("SELECT COUNT(*) FROM " + db.ident(entity.table)).fetchone()[0]
                    self.assertEqual(total, counts[entity.name])
            finally:
                connection.close()


def _bind(check, *args):
    def test(self):
        getattr(self, "_" + check)(*args)
    return test


for _entity in SCHEMA.entities:
    for _check in ("create", "list", "get", "update", "delete", "validation", "not_found"):
        setattr(ApiTests, f"test_{_check}_{_entity.table}", _bind(_check, _entity))
    for _ref in _entity.references:
        setattr(ApiTests, f"test_reference_{_entity.table}_{_ref['field']}_missing", _bind("reference_missing", _entity, _ref))
        setattr(ApiTests, f"test_reference_{_entity.table}_{_ref['field']}_delete_parent",
                _bind("reference_delete_parent", _entity, _ref))
    for _link in _entity.links:
        setattr(ApiTests, f"test_links_{_entity.table}_{_link['field']}", _bind("links", _entity, _link))


if __name__ == "__main__":
    unittest.main()
