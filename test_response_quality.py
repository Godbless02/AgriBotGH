"""Regression tests for TODOs 29 and 30 response quality and safety."""

import unittest

import app as agribot
from evaluate_response_quality import evaluate_response_quality


class ResponseQualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        agribot.app.config.update(TESTING=True)
        cls.client = agribot.app.test_client()

    def test_complete_quality_and_safety_audit_passes(self):
        report = evaluate_response_quality(self.client)
        summary = report["summary"]
        self.assertTrue(summary["passed"])
        self.assertEqual(summary["canonical_answers_audited"], 1126)
        self.assertEqual(summary["structural_quality_blockers"], 0)
        self.assertGreater(summary["high_risk_answers"], 0)
        self.assertEqual(summary["high_risk_notice_coverage"], 1.0)

    def test_high_risk_notice_is_separate_and_bilingual(self):
        for language, record, expected in (
            ("en", agribot.CANONICAL_RECORDS[1], "current product label"),
            ("tw", agribot.CANONICAL_RECORDS[1], "Ahobammɔ ho nkae"),
        ):
            question_field = "question_twi" if language == "tw" else "question_en"
            answer_field = "answer_twi" if language == "tw" else "answer_en"
            payload = self.client.post(
                "/api/chat",
                json={"message": record[question_field], "language": language},
            ).get_json()
            self.assertEqual(payload["text"], record[answer_field])
            self.assertIn(expected, payload["safety_notice"])
            self.assertEqual(
                payload["safety_classification"],
                "high_risk_agricultural_guidance",
            )

    def test_low_risk_answer_has_no_unnecessary_warning(self):
        record = agribot.CANONICAL_RECORDS[0]
        payload = self.client.post(
            "/api/chat",
            json={"message": record["question_en"], "language": "en"},
        ).get_json()
        self.assertNotIn("safety_notice", payload)


if __name__ == "__main__":
    unittest.main()
