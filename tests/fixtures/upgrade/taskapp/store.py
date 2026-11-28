"""SQLite storage of the task management fixture (synthetic seed data, stdlib only)."""

import sqlite3
from pathlib import Path

SCHEMA = Path(__file__).resolve().with_name("schema.sql")
SEED = [("Prepare the weekly report", "todo", "high"), ("Review the supplier contract", "in_progress", "medium"),
        ("Archive last year's invoices", "done", "low")]


def connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init(conn):
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    if conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0:
        for number, (title, status, priority) in enumerate(SEED, 1):
            conn.execute("INSERT INTO tasks (title, status, priority, created_at) VALUES (?, ?, ?, ?)",
                         (title, status, priority, f"2026-01-0{number}T09:00:00Z"))
    conn.commit()


def list_tasks(conn, status=None):
    if status is None:
        rows = conn.execute("SELECT id, title, status, priority, created_at FROM tasks ORDER BY id").fetchall()
    else:
        rows = conn.execute("SELECT id, title, status, priority, created_at FROM tasks WHERE status = ? ORDER BY created_at, id",
                            (status,)).fetchall()
    return [dict(row) for row in rows]


def count_tasks(conn):
    return conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]


def create_task(conn, title, status, priority, created_at):
    cursor = conn.execute("INSERT INTO tasks (title, status, priority, created_at) VALUES (?, ?, ?, ?)",
                          (title, status, priority, created_at))
    conn.commit()
    row = conn.execute("SELECT id, title, status, priority, created_at FROM tasks WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return dict(row)
