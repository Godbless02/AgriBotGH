"""Create TODO 31's source-traceable final retrieval architecture comparison."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
MODEL_DIR = BASE_DIR / "models"
OUTPUT_PATH = MODEL_DIR / "final_model_comparison.json"


def load(name):
    with (MODEL_DIR / name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def metric_subset(payload):
    return {
        key: payload[key]
        for key in (
            "top_1_accuracy",
            "top_3_accuracy",
            "precision",
            "coverage",
            "category_match_rate",
        )
    }


def language_payload(source):
    return {
        language: {
            "metrics": metric_subset(payload["metrics"]),
            "cost": payload.get("cost", {}),
        }
        for language, payload in source.items()
    }


def create_comparison():
    tfidf = load("model_experiments.json")
    topic = load("topic_aware_experiments.json")
    embedding = load("embedding_experiments.json")
    hybrid = load("hybrid_experiments.json")
    active = load("production/active_model.json")
    active_version = active["active_semantic_version"]
    production_eval = load(f"production/{active_version}/evaluation_summary.json")
    production_config = load(f"production/{active_version}/retrieval_config.json")
    confidence = production_config["answer_confidence"]
    confidence_threshold = confidence.get("similarity_threshold", confidence.get("threshold"))

    baseline_source = tfidf["experiments"]["B_word_unigram_bigram"]["languages"]
    improved_source = tfidf["experiments"][tfidf["winner"]["configuration"]]["languages"]
    topic_key = f"topic_{topic['winner']['topic_weight']:.2f}"
    topic_source = topic["experiments"][topic_key]
    embedding_source = embedding["experiments"][embedding["winner"]["configuration"]]
    hybrid_source = hybrid["winner"]["languages"]

    architectures = [
        {
            "id": "baseline_tfidf",
            "name": "Baseline word TF-IDF",
            "configuration": "word unigrams and bigrams",
            "languages": language_payload(baseline_source),
            "macro": {
                "top_1_accuracy": sum(p["metrics"]["top_1_accuracy"] for p in baseline_source.values()) / 2,
                "top_3_accuracy": sum(p["metrics"]["top_3_accuracy"] for p in baseline_source.values()) / 2,
                "category_match_rate": sum(p["metrics"]["category_match_rate"] for p in baseline_source.values()) / 2,
            },
            "threshold": None,
            "weaknesses": ["Weak semantic discrimination", "Confuses similarly worded agricultural categories"],
            "computational_cost": "Lowest of the compared sparse models",
            "source": "models/model_experiments.json",
        },
        {
            "id": "improved_tfidf",
            "name": "Improved word + character TF-IDF",
            "configuration": tfidf["winner"]["configuration"],
            "languages": language_payload(improved_source),
            "macro": {
                "top_1_accuracy": tfidf["winner"]["macro_top_1_accuracy"],
                "top_3_accuracy": tfidf["winner"]["macro_top_3_accuracy"],
                "category_match_rate": tfidf["winner"]["macro_category_match_rate"],
            },
            "threshold": None,
            "weaknesses": ["Better spelling robustness but no explicit topic compatibility", "Sparse lexical matching remains paraphrase-sensitive"],
            "computational_cost": "Moderate sparse matrices; larger than baseline",
            "source": "models/model_experiments.json",
        },
        {
            "id": "topic_aware_tfidf",
            "name": "Topic-aware improved TF-IDF",
            "configuration": {"text_weight": 0.38, "topic_weight": 0.62},
            "languages": language_payload(topic_source),
            "macro": {
                "top_1_accuracy": topic["winner"]["macro_top_1_accuracy"],
                "top_3_accuracy": topic["winner"]["macro_top_3_accuracy"],
                "category_match_rate": topic["winner"]["macro_category_match_rate"],
            },
            "threshold": confidence_threshold,
            "weaknesses": ["Lexically distant paraphrases still require State B clarification", "The reviewed paraphrase benchmark needs expansion with real farmer queries"],
            "computational_cost": "Moderate CPU-only sparse retrieval; no external model download",
            "source": "models/topic_aware_experiments.json",
        },
        {
            "id": "embedding_retrieval",
            "name": "Local dense LSA embedding retrieval",
            "configuration": embedding["winner"]["configuration"],
            "languages": language_payload(embedding_source),
            "macro": {
                "top_1_accuracy": embedding["winner"]["macro_top_1_accuracy"],
                "top_3_accuracy": embedding["winner"]["macro_top_3_accuracy"],
                "category_match_rate": embedding["winner"]["macro_category_match_rate"],
            },
            "threshold": None,
            "weaknesses": ["Lower bilingual ranking accuracy than improved and topic-aware TF-IDF", "Pretrained multilingual model transfer could not be integrity-verified under host throttling"],
            "computational_cost": "Dense 256-dimensional projection plus fitting cost",
            "source": "models/embedding_experiments.json",
        },
        {
            "id": "hybrid_retrieval",
            "name": "TF-IDF + embedding + topic weight search",
            "configuration": hybrid["winner"]["weights"],
            "languages": language_payload(hybrid_source),
            "macro": {
                "top_1_accuracy": hybrid["winner"]["macro_top_1_accuracy"],
                "top_3_accuracy": hybrid["winner"]["macro_top_3_accuracy"],
                "category_match_rate": hybrid["winner"]["macro_category_match_rate"],
            },
            "threshold": confidence_threshold,
            "weaknesses": ["Best validated hybrid assigned zero weight to embeddings", "Adding an embedding component increased complexity without measured benefit"],
            "computational_cost": "Winning weights collapse to the topic-aware sparse model, avoiding dense runtime cost",
            "source": "models/hybrid_experiments.json",
        },
    ]

    selected = next(item for item in architectures if item["id"] == "topic_aware_tfidf")
    if hybrid["winner"]["weights"]["embedding"] != 0.0:
        raise RuntimeError("Hybrid winner no longer supports the selected sparse architecture")
    if production_config["weights"] != {"tfidf": 0.38, "embedding": 0.0, "topic": 0.62}:
        raise RuntimeError("Active production weights differ from the validated winner")
    if production_eval["retrieval_selection"] != {
        "macro_top_1_accuracy": selected["macro"]["top_1_accuracy"],
        "macro_top_3_accuracy": selected["macro"]["top_3_accuracy"],
        "macro_category_match_rate": selected["macro"]["category_match_rate"],
    }:
        raise RuntimeError("Production evaluation differs from the comparison winner")

    return {
        "schema_version": 1,
        "todo": 31,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "evaluation_basis": {
            "validation_records_per_language": 84,
            "gold_answerable_per_language": 18,
            "ranking_coverage_definition": "A top candidate is produced for every validation query; this is not automatic-answer coverage.",
            "threshold_note": "Thresholds were selected only after architecture selection; null means no response threshold was applied in that ranking experiment.",
        },
        "architectures": architectures,
        "selection": {
            "architecture_id": "topic_aware_tfidf",
            "active_semantic_version": active["active_semantic_version"],
            "reason": (
                "Highest validated macro top-1 and top-3 accuracy with the highest category-match rate, "
                "tied by the hybrid grid only when embedding weight is zero; practical CPU-only deployment."
            ),
            "answer_confidence_threshold": confidence_threshold,
            "answer_confidence_minimum_margin": confidence.get("minimum_margin"),
            "threshold_response_precision": production_eval["threshold_validation"]["response_precision"],
            "threshold_response_coverage": production_eval["threshold_validation"]["coverage"],
        },
    }


def main():
    report = create_comparison()
    OUTPUT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    selected = report["selection"]
    print(
        f"Selected: {selected['architecture_id']} v{selected['active_semantic_version']} "
        f"at threshold {selected['answer_confidence_threshold']}"
    )
    print(f"Compared architectures: {len(report['architectures'])}")
    print(f"Report: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
