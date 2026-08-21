"""Regression tests for the TODO 22 executable model test suite."""

import unittest

from test_model import MODEL_CASES, evaluate_response, run_model_tests


class FinalModelScriptTests(unittest.TestCase):
    def test_required_case_matrix_is_complete(self):
        required_groups = {
            "exact_known_question",
            "paraphrased_question",
            "agricultural_question",
            "unsupported_agricultural_question",
            "unrelated_question",
            "empty_input",
            "extremely_short_input",
            "very_long_input",
            "capitalization_and_punctuation",
            "mixed_language_input",
            "language_separation",
        }
        groups = {definition["group"] for definition in MODEL_CASES}
        self.assertTrue(required_groups <= groups)
        for group in required_groups - {"empty_input"}:
            languages = {
                definition["language"]
                for definition in MODEL_CASES
                if definition["group"] == group
            }
            self.assertEqual(languages, {"en", "tw"}, group)

    def test_evaluator_reports_contract_failures(self):
        definition = next(case for case in MODEL_CASES if case["case_id"] == "en_exact_known")
        result = evaluate_response(
            definition,
            200,
            {"type": "off_topic", "routing_state": "C", "source": "retrieval_v1"},
            1.0,
        )
        self.assertFalse(result["passed"])
        self.assertGreaterEqual(len(result["failures"]), 3)

    def test_live_final_model_matrix_passes(self):
        report = run_model_tests()
        self.assertGreaterEqual(report["summary"]["total"], 20)
        self.assertTrue(report["summary"]["all_passed"])


if __name__ == "__main__":
    unittest.main()
