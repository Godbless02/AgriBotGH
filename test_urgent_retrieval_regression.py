"""End-to-end regressions for the urgent reordered-question retrieval bug."""

import unittest

import app as agribot


class UrgentRetrievalRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        agribot.app.config.update(TESTING=True)
        cls.client = agribot.app.test_client()

    def ask(self, question, language="en"):
        response = self.client.post(
            "/api/chat", json={"message": question, "language": language}
        )
        self.assertEqual(response.status_code, 200)
        return response.get_json()

    def test_exact_and_reordered_fertilizer_questions_return_same_answer(self):
        exact = self.ask("What fertilizer is best for maize?")
        reordered = self.ask("For maize what fertilizer is best")
        self.assertEqual(exact["routing_state"], "A")
        self.assertEqual(reordered["routing_state"], "A")
        self.assertEqual(exact["record_id"], "qa-0002")
        self.assertEqual(reordered["record_id"], "qa-0002")
        self.assertEqual(exact["text"], reordered["text"])

    def test_requested_acceptance_questions(self):
        expected = {
            "Which fertilizer should I use for maize?": "qa-0002",
            "What is the best fertilizer for maize?": "qa-0002",
            "Maize fertilizer which one is best?": "qa-0002",
            "How do I grow maize?": "qa-0282",
            "When is the best time to plant maize in Ghana?": "qa-0016",
            "How deep should I plant maize seeds?": "qa-0017",
        }
        for question, record_id in expected.items():
            with self.subTest(question=question):
                payload = self.ask(question)
                self.assertEqual(payload["routing_state"], "A")
                self.assertEqual(payload["record_id"], record_id)

    def test_requested_off_topic_questions(self):
        for question in ("What is the capital of France?", "Tell me a joke."):
            with self.subTest(question=question):
                payload = self.ask(question)
                self.assertEqual(payload["routing_state"], "C")
                self.assertEqual(payload["type"], "off_topic")

    def test_normalized_exact_identity_ignores_formatting_only(self):
        result = agribot.RETRIEVAL_RUNTIME.retrieve(
            "  WHAT fertilizer is best for maize!!!  ", "en"
        )
        self.assertEqual(result["state"], "A")
        self.assertTrue(result["normalized_exact_match"])
        self.assertEqual(result["match_level"], "normalized_exact")
        self.assertEqual(result["candidates"][0]["id"], 2)

    def test_artifact_records_and_answers_align_with_canonical_dataset(self):
        for language, suffix in (("English", "en"), ("Twi", "tw")):
            artifact = agribot.RETRIEVAL_RUNTIME.models[language]
            self.assertEqual(len(artifact["records"]), 563)
            for record in artifact["records"]:
                canonical = agribot.KNOWN_RECORDS[f"qa-{record['id']:04d}"]
                self.assertEqual(record["question"], canonical[f"question_{suffix}"])
                self.assertEqual(record["answer"], canonical[f"answer_{suffix}"])


if __name__ == "__main__":
    unittest.main()
