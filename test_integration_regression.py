"""Regression test for TODO 33's integrated behavior matrix."""

import unittest

from evaluate_integration_regression import evaluate_integration


class IntegrationRegressionTests(unittest.TestCase):
    def test_live_integration_matrix_passes(self):
        report = evaluate_integration()
        self.assertEqual(report["summary"]["failed"], 0)
        self.assertEqual(report["summary"]["passed"], report["summary"]["total_checks"])
        self.assertEqual(report["active_model"], "AgriBotGH Retrieval Model v1.0.1")
        self.assertEqual(len(report["freeze_id"]), 64)


if __name__ == "__main__":
    unittest.main()
