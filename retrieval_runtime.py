"""Load and run the validated AgriBotGH retrieval model without retraining."""

import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

from query_normalization import normalize_query
from retrieval_signals import (
    build_term_coverage_context,
    normalize_question_identity,
    substantive_query_term_count,
    weighted_query_term_coverage,
)
from retrieval_semantics import (
    entity_compatibility,
    expand_semantic_text,
    extract_entities,
    has_agricultural_intent,
)


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
        semantic_matrix = artifact.get("semantic_matrix")
        expected_records = self.metadata.get(
            "production_index_records", self.metadata["training_records"]
        )
        if (
            len(records) != expected_records
            or matrix is None
            or matrix.shape[0] != len(records)
        ):
            raise RuntimeError(f"Invalid training matrix in {language} artifact")
        if centroids is None or centroids.shape[0] != len(categories):
            raise RuntimeError(f"Invalid category centroids in {language} artifact")
        if artifact.get("configuration", {}).get("semantic_fallback") and (
            artifact.get("semantic_vectorizer") is None
            or semantic_matrix is None
            or semantic_matrix.shape[0] != len(records)
            or len(artifact.get("record_entities", [])) != len(records)
        ):
            raise RuntimeError(f"Invalid semantic fallback index in {language} artifact")
        return self.prepare_artifact(artifact, language)

    @staticmethod
    def prepare_artifact(artifact, language):
        """Attach deterministic runtime indexes that are not serialized."""
        identities = {}
        normalized_questions = []
        for index, record in enumerate(artifact["records"]):
            normalized = normalize_query(record["question"], language)
            normalized_questions.append(normalized)
            identity = normalize_question_identity(record["question"], language)
            if identity in identities:
                raise RuntimeError(
                    f"Duplicate normalized {language} question identity: {identity}"
                )
            identities[identity] = index
        artifact["_question_identity_index"] = identities
        artifact["_term_coverage_context"] = build_term_coverage_context(
            artifact["vectorizer"], normalized_questions, language
        )
        if "semantic_vectorizer" not in artifact:
            artifact["semantic_vectorizer"] = artifact["vectorizer"]
            artifact["semantic_matrix"] = artifact["matrix"]
        if "record_entities" not in artifact:
            artifact["record_entities"] = [
                sorted(extract_entities(record["question"], language))
                for record in artifact["records"]
            ]
        return artifact

    def retrieve(self, question, language_code):
        language = "Twi" if language_code == "tw" else "English"
        artifact = self.models[language]
        normalized_query = normalize_query(question, language)
        query = artifact["vectorizer"].transform([normalized_query])

        raw_text = cosine_similarity(query, artifact["matrix"])[0]
        term_coverage = weighted_query_term_coverage(
            normalized_query, artifact["_term_coverage_context"]
        )
        substantive_terms = substantive_query_term_count(
            normalized_query, artifact["_term_coverage_context"]
        )
        semantic_query = artifact["semantic_vectorizer"].transform([
            expand_semantic_text(normalized_query, language)
        ])
        raw_semantic = cosine_similarity(
            semantic_query, artifact["semantic_matrix"]
        )[0]
        query_entities = extract_entities(normalized_query, language)
        entity_compatibilities = np.asarray([
            entity_compatibility(query_entities, set(candidate_entities))
            for candidate_entities in artifact["record_entities"]
        ])
        semantic_scores = raw_semantic * (0.2 + 0.8 * entity_compatibilities)
        semantic_ranked = np.argsort(semantic_scores)[::-1]
        semantic_best_index = int(semantic_ranked[0])
        semantic_second_index = int(semantic_ranked[1])
        semantic_margin = float(
            semantic_scores[semantic_best_index]
            - semantic_scores[semantic_second_index]
        )
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
        # Normalized dataset identity is the strongest retrieval level. It is
        # still an indexed-record lookup, so answer mapping cannot drift.
        identity = normalize_question_identity(question, language)
        exact_index = artifact["_question_identity_index"].get(identity)
        normalized_exact_match = exact_index is not None
        if normalized_exact_match:
            exact_index = int(exact_index)
            ranked = np.concatenate((
                np.asarray([exact_index]),
                ranked[ranked != exact_index],
            ))
        top_indices = ranked[:3]
        best_index = int(top_indices[0])
        second_index = int(top_indices[1])
        margin = float(final_scores[best_index] - final_scores[second_index])
        raw_similarity_margin = float(raw_text[best_index] - raw_text[second_index])
        max_raw_text = float(raw_text.max())
        max_raw_topic = float(raw_categories.max())

        domain = config["domain_detection"][language]
        domain_score = float(
            domain["text_weight"] * max_raw_text
            + domain["topic_weight"] * max_raw_topic
        )
        agricultural = domain_score >= domain["threshold"]
        exact_training_match = normalized_exact_match
        base_candidate_entities = set(artifact["record_entities"][best_index])
        base_specificity_safe = not (
            (not query_entities and base_candidate_entities)
            or (
                query_entities and base_candidate_entities
                and not query_entities & base_candidate_entities
            )
        )
        semantic_candidate_entities = set(
            artifact["record_entities"][semantic_best_index]
        )
        semantic_specificity_safe = not (
            (not query_entities and semantic_candidate_entities)
            or (
                query_entities and semantic_candidate_entities
                and not query_entities & semantic_candidate_entities
            )
        )
        confidence = config["answer_confidence"]
        answer_threshold = confidence.get("threshold")
        similarity_threshold = confidence.get("similarity_threshold")
        minimum_raw_margin = confidence.get("minimum_margin")
        if similarity_threshold is None:
            base_confident_answer = margin >= answer_threshold
        else:
            base_confident_answer = (
                float(raw_text[best_index]) >= similarity_threshold
                and raw_similarity_margin >= minimum_raw_margin
            )
        supplemental = confidence.get("supplemental_acceptance")
        supplemental_confident_answer = bool(
            supplemental
            and float(raw_text[best_index])
                >= supplemental["similarity_threshold"]
            and float(term_coverage[best_index])
                >= supplemental["term_coverage_threshold"]
            and raw_similarity_margin >= supplemental["minimum_margin"]
            and substantive_terms >= supplemental["minimum_substantive_terms"]
        )
        semantic_config = config.get("semantic_fallback", {}).get(
            "languages", {}
        ).get(language)
        semantic_confident_answer = bool(
            semantic_config
            and semantic_specificity_safe
            and float(semantic_scores[semantic_best_index])
                >= semantic_config["retrieval_score_threshold"]
            and semantic_margin >= semantic_config["minimum_margin"]
        )
        agricultural_intent = has_agricultural_intent(normalized_query, language)
        agricultural_route = agricultural or agricultural_intent
        if not agricultural_route:
            state = "C"
            match_level = "off_topic"
        elif exact_training_match:
            state = "A"
            match_level = "normalized_exact"
        elif base_confident_answer and base_specificity_safe:
            state = "A"
            match_level = "strong_similarity"
        elif supplemental_confident_answer and base_specificity_safe:
            state = "A"
            match_level = "calibrated_term_coverage"
        elif semantic_confident_answer:
            state = "A"
            match_level = "semantic_fallback"
            top_indices = semantic_ranked[:3]
            best_index = int(top_indices[0])
            second_index = int(top_indices[1])
            margin = semantic_margin
        else:
            state = "B"
            match_level = "agricultural_uncertain"
            # Even when evidence is insufficient to answer, use a compatible
            # semantic ranking to offer more relevant clarification choices.
            if (
                semantic_specificity_safe
                and float(semantic_scores[semantic_best_index]) >= 0.20
            ):
                top_indices = semantic_ranked[:3]
                best_index = int(top_indices[0])
                second_index = int(top_indices[1])
                margin = semantic_margin
                match_level = "semantic_suggestion"

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
                "weighted_query_term_coverage": float(term_coverage[index]),
                "semantic_similarity": float(raw_semantic[index]),
                "semantic_retrieval_score": float(semantic_scores[index]),
                "entity_compatibility": float(entity_compatibilities[index]),
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
            "raw_similarity_margin": raw_similarity_margin,
            "similarity_threshold": similarity_threshold,
            "minimum_raw_margin": minimum_raw_margin,
            "exact_training_match": exact_training_match,
            "normalized_exact_match": normalized_exact_match,
            "substantive_query_terms": substantive_terms,
            "supplemental_confident_answer": supplemental_confident_answer,
            "semantic_confident_answer": semantic_confident_answer,
            "semantic_margin": semantic_margin,
            "entity_specificity_safe": (
                semantic_specificity_safe
                if match_level == "semantic_fallback"
                else base_specificity_safe
            ),
            "agricultural_intent": agricultural_intent,
            "match_level": match_level,
            "candidates": candidates,
        }

    def debug_retrieve(self, question, language_code):
        """Return development diagnostics; Flask never exposes this method."""
        result = self.retrieve(question, language_code)
        language = "Twi" if language_code == "tw" else "English"
        return {
            "original_query": question,
            "normalized_query": normalize_query(question, language),
            "language": result["language"],
            "candidates": result["candidates"],
            "domain_score": result["domain_score"],
            "raw_similarity_margin": result["raw_similarity_margin"],
            "similarity_threshold": result["similarity_threshold"],
            "minimum_raw_margin": result["minimum_raw_margin"],
            "match_level": result["match_level"],
            "normalized_exact_match": result["normalized_exact_match"],
            "substantive_query_terms": result["substantive_query_terms"],
            "decision": "ACCEPTED" if result["state"] == "A" else "REJECTED",
            "state": result["state"],
        }
