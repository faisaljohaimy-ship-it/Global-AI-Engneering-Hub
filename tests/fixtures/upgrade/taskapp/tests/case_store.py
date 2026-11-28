"""Storage tests of the task management fixture, including the shipped data file (read-only)."""

import sqlite3
import unittest

import store


class StoreTests(unittest.TestCase):
    def test_init_is_idempotent(self):
        conn = store.connect(":memory:")
        store.init(conn)
        store.init(conn)
        self.assertEqual(store.count_tasks(conn), 3)
        conn.close()

    def test_status_filter_is_ordered_by_creation(self):
        conn = store.connect(":memory:")
        store.init(conn)
        store.create_task(conn, "Later", "todo", "low", "2026-03-01T00:00:00Z")
        store.create_task(conn, "Earlier", "todo", "low", "2026-02-01T00:00:00Z")
        titles = [task["title"] for task in store.list_tasks(conn, "todo")]
        self.assertEqual(titles, ["Prepare the weekly report", "Earlier", "Later"])
        conn.close()

    def test_shipped_data_is_readable(self):
        conn = sqlite3.connect("file:data/tasks.db?mode=ro&immutable=1", uri=True)
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], 300)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM tasks WHERE status = 'done'").fetchone()[0], 100)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
