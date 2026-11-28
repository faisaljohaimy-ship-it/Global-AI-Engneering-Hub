"""Task management web app: the Master Upgrade Engine fixture (synthetic data, stdlib only).

Run it with ``python3 app.py --port 8124 --db data/tasks.db``. Handlers take
``(conn, query, body)`` and return ``(status, content_type, body)``; ``ROUTES`` maps a
``(method, path)`` pair to a handler name; ``dispatch`` is the in-process entry the
test suite uses. Files under ``static/`` are served by name.
"""

import argparse
import datetime
import json
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import store

HERE = Path(__file__).resolve().parent
STATIC_TYPES = {".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png"}

ROUTES = {
    ("GET", "/"): "index",
    ("GET", "/health"): "health",
    ("GET", "/api/tasks"): "list_tasks",
    ("POST", "/api/tasks"): "create_task",
    ("GET", "/api/tasks/count"): "count_tasks",
}


def index(conn, query, body):
    return 200, "text/html; charset=utf-8", (HERE / "templates" / "index.html").read_text(encoding="utf-8")


def health(conn, query, body):
    return 200, "application/json", {"status": "ok"}


def list_tasks(conn, query, body):
    status = query.get("status", [None])[0]
    return 200, "application/json", {"tasks": store.list_tasks(conn, status)}


def count_tasks(conn, query, body):
    return 200, "application/json", {"count": store.count_tasks(conn)}


def create_task(conn, query, body):
    created = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    task = store.create_task(conn, body.get("title"), body.get("status", "todo"), body.get("priority", "medium"), created)
    return 201, "application/json", task


def static_file(path):
    name = path[len("/static/"):]
    target = HERE / "static" / name
    if "/" in name or name.startswith(".") or not target.is_file():
        return 404, "application/json", {"error": "not found"}
    return 200, STATIC_TYPES.get(target.suffix, "application/octet-stream"), target.read_bytes()


def dispatch(method, target, conn, body=None):
    parsed = urllib.parse.urlsplit(target)
    name = ROUTES.get((method, parsed.path))
    if name is None:
        if method == "GET" and parsed.path.startswith("/static/"):
            return static_file(parsed.path)
        return 404, "application/json", {"error": "not found"}
    try:
        return globals()[name](conn, urllib.parse.parse_qs(parsed.query), body)
    except Exception:
        return 500, "application/json", {"error": "handler failed"}


class Handler(BaseHTTPRequestHandler):
    def respond(self, method):
        body = None
        if method == "POST":
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"null")
            except ValueError:
                body = None
        conn = store.connect(self.server.db_path)
        try:
            status, content_type, payload = dispatch(method, self.path, conn, body)
        finally:
            conn.close()
        data = payload if isinstance(payload, bytes) else payload.encode("utf-8") if isinstance(payload, str) \
            else json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.respond("GET")

    def do_POST(self):
        self.respond("POST")

    def log_message(self, format, *args):
        return


def main(argv=None):
    parser = argparse.ArgumentParser(description="Task management fixture server (loopback only).")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--db", required=True)
    args = parser.parse_args(argv)
    conn = store.connect(args.db)
    store.init(conn)
    conn.close()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.db_path = args.db
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
