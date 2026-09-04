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
        with (BASE_DIR / "data/evaluation/retrieval_paraphrase_cases.json").open(
            "r", encoding="utf-8"
        ) as handle:
            cls.paraphrases = json.load(handle)

    def test_required_maize_paraphrases_are_statistically_retrieved(self):
        variants = [
            case for case in self.paraphrases["cases"]
            if case.get("expected_record_id") == 2
        ]
        self.assertGreaterEqual(len(variants), 6)
        for case in variants:
            with self.subTest(question=case["question"]):
                language = "tw" if case["language"] == "Twi" else "en"
                actual = agribot.RETRIEVAL_RUNTIME.retrieve(case["question"], language)
                self.assertEqual(actual["state"], "A")
                self.assertEqual(actual["candidates"][0]["id"], 2)
                self.assertGreaterEqual(actual["candidates"][0]["raw_tfidf_similarity"], 0.5)
                self.assertGreaterEqual(actual["raw_similarity_margin"], 0.05)

    def test_all_canonical_questions_remain_exactly_answerable(self):
        tested = 0
        for record in agribot.KNOWN_RECORDS.values():
            for language in ("en", "tw"):
                response = agribot.RETRIEVAL_RUNTIME.retrieve(
                    record[f"question_{language}"], language
                )
                candidate = response["candidates"][0]
                self.assertEqual(response["state"], "A")
                self.assertEqual(f"qa-{candidate['id']:04d}", record["id"])
                self.assertEqual(candidate["answer"], record[f"answer_{language}"])
                tested += 1
        self.assertEqual(tested, 1126)

    def test_uncertain_agriculture_returns_state_d_and_dataset_topics(self):
        response = self.client.post(
            "/api/chat",
            json={
                "message": "My maize leaves are changing colour and I am not sure why",
                "language": "en",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["type"], "knowledge_gap")
        self.assertEqual(payload["routing_state"], "D")
        self.assertEqual(payload["available_topics"], list(agribot.AVAILABLE_CATEGORIES))

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
        self.assertEqual(payload["model_version"], "AgriBotGH Retrieval Model v1.3.1")
        self.assertEqual(payload["retrieval_architecture"], "topic_aware_tfidf")
        self.assertEqual(payload["training_records"], 563)
        self.assertEqual(payload["en_pairs"], 563)
        self.assertEqual(payload["tw_pairs"], 563)

    def test_chat_rejects_malformed_types_and_oversized_payloads(self):
        for payload in (
            {"message": 123, "language": "en"},
            {"message": ["maize"], "language": "en"},
            {"message": "maize", "language": ["en"]},
            {"message": "maize", "language": "en", "username": {}},
        ):
            with self.subTest(payload=payload):
                response = self.client.post("/api/chat", json=payload)
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.get_json())

        response = self.client.post(
            "/api/chat", json={"message": "m" * 2001, "language": "en"}
        )
        self.assertEqual(response.status_code, 400)
        response = self.client.post(
            "/api/chat", json={"message": "m" * 40000, "language": "en"}
        )
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.get_json()["error"], "Request payload is too large")

    def test_flask_does_not_fit_a_model_during_startup(self):
        source = (BASE_DIR / "app.py").read_text(encoding="utf-8")
        self.assertNotIn("fit_transform(", source)
        self.assertNotIn("TfidfVectorizer(", source)


if __name__ == "__main__":
    unittest.main()
