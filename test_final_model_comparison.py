"""Regression tests for TODOs 31 and 32."""

import unittest

from create_final_model_comparison import create_comparison
from freeze_model import create_freeze_manifest


class FinalModelComparisonTests(unittest.TestCase):
    def test_comparison_contains_all_required_architectures(self):
        report = create_comparison()
        self.assertEqual(len(report["architectures"]), 5)
        self.assertEqual(
            {item["id"] for item in report["architectures"]},
            {
                "baseline_tfidf",
                "improved_tfidf",
                "topic_aware_tfidf",
                "embedding_retrieval",
                "hybrid_retrieval",
            },
        )
        self.assertEqual(report["selection"]["architecture_id"], "topic_aware_tfidf")
        self.assertEqual(report["selection"]["answer_confidence_threshold"], 0.5)
        self.assertEqual(report["selection"]["answer_confidence_minimum_margin"], 0.05)

    def test_freeze_matches_selected_active_model(self):
        manifest = create_freeze_manifest()
        self.assertEqual(manifest["status"], "frozen")
        self.assertEqual(manifest["semantic_version"], "1.3.1")
        self.assertEqual(manifest["architecture"], "topic_aware_tfidf")
        self.assertEqual(manifest["selected_architecture"], "topic_aware_tfidf")
        self.assertEqual(manifest["answer_confidence_threshold"], 0.5)
        self.assertEqual(len(manifest["freeze_id"]), 64)
        self.assertEqual(set(manifest["artifacts"]), {"English", "Twi"})


if __name__ == "__main__":
    unittest.main()
