"""Regression tests for TODO 16 topic selection and direct questions."""

import unittest

import app as agribot


class TopicSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        agribot.app.config.update(TESTING=True)
        cls.client = agribot.app.test_client()

    def test_topic_catalogue_exposes_every_backend_topic(self):
        response = self.client.get("/api/topics")
        self.assertEqual(response.status_code, 200)
        catalogue = response.get_json()
        self.assertEqual(set(catalogue), set(agribot.TOPICS))
        self.assertEqual(len(catalogue), 28)

        for topic, item in catalogue.items():
            self.assertEqual(item["icon"], agribot.TOPICS[topic]["icon"])
            self.assertEqual(item["tw_name"], agribot.TOPICS[topic]["tw_name"])
            self.assertEqual(item["suggestion_count"], len(agribot.SUGGESTION_LINKS[topic]))
            self.assertEqual(item["suggestions"], agribot.get_suggestions(topic, "en"))

    def test_every_topic_returns_canonical_suggestions_in_both_languages(self):
        for language in ("en", "tw"):
            for topic, info in agribot.TOPICS.items():
                with self.subTest(language=language, topic=topic):
                    response = self.client.post(
                        "/api/topic-suggestions",
                        json={"topic": topic, "lang": language},
                    )
                    self.assertEqual(response.status_code, 200)
                    payload = response.get_json()
                    self.assertEqual(payload["topic"], topic)
                    self.assertEqual(payload["icon"], info["icon"])
                    expected_name = info["tw_name"] if language == "tw" else topic
                    self.assertEqual(payload["display_name"], expected_name)
                    self.assertEqual(
                        payload["suggestions"],
                        agribot.get_suggestions(topic, language),
                    )
                    self.assertTrue(payload["suggestions"])

    def test_natural_question_works_without_topic_selection(self):
        record = agribot.KNOWN_RECORDS["qa-0001"]
        response = self.client.post(
            "/api/chat",
            json={"message": record["question_en"], "language": "en"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["type"], "answer")
        self.assertEqual(payload["text"], record["answer_en"])

    def test_invalid_topic_requests_fail_cleanly(self):
        invalid_topic = self.client.post(
            "/api/topic-suggestions",
            json={"topic": "Not a canonical topic", "lang": "en"},
        )
        self.assertEqual(invalid_topic.status_code, 404)
        self.assertEqual(invalid_topic.get_json()["error"], "Topic not found")

        invalid_json = self.client.post(
            "/api/topic-suggestions",
            data="not json",
            content_type="text/plain",
        )
        self.assertEqual(invalid_json.status_code, 400)
        self.assertEqual(invalid_json.get_json()["error"], "Invalid JSON payload")


if __name__ == "__main__":
    unittest.main()
