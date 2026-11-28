"""Unit tests for pricing.quote (fixture suite; run with -p 'case_*.py')."""

import unittest

from pricing import quote


class PricingTests(unittest.TestCase):
    def test_single_unit(self):
        self.assertEqual(quote(200, 1), 200)

    def test_no_discount_below_ten(self):
        self.assertEqual(quote(200, 9), 1800)

    def test_bulk_discount_starts_at_ten(self):
        self.assertEqual(quote(200, 10), 1700)

    def test_large_order_discount(self):
        self.assertEqual(quote(200, 20), 3400)

    def test_rejects_empty_or_negative_orders(self):
        for unit, quantity in ((200, 0), (-1, 3)):
            with self.subTest(unit=unit, quantity=quantity), self.assertRaises(ValueError):
                quote(unit, quantity)


if __name__ == "__main__":
    unittest.main()
