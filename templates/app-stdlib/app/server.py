"""JSON REST API and static frontend on http.server + sqlite3 (standard library only).

Security posture (see README "Security"): every response carries a restrictive
Content-Security-Policy with frame-ancestors 'none', nosniff and no-referrer;
every API route except health and login needs a session (HttpOnly, SameSite=Strict
cookie) and the role permission for its method; writes also need the session's CSRF
token, a JSON body and a same-origin request (no CORS headers are ever sent); bodies
are size-limited; SQL is parameterized; nothing is evaluated. The server binds to
loopback unless explicitly allowed.
"""
import datetime
import hmac
import http.cookies
import http.server
import json
import pathlib
import re
import sqlite3
import sys
import traceback
import urllib.parse

from . import auth, db, model

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
SAFE_METHODS = frozenset({"GET", "HEAD"})
NEED = {"GET": "read", "HEAD": "read", "POST": "write", "PUT": "write", "PATCH": "write", "DELETE": "delete"}
MAX_URL = 2048
COOKIE = "session"


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


def today():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


class App:
    """Application state shared by request handlers (read-only after start)."""

    def __init__(self, db_path, schema=None, static_dir=STATIC, quiet=False, secure_cookies=False):
        self.schema = schema or model.load_schema()
        self.db_path = str(db_path)
        self.quiet = quiet
        self.secure_cookies = secure_cookies
        self.sessions = auth.Sessions(self.schema)
        self.static, self.pages = {}, {}
        for path in sorted(pathlib.Path(static_dir).iterdir()):
            if path.is_file() and not path.is_symlink() and path.suffix in CONTENT_TYPES:
                self.static[path.name] = (path.read_bytes(), CONTENT_TYPES[path.suffix])
        for locale in self.schema.app["locales"]:
            self.pages[locale] = self.static[f"index.{locale}.html"][0]
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

    @property
    def schema(self):
        return self.server.app.schema

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

    def do_PATCH(self):
        self._dispatch("PATCH")

    def do_DELETE(self):
        self._dispatch("DELETE")

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
                self._page(method, parts.query)
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
        except auth.AuthError as error:
            self._error(ApiError(error.status, error.code, error.message))
        except Exception:  # pragma: no cover - defensive: never leak internals
            traceback.print_exc(file=sys.stderr)
            self._error(ApiError(500, "internal_error", "internal server error"))

    def _only(self, method, allowed):
        if method not in allowed:
            raise ApiError(405, "method_not_allowed", "method not allowed", headers=(("Allow", ", ".join(allowed)),))

    def _page(self, method, query):
        self._only(method, ("GET", "HEAD"))
        try:
            params = urllib.parse.parse_qs(query, max_num_fields=5)
        except ValueError:
            params = {}
        lang = (params.get("lang") or [""])[0]
        page = self.app.pages.get(lang) or self.app.pages[self.schema.app["default_locale"]]
        self._send(200, page, CONTENT_TYPES[".html"], cache="no-cache")

    def _static(self, method, name):
        self._only(method, ("GET", "HEAD"))
        entry = self.app.static.get(name)
        if entry is None:
            raise ApiError(404, "not_found", "no such file")
        self._send(200, entry[0], entry[1], cache="no-cache")

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
        if size > self.schema.limits["max_body_bytes"]:
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

    def _token(self):
        raw = self.headers.get("Cookie")
        if not raw:
            return None
        try:
            jar = http.cookies.SimpleCookie(raw)
        except http.cookies.CookieError:
            return None
        return jar[COOKIE].value if COOKIE in jar else None

    def _cookie(self, token, max_age):
        flags = f"{COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={max_age}"
        return ("Set-Cookie", flags + ("; Secure" if self.app.secure_cookies else ""))

    def _authenticate(self):
        token = self._token()
        with db.session(self.app.db_path) as connection:
            account = self.app.sessions.account(connection, token) if token else None
            if account is not None:
                account["principal_id"] = db.principal_id(connection, self.schema, account["email"])
        if account is None:
            raise ApiError(401, "unauthenticated", "sign in first")
        return token, account

    def _csrf(self, account):
        supplied = self.headers.get("X-CSRF-Token") or ""
        if not hmac.compare_digest(supplied.encode("utf-8"), account["csrf_token"].encode("utf-8")):
            raise ApiError(403, "csrf", "missing or invalid CSRF token")

    def _permit(self, account, method):
        mode = model.allowed(self.schema.permissions(account["role"]), NEED[method])
        if mode is None:
            raise ApiError(403, "forbidden", "your role does not allow this action")
        return mode

    def _validated(self, entity, payload, base=None):
        try:
            return model.validate(entity, payload, self.schema.limits, base=base)
        except model.ValidationError as error:
            raise ApiError(400, "validation_failed", "validation failed", fields=error.fields) from None

    # -- API -------------------------------------------------------------------
    def _api(self, method, path, query):
        segments = path.split("/")[2:]
        if segments == ["health"]:
            self._only(method, ("GET", "HEAD"))
            return self._json(200, {"ok": True})
        if segments == ["login"]:
            self._only(method, ("POST",))
            return self._login()
        token, account = self._authenticate()
        if method not in SAFE_METHODS:
            self._csrf(account)
        if segments == ["logout"]:
            self._only(method, ("POST",))
            self._same_origin()
            with db.session(self.app.db_path) as connection:
                self.app.sessions.logout(connection, token)
            return self._json(204, None, (self._cookie("", 0),))
        if segments == ["session"]:
            self._only(method, ("GET", "HEAD"))
            return self._json(200, {"account": {"email": account["email"], "role": account["role"]},
                                    "csrf_token": account["csrf_token"]})
        if segments == ["schema"]:
            self._only(method, ("GET", "HEAD"))
            self._permit(account, "GET")
            return self._json(200, self.schema.public())
        entity = self.schema.by_collection.get(segments[0]) if segments else None
        if entity is None:
            raise ApiError(404, "unknown_collection", "no such collection")
        if len(segments) == 1:
            self._only(method, ("GET", "HEAD", "POST"))
            mode = self._permit(account, method)
            scope = db.Scope(self.schema, account, account["principal_id"], own=(method in SAFE_METHODS and mode == "own"))
            if method == "POST":
                return self._create(entity, account, scope)
            return self._list(entity, query, scope)
        if not RECORD_ID.fullmatch(segments[1]):
            raise ApiError(404, "not_found", "no such record")
        record_id = int(segments[1])
        if len(segments) == 2:
            self._only(method, ("GET", "HEAD", "PUT", "PATCH", "DELETE"))
            mode = self._permit(account, method)
            scope = db.Scope(self.schema, account, account["principal_id"], own=(method in SAFE_METHODS and mode == "own"))
            if method in ("PUT", "PATCH"):
                return self._update(entity, record_id, account, scope, mode, partial=method == "PATCH")
            if method == "DELETE":
                return self._delete(entity, record_id, account, scope, mode)
            return self._get(entity, record_id, scope)
        return self._sub(method, entity, record_id, segments[2:], query, account)

    def _login(self):
        body = self._body()
        if set(body) - {"email", "password"}:
            raise ApiError(400, "validation_failed", "only email and password are accepted")
        with db.session(self.app.db_path) as connection:
            token, account = self.app.sessions.login(connection, body.get("email"), body.get("password"))
        max_age = int(self.app.sessions.hours * 3600)
        self._json(200, {"account": {"email": account["email"], "role": account["role"]},
                         "csrf_token": account["csrf_token"]}, (self._cookie(token, max_age),))

    def _create(self, entity, account, scope):
        values = self._validated(entity, self._body())
        try:
            with db.session(self.app.db_path) as connection:
                db.check_references(connection, self.schema, entity, values, scope)
                db.check_unique(connection, entity, values)
                record_id = db.insert(connection, entity, values, utc_now(), created_by=account["id"])
                config = self.schema.auth.get("scoping")
                if scope.limited and config and entity.name == config["entity"] and account["principal_id"]:
                    connection.execute("INSERT INTO " + db.ident(config["link_table"]) + " (" + db.ident("source_id")
                                       + ", " + db.ident("target_id") + ") VALUES (?, ?)",
                                       (record_id, account["principal_id"]))
                record = db.get(connection, entity, record_id)
        except db.ReferenceMissing as error:
            raise ApiError(400, "validation_failed", "a referenced record does not exist", fields=error.fields) from None
        except db.Duplicate as error:
            raise ApiError(409, "duplicate", "a record with this value already exists", fields=error.fields) from None
        except sqlite3.IntegrityError:
            raise ApiError(409, "constraint_failed", "the record violates a database constraint") from None
        self._json(201, record, (("Location", f"/api/{entity.collection}/{record_id}"),))

    def _query(self, entity, query):
        try:
            params = urllib.parse.parse_qs(query, keep_blank_values=True, strict_parsing=bool(query), max_num_fields=20)
        except ValueError:
            raise ApiError(400, "bad_query", "malformed query string") from None
        limits = self.schema.limits
        options = {"equals": {}, "before": {}, "not_equal": {}, "sort": None,
                   "limit": limits["page_size"], "offset": 0}
        references = {ref["field"] for ref in entity.references}
        fields = {field["name"]: field for field in entity.fields}
        overdue = [rule for rule in self.schema.rules.get("overdue", []) if rule["entity"] == entity.name]
        for key, values in params.items():
            value = values[0] if len(values) == 1 else None
            if value is None or len(value) > 64:
                raise ApiError(400, "bad_query", f"invalid value for {key[:40]}")
            if key in ("limit", "offset") or key in references:
                if not value.isdigit() or len(value) > 16:
                    raise ApiError(400, "bad_query", f"invalid value for {key[:40]}")
                number = int(value)
                if key == "limit" and 1 <= number <= limits["max_page_size"]:
                    options["limit"] = number
                elif key == "offset":
                    options["offset"] = number
                elif key in references and number >= 1:
                    options["equals"][key] = number
                else:
                    raise ApiError(400, "bad_query", f"out-of-range {key[:40]}")
            elif key in fields and fields[key]["type"] == "enum" and value in fields[key]["values"]:
                options["equals"][key] = value
            elif key in fields and fields[key]["type"] == "bool" and value in ("true", "false"):
                options["equals"][key] = 1 if value == "true" else 0
            elif key == "sort" and value.lstrip("-") in set(fields) | references | {"id"}:
                options["sort"] = value
            elif key == "overdue" and overdue and value == "true":
                rule = overdue[0]
                options["before"][rule["date"]] = today()
                options["not_equal"][rule["field"]] = rule["value"]
            else:
                raise ApiError(400, "bad_query", f"unknown or invalid parameter {key[:40]}")
        return options

    def _list(self, entity, query, scope, equals=None):
        options = self._query(entity, query)
        options["equals"].update(equals or {})
        with db.session(self.app.db_path) as connection:
            items, total = db.list_records(connection, entity, scope=scope, **options)
        self._json(200, {"items": items, "total": total, "limit": options["limit"], "offset": options["offset"]})

    def _get(self, entity, record_id, scope):
        with db.session(self.app.db_path) as connection:
            record = db.get(connection, entity, record_id, scope)
        if record is None:
            raise ApiError(404, "not_found", "no such record")
        self._json(200, record)

    def _owned(self, connection, entity, record_id, account, scope, mode):
        stored = db.stored(connection, entity, record_id)
        if stored is None or not db.visible(connection, entity, record_id, scope):
            raise ApiError(404, "not_found", "no such record")
        if mode == "own" and stored["created_by"] != account["id"]:
            raise ApiError(403, "forbidden", "you can only change your own records")
        return stored

    def _update(self, entity, record_id, account, scope, mode, partial):
        payload = self._body()
        with db.session(self.app.db_path) as connection:
            stored = self._owned(connection, entity, record_id, account, scope, mode)
        values = self._validated(entity, payload, base=stored if partial else None)
        try:
            with db.session(self.app.db_path) as connection:
                db.check_references(connection, self.schema, entity, values, scope)
                db.check_unique(connection, entity, values, record_id)
                db.check_rules(connection, self.schema, entity, values, record_id)
                if not db.update(connection, entity, record_id, values, utc_now()):
                    raise ApiError(404, "not_found", "no such record")
                record = db.get(connection, entity, record_id)
        except db.ReferenceMissing as error:
            raise ApiError(400, "validation_failed", "a referenced record does not exist", fields=error.fields) from None
        except db.Duplicate as error:
            raise ApiError(409, "duplicate", "a record with this value already exists", fields=error.fields) from None
        except db.StateConflict as error:
            raise ApiError(409, "state_conflict", "this change breaks a state rule", extra=error.detail) from None
        except sqlite3.IntegrityError:
            raise ApiError(409, "constraint_failed", "the record violates a database constraint") from None
        self._json(200, record)

    def _delete(self, entity, record_id, account, scope, mode):
        self._same_origin()
        try:
            with db.session(self.app.db_path) as connection:
                self._owned(connection, entity, record_id, account, scope, mode)
                if not db.delete(connection, self.schema, entity, record_id):
                    raise ApiError(404, "not_found", "no such record")
        except db.HasDependents as error:
            raise ApiError(409, "has_dependents", "other records still reference this record",
                           extra={"dependents": error.dependents}) from None
        except sqlite3.IntegrityError:
            raise ApiError(409, "constraint_failed", "the record is still referenced") from None
        self._json(204, None)

    def _sub(self, method, entity, record_id, rest, query, account):
        """/api/<collection>/{id}/<progress | link | child collection>[/{target id}]"""
        name = rest[0]
        link = next((item for item in entity.links if item["segment"] == name), None)
        child = next((item for item in entity.children if item["collection"] == name), None)
        rule = next((item for item in self.schema.rules.get("progress", []) if item["parent"] == entity.name), None)
        if len(rest) == 2 and link is not None and RECORD_ID.fullmatch(rest[1]):
            self._only(method, ("DELETE",))
            self._permit(account, "PUT")
        elif len(rest) == 1 and link is not None:
            self._only(method, ("GET", "HEAD", "POST"))
            self._permit(account, "PUT" if method == "POST" else "GET")
        elif len(rest) == 1 and (child is not None or (name == "progress" and rule is not None)):
            self._only(method, ("GET", "HEAD"))
            self._permit(account, "GET")
        else:
            raise ApiError(404, "not_found", "no such resource")
        scope = db.Scope(self.schema, account, account["principal_id"])
        with db.session(self.app.db_path) as connection:
            if not db.visible(connection, entity, record_id, scope):
                raise ApiError(404, "not_found", "no such record")
            if name == "progress" and link is None and child is None:
                return self._json(200, {"id": record_id, **db.progress(connection, self.schema, rule, record_id)})
        if child is not None and link is None:
            return self._list(child["entity"], query, scope, equals={child["field"]: record_id})
        if len(rest) == 2:
            with db.session(self.app.db_path) as connection:
                removed = db.remove_link(connection, link, record_id, int(rest[1]))
            if not removed:
                raise ApiError(404, "not_found", "no such link")
            return self._json(204, None)
        if method in SAFE_METHODS:
            with db.session(self.app.db_path) as connection:
                items = db.link_targets(connection, self.schema, link, record_id)
            return self._json(200, {"items": items, "total": len(items)})
        body = self._body()
        target = body.get(link["target_key"])
        if set(body) != {link["target_key"]} or not model._identifier(target):
            raise ApiError(400, "validation_failed", "validation failed", fields={link["target_key"]: "required"})
        try:
            with db.session(self.app.db_path) as connection:
                if not db.visible(connection, self.schema.by_name[link["entity"]], target, scope):
                    raise db.ReferenceMissing({link["target_key"]: "not_found"})
                db.add_link(connection, link, record_id, target)
        except db.ReferenceMissing as error:
            raise ApiError(400, "validation_failed", "a referenced record does not exist", fields=error.fields) from None
        except db.Duplicate as error:
            raise ApiError(409, "duplicate", "the link already exists", fields=error.fields) from None
        self._json(201, {link["source_key"]: record_id, link["target_key"]: target})


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, app):
        self.app = app
        super().__init__(address, Handler)


def make_server(host, port, app):
    return Server((host, port), app)


def serve(host="127.0.0.1", port=8000, db_path=None, allow_network=False, secure_cookies=False):
    if host not in LOOPBACK and not allow_network:
        raise SystemExit("refusing to bind to a non-loopback address: put the application behind TLS and an "
                         "authenticating reverse proxy first, then pass --allow-network (and --secure-cookies).")
    db_path = pathlib.Path(db_path) if db_path else ROOT / "data" / "app.sqlite3"
    db_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    server = make_server(host, port, App(db_path, secure_cookies=secure_cookies))
    print(f"listening on http://{host}:{server.server_address[1]}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
