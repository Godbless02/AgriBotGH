"""Regression tests for TODO 23's independent off-topic challenge."""

import unittest

import app as agribot

from evaluate_off_topic_questions import (
    CHALLENGE_PATH,
    LEGACY_PATH,
    evaluate_challenge,
    load_json,
    normalize_question,
    validate_challenge,
)


class OffTopicQuestionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.challenge = load_json(CHALLENGE_PATH)
        cls.legacy = load_json(LEGACY_PATH)

    def test_challenge_schema_pairing_balance_and_independence(self):
        validate_challenge(self.challenge, self.legacy)
        self.assertEqual(self.challenge["pair_count"], 24)
        self.assertEqual(self.challenge["case_count"], 48)
        legacy_questions = {
            normalize_question(item["question"]) for item in self.legacy["cases"]
        }
        challenge_questions = {
            normalize_question(item["question"]) for item in self.challenge["cases"]
        }
        self.assertFalse(legacy_questions & challenge_questions)

    def test_live_router_rejects_every_challenge_without_answering(self):
        report = evaluate_challenge()
        self.assertEqual(report["summary"]["total"], 48)
        self.assertEqual(report["summary"]["failed"], 0)
        self.assertEqual(report["summary"]["state_c_recall"], 1.0)
        self.assertEqual(report["summary"]["agricultural_answers_returned"], 0)

    def test_explicit_guard_does_not_block_agricultural_word_usage(self):
        agricultural_cases = (
            ("en", "How should I store maize seed after harvest?"),
            ("en", "How can crop residues improve my field soil?"),
            ("en", "What feed should I give poultry on my farm?"),
            ("tw", "Mɛyɛ dɛn de aburo aba asie wɔ otwa akyi?"),
            ("tw", "Aduan bɛn na mede ma akokɔ wɔ m'afuo mu?"),
        )
        for language, question in agricultural_cases:
            with self.subTest(language=language, question=question):
                self.assertFalse(agribot.is_explicitly_off_topic(question, language))


if __name__ == "__main__":
    unittest.main()
