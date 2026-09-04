"""Regression tests for TODO 15 direct suggestion routing."""

import json
import unittest

import app as agribot


class SuggestionRoutingTests(unittest.TestCase):
    RIGHT_PANEL_ENGLISH = (
        ("How should I prepare the soil before planting maize?", "qa-0208"),
        ("When is the best time to plant maize in Ghana?", "qa-0016"),
        ("What fertilizer programme should I use for tomatoes?", "qa-0344"),
        ("How can I prevent pests from attacking my crops?", "qa-0038"),
        ("What is composting and how do I do it?", "qa-0114"),
        ("How do I start a fish farm in Ghana?", "qa-0251"),
        ("What is the best way to plant cassava stems?", "qa-0220"),
        ("How can I prevent tomato late blight?", "qa-0238"),
    )

    @classmethod
    def setUpClass(cls):
        agribot.app.config.update(TESTING=True)
        cls.client = agribot.app.test_client()

    def test_every_predefined_suggestion_returns_its_linked_answer(self):
        tested = 0
        for language in ("en", "tw"):
            answer_key = f"answer_{language}"
            for topic in agribot.TOPICS:
                suggestions = agribot.get_suggestions(topic, language)
                self.assertTrue(suggestions)
                for suggestion in suggestions:
                    self.assertIn(suggestion["id"], agribot.KNOWN_RECORDS)
                    response = self.client.post(
                        "/api/chat",
                        json={
                            "message": suggestion["text"],
                            "language": language,
                            "suggestion_id": suggestion["id"],
                        },
                    )
                    self.assertEqual(response.status_code, 200)
                    payload = response.get_json()
                    self.assertEqual(payload["type"], "answer")
                    self.assertEqual(payload["source"], "retrieval_v1")
                    self.assertEqual(payload["record_id"], suggestion["id"])
                    self.assertEqual(
                        payload["text"],
                        agribot.KNOWN_RECORDS[suggestion["id"]][answer_key],
                    )
                    tested += 1
        expected = 2 * sum(
            len(items) for items in agribot.SUGGESTION_LINKS.values()
        )
        self.assertEqual(tested, expected)

    def test_links_and_registry_match_the_canonical_563_record_dataset(self):
        self.assertEqual(
            agribot.DATA_FILE.name, "agribotgh_dataset_bilingual_563.json"
        )
        with open(agribot.DATA_FILE, "r", encoding="utf-8") as handle:
            canonical_records = json.load(handle)
        self.assertEqual(len(canonical_records), 563)
        self.assertEqual(len(agribot.KNOWN_RECORDS), 563)
        self.assertEqual(len(agribot.en_qs), 563)
        self.assertEqual(len(agribot.tw_qs), 563)

        canonical_by_id = {record["id"]: record for record in canonical_records}
        for links in agribot.SUGGESTION_LINKS.values():
            for link in links:
                source = canonical_by_id[link["dataset_id"]]
                record = agribot.KNOWN_RECORDS[link["record_id"]]
                self.assertEqual(record["dataset_id"], source["id"])
                self.assertEqual(record["category"], source["category"])
                self.assertEqual(link["suggestion_en"], source["question_en"])
                self.assertEqual(link["suggestion_tw"], source["question_twi"])
                self.assertEqual(record["answer_en"], source["answer_en"])
                self.assertEqual(record["answer_tw"], source["answer_twi"])

    def test_topic_endpoint_returns_structured_suggestions(self):
        response = self.client.post(
            "/api/topic-suggestions", json={"topic": "Maize", "lang": "en"}
        )
        self.assertEqual(response.status_code, 200)
        suggestions = response.get_json()["suggestions"]
        self.assertTrue(suggestions)
        self.assertTrue(all(item.get("id") and item.get("text") for item in suggestions))

    def test_unknown_suggestion_id_is_rejected(self):
        response = self.client.post(
            "/api/chat",
            json={
                "message": "When is the best time to plant maize in Ghana?",
                "language": "en",
                "suggestion_id": "qa-does-not-exist",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "Unknown suggestion ID")

    def test_mismatched_suggestion_text_and_id_is_rejected(self):
        maize = agribot.get_suggestions("Maize", "en")[0]
        cassava = agribot.get_suggestions("Cassava", "en")[0]
        self.assertNotEqual(maize["id"], cassava["id"])
        response = self.client.post(
            "/api/chat",
            json={
                "message": cassava["text"],
                "language": "en",
                "suggestion_id": maize["id"],
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.get_json()["error"],
            "Suggestion text does not match its record ID",
        )

    def test_ordinary_chat_does_not_require_a_suggestion_id(self):
        response = self.client.post(
            "/api/chat", json={"message": "hello", "language": "en"}
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["type"], "answer")
        self.assertNotEqual(payload.get("source"), "known_suggestion")

    def test_right_panel_questions_use_canonical_answers_when_typed(self):
        for question, record_id in self.RIGHT_PANEL_ENGLISH:
            with self.subTest(question=question):
                response = self.client.post(
                    "/api/chat", json={"message": question, "language": "en"}
                )
                self.assertEqual(response.status_code, 200)
                payload = response.get_json()
                self.assertEqual(payload["type"], "answer")
                self.assertEqual(payload["language"], "en")
                self.assertEqual(payload["routing_state"], "A")
                self.assertEqual(payload["source"], "retrieval_v1")
                self.assertEqual(payload["record_id"], record_id)
                self.assertEqual(
                    payload["text"], agribot.KNOWN_RECORDS[record_id]["answer_en"]
                )

    def test_quick_question_catalogue_is_valid_in_both_languages(self):
        for language, expected_count in (("en", 8), ("tw", 6)):
            response = self.client.get(f"/api/quick-suggestions?lang={language}")
            self.assertEqual(response.status_code, 200)
            suggestions = response.get_json()["suggestions"]
            self.assertEqual(len(suggestions), expected_count)
            for suggestion in suggestions:
                answer = self.client.post(
                    "/api/chat",
                    json={"message": suggestion["text"], "language": language},
                )
                self.assertEqual(answer.status_code, 200)
                payload = answer.get_json()
                self.assertEqual(payload["type"], "answer")
                self.assertEqual(payload["language"], language)
                self.assertEqual(set(suggestion), {"text"})
                self.assertEqual(payload["source"], "retrieval_v1")

    def test_fertilizer_word_order_variants_normalize_to_same_record(self):
        variants = (
            "What fertilizer is best for maize?",
            "Which fertilizer should I use for maize?",
            "For maize what fertilizer should I use?",
            "What is the best fertilizer for maize?",
            "For maize what is the best fertilizer it?",
        )
        for question in variants:
            with self.subTest(question=question):
                payload = self.client.post(
                    "/api/chat", json={"message": question, "language": "en"}
                ).get_json()
                self.assertEqual(payload["type"], "answer")
                self.assertEqual(payload["record_id"], "qa-0002")

    def test_uncertain_agriculture_and_off_topic_guards_are_preserved(self):
        uncertain = self.client.post(
            "/api/chat",
            json={
                "message": "My maize leaves are changing colour and I am not sure why",
                "language": "en",
            },
        ).get_json()
        self.assertEqual(uncertain["type"], "knowledge_gap")
        self.assertEqual(uncertain["routing_state"], "D")
        self.assertTrue(uncertain["available_topics"])

        off_topic = self.client.post(
            "/api/chat",
            json={"message": "How do I repair a laptop screen?", "language": "en"},
        ).get_json()
        self.assertEqual(off_topic["type"], "off_topic")
        self.assertEqual(off_topic["routing_state"], "C")


if __name__ == "__main__":
    unittest.main()
