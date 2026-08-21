"""TODO 17 evaluation-parity and Flask integration regression tests."""

import json
import unittest
from pathlib import Path

import app as agribot


BASE_DIR = Path(__file__).resolve().parent


class RetrievalIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        agribot.app.config.update(TESTING=True)
        cls.client = agribot.app.test_client()
        with (BASE_DIR / "models/off_topic_experiments.json").open(
            "r", encoding="utf-8"
        ) as handle:
            cls.router_report = json.load(handle)

    def test_saved_runtime_matches_all_evaluated_router_decisions(self):
        tested = 0
        for language, payload in self.router_report["languages"].items():
            language_code = "tw" if language == "Twi" else "en"
            for expected in payload["details"]:
                actual = agribot.RETRIEVAL_RUNTIME.retrieve(
                    expected["question"], language_code
                )
                self.assertEqual(actual["state"], expected["predicted_state"])
                self.assertEqual(
                    actual["candidates"][0]["id"], expected["top_train_id"]
                )
                tested += 1
        self.assertEqual(tested, 232)

    def test_all_canonical_questions_remain_exactly_answerable(self):
        tested = 0
        for record in agribot.KNOWN_RECORDS.values():
            for language in ("en", "tw"):
                response = agribot.get_exact_canonical_answer(
                    record[f"question_{language}"], language
                )
                self.assertIsNotNone(response)
                self.assertEqual(response["routing_state"], "A")
                self.assertEqual(response["record_id"], record["id"])
                self.assertEqual(response["text"], record[f"answer_{language}"])
                tested += 1
        self.assertEqual(tested, 1126)

    def test_uncertain_agriculture_returns_state_b_and_safe_suggestions(self):
        response = self.client.post(
            "/api/chat",
            json={
                "message": "My maize leaves are changing colour and I am not sure why",
                "language": "en",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["type"], "low_confidence")
        self.assertEqual(payload["routing_state"], "B")
        self.assertTrue(payload["suggestions"])

        suggestion = payload["suggestions"][0]
        clicked = self.client.post(
            "/api/chat",
            json={
                "message": suggestion["text"],
                "language": "en",
                "suggestion_id": suggestion["id"],
            },
        )
        self.assertEqual(clicked.status_code, 200)
        self.assertEqual(clicked.get_json()["source"], "known_suggestion")

    def test_clearly_unrelated_questions_return_state_c(self):
        cases = (
            ("en", "Who won the football match last night?"),
            ("tw", "Hena na odii bɔɔlbɔ no mu nkonim anadwo no?"),
        )
        for language, question in cases:
            with self.subTest(language=language):
                response = self.client.post(
                    "/api/chat", json={"message": question, "language": language}
                )
                self.assertEqual(response.status_code, 200)
                payload = response.get_json()
                self.assertEqual(payload["type"], "off_topic")
                self.assertEqual(payload["routing_state"], "C")

    def test_health_reports_loaded_v1_artifacts(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["model_version"], "AgriBotGH Retrieval Model v1.0.1")
        self.assertEqual(payload["retrieval_architecture"], "topic_aware_tfidf")
        self.assertEqual(payload["training_records"], 394)
        self.assertEqual(payload["en_pairs"], 563)
        self.assertEqual(payload["tw_pairs"], 563)

    def test_flask_does_not_fit_a_model_during_startup(self):
        source = (BASE_DIR / "app.py").read_text(encoding="utf-8")
        self.assertNotIn("fit_transform(", source)
        self.assertNotIn("TfidfVectorizer(", source)


if __name__ == "__main__":
    unittest.main()
