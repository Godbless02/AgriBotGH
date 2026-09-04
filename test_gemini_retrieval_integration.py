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


class GeminiRetrievalIntegrationTests(unittest.TestCase):
    def test_low_confidence_query_can_be_rescued_only_to_dataset_answer(self):
        service = FakeGeminiService({
            "success": True,
            "interpreted_query": "How can I control weeds in my maize farm?",
        })
        with patch.object(app, "GEMINI_SERVICE", service):
            result = app.get_answer(
                "I have some troublesome plants mixed among my maize", "en"
            )
        self.assertEqual(result["type"], "answer")
        self.assertEqual(result["record_id"], "qa-0212")
        self.assertEqual(result["source"], "retrieval_v1")
        self.assertTrue(result["gemini_assisted"])
        self.assertEqual(len(service.calls), 1)

    def test_strong_dataset_match_is_unchanged_and_never_calls_gemini(self):
        service = FakeGeminiService({"success": False, "code": "should_not_call"})
        with patch.object(app, "GEMINI_SERVICE", service):
            result = app.get_answer("What fertilizer is best for maize?", "en")
            twi_result = app.get_answer("Ferefere bɛn na ɛyɛ papa ma aburo?", "tw")
        self.assertEqual(result["record_id"], "qa-0002")
        self.assertEqual(twi_result["record_id"], "qa-0002")
        self.assertNotIn("gemini_assisted", result)
        self.assertNotIn("gemini_assisted", twi_result)
        self.assertEqual(service.calls, [])

    def test_missing_key_returns_safe_knowledge_gap_response(self):
        with patch.object(app, "GEMINI_SERVICE", GeminiService(api_key="")):
            result = app.get_answer(
                "My maize leaves are changing colour and I am not sure why", "en"
            )
        self.assertEqual(result["type"], "knowledge_gap")
        self.assertEqual(result["routing_state"], "D")
        self.assertNotIn("gemini_assisted", result)

    def test_provider_failure_returns_safe_knowledge_gap_response(self):
        service = FakeGeminiService({"success": False, "code": "timeout"})
        with patch.object(app, "GEMINI_SERVICE", service):
            result = app.get_answer(
                "My maize leaves are changing colour and I am not sure why", "en"
            )
        self.assertEqual(result["type"], "knowledge_gap")
        self.assertEqual(result["routing_state"], "D")
        self.assertEqual(len(service.calls), 1)

    def test_off_topic_and_weather_requests_never_call_gemini(self):
        service = FakeGeminiService({"success": False, "code": "should_not_call"})
        with patch.object(app, "GEMINI_SERVICE", service):
            off_topic = app.get_answer("Who won the football match?", "en")
            weather = app.get_answer("Will it rain tomorrow in Kumasi?", "en")
            twi_weather = app.get_answer("Osuo bɛtɔ ɔkyena wɔ Kumasi?", "tw")
        self.assertEqual(off_topic["routing_state"], "C")
        self.assertIn(weather["routing_state"], {"B", "C"})
        self.assertIn(twi_weather["routing_state"], {"B", "C"})
        self.assertEqual(service.calls, [])

    def test_chat_api_does_not_expose_interpreted_query(self):
        service = FakeGeminiService({
            "success": True,
            "interpreted_query": "How can I control weeds in my maize farm?",
        })
        with patch.object(app, "GEMINI_SERVICE", service):
            response = app.app.test_client().post("/api/chat", json={
                "message": "I have some troublesome plants mixed among my maize",
                "language": "en",
            })
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertNotIn("interpreted_query", payload)
        self.assertNotIn("original_query", payload)
        self.assertEqual(payload["record_id"], "qa-0212")


if __name__ == "__main__":
    unittest.main()
