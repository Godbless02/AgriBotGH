"""Load and run the validated AgriBotGH retrieval model without retraining."""

import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clean_text(value):
    return " ".join(str(value or "").strip().lower().split())


def normalize_nonnegative(scores):
    clipped = np.maximum(scores, 0.0)
    maximum = float(clipped.max()) if clipped.size else 0.0
    return clipped / maximum if maximum > 0.0 else np.zeros_like(clipped)


class RetrievalRuntime:
    """Validated topic-aware TF-IDF retrieval and three-state routing."""

    def __init__(self, base_dir, dataset_file):
        self.base_dir = Path(base_dir)
        self.dataset_file = Path(dataset_file)
        self.manifest_file = (
            self.base_dir / "models" / "production" / "active_model.json"
        )
        self.manifest = self._load_json(self.manifest_file)
        self.metadata_file = self.base_dir / self.manifest["metadata_file"]
        if sha256_file(self.metadata_file) != self.manifest.get("metadata_sha256"):
            raise RuntimeError("Active-model metadata checksum mismatch")
        self.metadata = self._load_json(self.metadata_file)
        self.version_dir = self.metadata_file.parent
        self._validate_metadata()
        self.models = {
            language: self._load_artifact(language)
            for language in ("English", "Twi")
        }

    @staticmethod
    def _load_json(path):
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _validate_metadata(self):
        if self.manifest.get("manifest_schema_version") != 1:
            raise RuntimeError("Unsupported active-model manifest schema")
        if self.metadata.get("metadata_schema_version") != 1:
            raise RuntimeError("Unsupported model metadata schema")
        if self.metadata.get("semantic_version") != self.manifest.get(
            "active_semantic_version"
        ):
            raise RuntimeError("Active-model version and metadata disagree")
        if self.metadata.get("model_id") != "agribotgh-retrieval":
            raise RuntimeError("Unsupported retrieval model ID")
        if self.metadata.get("model_version") != self.manifest.get("model_version"):
            raise RuntimeError("Active-model display version and metadata disagree")
        if self.metadata.get("retrieval_architecture") != "topic_aware_tfidf":
            raise RuntimeError("Unsupported retrieval architecture")
        if self.metadata.get("canonical_dataset_records") != 563:
            raise RuntimeError("Retrieval metadata has the wrong dataset size")
        current_hash = sha256_file(self.dataset_file)
        if current_hash != self.metadata.get("canonical_dataset_sha256"):
            raise RuntimeError(
                "Retrieval artifacts are stale for the canonical 563-record dataset"
            )
        config_path = self.version_dir / self.metadata["configuration_file"]
        evaluation_path = self.version_dir / self.metadata["evaluation_file"]
        if sha256_file(config_path) != self.metadata.get("configuration_sha256"):
            raise RuntimeError("Retrieval configuration checksum mismatch")
        if sha256_file(evaluation_path) != self.metadata.get("evaluation_sha256"):
            raise RuntimeError("Evaluation summary checksum mismatch")

    def _load_artifact(self, language):
        summary = self.metadata["artifacts"][language]
        path = self.version_dir / summary["file"]
        if not path.exists():
            raise RuntimeError(f"Missing {language} retrieval artifact: {path}")
        if sha256_file(path) != summary["sha256"]:
            raise RuntimeError(f"{language} retrieval artifact checksum mismatch")
        artifact = joblib.load(path)
        if artifact.get("language") != language:
            raise RuntimeError(f"Wrong language in {language} retrieval artifact")
        if artifact.get("dataset_sha256") != self.metadata["canonical_dataset_sha256"]:
            raise RuntimeError(f"Stale dataset hash in {language} retrieval artifact")
        if artifact.get("architecture") != "topic_aware_tfidf":
            raise RuntimeError(f"Wrong architecture in {language} retrieval artifact")
        if artifact.get("model_version") != self.metadata["semantic_version"]:
            raise RuntimeError(f"Wrong model version in {language} retrieval artifact")
        records = artifact.get("records", [])
        matrix = artifact.get("matrix")
        categories = artifact.get("category_names", [])
        centroids = artifact.get("category_centroids")
        if len(records) != 394 or matrix is None or matrix.shape[0] != len(records):
            raise RuntimeError(f"Invalid training matrix in {language} artifact")
        if centroids is None or centroids.shape[0] != len(categories):
            raise RuntimeError(f"Invalid category centroids in {language} artifact")
        return artifact

    def retrieve(self, question, language_code):
        language = "Twi" if language_code == "tw" else "English"
        artifact = self.models[language]
        query = artifact["vectorizer"].transform([clean_text(question)])

        raw_text = cosine_similarity(query, artifact["matrix"])[0]
        normalized_text = normalize_nonnegative(raw_text)
        raw_categories = cosine_similarity(query, artifact["category_centroids"])[0]
        normalized_categories = normalize_nonnegative(raw_categories)
        category_positions = {
            category: index
            for index, category in enumerate(artifact["category_names"])
        }
        raw_topic = np.asarray([
            raw_categories[category_positions[record["category"]]]
            for record in artifact["records"]
        ])
        normalized_topic = np.asarray([
            normalized_categories[category_positions[record["category"]]]
            for record in artifact["records"]
        ])

        config = artifact["configuration"]
        weights = config["weights"]
        final_scores = (
            weights["tfidf"] * normalized_text
            + weights["topic"] * normalized_topic
        )
        ranked = np.argsort(final_scores)[::-1]
        top_indices = ranked[:3]
        best_index = int(top_indices[0])
        second_index = int(top_indices[1])
        margin = float(final_scores[best_index] - final_scores[second_index])
        max_raw_text = float(raw_text.max())
        max_raw_topic = float(raw_categories.max())

        domain = config["domain_detection"][language]
        domain_score = float(
            domain["text_weight"] * max_raw_text
            + domain["topic_weight"] * max_raw_topic
        )
        agricultural = domain_score >= domain["threshold"]
        exact_training_match = max_raw_text >= 1.0 - 1e-12
        answer_threshold = config["answer_confidence"]["threshold"]
        if not agricultural:
            state = "C"
        elif exact_training_match or margin >= answer_threshold:
            state = "A"
        else:
            state = "B"

        candidates = []
        for rank, index in enumerate(top_indices, start=1):
            record = artifact["records"][int(index)]
            candidates.append({
                "rank": rank,
                "id": record["id"],
                "category": record["category"],
                "question": record["question"],
                "answer": record["answer"],
                "raw_tfidf_similarity": float(raw_text[index]),
                "normalized_tfidf_score": float(normalized_text[index]),
                "raw_topic_relevance": float(raw_topic[index]),
                "normalized_topic_score": float(normalized_topic[index]),
                "final_score": float(final_scores[index]),
            })

        return {
            "language": language,
            "state": state,
            "domain_score": domain_score,
            "domain_threshold": domain["threshold"],
            "answer_margin": margin,
            "answer_threshold": answer_threshold,
            "exact_training_match": exact_training_match,
            "candidates": candidates,
        }
