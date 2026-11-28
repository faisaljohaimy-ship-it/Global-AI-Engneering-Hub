"""In-process route tests of the task management fixture (no network, in-memory database)."""

import unittest

import app
import store


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.conn = store.connect(":memory:")
        store.init(self.conn)

    def tearDown(self):
        self.conn.close()

    def call(self, method, target, body=None):
        return app.dispatch(method, target, self.conn, body)

    def test_health(self):
        self.assertEqual(self.call("GET", "/health"), (200, "application/json", {"status": "ok"}))

    def test_index_renders_the_task_form(self):
        status, content_type, body = self.call("GET", "/")
        self.assertEqual(status, 200)
        self.assertTrue(content_type.startswith("text/html"))
        self.assertIn('action="/api/tasks"', body)
        self.assertIn('name="title"', body)
        self.assertIn('href="/static/app.css"', body)

    def test_list_tasks(self):
        status, _, body = self.call("GET", "/api/tasks")
        self.assertEqual(status, 200)
        self.assertEqual([task["status"] for task in body["tasks"]], ["todo", "in_progress", "done"])

    def test_filter_by_status(self):
        status, _, body = self.call("GET", "/api/tasks?status=done")
        self.assertEqual(status, 200)
        self.assertEqual([task["title"] for task in body["tasks"]], ["Archive last year's invoices"])

    def test_create_task(self):
        status, _, task = self.call("POST", "/api/tasks", {"title": "Call the auditor", "priority": "high"})
        self.assertEqual(status, 201)
        self.assertEqual((task["title"], task["status"], task["priority"]), ("Call the auditor", "todo", "high"))
        self.assertEqual(self.call("GET", "/api/tasks/count")[2], {"count": 4})

    def test_static_stylesheet_is_served(self):
        status, content_type, data = self.call("GET", "/static/app.css")
        self.assertEqual(status, 200)
        self.assertTrue(content_type.startswith("text/css"))
        self.assertIn(b"font-family", data)

    def test_static_path_traversal_is_refused(self):
        self.assertEqual(self.call("GET", "/static/../app.py")[0], 404)

    def test_unknown_route_is_404(self):
        self.assertEqual(self.call("GET", "/missing")[0], 404)


if __name__ == "__main__":
    unittest.main()
