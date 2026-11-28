"""Shared test helpers: synthetic records, signed-in sessions and a real server on a free port."""
import http.client
import http.cookies
import itertools
import json
import pathlib
import secrets
import sys
import tempfile
import threading

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import auth, db, model, server  # noqa: E402

SCHEMA = model.load_schema()
ADMIN = SCHEMA.auth["admin_role"]
FAST_ITERATIONS = 1000  # test accounts only; real accounts use schema.auth.pbkdf2_iterations
_UNIQUE = itertools.count(1)


def sample(entity, n, references=None, **overrides):
    """A valid synthetic record for `entity`; unique fields always get fresh values."""
    record = {}
    for field in entity.fields:
        kind, name = field["type"], field["name"]
        tag = f"{n}-{next(_UNIQUE)}" if field.get("unique") else str(n)
        if kind == "text":
            value = f"Synthetic {entity.name} {name} {tag}"
            record[name] = value[: field.get("max", 200)]
        elif kind == "email":
            record[name] = f"user{tag}@example.invalid"
        elif kind == "enum":
            record[name] = field["values"][n % len(field["values"])]
        elif kind in ("int", "number"):
            value = n if kind == "int" else n + 0.5
            record[name] = max(field.get("min", value), min(field.get("max", value), value))
        elif kind == "bool":
            record[name] = n % 2 == 0
        elif kind == "date":
            record[name] = f"2026-01-{n % 28 + 1:02d}"
        elif kind == "datetime":
            record[name] = f"2026-01-{n % 28 + 1:02d}T10:00:00Z"
    for ref in entity.references:
        if references and ref["field"] in references:
            record[ref["field"]] = references[ref["field"]]
    for rule in SCHEMA.rules.get("completion", []):
        if rule["entity"] == entity.name and record.get(rule["field"]) == rule["value"]:
            other = [v for v in entity.field(rule["field"])["values"] if v != rule["value"]]
            record[rule["field"]] = other[0] if other else record[rule["field"]]
    record.update(overrides)
    return record


def wrong_type(field):
    return {"text": 123, "email": 123, "int": "x", "number": "x", "bool": "yes",
            "date": 20260101, "datetime": 20260101, "enum": 7}[field["type"]]


def bad_format(field):
    return {"email": "not-an-email", "date": "2026-13-45", "datetime": "yesterday"}.get(field["type"])


class Running:
    """The real HTTP server on 127.0.0.1 with a private temporary database."""

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = pathlib.Path(self._tmp.name) / "test.sqlite3"
        self.app = server.App(self.db_path, quiet=True)
        self.httpd = server.make_server("127.0.0.1", 0, self.app)
        self.port = self.httpd.server_address[1]
        self.origin = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.sessions = {}

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self._tmp.cleanup()

    def account(self, role, iterations=FAST_ITERATIONS, email=None):
        email = email or f"{role}.{next(_UNIQUE)}@example.invalid"
        password = secrets.token_urlsafe(18)
        with db.session(self.db_path) as connection:
            auth.create_account(connection, SCHEMA, email, role, password, iterations=iterations)
        return email, password

    def login(self, role=ADMIN, email=None, password=None):
        """A fresh session for a new account with `role`: {cookie, csrf, email}."""
        if password is None:
            email, password = self.account(role, email=email)
        status, headers, body = self.request("POST", "/api/login", {"email": email, "password": password}, role=None)
        if status != 200:
            raise AssertionError(f"login failed: {status} {body}")
        jar = http.cookies.SimpleCookie(headers["set-cookie"])
        return {"cookie": f"session={jar['session'].value}", "csrf": body["csrf_token"], "email": email,
                "set_cookie": headers["set-cookie"]}

    def session(self, role):
        if role not in self.sessions:
            self.sessions[role] = self.login(role)
        return self.sessions[role]

    def request(self, method, path, body=None, headers=None, raw=None, role=ADMIN, session=None, csrf=True):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        try:
            sent = {"Content-Type": "application/json"} if (body is not None or raw is not None) else {}
            active = session if session is not None else (self.session(role) if role else None)
            if active:
                sent["Cookie"] = active["cookie"]
                if csrf and method not in ("GET", "HEAD"):
                    sent["X-CSRF-Token"] = active["csrf"]
            sent.update(headers or {})
            data = raw if raw is not None else (None if body is None else json.dumps(body).encode("utf-8"))
            connection.request(method, path, body=data, headers=sent)
            response = connection.getresponse()
            payload = response.read()
            kind = response.getheader("Content-Type") or ""
            value = json.loads(payload) if payload and "json" in kind else payload
            return response.status, {k.lower(): v for k, v in response.getheaders()}, value
        finally:
            connection.close()

    def create(self, entity, n=1, references=None, role=ADMIN, **overrides):
        """Create a record (and any required parents first) through the API."""
        references = dict(references or {})
        for ref in entity.references:
            if ref["field"] not in references and ref.get("required"):
                references[ref["field"]] = self.create(SCHEMA.by_name[ref["entity"]], n, role=role)["id"]
        status, _, value = self.request("POST", f"/api/{entity.collection}", sample(entity, n, references, **overrides),
                                        role=role)
        if status != 201:
            raise AssertionError(f"create {entity.name} failed: {status} {value}")
        return value
