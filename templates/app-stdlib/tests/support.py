"""Shared test helpers: synthetic sample records and an in-process server on a free port."""
import http.client
import json
import pathlib
import sys
import tempfile
import threading

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import model, server  # noqa: E402

SCHEMA = model.load_schema()
ORIGIN_HEADERS = {"Content-Type": "application/json"}


def sample(entity, n, references=None):
    """A valid synthetic record for `entity`; `references` maps reference fields to ids."""
    record = {}
    for field in entity.fields:
        kind, name = field["type"], field["name"]
        if kind == "text":
            value = f"Synthetic {entity.name} {name} {n}"
            record[name] = value[: field.get("max", 200)]
        elif kind == "email":
            record[name] = f"user{n}@example.invalid"
        elif kind == "enum":
            record[name] = field["values"][n % len(field["values"])]
        elif kind in ("int", "number"):
            value = n if kind == "int" else n + 0.5
            value = max(field.get("min", value), min(field.get("max", value), value))
            record[name] = value
        elif kind == "bool":
            record[name] = n % 2 == 0
        elif kind == "date":
            record[name] = f"2026-01-{n % 28 + 1:02d}"
        elif kind == "datetime":
            record[name] = f"2026-01-{n % 28 + 1:02d}T10:00:00Z"
    for ref in entity.references:
        if references and ref["field"] in references:
            record[ref["field"]] = references[ref["field"]]
    return record


def wrong_type(field):
    return {"text": 123, "email": 123, "int": "x", "number": "x", "bool": "yes",
            "date": 20260101, "datetime": 20260101, "enum": 7}[field["type"]]


def bad_format(field):
    return {"email": "not-an-email", "date": "2026-13-45", "datetime": "yesterday"}.get(field["type"])


class Running:
    """Start the real HTTP server on 127.0.0.1 with a private temporary database."""

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = pathlib.Path(self._tmp.name) / "test.sqlite3"
        self.app = server.App(self.db_path, quiet=True)
        self.httpd = server.make_server("127.0.0.1", 0, self.app)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self._tmp.cleanup()

    def request(self, method, path, body=None, headers=None, raw=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            sent = dict(ORIGIN_HEADERS if (body is not None or raw is not None) else {})
            sent.update(headers or {})
            data = raw if raw is not None else (None if body is None else json.dumps(body).encode("utf-8"))
            connection.request(method, path, body=data, headers=sent)
            response = connection.getresponse()
            payload = response.read()
            value = json.loads(payload) if payload and "json" in (response.getheader("Content-Type") or "") else payload
            return response.status, {k.lower(): v for k, v in response.getheaders()}, value
        finally:
            connection.close()

    def create(self, entity, n=1, references=None):
        """Create a record (and any required parents first) through the API."""
        references = dict(references or {})
        for ref in entity.references:
            if ref["field"] not in references and ref.get("required"):
                parent = self.create(SCHEMA.by_name[ref["entity"]], n)
                references[ref["field"]] = parent["id"]
        status, _, value = self.request("POST", f"/api/{entity.collection}", sample(entity, n, references))
        if status != 201:
            raise AssertionError(f"create {entity.name} failed: {status} {value}")
        return value
