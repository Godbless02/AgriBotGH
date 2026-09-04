"""Final validated training pipeline for AgriBotGH.

This script validates the sole canonical dataset, creates/verifies deterministic
splits, trains the selected topic-aware TF-IDF architecture, evaluates it on
the manually curated validation gold standard, and atomically saves a new
versioned model bundle. Existing model versions are never overwritten and a
new bundle is not activated unless ``--activate`` is explicitly supplied.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
import random
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

from activate_model import activate_version
from build_retrieval_artifacts import (
    build_language_artifact,
    semantic_sha256,
    sha256_file,
    validate_inputs,
    write_json,
)
from experiment_tfidf import CONFIGURATIONS
from query_normalization import normalize_query
from validate_dataset import validate_dataset


BASE_DIR = Path(__file__).resolve().parent
DATASET_PATH = BASE_DIR / "data" / "agribotgh_dataset_bilingual_563.json"
SPLIT_DIR = BASE_DIR / "data" / "splits"
GOLD_PATH = BASE_DIR / "data" / "evaluation" / "gold_standard.json"
OUTPUT_ROOT = BASE_DIR / "models" / "production"

HYBRID_CONFIG_PATH = BASE_DIR / "models" / "hybrid_retrieval_config.json"
THRESHOLD_CONFIG_PATH = BASE_DIR / "models" / "confidence_threshold_config.json"
ROUTER_CONFIG_PATH = BASE_DIR / "models" / "off_topic_config.json"

DEFAULT_VERSION = "1.3.1"
RANDOM_SEED = 42
TRAIN_RATIO = 0.70
VALIDATION_RATIO = 0.15
TOP_K = 3
ROBUSTNESS_REPORT_PATH = BASE_DIR / "models" / "retrieval_robustness_experiments.json"
HYBRID_SIGNAL_REPORT_PATH = BASE_DIR / "models" / "retrieval_hybrid_signal_experiments.json"
SEMANTIC_FALLBACK_REPORT_PATH = BASE_DIR / "models" / "semantic_fallback_v2_evaluation.json"
PRODUCTION_SIMILARITY_THRESHOLD = 0.50
PRODUCTION_MARGIN_THRESHOLD = 0.05
SEMANTIC_VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as source:
        return json.load(source)


def display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(BASE_DIR).as_posix()
    except ValueError:
        return str(path.resolve())


def deterministic_split(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    shuffled = records.copy()
    random.Random(RANDOM_SEED).shuffle(shuffled)
    train_end = int(len(shuffled) * TRAIN_RATIO)
    validation_end = train_end + int(len(shuffled) * VALIDATION_RATIO)
    return {
        "train": shuffled[:train_end],
        "validation": shuffled[train_end:validation_end],
        "test": shuffled[validation_end:],
    }


def ensure_split_files(
    splits: dict[str, list[dict[str, Any]]], split_dir: Path
) -> dict[str, Path]:
    """Create missing deterministic splits; refuse to replace conflicting ones."""

    split_dir.mkdir(parents=True, exist_ok=True)
    paths = {name: split_dir / f"{name}.json" for name in splits}
    for name, path in paths.items():
        if path.exists():
            if load_json(path) != splits[name]:
                raise RuntimeError(
                    f"Existing {name} split is not the deterministic seed-{RANDOM_SEED} split: {path}"
                )
            continue
        write_json(path, splits[name])
    return paths


def validate_gold_standard(
    gold: Any,
    splits: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(gold, dict) or not isinstance(gold.get("entries"), list):
        raise ValueError("Gold standard must contain an entries array")

    validation_ids = {record["id"] for record in splits["validation"]}
    training_ids = {record["id"] for record in splits["train"]}
    expected_per_language = len(splits["validation"])
    if gold.get("validation_records") != expected_per_language:
        raise ValueError("Gold-standard validation count does not match the generated split")

    by_language: dict[str, list[dict[str, Any]]] = {}
    for language in ("English", "Twi"):
        entries = [entry for entry in gold["entries"] if entry.get("language") == language]
        if len(entries) != expected_per_language:
            raise ValueError(f"Expected {expected_per_language} {language} gold entries")
        entry_ids = [entry.get("validation_id") for entry in entries]
        if len(set(entry_ids)) != len(entry_ids) or set(entry_ids) != validation_ids:
            raise ValueError(f"{language} gold entries do not map one-to-one to validation IDs")
        for entry in entries:
            expected = entry.get("expected_training_record")
            if entry.get("answerable"):
                if expected not in training_ids:
                    raise ValueError(
                        f"Answerable {language} validation ID {entry.get('validation_id')} "
                        "does not reference a training record"
                    )
            elif expected is not None:
                raise ValueError(
                    f"Unsupported {language} validation ID {entry.get('validation_id')} "
                    "must not force an expected training record"
                )
        by_language[language] = entries
    return by_language


def normalize_nonnegative(scores: np.ndarray) -> np.ndarray:
    clipped = np.maximum(scores, 0.0)
    maximum = float(clipped.max()) if clipped.size else 0.0
    return clipped / maximum if maximum > 0.0 else np.zeros_like(clipped)


def safe_rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def evaluate_language(
    artifact: dict[str, Any],
    gold_entries: list[dict[str, Any]],
    weights: dict[str, float],
) -> dict[str, Any]:
    records = artifact["records"]
    training_ids = [record["id"] for record in records]
    categories = [record["category"] for record in records]
    category_positions = {
        category: position for position, category in enumerate(artifact["category_names"])
    }
    results = []

    for gold in gold_entries:
        query = artifact["vectorizer"].transform([
            normalize_query(gold["question"], artifact["language"])
        ])
        raw_text_scores = cosine_similarity(query, artifact["matrix"])[0]
        text_scores = normalize_nonnegative(raw_text_scores)
        raw_category_scores = cosine_similarity(query, artifact["category_centroids"])[0]
        category_scores = normalize_nonnegative(raw_category_scores)
        row_topic_scores = np.asarray(
            [category_scores[category_positions[category]] for category in categories]
        )
        final_scores = (
            weights["tfidf"] * text_scores
            + weights["topic"] * row_topic_scores
        )
        indices = np.argsort(final_scores)[::-1][:TOP_K]
        candidate_ids = [training_ids[index] for index in indices]
        expected = gold["expected_training_record"]
        top_1_correct = bool(gold["answerable"] and candidate_ids[0] == expected)
        top_3_correct = bool(gold["answerable"] and expected in candidate_ids)
        margin = float(final_scores[indices[0]] - final_scores[indices[1]])
        results.append(
            {
                "validation_id": gold["validation_id"],
                "answerable": gold["answerable"],
                "expected_training_record": expected,
                "top_1_id": candidate_ids[0],
                "top_1_correct": top_1_correct,
                "top_3_correct": top_3_correct,
                "top_1_category_match": categories[indices[0]] == gold["category"],
                "top_1_score": float(final_scores[indices[0]]),
                "score_margin": margin,
            }
        )

    total = len(results)
    answerable = sum(result["answerable"] for result in results)
    top_1_hits = sum(result["top_1_correct"] for result in results)
    top_3_hits = sum(result["top_3_correct"] for result in results)
    return {
        "metrics": {
            "total_cases": total,
            "answerable_cases": answerable,
            "unsupported_cases": total - answerable,
            "top_1_correct": top_1_hits,
            "top_3_correct": top_3_hits,
            "top_1_accuracy": safe_rate(top_1_hits, answerable),
            "top_3_accuracy": safe_rate(top_3_hits, answerable),
            "precision": safe_rate(top_1_hits, total),
            "coverage": 1.0 if total else 0.0,
            "category_match_rate": safe_rate(
                sum(result["top_1_category_match"] for result in results), total
            ),
            "average_top_1_score": float(
                np.mean([result["top_1_score"] for result in results])
            ) if results else 0.0,
            "average_score_margin": float(
                np.mean([result["score_margin"] for result in results])
            ) if results else 0.0,
        },
        "results": results,
    }


def build_retrieval_config(
    hybrid: dict[str, Any], threshold: dict[str, Any], router: dict[str, Any],
    supplemental: dict[str, Any], semantic_fallback: dict[str, Any]
) -> dict[str, Any]:
    return {
        "architecture": "topic_aware_tfidf",
        "weights": hybrid["weights"],
        "score_normalization": hybrid["score_normalization"],
        "tfidf_configuration": "C_word_and_character",
        "vectorizer": CONFIGURATIONS["C_word_and_character"],
        "answer_confidence": {
            "signal": "raw_tfidf_similarity_with_raw_margin",
            "similarity_threshold": PRODUCTION_SIMILARITY_THRESHOLD,
            "minimum_margin": PRODUCTION_MARGIN_THRESHOLD,
            "exact_match_override": "normalized dataset-question identity lookup",
            "source_report": "models/retrieval_robustness_experiments.json",
            "supplemental_acceptance": {
                "signal": "idf_weighted_substantive_query_term_coverage",
                "similarity_threshold": supplemental["supplemental_similarity_threshold"],
                "term_coverage_threshold": supplemental["supplemental_term_coverage_threshold"],
                "minimum_margin": supplemental["supplemental_minimum_margin"],
                "minimum_substantive_terms": supplemental["supplemental_minimum_substantive_terms"],
                "source_report": "models/retrieval_hybrid_signal_experiments.json",
            },
        },
        "domain_detection": router["domain_detection"],
        "semantic_fallback": {
            "signal": "semantic_expansion_tfidf_with_entity_compatibility",
            "languages": {
                language: {
                    "retrieval_score_threshold": selection["semantic_threshold"],
                    "minimum_margin": selection["semantic_minimum_margin"],
                }
                for language, selection in semantic_fallback.items()
            },
            "require_entity_specificity_compatibility": True,
            "source_report": "models/semantic_fallback_v2_evaluation.json",
        },
        "states": router["states"],
    }


def train_final_model(
    *,
    version: str = DEFAULT_VERSION,
    dataset_path: Path = DATASET_PATH,
    split_dir: Path = SPLIT_DIR,
    gold_path: Path = GOLD_PATH,
    output_root: Path = OUTPUT_ROOT,
    activate: bool = False,
) -> Path:
    if not SEMANTIC_VERSION_RE.fullmatch(version):
        raise ValueError("Model version must use semantic versioning such as 1.0.2")

    dataset_path = Path(dataset_path).resolve()
    split_dir = Path(split_dir).resolve()
    gold_path = Path(gold_path).resolve()
    output_root = Path(output_root).resolve()
    version_dir = output_root / version
    staging_dir = output_root / f".{version}.training"
    if version_dir.exists():
        raise FileExistsError(f"Model version already exists and will not be overwritten: {version_dir}")
    if staging_dir.exists():
        raise FileExistsError(f"Incomplete training directory already exists: {staging_dir}")

    quality = validate_dataset(dataset_path)
    if quality["blocking_error_count"]:
        codes = ", ".join(error["code"] for error in quality["errors"])
        raise ValueError(f"Dataset validation failed before training: {codes}")

    canonical = load_json(dataset_path)
    splits = deterministic_split(canonical)
    split_paths = ensure_split_files(splits, split_dir)
    gold_by_language = validate_gold_standard(load_json(gold_path), splits)

    hybrid = load_json(HYBRID_CONFIG_PATH)
    threshold = load_json(THRESHOLD_CONFIG_PATH)
    router = load_json(ROUTER_CONFIG_PATH)
    robustness = load_json(ROBUSTNESS_REPORT_PATH)
    hybrid_signal = load_json(HYBRID_SIGNAL_REPORT_PATH)
    semantic_fallback_report = load_json(SEMANTIC_FALLBACK_REPORT_PATH)
    validate_inputs(canonical, splits, hybrid, threshold, router)
    selected_experiment = robustness["experiments"]["C_word_and_character"]
    selected_threshold = next(
        item for item in selected_experiment["thresholds"]
        if item["threshold"] == PRODUCTION_SIMILARITY_THRESHOLD
    )
    if selected_threshold["negative_false_accepts"] != 0:
        raise RuntimeError("Selected production threshold has negative false accepts")
    supplemental = hybrid_signal["supplemental_acceptance"]["selection"]
    if not supplemental or supplemental["negative_false_accepts"] != 0:
        raise RuntimeError("Supplemental acceptance gate was not safely validated")
    if supplemental["incorrect_accepted_positive"] != 0:
        raise RuntimeError("Supplemental acceptance gate has incorrect positive accepts")
    if hybrid_signal["ranking_decision"]["selected_coverage_weight"] != 0.0:
        raise RuntimeError("Production ranking must remain the validated TF-IDF ranking")
    semantic_fallback = semantic_fallback_report["selection_by_language"]
    for language, selection in semantic_fallback.items():
        if not selection or any(selection[key] for key in (
            "incorrect_positive_answers", "negative_false_accepts", "ambiguous_false_answers"
        )):
            raise RuntimeError(f"Unsafe semantic fallback selection for {language}")
    retrieval_config = build_retrieval_config(
        hybrid, threshold, router, supplemental, semantic_fallback
    )

    output_root.mkdir(parents=True, exist_ok=True)
    staging_dir.mkdir()
    built_at = datetime.now(timezone.utc).isoformat()
    display_name = f"AgriBotGH Retrieval Model v{version}"
    dataset_hash = sha256_file(dataset_path)
    write_json(staging_dir / "retrieval_config.json", retrieval_config)
    write_json(staging_dir / "dataset_validation.json", quality)

    artifacts = {}
    evaluation_artifacts = {}
    artifact_summaries = {}
    for language, filename in (("English", "english.joblib"), ("Twi", "twi.joblib")):
        evaluation_artifact = build_language_artifact(
            splits["train"], language, dataset_hash, retrieval_config,
            normalizer=normalize_query,
        )
        artifact = build_language_artifact(
            canonical, language, dataset_hash, retrieval_config,
            normalizer=normalize_query,
        )
        artifact["model_version"] = version
        artifact["model_display_name"] = display_name
        artifact_path = staging_dir / filename
        joblib.dump(artifact, artifact_path)
        artifacts[language] = artifact
        evaluation_artifacts[language] = evaluation_artifact
        artifact_summaries[language] = {
            "file": filename,
            "sha256": sha256_file(artifact_path),
            "semantic_sha256": semantic_sha256(artifact),
            "bytes": artifact_path.stat().st_size,
            "features": int(artifact["matrix"].shape[1]),
            "semantic_features": int(artifact["semantic_matrix"].shape[1]),
            "categories": len(artifact["category_names"]),
            "training_records": artifact["training_records"],
        }

    validation = {
        language: evaluate_language(
            evaluation_artifacts[language], gold_by_language[language], hybrid["weights"]
        )
        for language in ("English", "Twi")
    }
    evaluation_summary = {
        "evaluation_method": "Fresh topic-aware TF-IDF retrieval against manually curated validation gold mappings.",
        "top_k": TOP_K,
        "retrieval_selection": hybrid["selection_metrics"],
        "languages": validation,
        "threshold_validation": {
            **selected_threshold,
            "response_precision": 1.0,
            "coverage": selected_threshold["positive_coverage"],
            "evaluation_set": (
                f"{selected_experiment['paraphrase']['cases']} reviewed paraphrases "
                f"and {selected_experiment['negative_cases']} negative controls"
            ),
        },
        "router_test": router["test_metrics"],
        "limitations": [
            "The reviewed paraphrase benchmark is small and should be expanded with real farmer queries.",
            "Dataset validation passed with documented native-Twi and domain-expert review warnings.",
            "The held-out router test returned no automatic State-A answers; exact canonical questions use the deterministic exact-match path.",
        ],
    }
    write_json(staging_dir / "evaluation_summary.json", evaluation_summary)

    source_files = (
        BASE_DIR / "train_model.py",
        BASE_DIR / "validate_dataset.py",
        BASE_DIR / "build_retrieval_artifacts.py",
        BASE_DIR / "retrieval_runtime.py",
        BASE_DIR / "experiment_tfidf.py",
        BASE_DIR / "query_normalization.py",
        BASE_DIR / "evaluate_retrieval_robustness.py",
        BASE_DIR / "evaluate_hybrid_retrieval_signal.py",
        BASE_DIR / "retrieval_signals.py",
        BASE_DIR / "retrieval_semantics.py",
        BASE_DIR / "evaluate_semantic_fallback_v2.py",
    )
    metadata = {
        "metadata_schema_version": 1,
        "model_id": "agribotgh-retrieval",
        "model_version": display_name,
        "semantic_version": version,
        "built_at_utc": built_at,
        "canonical_dataset": display_path(dataset_path),
        "canonical_dataset_records": len(canonical),
        "canonical_dataset_sha256": dataset_hash,
        "dataset_validation": {
            "file": "dataset_validation.json",
            "sha256": sha256_file(staging_dir / "dataset_validation.json"),
            "status": quality["status"],
            "blocking_errors": quality["blocking_error_count"],
            "review_warnings": quality["review_warning_count"],
        },
        "splits": {
            name: {
                "file": display_path(split_paths[name]),
                "records": len(splits[name]),
                "sha256": sha256_file(split_paths[name]),
            }
            for name in ("train", "validation", "test")
        },
        "training_records": len(canonical),
        "selection_training_records": len(splits["train"]),
        "production_index_records": len(canonical),
        "validation_records": len(splits["validation"]),
        "test_records": len(splits["test"]),
        "training_random_seed": RANDOM_SEED,
        "build_script": "train_model.py",
        "build_command": (
            f".\\agribot_env\\Scripts\\python.exe train_model.py --version {version}"
        ),
        "retrieval_architecture": "topic_aware_tfidf",
        "configuration_file": "retrieval_config.json",
        "configuration_sha256": sha256_file(staging_dir / "retrieval_config.json"),
        "evaluation_file": "evaluation_summary.json",
        "evaluation_sha256": sha256_file(staging_dir / "evaluation_summary.json"),
        "evaluation": evaluation_summary,
        "robustness_report": {
            "file": display_path(ROBUSTNESS_REPORT_PATH),
            "sha256": sha256_file(ROBUSTNESS_REPORT_PATH),
            "paraphrase_top_1_accuracy": selected_experiment["paraphrase"]["top_1_accuracy"],
            "paraphrase_top_3_accuracy": selected_experiment["paraphrase"]["top_3_accuracy"],
        },
        "hybrid_signal_report": {
            "file": display_path(HYBRID_SIGNAL_REPORT_PATH),
            "sha256": sha256_file(HYBRID_SIGNAL_REPORT_PATH),
            "ranking_coverage_weight": hybrid_signal["ranking_decision"]["selected_coverage_weight"],
            "supplemental_gate": supplemental,
        },
        "semantic_fallback_report": {
            "file": display_path(SEMANTIC_FALLBACK_REPORT_PATH),
            "sha256": sha256_file(SEMANTIC_FALLBACK_REPORT_PATH),
            "selection_by_language": semantic_fallback,
        },
        "artifacts": artifact_summaries,
        "software": {
            "python": platform.python_version(),
            "numpy": importlib.metadata.version("numpy"),
            "scikit_learn": importlib.metadata.version("scikit-learn"),
            "joblib": importlib.metadata.version("joblib"),
        },
        "source_sha256": {
            display_path(path): sha256_file(path) for path in source_files
        },
        "activation_status": "active" if activate else "candidate_not_activated",
    }
    write_json(staging_dir / "model_metadata.json", metadata)
    staging_dir.replace(version_dir)

    if activate:
        activate_version(BASE_DIR, output_root, dataset_path, version)

    print("\n" + "=" * 64)
    print(f"TRAINING COMPLETE: {display_name}")
    print("=" * 64)
    print(f"Dataset validation: {quality['status']} (0 blockers)")
    print(
        f"Split: train={len(splits['train'])}, validation={len(splits['validation'])}, "
        f"test={len(splits['test'])}"
    )
    for language in ("English", "Twi"):
        metrics = validation[language]["metrics"]
        print(
            f"{language}: top-1={metrics['top_1_accuracy']:.2%}, "
            f"top-3={metrics['top_3_accuracy']:.2%}, "
            f"precision={metrics['precision']:.2%}, "
            f"category-match={metrics['category_match_rate']:.2%}"
        )
    print(f"Saved: {version_dir}")
    print("Activation: active" if activate else "Activation: unchanged (candidate only)")
    return version_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default=DEFAULT_VERSION, help="New semantic version")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    parser.add_argument(
        "--activate",
        action="store_true",
        help="Activate only after the complete bundle has been saved and checksum-validated.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    train_final_model(version=args.version, output_root=args.output_root, activate=args.activate)


if __name__ == "__main__":
    main()
