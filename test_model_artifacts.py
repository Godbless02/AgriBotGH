"""TODO 18 model artifact management and reproducibility tests."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from activate_model import activate_version
from build_retrieval_artifacts import MODEL_VERSION as LEGACY_MODEL_VERSION, build_bundle
from retrieval_runtime import RetrievalRuntime, sha256_file


BASE_DIR = Path(__file__).resolve().parent
PRODUCTION_DIR = BASE_DIR / "models" / "production"
MANIFEST_FILE = PRODUCTION_DIR / "active_model.json"
DATA_FILE = BASE_DIR / "data" / "agribotgh_dataset_bilingual_563.json"


class ModelArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
        cls.metadata_file = BASE_DIR / cls.manifest["metadata_file"]
        cls.metadata = json.loads(cls.metadata_file.read_text(encoding="utf-8"))

    def test_active_manifest_and_metadata_are_complete(self):
        self.assertEqual(self.manifest["manifest_schema_version"], 1)
        self.assertEqual(self.manifest["active_semantic_version"], "1.3.1")
        self.assertEqual(
            sha256_file(self.metadata_file), self.manifest["metadata_sha256"]
        )
        required = {
            "model_id",
            "model_version",
            "semantic_version",
            "built_at_utc",
            "canonical_dataset",
            "canonical_dataset_records",
            "canonical_dataset_sha256",
            "splits",
            "training_records",
            "training_random_seed",
            "retrieval_architecture",
            "configuration_file",
            "evaluation_file",
            "evaluation",
            "artifacts",
            "software",
            "source_sha256",
        }
        self.assertTrue(required.issubset(self.metadata))
        self.assertEqual(self.metadata["semantic_version"], "1.3.1")
        self.assertEqual(self.metadata["canonical_dataset_records"], 563)
        self.assertEqual(self.metadata["training_records"], 563)
        self.assertEqual(self.metadata["selection_training_records"], 394)
        self.assertEqual(self.metadata["production_index_records"], 563)

    def test_dataset_splits_support_files_and_artifacts_match_checksums(self):
        self.assertEqual(
            sha256_file(DATA_FILE), self.metadata["canonical_dataset_sha256"]
        )
        for split in self.metadata["splits"].values():
            self.assertEqual(sha256_file(BASE_DIR / split["file"]), split["sha256"])

        version_dir = self.metadata_file.parent
        self.assertEqual(
            sha256_file(version_dir / self.metadata["configuration_file"]),
            self.metadata["configuration_sha256"],
        )
        self.assertEqual(
            sha256_file(version_dir / self.metadata["evaluation_file"]),
            self.metadata["evaluation_sha256"],
        )
        for artifact in self.metadata["artifacts"].values():
            artifact_path = version_dir / artifact["file"]
            self.assertEqual(artifact_path.stat().st_size, artifact["bytes"])
            self.assertEqual(sha256_file(artifact_path), artifact["sha256"])
        for source_file, expected_hash in self.metadata["source_sha256"].items():
            self.assertEqual(sha256_file(BASE_DIR / source_file), expected_hash)

    def test_evaluation_and_configuration_are_recorded(self):
        evaluation = self.metadata["evaluation"]
        self.assertEqual(
            evaluation["retrieval_selection"]["macro_top_1_accuracy"], 0.5
        )
        self.assertEqual(evaluation["threshold_validation"]["threshold"], 0.5)
        self.assertEqual(evaluation["router_test"]["total"], 104)
        self.assertTrue(evaluation["limitations"])

        config_path = self.metadata_file.parent / self.metadata["configuration_file"]
        config = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual(config["weights"], {
            "tfidf": 0.38,
            "embedding": 0.0,
            "topic": 0.62,
        })
        self.assertEqual(config["tfidf_configuration"], "C_word_and_character")
        self.assertIn("components", config["vectorizer"])

    def test_existing_model_version_cannot_be_overwritten(self):
        with self.assertRaises(FileExistsError):
            build_bundle(PRODUCTION_DIR, activate=False)

    def test_isolated_rebuild_reproduces_the_active_bundle(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            rebuilt_dir = build_bundle(
                Path(temp_dir) / "production", activate=False
            )
            rebuilt = json.loads(
                (rebuilt_dir / "model_metadata.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                rebuilt["canonical_dataset_sha256"],
                self.metadata["canonical_dataset_sha256"],
            )
            self.assertEqual(rebuilt["splits"], self.metadata["splits"])
            legacy_metadata = json.loads(
                (PRODUCTION_DIR / LEGACY_MODEL_VERSION / "model_metadata.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(rebuilt["configuration_sha256"], legacy_metadata["configuration_sha256"])
            self.assertEqual(
                rebuilt["evaluation_sha256"], legacy_metadata["evaluation_sha256"]
            )
            for language in ("English", "Twi"):
                self.assertEqual(
                    rebuilt["artifacts"][language]["semantic_sha256"],
                    legacy_metadata["artifacts"][language]["semantic_sha256"],
                )

    def test_runtime_rejects_corrupted_artifact(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_base = Path(temp_dir)
            fake_production = fake_base / "models" / "production"
            shutil.copytree(PRODUCTION_DIR, fake_production)
            active_version = self.manifest["active_semantic_version"]
            fake_metadata = json.loads(
                (fake_production / active_version / "model_metadata.json").read_text(
                    encoding="utf-8"
                )
            )
            artifact_path = (
                fake_production
                / active_version
                / fake_metadata["artifacts"]["English"]["file"]
            )
            with artifact_path.open("ab") as handle:
                handle.write(b"corruption")
            with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
                RetrievalRuntime(fake_base, DATA_FILE)

    def test_runtime_rejects_corrupted_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_base = Path(temp_dir)
            fake_production = fake_base / "models" / "production"
            shutil.copytree(PRODUCTION_DIR, fake_production)
            active_version = self.manifest["active_semantic_version"]
            metadata_path = fake_production / active_version / "model_metadata.json"
            with metadata_path.open("a", encoding="utf-8") as handle:
                handle.write("\n")
            with self.assertRaisesRegex(RuntimeError, "metadata checksum mismatch"):
                RetrievalRuntime(fake_base, DATA_FILE)

    def test_previous_version_can_be_safely_activated_for_rollback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_base = Path(temp_dir)
            fake_production = fake_base / "models" / "production"
            shutil.copytree(PRODUCTION_DIR, fake_production)
            manifest = activate_version(
                fake_base, fake_production, DATA_FILE, "1.0.0"
            )
            self.assertEqual(manifest["active_semantic_version"], "1.0.0")
            runtime = RetrievalRuntime(fake_base, DATA_FILE)
            self.assertEqual(runtime.metadata["semantic_version"], "1.0.0")


if __name__ == "__main__":
    unittest.main()
