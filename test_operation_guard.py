import unittest
from unittest.mock import patch

import app
from retrieval_assistance import attempt_retrieval_assistance
from operation_guard import (
    HARVEST_MATURITY,
    PLANTING_ESTABLISHMENT,
    SITE_LAND_SELECTION,
    OperationCompatibilityGuard,
)


class FakeGeminiService:
    available = True

    def __init__(self, interpreted_query):
        self.interpreted_query = interpreted_query
        self.calls = []

    def availability(self):
        return {"available": True, "reason": "configured"}

    def interpret_query(self, query, language):
        self.calls.append((query, language))
        return {"success": True, "interpreted_query": self.interpreted_query}


class UnavailableGeminiService:
    available = False

    def availability(self):
        return {"available": False, "reason": "missing_api_key"}


class FakeRuntime:
    def __init__(self, result):
        self.result = result

    def retrieve(self, query, language):
        return self.result


class OperationGuardTests(unittest.TestCase):
    def setUp(self):
        self.guard = OperationCompatibilityGuard()

    def test_noun_plant_is_not_classified_as_planting(self):
        operations = self.guard.detect(
            "How do I harvest pepper without damaging the plant?", "en"
        )
        self.assertEqual(operations, frozenset({HARVEST_MATURITY}))

    def test_planting_and_site_selection_frames_are_distinct(self):
        self.assertEqual(
            self.guard.detect("How do I plant watermelon?", "en"),
            frozenset({PLANTING_ESTABLISHMENT}),
        )
        for question in (
            "Where should I plant watermelon?",
            "How do I select land for watermelon?",
        ):
            with self.subTest(question=question):
                self.assertEqual(
                    self.guard.detect(question, "en"),
                    frozenset({SITE_LAND_SELECTION}),
                )

    def test_high_confidence_conflicts_and_positive_controls(self):
        cases = (
            ("How do I plant pepper?", "How do I harvest pepper without damaging the plant?", False),
            ("How do I plant watermelon?", "How do I select land for watermelon?", False),
            ("How do I harvest maize?", "How should I plant maize?", False),
            ("How should I grow pepper successfully?", "How should I grow pepper successfully?", True),
            ("How do I harvest pepper without damaging the plant?", "How do I harvest pepper without damaging the plant?", True),
            ("How do I plant pepper and when should I harvest it?", "How do I harvest pepper without damaging the plant?", True),
        )
        for query, candidate, compatible in cases:
            with self.subTest(query=query, candidate=candidate):
                self.assertEqual(
                    self.guard.evaluate(query, candidate, "en").compatible,
                    compatible,
                )

    def test_corpus_grounded_twi_frames_and_unknown_fail_open(self):
        self.assertEqual(
            self.guard.detect("Mɛyɛ dɛn dua aburo?", "tw"),
            frozenset({PLANTING_ESTABLISHMENT}),
        )
        self.assertTrue(self.guard.evaluate("Asɛmmisa bi", "Biribi foforo", "tw").compatible)

    def test_pepper_and_watermelon_are_safe_without_gemini(self):
        for question, forbidden_id in (
            ("How do I plant pepper?", "qa-0070"),
            ("How do I plant watermelon?", "qa-0414"),
        ):
            with self.subTest(question=question):
                with patch.object(app, "GEMINI_SERVICE", UnavailableGeminiService()):
                    result = app.get_answer(question, "en")
                self.assertEqual(result["routing_state"], "D")
                self.assertNotEqual(result.get("record_id"), forbidden_id)

    def test_mocked_gemini_can_rescue_pepper_only_to_canonical_planting_answer(self):
        service = FakeGeminiService("How should I grow pepper successfully?")
        with patch.object(app, "GEMINI_SERVICE", service):
            result = app.get_answer("How do I plant pepper?", "en")
        self.assertEqual(result["routing_state"], "A")
        self.assertEqual(result["record_id"], "qa-0129")
        self.assertEqual(result["text"], app.KNOWN_RECORDS["qa-0129"]["answer_en"])
        self.assertTrue(result["gemini_assisted"])

    def test_gemini_cannot_change_planting_into_harvesting(self):
        service = FakeGeminiService("How do I harvest pepper?")
        with patch.object(app, "GEMINI_SERVICE", service):
            result = app.get_answer("How do I plant pepper?", "en")
        self.assertEqual(result["routing_state"], "D")
        self.assertEqual(
            result["retrieval_assistance"]["reason"], "operation_not_preserved"
        )

    def test_second_pass_candidate_is_validated_against_original_operation(self):
        first = {"state": "B", "candidates": [{"raw_tfidf_similarity": 0.2}]}
        second = {
            "state": "A",
            "candidates": [{
                "raw_tfidf_similarity": 0.8,
                "question": "How do I harvest pepper without damaging the plant?",
                "category": "Pepper",
            }],
        }
        result = attempt_retrieval_assistance(
            "How do I plant pepper?", "en", first, FakeRuntime(second),
            FakeGeminiService("How should I plant pepper?"),
            operation_guard=self.guard,
        )
        self.assertFalse(result["accepted"])
        self.assertEqual(result["reason"], "operation_incompatible_second_pass")


if __name__ == "__main__":
    unittest.main()
