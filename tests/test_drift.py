import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from drift import diff_html, run_mutation
from helpers import by_id, fixture, manifest


class TestMutationSuite(unittest.TestCase):
    def test_every_breaking_mutation_is_caught_as_labelled(self):
        for m in manifest():
            if m["category"] != "breaking":
                continue
            with self.subTest(mutation=m["id"]):
                result = run_mutation(m)
                self.assertTrue(result["has_breaking"])
                self.assertEqual(
                    sorted(d["field"] for d in result["diffs"]),
                    sorted(m["expected_fields"]))
                self.assertEqual(
                    sorted(d["kind"] for d in result["diffs"]),
                    sorted(m["expected_kinds"]))
                self.assertTrue(all(d["severity"] == "breaking"
                                    for d in result["diffs"]))
                if m["silent"]:
                    self.assertTrue(all(d["silent"]
                                        for d in result["diffs"]))
                    self.assertEqual(result["silent_count"],
                                     len(result["diffs"]))
                else:
                    self.assertEqual(result["silent_count"], 0)

    def test_no_cosmetic_mutation_alarms(self):
        for m in manifest():
            if m["category"] != "cosmetic":
                continue
            with self.subTest(mutation=m["id"]):
                result = run_mutation(m)
                self.assertFalse(result["has_breaking"])
                self.assertEqual(result["diffs"], [])

    def test_suite_counts(self):
        ms = manifest()
        self.assertEqual(sum(1 for m in ms if m["category"] == "breaking"), 12)
        self.assertEqual(sum(1 for m in ms if m["category"] == "cosmetic"), 6)
        self.assertEqual(sum(1 for m in ms if m["silent"]), 3)


class TestDriftKinds(unittest.TestCase):
    def test_baseline_vs_itself_is_clean(self):
        html = fixture("product_baseline.html")
        result = diff_html(html, html, "product")
        self.assertEqual(result["diffs"], [])
        self.assertFalse(result["has_breaking"])

    def test_price_format_change_same_value_still_breaking(self):
        result = run_mutation(by_id("PB4"))
        d = result["diffs"][0]
        self.assertEqual(d["kind"], "format-changed")
        # Numerically identical (129900 cents both sides) — the drift
        # is the format, and it must still alarm.
        self.assertEqual(d["baseline_value"], d["current_value"])

    def test_silent_price_move_returns_wrong_value(self):
        result = run_mutation(by_id("PB6"))
        d = result["diffs"][0]
        self.assertEqual(d["kind"], "value-changed")
        self.assertTrue(d["silent"])
        self.assertEqual(d["baseline_value"], 129900)
        self.assertEqual(d["current_value"], 49900)

    def test_renamed_class_falls_through_silently(self):
        # First draft expected "missing" here; the suite caught that
        # the document-wide price hook instead falls through to the
        # related item's $499.00 — a silent wrong value, not a miss.
        result = run_mutation(by_id("PB1"))
        d = result["diffs"][0]
        self.assertEqual(d["kind"], "value-changed")
        self.assertTrue(d["silent"])
        self.assertEqual(d["current_value"], 49900)

    def test_page_type_mismatch_raises(self):
        with self.assertRaises(ValueError):
            from drift import diff_extractions
            from extract import extract_html
            diff_extractions(
                extract_html(fixture("product_baseline.html"), "product"),
                extract_html(fixture("pricing_baseline.html"), "pricing"))


if __name__ == "__main__":
    unittest.main()
