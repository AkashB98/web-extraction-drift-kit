import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extract import (extract_html, parse_date, parse_int, parse_price)
from helpers import fixture


class TestTypedParsing(unittest.TestCase):
    def test_usd_price_with_thousands(self):
        r = parse_price("$1,299.00")
        self.assertEqual(r["value"], 129900)
        self.assertIsNone(r["error"])
        self.assertIn("USD", r["format"])

    def test_eu_price_is_recognised_not_misparsed(self):
        # "1.299 €": a naive strip-non-digits parser could read this
        # several wrong ways; here it must parse as 1299 euros AND
        # carry a different format signature from USD.
        r = parse_price("1.299 €")
        self.assertEqual(r["value"], 129900)
        self.assertIsNone(r["error"])
        self.assertNotEqual(r["format"], parse_price("$1,299.00")["format"])

    def test_eu_comma_price(self):
        r = parse_price("290,00 €")
        self.assertEqual(r["value"], 29000)
        self.assertIn("EUR", r["format"])

    def test_unparseable_price_errors(self):
        for raw in ("1299 dollars", "$1,299", "free", ""):
            self.assertIsNotNone(parse_price(raw)["error"], raw)

    def test_dates(self):
        self.assertEqual(parse_date("2026-01-15")["value"], "2026-01-15")
        eu = parse_date("15/01/2026")
        self.assertEqual(eu["value"], "2026-01-15")
        self.assertNotEqual(eu["format"], parse_date("2026-01-15")["format"])
        us = parse_date("Feb 1, 2026")
        self.assertEqual(us["value"], "2026-02-01")
        self.assertIsNotNone(parse_date("2026-13-40")["error"])
        self.assertIsNotNone(parse_date("next Tuesday")["error"])

    def test_ints(self):
        self.assertEqual(parse_int("42")["value"], 42)
        self.assertEqual(parse_int("1,200")["value"], 1200)
        self.assertIsNotNone(parse_int("unlimited")["error"])
        self.assertIsNotNone(parse_int("4.5")["error"])


class TestExtraction(unittest.TestCase):
    def test_product_baseline_all_fields(self):
        result = extract_html(fixture("product_baseline.html"), "product")
        f = result["fields"]
        self.assertEqual(f["name"]["value"], "Aurora Home Hub Pro")
        self.assertEqual(f["sku"]["value"], "HH-AURORA-100")
        self.assertEqual(f["price"]["value"], 129900)
        self.assertEqual(f["stock"]["value"], 42)
        self.assertEqual(f["release_date"]["value"], "2026-01-15")
        self.assertTrue(all(e["found"] and e["error"] is None
                            for e in f.values()))

    def test_pricing_baseline_all_fields(self):
        result = extract_html(fixture("pricing_baseline.html"), "pricing")
        f = result["fields"]
        self.assertEqual(f["plan_name"]["value"], "Helios Plus")
        self.assertEqual(f["monthly_price"]["value"], 2900)
        self.assertEqual(f["annual_price"]["value"], 29000)
        self.assertEqual(f["seats"]["value"], 10)
        self.assertEqual(f["renewal_date"]["value"], "2026-02-01")

    def test_missing_node_is_found_false_not_error(self):
        result = extract_html(fixture("product_b3_removed_field.html"),
                              "product")
        entry = result["fields"]["release_date"]
        self.assertFalse(entry["found"])
        self.assertIsNone(entry["error"])

    def test_unparseable_node_is_found_with_error(self):
        result = extract_html(fixture("pricing_b3_type_changed.html"),
                              "pricing")
        entry = result["fields"]["seats"]
        self.assertTrue(entry["found"])
        self.assertIsNotNone(entry["error"])
        self.assertIsNone(entry["value"])

    def test_scoped_hook_misses_node_moved_out_of_scope(self):
        result = extract_html(fixture("product_b2_moved_node.html"),
                              "product")
        self.assertFalse(result["fields"]["stock"]["found"])

    def test_unknown_page_type_raises(self):
        with self.assertRaises(ValueError):
            extract_html("<p>x</p>", "checkout")


if __name__ == "__main__":
    unittest.main()
