"""Opt-in live Abena smoke test; never runs during normal automation."""

import os
import unittest

from services.abena_tts_service import AbenaTTSService


LIVE_ENABLED = os.getenv("RUN_LIVE_ABENA_TTS", "").strip().casefold() in {"1", "true"}


@unittest.skipUnless(LIVE_ENABLED, "Set RUN_LIVE_ABENA_TTS=1 for the optional live test")
class AbenaTTSLiveTest(unittest.TestCase):
    def test_live_twi_synthesis_returns_audio(self):
        result = AbenaTTSService(enabled=True).synthesize(
            "Akwaaba. Ɛnnɛ yɛbɛka afuo ho nsɛm kakra."
        )
        self.assertTrue(result.get("success"), result.get("code"))
        self.assertEqual(result.get("chunk_count"), 1)
        self.assertTrue(result["clips"][0]["audio_base64"])
        self.assertTrue(result["clips"][0]["mime_type"].startswith("audio/"))


if __name__ == "__main__":
    unittest.main()
