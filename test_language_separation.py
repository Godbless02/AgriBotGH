"""Regression tests for TODO 25 language separation."""

import unittest

from evaluate_language_separation import (
    category_representatives,
    evaluate_language_separation,
)


class LanguageSeparationTests(unittest.TestCase):
    def test_representatives_cover_every_canonical_category(self):
        records = category_representatives()
        self.assertEqual(len(records), 40)
        self.assertEqual(len({record["category"] for record in records}), 40)

    def test_api_and_retrieval_never_cross_languages(self):
        report = evaluate_language_separation()
        self.assertEqual(report["summary"]["total_language_cases"], 80)
        self.assertEqual(report["summary"]["english_cases"], 40)
        self.assertEqual(report["summary"]["twi_cases"], 40)
        self.assertEqual(report["summary"]["failed"], 0)
        self.assertEqual(report["summary"]["cross_language_errors"], 0)
        self.assertTrue(report["summary"]["invalid_language_rejected"])


if __name__ == "__main__":
    unittest.main()
