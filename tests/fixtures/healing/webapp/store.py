"""SQLite storage for the inventory fixture (synthetic seed data)."""

import sqlite3
from pathlib import Path

SCHEMA = Path(__file__).resolve().with_name("schema.sql")
SEED = [("widget", 250, 12), ("gadget", 1200, 3), ("gizmo", 75, 40)]


def connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init(conn):
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    if conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0:
        conn.executemany("INSERT INTO items (name, unit_price_cents, stock) VALUES (?, ?, ?)", SEED)
    conn.commit()


def list_items(conn):
    rows = conn.execute("SELECT id, name, unit_price_cents, stock FROM items ORDER BY id").fetchall()
    return [dict(row) for row in rows]
