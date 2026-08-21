"""Regression tests for TODO 35's backend presentation matrix."""

import unittest

from evaluate_presentation import EXPECTED_COUNTS, evaluate_backend, load_set


class PresentationTests(unittest.TestCase):
    def test_set_has_exact_required_80_case_distribution(self):
        data = load_set()
        self.assertEqual(data["case_count"], 80)
        self.assertEqual(data["group_counts"], EXPECTED_COUNTS)

    def test_all_70_backend_presentation_cases_pass(self):
        report = evaluate_backend()
        self.assertEqual(report["summary"]["backend_cases"], 70)
        self.assertEqual(report["summary"]["backend_failed"], 0)
        self.assertEqual(report["summary"]["backend_passed"], 70)
        self.assertEqual(report["summary"]["tts_pending_browser"], 10)


if __name__ == "__main__":
    unittest.main()
