"""Build a versioned, reproducible AgriBotGH production retrieval bundle."""

import argparse
import hashlib
import importlib.metadata
import json
import platform
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np

from experiment_tfidf import CONFIGURATIONS, build_vectorizer, clean_text


BASE_DIR = Path(__file__).resolve().parent
MODEL_VERSION = "1.0.1"
MODEL_DISPLAY_NAME = "AgriBotGH Retrieval Model v1.0.1"
DATA_FILE = BASE_DIR / "data" / "agribotgh_dataset_bilingual_563.json"
SPLIT_FILES = {
    "train": BASE_DIR / "data" / "splits" / "train.json",
    "validation": BASE_DIR / "data" / "splits" / "validation.json",
    "test": BASE_DIR / "data" / "splits" / "test.json",
}
HYBRID_CONFIG_FILE = BASE_DIR / "models" / "hybrid_retrieval_config.json"
THRESHOLD_CONFIG_FILE = BASE_DIR / "models" / "confidence_threshold_config.json"
OFF_TOPIC_CONFIG_FILE = BASE_DIR / "models" / "off_topic_config.json"
HYBRID_REPORT_FILE = BASE_DIR / "models" / "hybrid_experiments.json"
SOURCE_FILES = (
    BASE_DIR / "build_retrieval_artifacts.py",
    BASE_DIR / "retrieval_runtime.py",
    BASE_DIR / "experiment_tfidf.py",
)


def load_json(path):
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def semantic_sha256(artifact):
    """Hash learned model content independently of joblib serialization bytes."""
    digest = hashlib.sha256()
    stable_values = {
        "language": artifact["language"],
        "dataset_sha256": artifact["dataset_sha256"],
        "architecture": artifact["architecture"],
        "configuration": artifact["configuration"],
        "category_names": artifact["category_names"],
        "records": artifact["records"],
    }
    digest.update(
        json.dumps(
            stable_values, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    )
    features = artifact["vectorizer"].get_feature_names_out()
    digest.update("\n".join(features.tolist()).encode("utf-8"))
    matrix = artifact["matrix"].tocsr(copy=True)
    matrix.sort_indices()
    for value in (matrix.shape, matrix.data, matrix.indices, matrix.indptr):
        if isinstance(value, tuple):
            digest.update(json.dumps(value).encode("ascii"))
        else:
            digest.update(value.dtype.str.encode("ascii"))
            digest.update(value.tobytes(order="C"))
    centroids = np.ascontiguousarray(artifact["category_centroids"])
    digest.update(centroids.dtype.str.encode("ascii"))
    digest.update(json.dumps(centroids.shape).encode("ascii"))
    digest.update(centroids.tobytes(order="C"))
    return digest.hexdigest()


def validate_inputs(canonical, splits, hybrid, threshold, router):
    required = (
        "id", "category", "question_en", "answer_en", "question_twi", "answer_twi"
    )
    if len(canonical) != 563:
        raise ValueError(f"Expected 563 canonical records, found {len(canonical)}")
    canonical_by_id = {record["id"]: record for record in canonical}
    if len(canonical_by_id) != len(canonical):
        raise ValueError("Canonical dataset IDs are not unique")
    for record in canonical:
        if any(field not in record or not str(record[field]).strip() for field in required):
            raise ValueError(f"Invalid canonical record: {record.get('id')}")

    expected_sizes = {"train": 394, "validation": 84, "test": 85}
    combined = []
    for name, records in splits.items():
        if len(records) != expected_sizes[name]:
            raise ValueError(f"Unexpected {name} split size: {len(records)}")
        combined.extend(records)
    if len({record["id"] for record in combined}) != 563:
        raise ValueError("Splits must contain every canonical ID exactly once")
    for record in combined:
        if canonical_by_id.get(record["id"]) != record:
            raise ValueError(f"Split record {record.get('id')} is not canonical")

    if hybrid.get("selected_architecture") != "topic_aware_tfidf":
        raise ValueError("Selected architecture is not topic-aware TF-IDF")
    weights = hybrid.get("weights", {})
    if weights != {"tfidf": 0.38, "embedding": 0.0, "topic": 0.62}:
        raise ValueError(f"Unexpected validated retrieval weights: {weights}")
    if threshold.get("confidence_signal") != "normalized_score_margin":
        raise ValueError("Unexpected answer confidence signal")
    if threshold.get("threshold") != 0.27:
        raise ValueError("Unexpected validated answer threshold")
    if router.get("router") != "three_state_agriculture_router":
        raise ValueError("Unexpected off-topic router configuration")
    if set(router.get("domain_detection", {})) != {"English", "Twi"}:
        raise ValueError("Domain configuration must contain English and Twi")


def build_language_artifact(train, language, dataset_hash, retrieval_config):
    question_field = "question_en" if language == "English" else "question_twi"
    answer_field = "answer_en" if language == "English" else "answer_twi"
    questions = [clean_text(record[question_field]) for record in train]
    vectorizer = build_vectorizer(CONFIGURATIONS["C_word_and_character"])
    matrix = vectorizer.fit_transform(questions)

    category_indices = defaultdict(list)
    for index, record in enumerate(train):
        category_indices[record["category"]].append(index)
    category_names = sorted(category_indices)
    centroids = np.vstack([
        np.asarray(matrix[category_indices[category]].mean(axis=0)).ravel()
        for category in category_names
    ])

    return {
        "artifact_schema_version": 1,
        "model_version": MODEL_VERSION,
        "model_display_name": MODEL_DISPLAY_NAME,
        "language": language,
        "dataset_sha256": dataset_hash,
        "training_records": len(train),
        "architecture": "topic_aware_tfidf",
        "configuration": retrieval_config,
        "question_field": question_field,
        "answer_field": answer_field,
        "vectorizer": vectorizer,
        "matrix": matrix,
        "category_names": category_names,
        "category_centroids": centroids,
        "records": [
            {
                "id": record["id"],
                "category": record["category"],
                "question": record[question_field],
                "answer": record[answer_field],
            }
            for record in train
        ],
    }


def build_bundle(output_root, activate):
    canonical = load_json(DATA_FILE)
    splits = {name: load_json(path) for name, path in SPLIT_FILES.items()}
    hybrid = load_json(HYBRID_CONFIG_FILE)
    threshold = load_json(THRESHOLD_CONFIG_FILE)
    router = load_json(OFF_TOPIC_CONFIG_FILE)
    hybrid_report = load_json(HYBRID_REPORT_FILE)
    validate_inputs(canonical, splits, hybrid, threshold, router)

    output_root = Path(output_root).resolve()
    version_dir = output_root / MODEL_VERSION
    if version_dir.exists():
        raise FileExistsError(
            f"Model version already exists and will not be overwritten: {version_dir}"
        )
    staging_dir = output_root / f".{MODEL_VERSION}.building"
    if staging_dir.exists():
        raise FileExistsError(
            f"Incomplete staging directory already exists: {staging_dir}"
        )
    staging_dir.mkdir(parents=True)

    built_at = datetime.now(timezone.utc).isoformat()
    dataset_hash = sha256_file(DATA_FILE)
    retrieval_config = {
        "architecture": "topic_aware_tfidf",
        "weights": hybrid["weights"],
        "score_normalization": hybrid["score_normalization"],
        "tfidf_configuration": "C_word_and_character",
        "vectorizer": CONFIGURATIONS["C_word_and_character"],
        "answer_confidence": router["answer_confidence"],
        "domain_detection": router["domain_detection"],
        "states": router["states"],
    }
    write_json(staging_dir / "retrieval_config.json", retrieval_config)

    evaluation_summary = {
        "retrieval_selection": hybrid["selection_metrics"],
        "languages": {
            language: hybrid_report["winner"]["languages"][language]["metrics"]
            for language in ("English", "Twi")
        },
        "threshold_validation": threshold["validation_metrics"],
        "router_test": router["test_metrics"],
        "limitations": [
            threshold["limitation"],
            "The held-out router test returned no automatic State-A answers; exact canonical questions use a deterministic exact-match path.",
            "Some unrelated hard negatives can be classified as uncertain State B instead of off-topic State C.",
        ],
    }
    write_json(staging_dir / "evaluation_summary.json", evaluation_summary)

    artifact_summaries = {}
    for language, filename in (
        ("English", "english.joblib"),
        ("Twi", "twi.joblib"),
    ):
        artifact = build_language_artifact(
            splits["train"], language, dataset_hash, retrieval_config
        )
        artifact_path = staging_dir / filename
        joblib.dump(artifact, artifact_path)
        artifact_summaries[language] = {
            "file": filename,
            "sha256": sha256_file(artifact_path),
            "semantic_sha256": semantic_sha256(artifact),
            "bytes": artifact_path.stat().st_size,
            "features": int(artifact["matrix"].shape[1]),
            "categories": len(artifact["category_names"]),
            "training_records": artifact["training_records"],
        }

    metadata = {
        "metadata_schema_version": 1,
        "model_id": "agribotgh-retrieval",
        "model_version": MODEL_DISPLAY_NAME,
        "semantic_version": MODEL_VERSION,
        "built_at_utc": built_at,
        "canonical_dataset": "data/agribotgh_dataset_bilingual_563.json",
        "canonical_dataset_records": len(canonical),
        "canonical_dataset_sha256": dataset_hash,
        "splits": {
            name: {
                "file": str(path.relative_to(BASE_DIR)).replace("\\", "/"),
                "records": len(splits[name]),
                "sha256": sha256_file(path),
            }
            for name, path in SPLIT_FILES.items()
        },
        "training_records": len(splits["train"]),
        "training_random_seed": 42,
        "build_script": "build_retrieval_artifacts.py",
        "build_command": ".\\agribot_env\\Scripts\\python.exe build_retrieval_artifacts.py",
        "retrieval_architecture": "topic_aware_tfidf",
        "configuration_file": "retrieval_config.json",
        "configuration_sha256": sha256_file(staging_dir / "retrieval_config.json"),
        "evaluation_file": "evaluation_summary.json",
        "evaluation_sha256": sha256_file(staging_dir / "evaluation_summary.json"),
        "evaluation": evaluation_summary,
        "artifacts": artifact_summaries,
        "serialization_note": (
            "The file SHA-256 protects the deployed bytes. semantic_sha256 "
            "proves reproducible learned content because joblib bytes are not "
            "guaranteed to be identical across separate Python processes."
        ),
        "software": {
            "python": platform.python_version(),
            "numpy": importlib.metadata.version("numpy"),
            "scikit_learn": importlib.metadata.version("scikit-learn"),
            "joblib": importlib.metadata.version("joblib"),
        },
        "source_sha256": {
            str(path.relative_to(BASE_DIR)).replace("\\", "/"): sha256_file(path)
            for path in SOURCE_FILES
        },
        "evaluation_sources": [
            "models/hybrid_experiments.json",
            "models/threshold_experiments.json",
            "models/off_topic_experiments.json",
        ],
    }
    write_json(staging_dir / "model_metadata.json", metadata)
    staging_dir.replace(version_dir)

    if activate:
        active_manifest = {
            "manifest_schema_version": 1,
            "active_semantic_version": MODEL_VERSION,
            "model_version": MODEL_DISPLAY_NAME,
            "metadata_file": (
                f"models/production/{MODEL_VERSION}/model_metadata.json"
            ),
            "metadata_sha256": sha256_file(version_dir / "model_metadata.json"),
            "activated_at_utc": built_at,
        }
        write_json(output_root / "active_model.json", active_manifest)

    print(f"Built: {version_dir}")
    if activate:
        print(f"Activated: {MODEL_VERSION}")
    return version_dir


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-root",
        type=Path,
        default=BASE_DIR / "models" / "production",
    )
    parser.add_argument(
        "--no-activate",
        action="store_true",
        help="Build a bundle without changing the active-model manifest.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    build_bundle(args.output_root, activate=not args.no_activate)


if __name__ == "__main__":
    main()
