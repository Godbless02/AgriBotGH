import base64
import os
import unittest
from unittest.mock import patch

import requests

import app as app_module
from services.abena_tts_service import (
    AbenaTTSService,
    CHUNK_TARGET_CHARS,
    MAX_TTS_TEXT_LENGTH,
    chunk_twi_text,
)


VALID_AUDIO = base64.b64encode(b"RIFF-test-audio").decode("ascii")


class FakeResponse:
    def __init__(self, status_code=200, payload=None, json_error=None):
        self.status_code = status_code
        self._payload = payload
        self._json_error = json_error

    def json(self):
        if self._json_error:
            raise self._json_error
        return self._payload


class FakeSession:
    def __init__(self, responses=None, error=None):
        self.responses = list(responses or [])
        self.error = error
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error
        return self.responses.pop(0)


def success_response(**overrides):
    payload = {
        "status": "success",
        "audio_base64": VALID_AUDIO,
        "duration_seconds": 1.25,
        "mime_type": "audio/wav",
    }
    payload.update(overrides)
    return FakeResponse(payload=payload)


class AbenaChunkingTests(unittest.TestCase):
    def test_short_text_stays_in_one_chunk(self):
        self.assertEqual(chunk_twi_text("Akwaaba okuafo."), ["Akwaaba okuafo."])

    def test_empty_text_has_no_chunks(self):
        self.assertEqual(chunk_twi_text("  \n "), [])

    def test_whitespace_is_normalized(self):
        self.assertEqual(chunk_twi_text("Maame\n\n  fa   nsuo."), ["Maame fa nsuo."])

    def test_unicode_twi_characters_are_preserved(self):
        text = "Ɛmo ne borɔdeɛ yɛ nnɔbaeɛ a ɛho hia."
        self.assertEqual(" ".join(chunk_twi_text(text)), text)

    def test_long_text_never_exceeds_provider_limit(self):
        chunks = chunk_twi_text("afuo " * 500)
        self.assertTrue(all(0 < len(chunk) <= 500 for chunk in chunks))

    def test_long_text_uses_target_sized_chunks(self):
        chunks = chunk_twi_text("a" * (CHUNK_TARGET_CHARS + 1))
        self.assertEqual([len(chunk) for chunk in chunks], [CHUNK_TARGET_CHARS, 1])

    def test_sentence_boundary_is_preferred(self):
        text = ("a" * 360) + ". " + ("b" * 200)
        self.assertTrue(chunk_twi_text(text)[0].endswith("."))

    def test_comma_boundary_is_second_choice(self):
        text = ("a" * 360) + ", " + ("b" * 200)
        self.assertTrue(chunk_twi_text(text)[0].endswith(","))

    def test_word_boundary_is_used_before_hard_cut(self):
        text = ("a" * 360) + " " + ("b" * 200)
        self.assertEqual(len(chunk_twi_text(text)[0]), 360)

    def test_invalid_text_type_is_rejected(self):
        with self.assertRaises(TypeError):
            chunk_twi_text(None)

    def test_invalid_target_is_rejected(self):
        with self.assertRaises(ValueError):
            chunk_twi_text("text", 501)


class AbenaTTSServiceTests(unittest.TestCase):
    def make_service(self, session, **kwargs):
        return AbenaTTSService(
            session=session,
            enabled=True,
            api_url="https://provider.invalid/tts",
            voice="abena_twi_lite",
            speed=1.0,
            api_key="",
            **kwargs,
        )

    def test_success_returns_memory_only_clip_metadata(self):
        service = self.make_service(FakeSession([success_response()]))
        result = service.synthesize("Akwaaba")
        self.assertTrue(result["success"])
        self.assertEqual(result["chunk_count"], 1)
        self.assertEqual(result["clips"][0]["audio_base64"], VALID_AUDIO)

    def test_request_uses_fixed_voice_speed_and_timeout(self):
        session = FakeSession([success_response()])
        self.make_service(session).synthesize("Akwaaba")
        _, kwargs = session.calls[0]
        self.assertEqual(kwargs["json"], {
            "text": "Akwaaba", "voice": "abena_twi_lite", "speed": 1.0
        })
        self.assertEqual(kwargs["timeout"], (5, 120))

    def test_request_has_no_authorization_header_without_key(self):
        session = FakeSession([success_response()])
        self.make_service(session).synthesize("Akwaaba")
        self.assertNotIn("Authorization", session.calls[0][1]["headers"])

    def test_optional_key_is_sent_only_as_bearer_header(self):
        session = FakeSession([success_response()])
        service = AbenaTTSService(session=session, enabled=True, api_key="secret")
        service.synthesize("Akwaaba")
        kwargs = session.calls[0][1]
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer secret")
        self.assertNotIn("secret", str(kwargs["json"]))

    def test_disabled_service_never_calls_provider(self):
        session = FakeSession()
        result = AbenaTTSService(session=session, enabled=False).synthesize("Akwaaba")
        self.assertEqual(result["code"], "disabled")
        self.assertEqual(session.calls, [])

    def test_multiple_chunks_are_requested_once_each_in_order(self):
        session = FakeSession([success_response(), success_response()])
        result = self.make_service(session).synthesize("a" * 600)
        self.assertEqual(result["chunk_count"], 2)
        self.assertEqual(len(session.calls), 2)
        self.assertEqual("".join(call[1]["json"]["text"] for call in session.calls), "a" * 600)

    def test_timeout_allows_browser_fallback(self):
        result = self.make_service(FakeSession(error=requests.Timeout())).synthesize("Akwaaba")
        self.assertEqual(result["code"], "timeout")
        self.assertTrue(result["fallback_allowed"])

    def test_transport_failure_allows_browser_fallback(self):
        error = requests.ConnectionError("private transport detail")
        result = self.make_service(FakeSession(error=error)).synthesize("Akwaaba")
        self.assertEqual(result["code"], "provider_unavailable")
        self.assertNotIn("private", str(result))

    def test_authentication_failure_is_stable(self):
        result = self.make_service(FakeSession([FakeResponse(401)])).synthesize("Akwaaba")
        self.assertEqual(result["code"], "authentication_failed")

    def test_credit_failure_is_stable(self):
        result = self.make_service(FakeSession([FakeResponse(402)])).synthesize("Akwaaba")
        self.assertEqual(result["code"], "credits_exhausted")

    def test_provider_limit_is_stable(self):
        result = self.make_service(FakeSession([FakeResponse(413)])).synthesize("Akwaaba")
        self.assertEqual(result["code"], "provider_limit")

    def test_rate_limit_is_stable(self):
        result = self.make_service(FakeSession([FakeResponse(429)])).synthesize("Akwaaba")
        self.assertEqual(result["code"], "rate_limited")

    def test_server_error_is_stable(self):
        result = self.make_service(FakeSession([FakeResponse(503)])).synthesize("Akwaaba")
        self.assertEqual(result["code"], "provider_unavailable")

    def test_non_json_response_is_rejected(self):
        response = FakeResponse(json_error=ValueError("not json"))
        result = self.make_service(FakeSession([response])).synthesize("Akwaaba")
        self.assertEqual(result["code"], "invalid_response")

    def test_provider_failure_payload_is_rejected(self):
        response = FakeResponse(payload={"status": "error", "audio_base64": VALID_AUDIO})
        result = self.make_service(FakeSession([response])).synthesize("Akwaaba")
        self.assertEqual(result["code"], "invalid_response")

    def test_missing_audio_is_rejected(self):
        result = self.make_service(FakeSession([success_response(audio_base64="")])).synthesize("Akwaaba")
        self.assertEqual(result["code"], "invalid_response")

    def test_invalid_base64_is_rejected(self):
        result = self.make_service(FakeSession([success_response(audio_base64="not base64!")])).synthesize("Akwaaba")
        self.assertEqual(result["code"], "invalid_response")

    def test_invalid_mime_type_gets_safe_default(self):
        result = self.make_service(FakeSession([success_response(mime_type="text/html")])).synthesize("Akwaaba")
        self.assertEqual(result["clips"][0]["mime_type"], "audio/wav")

    def test_invalid_duration_becomes_null(self):
        result = self.make_service(FakeSession([success_response(duration_seconds="soon")])).synthesize("Akwaaba")
        self.assertIsNone(result["clips"][0]["duration_seconds"])

    def test_later_chunk_failure_discards_partial_audio(self):
        session = FakeSession([success_response(), FakeResponse(503)])
        result = self.make_service(session).synthesize("a" * 600)
        self.assertFalse(result["success"])
        self.assertNotIn("clips", result)

    def test_environment_configuration_has_safe_defaults(self):
        with patch.dict(os.environ, {}, clear=True):
            service = AbenaTTSService(session=FakeSession())
        self.assertFalse(service.enabled)
        self.assertEqual(service.voice, "abena_twi_lite")
        self.assertEqual(service.speed, 1.0)


class AbenaTTSEndpointTests(unittest.TestCase):
    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.client = app_module.app.test_client()

    def test_json_content_type_is_required(self):
        response = self.client.post("/api/tts", data="text")
        self.assertEqual(response.status_code, 400)

    def test_json_object_is_required(self):
        response = self.client.post("/api/tts", json=["text"])
        self.assertEqual(response.status_code, 400)

    def test_text_is_required(self):
        response = self.client.post("/api/tts", json={"language": "twi"})
        self.assertEqual(response.status_code, 400)

    def test_empty_text_is_rejected(self):
        response = self.client.post("/api/tts", json={"text": "  ", "language": "twi"})
        self.assertEqual(response.status_code, 400)

    def test_non_string_text_is_rejected(self):
        response = self.client.post("/api/tts", json={"text": 3, "language": "twi"})
        self.assertEqual(response.status_code, 400)

    def test_only_twi_language_is_accepted(self):
        response = self.client.post("/api/tts", json={"text": "Hello", "language": "en"})
        self.assertEqual(response.status_code, 400)

    def test_oversized_text_is_413(self):
        response = self.client.post("/api/tts", json={
            "text": "a" * (MAX_TTS_TEXT_LENGTH + 1), "language": "twi"
        })
        self.assertEqual(response.status_code, 413)

    def test_successful_service_result_is_200(self):
        result = {"success": True, "clips": [], "chunk_count": 0}
        with patch.object(app_module.ABENA_TTS_SERVICE, "synthesize", return_value=result) as call:
            response = self.client.post("/api/tts", json={"text": "  Akwaaba  ", "language": "twi"})
        self.assertEqual(response.status_code, 200)
        call.assert_called_once_with("Akwaaba")

    def test_unavailable_service_result_is_503_with_fallback(self):
        result = {
            "success": False,
            "code": "timeout",
            "error": "Natural Twi audio is temporarily unavailable.",
            "fallback_allowed": True,
        }
        with patch.object(app_module.ABENA_TTS_SERVICE, "synthesize", return_value=result):
            response = self.client.post("/api/tts", json={"text": "Akwaaba", "language": "twi"})
        self.assertEqual(response.status_code, 503)
        self.assertTrue(response.get_json()["fallback_allowed"])

    def test_client_cannot_select_provider_voice_or_speed(self):
        result = {"success": True, "clips": [], "chunk_count": 0}
        with patch.object(app_module.ABENA_TTS_SERVICE, "synthesize", return_value=result) as call:
            self.client.post("/api/tts", json={
                "text": "Akwaaba", "language": "twi", "voice": "other", "speed": 9
            })
        call.assert_called_once_with("Akwaaba")


if __name__ == "__main__":
    unittest.main()
