"""Regression tests for TODO 36 report data."""

import unittest

from generate_final_project_report import generate_report


class FinalProjectReportTests(unittest.TestCase):
    def test_report_uses_complete_measured_sources(self):
        report = generate_report()
        self.assertEqual(report["dataset"]["records"], 563)
        self.assertEqual(report["split"], {"training": 394, "validation": 84, "testing": 85, "random_seed": 42})
        self.assertEqual(report["final_model"]["architecture"], "topic_aware_tfidf")
        self.assertEqual(report["final_model"]["answer_confidence_threshold"], 0.5)
        self.assertEqual(report["final_model"]["answer_confidence_minimum_margin"], 0.05)
        self.assertEqual(report["independent_behavior_evidence"]["presentation"]["total_passed"], 80)
        self.assertIsNone(report["usability"]["human_participant_results"])


if __name__ == "__main__":
    unittest.main()
