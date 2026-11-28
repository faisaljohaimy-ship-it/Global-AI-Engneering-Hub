"""In-process route tests for the fixture app (no network)."""

import unittest

import app
import store


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.conn = store.connect(":memory:")
        store.init(self.conn)

    def tearDown(self):
        self.conn.close()

    def call(self, target):
        return app.dispatch("GET", target, self.conn)

    def test_index_links_the_api(self):
        status, content_type, body = self.call("/")
        self.assertEqual(status, 200)
        self.assertTrue(content_type.startswith("text/html"))
        self.assertIn('href="/api/items"', body)

    def test_health(self):
        self.assertEqual(self.call("/health"), (200, "application/json", {"status": "ok"}))

    def test_list_items(self):
        status, _, body = self.call("/api/items")
        self.assertEqual(status, 200)
        self.assertEqual([item["name"] for item in body["items"]], ["widget", "gadget", "gizmo"])

    def test_count_items(self):
        self.assertEqual(self.call("/api/items/count"), (200, "application/json", {"count": 3}))

    def test_unknown_route_is_404(self):
        self.assertEqual(self.call("/missing")[0], 404)

    def test_price_route(self):
        self.assertEqual(self.call("/api/price?unit=200&qty=9"), (200, "application/json", {"total": 1800}))

    def test_price_route_rejects_bad_input(self):
        self.assertEqual(self.call("/api/price?unit=200&qty=many")[0], 400)


if __name__ == "__main__":
    unittest.main()
