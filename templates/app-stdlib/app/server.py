"""JSON REST API and static frontend on http.server + sqlite3 (standard library only).

Security posture (see README "Security"): every response carries a restrictive
Content-Security-Policy with frame-ancestors 'none', nosniff and no-referrer;
writes require a JSON body and a same-origin request (no CORS headers are ever
sent); bodies are size-limited; SQL is parameterized; nothing is evaluated.
There is no user authentication: the server binds to loopback by default.
"""
import datetime
import http.server
import json
import pathlib
import re
import sqlite3
import sys
import traceback
import urllib.parse

from . import db, model

ROOT = pathlib.Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
}
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; "
       "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
SECURITY_HEADERS = (
    ("Content-Security-Policy", CSP),
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "no-referrer"),
    ("Cross-Origin-Opener-Policy", "same-origin"),
    ("Cross-Origin-Resource-Policy", "same-origin"),
    ("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()"),
)
LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost"})
RECORD_ID = re.compile(r"[1-9][0-9]{0,15}")
MAX_URL = 2048


class ApiError(Exception):
    def __init__(self, status, code, message, fields=None, headers=(), extra=None):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message
        self.fields, self.headers, self.extra = fields, headers, extra or {}


def _no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _reject_constant(_):
    raise ValueError("invalid number")


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class App:
    """Application state shared by request handlers (read-only after start)."""

    def __init__(self, db_path, schema=None, static_dir=STATIC, quiet=False):
        self.schema = schema or model.load_schema()
        self.db_path = str(db_path)
        self.quiet = quiet
        self.static = {}
        for path in sorted(pathlib.Path(static_dir).iterdir()):
            if path.is_file() and not path.is_symlink() and path.suffix in CONTENT_TYPES:
                self.static[path.name] = (path.read_bytes(), CONTENT_TYPES[path.suffix])
        connection = db.connect(self.db_path)
        try:
            db.migrate(connection)
        finally:
            connection.close()


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "app"
    sys_version = ""
    timeout = 15

    @property
    def app(self):
        return self.server.app

    def log_message(self, fmt, *args):
        if not self.app.quiet:
            sys.stderr.write(f"{self.log_date_time_string()} {fmt % args}\n")

    def log_request(self, code="-", size="-"):
        if not self.app.quiet:
            path = urllib.parse.urlsplit(self.path).path[:200]
            sys.stderr.write(f"{self.log_date_time_string()} {self.command} {path} {code}\n")

    def do_GET(self):
        self._dispatch("GET")

    def do_HEAD(self):
        self._dispatch("HEAD")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def do_PATCH(self):
        self._dispatch("PATCH")

    def do_OPTIONS(self):
        self._dispatch("OPTIONS")

    # -- responses -------------------------------------------------------------
    def _send(self, status, body, content_type, headers=(), cache="no-store"):
        self.send_response(status)
        for name, value in SECURITY_HEADERS:
            self.send_header(name, value)
        self.send_header("Cache-Control", cache)
        for name, value in headers:
            self.send_header(name, value)
        if body is not None:
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body is not None and self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status, value, headers=()):
        body = None if value is None else json.dumps(value, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8", headers)

    def _error(self, error):
        payload = {"code": error.code, "message": error.message}
        if error.fields:
            payload["fields"] = error.fields
        payload.update(error.extra)
        self._json(error.status, {"error": payload}, error.headers)

    # -- routing ---------------------------------------------------------------
    def _dispatch(self, method):
        try:
            if len(self.path) > MAX_URL:
                raise ApiError(414, "uri_too_long", "request URI too long")
            parts = urllib.parse.urlsplit(self.path)
            path = parts.path
            if path in ("/", "/index.html"):
                self._static(method, "index.html", cache="no-cache")
            elif path.startswith("/static/"):
                self._static(method, path[len("/static/"):])
            elif path == "/api" or path.startswith("/api/"):
                self._api(method, path, parts.query)
            else:
                raise ApiError(404, "not_found", "no such resource")
        except ApiError as error:
            if error.status == 413:
                self.close_connection = True
            self._error(error)
        except Exception:  # pragma: no cover - defensive: never leak internals
            traceback.print_exc(file=sys.stderr)
            self._error(ApiError(500, "internal_error", "internal server error"))

    def _static(self, method, name, cache="no-cache"):
        if method not in ("GET", "HEAD"):
            raise ApiError(405, "method_not_allowed", "method not allowed", headers=(("Allow", "GET, HEAD"),))
        entry = self.app.static.get(name)
        if entry is None:
            raise ApiError(404, "not_found", "no such file")
        self._send(200, entry[0], entry[1], cache=cache)

    def _api(self, method, path, query):
        segments = path.split("/")[2:]
        if segments == ["health"]:
            self._only(method, ("GET", "HEAD"))
            return self._json(200, {"ok": True})
        if segments == ["schema"]:
            self._only(method, ("GET", "HEAD"))
            return self._json(200, self.app.schema.public())
        entity = self.app.schema.by_collection.get(segments[0]) if segments else None
        if entity is None:
            raise ApiError(404, "unknown_collection", "no such collection")
        if len(segments) == 1:
            self._only(method, ("GET", "HEAD", "POST"))
            if method == "POST":
                return self._create(entity)
            return self._list(entity, query)
        if len(segments) == 2:
            if not RECORD_ID.fullmatch(segments[1]):
                raise ApiError(404, "not_found", "no such record")
            self._only(method, ("GET", "HEAD", "PUT", "DELETE"))
            record_id = int(segments[1])
            if method == "PUT":
                return self._update(entity, record_id)
            if method == "DELETE":
                return self._delete(entity, record_id)
            return self._get(entity, record_id)
        raise ApiError(404, "not_found", "no such resource")

    def _only(self, method, allowed):
        if method not in allowed:
            raise ApiError(405, "method_not_allowed", "method not allowed", headers=(("Allow", ", ".join(allowed)),))

    # -- request guards --------------------------------------------------------
    def _same_origin(self):
        site = self.headers.get("Sec-Fetch-Site")
        if site is not None and site not in ("same-origin", "none"):
            raise ApiError(403, "cross_origin", "cross-site writes are refused")
        origin = self.headers.get("Origin")
        if origin is not None:
            host = self.headers.get("Host", "")
            parsed = urllib.parse.urlsplit(origin)
            if origin == "null" or parsed.scheme not in ("http", "https") or parsed.netloc != host:
                raise ApiError(403, "cross_origin", "cross-origin writes are refused")

    def _body(self):
        self._same_origin()
        content_type = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if content_type != "application/json":
            raise ApiError(415, "unsupported_media_type", "Content-Type must be application/json")
        if self.headers.get("Transfer-Encoding"):
            raise ApiError(411, "length_required", "chunked bodies are not accepted")
        length = self.headers.get("Content-Length")
        if length is None:
            raise ApiError(411, "length_required", "Content-Length is required")
        if not length.isdigit():
            raise ApiError(400, "bad_request", "invalid Content-Length")
        size = int(length)
        if size > self.app.schema.limits["max_body_bytes"]:
            raise ApiError(413, "payload_too_large", "request body too large")
        raw = self.rfile.read(size)
        if len(raw) != size:
            raise ApiError(400, "bad_request", "incomplete body")
        try:
            value = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicates, parse_constant=_reject_constant)
        except (UnicodeDecodeError, ValueError):
            raise ApiError(400, "invalid_json", "body is not valid JSON") from None
        if not isinstance(value, dict):
            raise ApiError(400, "invalid_json", "body must be a JSON object")
        return value

    def _validated(self, entity, payload):
        try:
            return model.validate(entity, payload, self.app.schema.limits)
        except model.ValidationError as error:
            raise ApiError(400, "validation_failed", "validation failed", fields=error.fields) from None

    # -- operations ------------------------------------------------------------
    def _create(self, entity):
        values, links = self._validated(entity, self._body())
        try:
            with db.session(self.app.db_path) as connection:
                db.check_references(connection, self.app.schema, entity, values, links)
                record_id = db.insert(connection, entity, values, links, utc_now())
                record = db.get(connection, entity, record_id)
        except db.ReferenceMissing as error:
            raise ApiError(409, "reference_not_found", "a referenced record does not exist", fields=error.fields) from None
        except sqlite3.IntegrityError:
            raise ApiError(409, "constraint_failed", "the record violates a database constraint") from None
        self._json(201, record, (("Location", f"/api/{entity.collection}/{record_id}"),))

    def _list(self, entity, query):
        try:
            params = urllib.parse.parse_qs(query, keep_blank_values=True, strict_parsing=bool(query), max_num_fields=20)
        except ValueError:
            raise ApiError(400, "bad_query", "malformed query string") from None
        limits = self.app.schema.limits
        filters, limit, offset = {}, limits["page_size"], 0
        references = {ref["field"] for ref in entity.references}
        for key, values in params.items():
            if len(values) != 1 or not values[0].isdigit() or len(values[0]) > 16:
                raise ApiError(400, "bad_query", f"invalid value for {key[:40]}")
            number = int(values[0])
            if key == "limit" and 1 <= number <= limits["max_page_size"]:
                limit = number
            elif key == "offset":
                offset = number
            elif key in references and number >= 1:
                filters[key] = number
            else:
                raise ApiError(400, "bad_query", f"unknown or out-of-range parameter {key[:40]}")
        with db.session(self.app.db_path) as connection:
            items, total = db.list_records(connection, entity, filters, limit, offset)
        self._json(200, {"items": items, "total": total, "limit": limit, "offset": offset})

    def _get(self, entity, record_id):
        with db.session(self.app.db_path) as connection:
            record = db.get(connection, entity, record_id)
        if record is None:
            raise ApiError(404, "not_found", "no such record")
        self._json(200, record)

    def _update(self, entity, record_id):
        payload = self._body()
        with db.session(self.app.db_path) as connection:
            if not db.exists(connection, entity.table, record_id):
                raise ApiError(404, "not_found", "no such record")
        values, links = self._validated(entity, payload)
        try:
            with db.session(self.app.db_path) as connection:
                db.check_references(connection, self.app.schema, entity, values, links)
                if not db.update(connection, entity, record_id, values, links, utc_now()):
                    raise ApiError(404, "not_found", "no such record")
                record = db.get(connection, entity, record_id)
        except db.ReferenceMissing as error:
            raise ApiError(409, "reference_not_found", "a referenced record does not exist", fields=error.fields) from None
        except sqlite3.IntegrityError:
            raise ApiError(409, "constraint_failed", "the record violates a database constraint") from None
        self._json(200, record)

    def _delete(self, entity, record_id):
        self._same_origin()
        try:
            with db.session(self.app.db_path) as connection:
                if not db.delete(connection, self.app.schema, entity, record_id):
                    raise ApiError(404, "not_found", "no such record")
        except db.HasDependents as error:
            raise ApiError(409, "has_dependents", "other records still reference this record",
                           extra={"dependents": error.dependents}) from None
        except sqlite3.IntegrityError:
            raise ApiError(409, "constraint_failed", "the record is still referenced") from None
        self._json(204, None)


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, app):
        self.app = app
        super().__init__(address, Handler)


def make_server(host, port, app):
    return Server((host, port), app)


def serve(host="127.0.0.1", port=8000, db_path=None, allow_network=False):
    if host not in LOOPBACK and not allow_network:
        raise SystemExit("refusing to bind to a non-loopback address: this application has no user "
                         "authentication. Pass --allow-network only behind an authenticating proxy.")
    db_path = pathlib.Path(db_path) if db_path else ROOT / "data" / "app.sqlite3"
    db_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    server = make_server(host, port, App(db_path))
    print(f"listening on http://{host}:{server.server_address[1]}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
