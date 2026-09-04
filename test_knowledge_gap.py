"""State D knowledge-gap routing and safety regressions."""

import unittest
from unittest.mock import patch

import app
from services.gemini_service import GeminiService


class FakeGeminiService:
    def __init__(self, result):
        self.result = result
        self.calls = []
        self.available = True

    def availability(self):
        return {"available": True, "reason": "configured", "model": "fake"}

    def interpret_query(self, query, language):
        self.calls.append((query, language))
        return self.result


class KnowledgeGapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.app.config.update(TESTING=True)
        cls.client = app.app.test_client()

    def test_supported_english_and_twi_questions_remain_state_a(self):
        service = FakeGeminiService({"success": False, "code": "must_not_call"})
        with patch.object(app, "GEMINI_SERVICE", service):
            english = app.get_answer("What fertilizer is best for maize?", "en")
            twi = app.get_answer("Ferefere bɛn na ɛyɛ papa ma aburo?", "tw")

        self.assertEqual((english["routing_state"], english["type"]), ("A", "answer"))
        self.assertEqual((twi["routing_state"], twi["type"]), ("A", "answer"))
        self.assertEqual(english["record_id"], "qa-0002")
        self.assertEqual(twi["record_id"], "qa-0002")
        self.assertEqual(service.calls, [])

    def test_gemini_can_rescue_weak_english_and_twi_only_to_dataset_answers(self):
        cases = (
            (
                "en",
                "I have some troublesome plants mixed among my maize",
                "How can I control weeds in my maize farm?",
            ),
            (
                "tw",
                "Nnɔbae bɔne bi fra me aburo mu",
                "Dɛn na menyɛ nhaban foforo a wɔ me aburoɔ afuom mu?",
            ),
        )
        for language, original, interpreted in cases:
            with self.subTest(language=language):
                service = FakeGeminiService({
                    "success": True,
                    "interpreted_query": interpreted,
                })
                with patch.object(app, "GEMINI_SERVICE", service):
                    result = app.get_answer(original, language)
                self.assertEqual(result["routing_state"], "A")
                self.assertEqual(result["record_id"], "qa-0212")
                self.assertTrue(result["gemini_assisted"])
                self.assertEqual(len(service.calls), 1)

    def test_unsupported_named_farming_entities_return_state_d(self):
        cases = (
            ("en", "What feed is suitable for ostriches?"),
            ("en", "How can I grow strawberries commercially in Ghana?"),
            ("en", "How do I manage alpacas on a farm?"),
            ("tw", "Mɛyɛ dɛn na mafi ostrich kuayɛ ase?"),
        )
        with patch.object(app, "GEMINI_SERVICE", GeminiService(api_key="")):
            for language, question in cases:
                with self.subTest(language=language, question=question):
                    result = app.get_answer(question, language)
                    self.assertEqual(result["routing_state"], "D")
                    self.assertEqual(result["type"], "knowledge_gap")
                    self.assertTrue(result["knowledge_gap"])
                    self.assertNotIn("record_id", result)
                    self.assertNotIn("gemini_assisted", result)
                    self.assertEqual(result["retrieval_assistance"]["accepted"], False)

    def test_twi_state_d_is_twi_and_does_not_leak_an_english_answer(self):
        with patch.object(app, "GEMINI_SERVICE", GeminiService(api_key="")):
            result = app.get_answer("Mɛyɛ dɛn na mafi ostrich kuayɛ ase?", "tw")
        self.assertIn("Mete ase sɛ eyi yɛ kuayɛ ho asɛmmisa", result["text"])
        self.assertNotIn("I understand that this is a farming question", result["text"])

    def test_off_topic_and_weather_requests_never_become_state_d(self):
        service = FakeGeminiService({"success": False, "code": "must_not_call"})
        with patch.object(app, "GEMINI_SERVICE", service):
            off_topic = app.get_answer("Who won the football match?", "en")
            weather = app.get_answer("Will it rain tomorrow in Kumasi?", "en")
            twi_weather = app.get_answer("Osuo bɛtɔ ɔkyena wɔ Kumasi?", "tw")

        self.assertEqual(off_topic["routing_state"], "C")
        self.assertNotEqual(weather.get("routing_state"), "D")
        self.assertNotEqual(twi_weather.get("routing_state"), "D")
        self.assertEqual(service.calls, [])

    def test_gemini_failure_and_missing_key_fail_safely_to_state_d(self):
        question = "My maize leaves are changing colour and I am not sure why"
        services = (
            GeminiService(api_key=""),
            FakeGeminiService({"success": False, "code": "timeout"}),
            FakeGeminiService({"success": False, "code": "malformed_response"}),
            FakeGeminiService({"success": False, "code": "rate_limited"}),
            FakeGeminiService({"success": False, "code": "unsafe_interpretation"}),
        )
        for service in services:
            with self.subTest(service=type(service).__name__, result=getattr(service, "result", None)):
                with patch.object(app, "GEMINI_SERVICE", service):
                    result = app.get_answer(question, "en")
                self.assertEqual(result["routing_state"], "D")
                self.assertEqual(result["type"], "knowledge_gap")
                self.assertNotIn("record_id", result)

    def test_available_topics_are_exactly_the_dataset_categories(self):
        expected = sorted(
            {
                record["category"].strip()
                for record in app.CANONICAL_RECORDS
                if record["category"].strip()
            },
            key=str.casefold,
        )
        self.assertEqual(list(app.AVAILABLE_CATEGORIES), expected)
        self.assertEqual(len(expected), len(set(expected)))
        self.assertNotIn("", expected)

        with patch.object(app, "GEMINI_SERVICE", GeminiService(api_key="")):
            payload = app.get_answer("How do I manage alpacas on a farm?", "en")
        self.assertEqual(payload["available_topics"], expected)
        self.assertEqual(set(payload["available_topic_icons"]), set(expected))
        self.assertEqual(set(payload["available_topic_names_tw"]), set(expected))

    def test_known_questions_across_categories_do_not_false_positive_as_gaps(self):
        categories = (
            "Maize",
            "Tomato",
            "Cassava",
            "Soil & Land Preparation",
            "Fertilizer & Nutrients",
            "Pest & Disease Control",
            "Irrigation & Water",
            "Poultry Farming",
            "Cattle Rearing",
            "Fish Farming",
            "Farm Records & Extension",
        )
        by_category = {}
        for record in app.CANONICAL_RECORDS:
            by_category.setdefault(record["category"], record)

        service = FakeGeminiService({"success": False, "code": "must_not_call"})
        with patch.object(app, "GEMINI_SERVICE", service):
            for category in categories:
                record = by_category[category]
                for language, question_key, answer_key in (
                    ("en", "question_en", "answer_en"),
                    ("tw", "question_twi", "answer_twi"),
                ):
                    with self.subTest(category=category, language=language):
                        result = app.get_answer(record[question_key], language)
                        self.assertEqual(result["routing_state"], "A")
                        self.assertEqual(result["text"], record[answer_key])
                        self.assertNotEqual(result["type"], "knowledge_gap")
        self.assertEqual(service.calls, [])


if __name__ == "__main__":
    unittest.main()
