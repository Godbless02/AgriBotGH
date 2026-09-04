"""Regression tests for TODO 21's final training workflow."""

import json
import tempfile
import unittest
from pathlib import Path

from train_model import (
    DATASET_PATH,
    GOLD_PATH,
    SPLIT_DIR,
    deterministic_split,
    load_json,
    train_final_model,
    validate_gold_standard,
)


class FinalTrainingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.canonical = load_json(DATASET_PATH)
        cls.splits = deterministic_split(cls.canonical)

    def test_deterministic_split_is_complete_disjoint_and_expected_size(self):
        self.assertEqual(
            {name: len(records) for name, records in self.splits.items()},
            {"train": 394, "validation": 84, "test": 85},
        )
        ids = [record["id"] for records in self.splits.values() for record in records]
        self.assertEqual(len(ids), 563)
        self.assertEqual(len(set(ids)), 563)
        self.assertEqual(self.splits, deterministic_split(self.canonical))

    def test_gold_standard_matches_generated_validation_and_training_sets(self):
        entries = validate_gold_standard(load_json(GOLD_PATH), self.splits)
        self.assertEqual(len(entries["English"]), 84)
        self.assertEqual(len(entries["Twi"]), 84)

    def test_training_builds_complete_non_active_version_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir) / "production"
            active_before = (Path("models/production/active_model.json")).read_bytes()
            version_dir = train_final_model(
                version="9.9.9",
                output_root=output_root,
                split_dir=SPLIT_DIR,
            )
            expected = {
                "english.joblib",
                "twi.joblib",
                "retrieval_config.json",
                "evaluation_summary.json",
                "dataset_validation.json",
                "model_metadata.json",
            }
            self.assertEqual({path.name for path in version_dir.iterdir()}, expected)
            metadata = json.loads((version_dir / "model_metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["semantic_version"], "9.9.9")
            self.assertEqual(metadata["activation_status"], "candidate_not_activated")
            self.assertEqual(metadata["dataset_validation"]["blocking_errors"], 0)
            self.assertEqual(metadata["training_records"], 563)
            self.assertEqual(metadata["selection_training_records"], 394)
            self.assertEqual(metadata["production_index_records"], 563)
            for language in ("English", "Twi"):
                self.assertEqual(
                    metadata["evaluation"]["languages"][language]["metrics"]["total_cases"],
                    84,
                )
            self.assertEqual(
                Path("models/production/active_model.json").read_bytes(), active_before
            )
            with self.assertRaises(FileExistsError):
                train_final_model(
                    version="9.9.9",
                    output_root=output_root,
                    split_dir=SPLIT_DIR,
                )

    def test_invalid_semantic_version_fails_before_writing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir) / "production"
            with self.assertRaises(ValueError):
                train_final_model(version="latest", output_root=output_root)
            self.assertFalse(output_root.exists())


if __name__ == "__main__":
    unittest.main()
