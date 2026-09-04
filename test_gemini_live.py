import os
import unittest

from services.gemini_service import GeminiService


@unittest.skipUnless(
    os.getenv("RUN_GEMINI_LIVE_TESTS", "").casefold() == "true"
    and bool(os.getenv("GEMINI_API_KEY")),
    "Set RUN_GEMINI_LIVE_TESTS=true and GEMINI_API_KEY for the optional live test",
)
class GeminiLiveTest(unittest.TestCase):
    def test_live_interpretation_returns_only_a_validated_query(self):
        result = GeminiService().interpret_query(
            "I have some troublesome plants mixed among my maize", "en"
        )
        self.assertTrue(result["success"], result.get("code"))
        self.assertIsInstance(result["interpreted_query"], str)


if __name__ == "__main__":
    unittest.main()
