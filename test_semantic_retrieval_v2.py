"""Regression tests for semantic fallback, entity safety, and intent routing."""

import unittest

from evaluate_retrieval_challenge_v2 import evaluate


class SemanticRetrievalV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = evaluate()

    def test_fresh_paraphrase_ranking_and_safe_answer_coverage(self):
        english = self.report["languages"]["English"]
        twi = self.report["languages"]["Twi"]
        self.assertGreaterEqual(english["top_1_correct"], 24)
        self.assertGreaterEqual(english["correct_answers"], 16)
        self.assertEqual(english["unsafe_answers"], 0)
        self.assertGreaterEqual(twi["top_1_correct"], 14)
        self.assertGreaterEqual(twi["correct_answers"], 10)
        self.assertEqual(twi["unsafe_answers"], 0)

    def test_ambiguous_farming_questions_are_all_safely_unanswered(self):
        metrics = self.report["ambiguous_agriculture"]
        self.assertEqual(metrics["cases"], 10)
        self.assertEqual(metrics["safe_uncertain"], 10)
        self.assertEqual(metrics["unsafe_answers"], 0)
        self.assertEqual(metrics["incorrect_off_topic"], 0)


if __name__ == "__main__":
    unittest.main()
