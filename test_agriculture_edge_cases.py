"""Regression tests for TODO 24's agricultural edge-case challenge."""

import unittest

import app as agribot

from evaluate_agriculture_edge_cases import (
    CANONICAL_PATH,
    EDGE_PATH,
    evaluate_edge_cases,
    load_json,
    validate_edge_dataset,
)


class AgricultureEdgeCaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.edge_data = load_json(EDGE_PATH)
        cls.canonical = load_json(CANONICAL_PATH)

    def test_schema_pairing_language_balance_and_required_types(self):
        validate_edge_dataset(self.edge_data, self.canonical)
        self.assertEqual(self.edge_data["pair_count"], 16)
        self.assertEqual(self.edge_data["case_count"], 32)
        self.assertEqual(len(self.edge_data["edge_types"]), 8)

    def test_live_router_handles_every_agricultural_edge_case_safely(self):
        report = evaluate_edge_cases()
        self.assertEqual(report["summary"]["total"], 32)
        self.assertEqual(report["summary"]["failed"], 0)
        self.assertEqual(report["summary"]["stable_response_rate"], 1.0)
        self.assertEqual(report["summary"]["off_topic_errors"], 0)
        self.assertEqual(report["summary"]["unapproved_answers"], 0)

    def test_twi_poultry_spelling_is_recognized(self):
        self.assertEqual(
            agribot.detect_topic("Akokɔ mma ayare", "tw"), "Poultry Farming"
        )
        self.assertTrue(
            agribot.has_agricultural_entity_signal("Akokɔ mma ayare", "tw")
        )

    def test_topic_fallback_is_safe_and_explicit_off_topic_keeps_priority(self):
        client = agribot.app.test_client()
        agricultural = client.post(
            "/api/chat",
            json={"message": "Akokɔ mma ayare", "language": "tw"},
        ).get_json()
        self.assertEqual(agricultural["routing_state"], "B")
        self.assertEqual(
            agricultural["domain_signal"], "recognized_agricultural_topic"
        )

        unrelated = client.post(
            "/api/chat",
            json={
                "message": "How do I set a random seed for a simulation?",
                "language": "en",
            },
        ).get_json()
        self.assertEqual(unrelated["routing_state"], "C")
        self.assertEqual(
            unrelated["off_topic_signal"], "explicit_non_agricultural_intent"
        )


if __name__ == "__main__":
    unittest.main()
