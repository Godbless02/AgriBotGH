"""Regression tests for TODO 20's canonical dataset validator."""

from copy import deepcopy
import unittest

from validate_dataset import validate_records


def valid_record(record_id=1):
    return {
        "id": record_id,
        "category": "Maize",
        "question_en": "How should I plant maize safely?",
        "answer_en": "Plant certified seed in moist soil and follow local extension guidance carefully.",
        "question_twi": "Ɛbɛyɛ dɛn na matɔ aburo aba no yie?",
        "answer_twi": "Fa aba pa gu asase a ɛwɔ nsuo mu na tie wo kuayɛ ɔfotufoɔ akwankyerɛ yie.",
    }


class DatasetValidationTests(unittest.TestCase):
    def validate(self, records):
        return validate_records(records, expected_count=None, dataset_sha256="test")

    def test_valid_bilingual_record_passes_all_blocking_checks(self):
        report = self.validate([valid_record()])
        self.assertEqual(report["blocking_error_count"], 0)
        self.assertTrue(all(report["checks"].values()))

    def test_missing_empty_and_unexpected_fields_are_blockers(self):
        record = valid_record()
        del record["answer_twi"]
        record["answer_en"] = "  "
        record["obsolete"] = "value"
        codes = {item["code"] for item in self.validate([record])["errors"]}
        self.assertTrue({"missing_fields", "empty_or_non_string", "unexpected_fields"} <= codes)

    def test_ids_must_be_unique(self):
        records = [valid_record(2), valid_record(2)]
        records[1]["question_en"] = "Why should I use certified maize seed?"
        records[1]["question_twi"] = "Adɛn nti na ɛsɛ sɛ mede aburo aba pa di dwuma?"
        codes = {item["code"] for item in self.validate(records)["errors"]}
        self.assertIn("duplicate_ids", codes)

    def test_normalized_question_duplicates_are_blockers(self):
        records = [valid_record(1), valid_record(2)]
        records[1]["question_en"] = " HOW should I plant maize safely ? "
        records[1]["question_twi"] = "Asɛmmisa foforɔ bɛn na mɛtumi abisa?"
        codes = {item["code"] for item in self.validate(records)["errors"]}
        self.assertIn("duplicate_questions", codes)

    def test_unknown_category_and_identical_pairs_are_blockers(self):
        record = valid_record()
        record["category"] = "maize"
        record["question_twi"] = record["question_en"]
        record["answer_twi"] = record["answer_en"]
        codes = {item["code"] for item in self.validate([record])["errors"]}
        self.assertTrue({"unknown_category", "identical_language_pair"} <= codes)

    def test_whitespace_and_question_shape_are_blockers(self):
        record = valid_record()
        record["question_en"] = "Question without punctuation"
        record["answer_twi"] = " " + record["answer_twi"]
        codes = {item["code"] for item in self.validate([record])["errors"]}
        self.assertTrue({"question_punctuation", "outer_whitespace"} <= codes)

    def test_pairing_number_difference_is_a_review_warning(self):
        record = valid_record()
        record["answer_en"] += " Wait 14 days before the next step."
        report = self.validate([record])
        self.assertEqual(report["blocking_error_count"], 0)
        self.assertIn("numeric_pairing_review", {item["code"] for item in report["warnings"]})

    def test_input_is_not_mutated(self):
        records = [valid_record()]
        original = deepcopy(records)
        self.validate(records)
        self.assertEqual(records, original)


if __name__ == "__main__":
    unittest.main()
