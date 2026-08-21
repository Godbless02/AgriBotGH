"""Regression tests for TODO 15 direct suggestion routing."""

import json
import unittest

import app as agribot


class SuggestionRoutingTests(unittest.TestCase):
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
                    self.assertEqual(payload["source"], "known_suggestion")
                    self.assertEqual(payload["suggestion_id"], suggestion["id"])
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


if __name__ == "__main__":
    unittest.main()
