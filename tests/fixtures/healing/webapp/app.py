"""Tiny inventory web app: the self-healing fixture (synthetic data, stdlib only).

Run it with ``python3 app.py --port 8123 --db /tmp/inventory.db``. Handlers take
``(conn, query)`` and return ``(status, content_type, body)``; ``ROUTES`` maps a
``(method, path)`` pair to a handler name, as declared in ``routes.json``.
"""

import argparse
import json
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pricing
import store

HERE = Path(__file__).resolve().parent

ROUTES = {
    ("GET", "/"): "index",
    ("GET", "/health"): "health",
    ("GET", "/api/items"): "list_items",
    ("GET", "/api/items/count"): "count_items",
    ("GET", "/api/price"): "price",
}


def index(conn, query):
    return 200, "text/html; charset=utf-8", (HERE / "templates" / "index.html").read_text(encoding="utf-8")


def health(conn, query):
    return 200, "application/json", {"status": "ok"}


def list_items(conn, query):
    return 200, "application/json", {"items": store.list_items(conn)}


def price(conn, query):
    try:
        unit = int(query.get("unit", [""])[0])
        quantity = int(query.get("qty", [""])[0])
        return 200, "application/json", {"total": pricing.quote(unit, quantity)}
    except ValueError:
        return 400, "application/json", {"error": "unit and qty must be positive integers"}


def dispatch(method, target, conn):
    parsed = urllib.parse.urlsplit(target)
    name = ROUTES.get((method, parsed.path))
    if name is None:
        return 404, "application/json", {"error": "not found"}
    handler = globals().get(name)
    if handler is None:
        return 500, "application/json", {"error": "route handler missing"}
    try:
        return handler(conn, urllib.parse.parse_qs(parsed.query))
    except Exception:
        return 500, "application/json", {"error": "handler failed"}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        conn = store.connect(self.server.db_path)
        try:
            status, content_type, body = dispatch("GET", self.path, conn)
        finally:
            conn.close()
        data = body.encode("utf-8") if isinstance(body, str) else json.dumps(body, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):
        return


def main(argv=None):
    parser = argparse.ArgumentParser(description="Inventory fixture server (loopback only).")
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
