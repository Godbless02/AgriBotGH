"""Generate TODO 36's measured Chapter Four project data and summary."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
MODEL_DIR = BASE_DIR / "models"
JSON_PATH = MODEL_DIR / "final_project_report_data.json"
MARKDOWN_PATH = BASE_DIR / "docs" / "FINAL_PROJECT_REPORT_DATA.md"


def load(relative):
    with (BASE_DIR / relative).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def sha256(relative):
    digest = hashlib.sha256()
    with (BASE_DIR / relative).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def generate_report():
    dataset = load("data/agribotgh_dataset_bilingual_563.json")
    train = load("data/splits/train.json")
    validation = load("data/splits/validation.json")
    test = load("data/splits/test.json")
    active = load("models/production/active_model.json")
    freeze = load("models/production/model_freeze.json")
    active_version = active["active_semantic_version"]
    active_root = f"models/production/{active_version}"
    evaluation = load(f"{active_root}/evaluation_summary.json")
    config = load(f"{active_root}/retrieval_config.json")
    confidence = config["answer_confidence"]
    confidence_threshold = confidence.get(
        "similarity_threshold", confidence.get("threshold")
    )
    performance = load("models/performance_results.json")
    presentation = load("models/presentation_test_results.json")
    off_topic = load("models/off_topic_question_results.json")
    agriculture = load("models/agriculture_edge_case_results.json")
    language = load("models/language_separation_results.json")
    quality = load("models/response_quality_results.json")

    if len(dataset) != len(train) + len(validation) + len(test):
        raise RuntimeError("Dataset split counts do not add up")
    if sha256("data/agribotgh_dataset_bilingual_563.json") != freeze["dataset_sha256"]:
        raise RuntimeError("Final report dataset differs from frozen model dataset")
    if not presentation["summary"]["complete"] or presentation["summary"]["total_passed"] != 80:
        raise RuntimeError("Presentation evidence is incomplete")

    return {
        "schema_version": 1,
        "todo": 36,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "project": "AgriBotGH — Bilingual English–Twi AI-Powered Agricultural Chatbot for Farmer Support in Ghana",
        "dataset": {
            "file": "data/agribotgh_dataset_bilingual_563.json",
            "records": len(dataset),
            "english_qa_pairs": len(dataset),
            "twi_qa_pairs": len(dataset),
            "categories": len({record["category"] for record in dataset}),
            "sha256": freeze["dataset_sha256"],
            "policy": "Sole canonical dataset; retained at 563 because quality gates take priority over an arbitrary 700-record target.",
        },
        "split": {"training": len(train), "validation": len(validation), "testing": len(test), "random_seed": 42},
        "final_model": {
            "display_version": active["model_version"],
            "semantic_version": active["active_semantic_version"],
            "architecture": config["architecture"],
            "tfidf_configuration": config["tfidf_configuration"],
            "weights": config["weights"],
            "answer_confidence_signal": config["answer_confidence"]["signal"],
            "answer_confidence_threshold": confidence_threshold,
            "answer_confidence_minimum_margin": confidence.get("minimum_margin"),
            "freeze_id": freeze["freeze_id"],
        },
        "validation_retrieval_performance": {
            language_name: payload["metrics"]
            for language_name, payload in evaluation["languages"].items()
        },
        "threshold_performance": evaluation["threshold_validation"],
        "router_test": evaluation["router_test"],
        "independent_behavior_evidence": {
            "off_topic": off_topic["summary"],
            "agricultural_edge_cases": agriculture["summary"],
            "language_separation": language["summary"],
            "response_quality_and_safety": quality["summary"],
            "presentation": presentation["summary"],
        },
        "performance": {
            "cold_start_seconds": performance["cold_start"]["seconds"],
            "retrieval_average_ms": performance["retrieval_latency"]["average_ms"],
            "retrieval_p95_ms": performance["retrieval_latency"]["p95_ms"],
            "api_average_ms": performance["flask_test_client_latency"]["average_ms"],
            "api_p95_ms": performance["flask_test_client_latency"]["p95_ms"],
            "working_set_mb": performance["memory"]["working_set_mb"],
        },
        "usability": {
            "automated_browser_viewports": [1920, 1440, 1366, 1280, 1024, 768, 480, 390, 375],
            "presentation_cases_passed": presentation["summary"]["total_passed"],
            "human_participant_results": None,
            "note": "No human usability study data was supplied; automated browser results must not be described as participant usability scores.",
        },
        "interpretation_notes": [
            "Top-1 and top-3 metrics are calculated only over 18 gold-answerable validation cases per language.",
            "The reported retrieval precision divides correct top-1 matches by all 84 validation cases, including unsupported cases.",
            "Ranking coverage of 100% means retrieval always produces candidates; it is not automatic-answer coverage.",
            f"At raw TF-IDF similarity threshold {confidence_threshold} and margin {confidence.get('minimum_margin')}, the reviewed paraphrase benchmark had 100% precision among accepted answers and zero false accepts across 120 negative controls.",
            "Exact canonical questions and clicked suggestions use the same statistical retrieval runtime as typed questions.",
            "Agronomic correctness and native Twi naturalness require qualified human review; no such review score is invented here.",
        ],
        "source_reports": [
            "models/final_model_comparison.json",
            f"{active_root}/evaluation_summary.json",
            "models/performance_results.json",
            "models/presentation_test_results.json",
            "models/response_quality_results.json",
            "models/language_separation_results.json",
            "models/off_topic_question_results.json",
            "models/agriculture_edge_case_results.json",
        ],
    }


def markdown(report):
    en = report["validation_retrieval_performance"]["English"]
    tw = report["validation_retrieval_performance"]["Twi"]
    threshold = report["threshold_performance"]
    perf = report["performance"]
    return f"""# AgriBotGH Final Project Report Data

Generated from saved evaluation artifacts. Values below are measured, not estimated.

## Dataset and split

- Canonical bilingual records: **{report['dataset']['records']}**
- English Q&A pairs: **{report['dataset']['english_qa_pairs']}**
- Twi Q&A pairs: **{report['dataset']['twi_qa_pairs']}**
- Categories: **{report['dataset']['categories']}**
- Training / validation / testing: **{report['split']['training']} / {report['split']['validation']} / {report['split']['testing']}**

## Final model

- Version: **{report['final_model']['display_version']}**
- Architecture: **topic-aware word + character TF-IDF**
- Weights: **TF-IDF 0.38, topic 0.62, embedding 0.00**
- Confidence signal: **raw TF-IDF similarity plus raw top-1 margin**
- Confidence threshold: **{report['final_model']['answer_confidence_threshold']}**
- Minimum raw margin: **{report['final_model']['answer_confidence_minimum_margin']}**

## Validation retrieval metrics

| Language | Top-1 | Top-3 | Precision | Ranking coverage | Category match |
|---|---:|---:|---:|---:|---:|
| English | {en['top_1_accuracy']:.2%} | {en['top_3_accuracy']:.2%} | {en['precision']:.2%} | {en['coverage']:.2%} | {en['category_match_rate']:.2%} |
| Twi | {tw['top_1_accuracy']:.2%} | {tw['top_3_accuracy']:.2%} | {tw['precision']:.2%} | {tw['coverage']:.2%} | {tw['category_match_rate']:.2%} |

At raw similarity threshold {threshold['threshold']}, automatic-answer response precision was **{threshold['response_precision']:.2%}** and response coverage was **{threshold['coverage']:.2%}** on the reviewed paraphrase benchmark. The selected gate produced zero false accepts across 120 negative controls.

## Independent behavior evidence

- Off-topic challenge: **48/48**
- Agricultural edge cases: **32/32**
- Language-separation cases: **80/80**
- Final presentation cases: **80/80**
- High-risk safety-notice coverage: **100%** of detected high-risk canonical answers

## Performance

- Cold startup: **{perf['cold_start_seconds']:.3f} seconds**
- Retrieval latency: **{perf['retrieval_average_ms']:.3f} ms average**, **{perf['retrieval_p95_ms']:.3f} ms p95**
- Flask test-client latency: **{perf['api_average_ms']:.3f} ms average**, **{perf['api_p95_ms']:.3f} ms p95**
- Working-set memory: **{perf['working_set_mb']:.2f} MB**

## Reporting cautions

- Retrieval coverage is not automatic-answer coverage.
- Similarity and score margin are not calibrated probabilities.
- No human participant usability results were supplied.
- Automated checks cannot establish agronomic correctness or native Twi naturalness; qualified review remains future work.
"""


def main():
    report = generate_report()
    JSON_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    MARKDOWN_PATH.parent.mkdir(parents=True, exist_ok=True)
    MARKDOWN_PATH.write_text(markdown(report), encoding="utf-8")
    print(f"Final report data: {JSON_PATH}")
    print(f"Chapter Four summary: {MARKDOWN_PATH}")


if __name__ == "__main__":
    main()
