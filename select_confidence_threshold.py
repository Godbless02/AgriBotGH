"""Select a conservative retrieval-confidence threshold for TODO 13.

This consumes the fully evaluated TODO 12 winner and does not retrain, modify,
or integrate the production chatbot. The score is a normalized weighted
retrieval score, not a calibrated probability.
"""

import json
import sys
from pathlib import Path

import numpy as np

from experiment_tfidf import load_json, safe_rate


HYBRID_REPORT_FILE = Path("models/hybrid_experiments.json")
HYBRID_CONFIG_FILE = Path("models/hybrid_retrieval_config.json")
OUTPUT_FILE = Path("models/threshold_experiments.json")
WINNER_FILE = Path("models/confidence_threshold_config.json")
THRESHOLDS = tuple(index / 100 for index in range(101))
REQUESTED_CHECKPOINTS = (0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85)
BETA = 0.5
SIGNAL_PREFERENCE = {
    "raw_weighted_evidence": 4,
    "raw_tfidf_similarity": 3,
    "raw_weighted_margin": 2,
    "normalized_score_margin": 1,
    "normalized_weighted_score": 0,
}

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def prepare_language(report, language):
    results = report["winner"]["languages"][language]["results"]
    weights = report["winner"]["weights"]
    top_candidates = [result["candidates"][0] for result in results]
    second_candidates = [result["candidates"][1] for result in results]

    def raw_weighted(candidate):
        return (
            weights["tfidf"] * candidate["raw_tfidf_similarity"]
            + weights["embedding"] * candidate["raw_embedding_similarity"]
            + weights["topic"] * candidate["raw_topic_relevance"]
        )

    top_raw_weighted = np.asarray([raw_weighted(item) for item in top_candidates])
    second_raw_weighted = np.asarray([raw_weighted(item) for item in second_candidates])
    return {
        "language": language,
        "results": results,
        "signals": {
            "normalized_weighted_score": np.asarray(
                [item["final_score"] for item in top_candidates], dtype=float
            ),
            "raw_tfidf_similarity": np.asarray(
                [item["raw_tfidf_similarity"] for item in top_candidates], dtype=float
            ),
            "raw_weighted_evidence": top_raw_weighted,
            "normalized_score_margin": np.asarray(
                [
                    first["final_score"] - second["final_score"]
                    for first, second in zip(top_candidates, second_candidates)
                ],
                dtype=float,
            ),
            "raw_weighted_margin": top_raw_weighted - second_raw_weighted,
        },
        "answerable": np.asarray([result["answerable"] for result in results], dtype=bool),
        "top_1_correct": np.asarray(
            [result["top_1_correct"] for result in results], dtype=bool
        ),
    }


def f_beta(precision, recall, beta=BETA):
    beta_squared = beta * beta
    denominator = beta_squared * precision + recall
    return (
        (1.0 + beta_squared) * precision * recall / denominator
        if denominator
        else 0.0
    )


def calculate_metrics(scores, answerable, top_1_correct, threshold):
    accepted = scores >= threshold
    reliable = answerable & top_1_correct

    true_positives = int(np.sum(accepted & reliable))
    false_positives = int(np.sum(accepted & ~reliable))
    false_negatives = int(np.sum(~accepted & reliable))
    true_negatives = int(np.sum(~accepted & ~reliable))
    accepted_count = int(np.sum(accepted))
    reliable_count = int(np.sum(reliable))
    total = len(scores)
    precision = safe_rate(true_positives, accepted_count)
    recall = safe_rate(true_positives, reliable_count)

    accepted_answerable = int(np.sum(accepted & answerable))
    accepted_unsupported = int(np.sum(accepted & ~answerable))
    accepted_wrong_matches = int(np.sum(accepted & answerable & ~top_1_correct))
    rejected_answerable = int(np.sum(~accepted & answerable))
    answerable_count = int(np.sum(answerable))
    return {
        "threshold": threshold,
        "total_cases": total,
        "accepted": accepted_count,
        "rejected": total - accepted_count,
        "coverage": safe_rate(accepted_count, total),
        "true_positives_reliable_answers": true_positives,
        "false_positives_unreliable_answers": false_positives,
        "false_negatives_missed_reliable_answers": false_negatives,
        "true_negatives_unreliable_answers_rejected": true_negatives,
        "response_precision": precision,
        "response_recall": recall,
        "response_f0_5": f_beta(precision, recall),
        "correct_answer_coverage": safe_rate(true_positives, total),
        "answerability": {
            "gold_answerable": answerable_count,
            "accepted_answerable": accepted_answerable,
            "accepted_unsupported": accepted_unsupported,
            "accepted_answerable_but_wrong_match": accepted_wrong_matches,
            "rejected_answerable": rejected_answerable,
            "precision": safe_rate(accepted_answerable, accepted_count),
            "recall": safe_rate(accepted_answerable, answerable_count),
        },
    }


def pooled_metrics(prepared, signal, threshold):
    return calculate_metrics(
        np.concatenate(
            [prepared[language]["signals"][signal] for language in ("English", "Twi")]
        ),
        np.concatenate(
            [prepared[language]["answerable"] for language in ("English", "Twi")]
        ),
        np.concatenate(
            [prepared[language]["top_1_correct"] for language in ("English", "Twi")]
        ),
        threshold,
    )


def selection_key(entry):
    pooled = entry["pooled"]
    return (
        pooled["response_f0_5"],
        pooled["response_precision"],
        -pooled["false_positives_unreliable_answers"],
        pooled["true_positives_reliable_answers"],
        pooled["coverage"],
        SIGNAL_PREFERENCE[entry["signal"]],
        entry["threshold"],
    )


def distribution(scores):
    return {
        "count": len(scores),
        "minimum": float(np.min(scores)),
        "p10": float(np.percentile(scores, 10)),
        "p25": float(np.percentile(scores, 25)),
        "median": float(np.median(scores)),
        "p75": float(np.percentile(scores, 75)),
        "p90": float(np.percentile(scores, 90)),
        "maximum": float(np.max(scores)),
        "mean": float(np.mean(scores)),
    }


def score_distributions(block, signal):
    scores = block["signals"][signal]
    answerable = block["answerable"]
    correct = block["top_1_correct"]
    reliable = answerable & correct
    return {
        "all": distribution(scores),
        "reliable_answer": distribution(scores[reliable]),
        "answerable_wrong_match": distribution(scores[answerable & ~correct]),
        "unsupported": distribution(scores[~answerable]),
    }


def detailed_decisions(block, signal, threshold):
    decisions = []
    for result, score in zip(block["results"], block["signals"][signal]):
        accepted = bool(score >= threshold)
        reliable = bool(result["answerable"] and result["top_1_correct"])
        if accepted and reliable:
            outcome = "reliable_answer_accepted"
        elif accepted and not result["answerable"]:
            outcome = "unsupported_false_positive"
        elif accepted:
            outcome = "wrong_match_false_positive"
        elif reliable:
            outcome = "reliable_answer_false_negative"
        elif result["answerable"]:
            outcome = "wrong_match_rejected"
        else:
            outcome = "unsupported_rejected"
        decisions.append({
            "validation_id": result["validation_id"],
            "question": result["question"],
            "answerable": result["answerable"],
            "top_1_correct": result["top_1_correct"],
            "confidence_signal": signal,
            "retrieval_score": float(score),
            "accepted": accepted,
            "outcome": outcome,
            "top_candidate": result["candidates"][0],
        })
    return decisions


def main():
    hybrid_report = load_json(HYBRID_REPORT_FILE)
    hybrid_config = load_json(HYBRID_CONFIG_FILE)
    prepared = {
        language: prepare_language(hybrid_report, language)
        for language in ("English", "Twi")
    }

    evaluations = []
    for signal in SIGNAL_PREFERENCE:
        for threshold in THRESHOLDS:
            evaluations.append({
                "signal": signal,
                "threshold": threshold,
                "languages": {
                    language: calculate_metrics(
                        prepared[language]["signals"][signal],
                        prepared[language]["answerable"],
                        prepared[language]["top_1_correct"],
                        threshold,
                    )
                    for language in ("English", "Twi")
                },
                "pooled": pooled_metrics(prepared, signal, threshold),
            })
    winner = max(evaluations, key=selection_key)
    winner_signal = winner["signal"]
    language_winners = {
        language: max(
            evaluations,
            key=lambda entry: (
                entry["languages"][language]["response_f0_5"],
                entry["languages"][language]["response_precision"],
                -entry["languages"][language]["false_positives_unreliable_answers"],
                entry["languages"][language]["true_positives_reliable_answers"],
                SIGNAL_PREFERENCE[entry["signal"]],
                entry["threshold"],
            ),
        )
        for language in ("English", "Twi")
    }
    winner_threshold = winner["threshold"]
    report = {
        "methodology": {
            "retrieval_architecture": hybrid_config["selected_architecture"],
            "retrieval_weights": hybrid_config["weights"],
            "score_name": "candidate retrieval-confidence signals",
            "score_warning": "None of these scores is a calibrated probability",
            "confidence_signals_tested": {
                "normalized_weighted_score": "TODO 12 top candidate ranking score",
                "raw_tfidf_similarity": "Absolute TF-IDF cosine similarity of the returned candidate",
                "raw_weighted_evidence": "TODO 12 weights applied to unnormalized component similarities",
                "normalized_score_margin": "Top-ranked normalized score minus runner-up score",
                "raw_weighted_margin": "Top-ranked raw weighted evidence minus runner-up evidence",
            },
            "acceptance_rule": "Return the top answer only when the selected confidence signal >= threshold",
            "reliable_answer_definition": "Gold-answerable case with the expected training record ranked first",
            "false_positive_definition": "Accepted unsupported case or accepted answerable case with the wrong top record",
            "thresholds_tested_per_signal": list(THRESHOLDS),
            "requested_checkpoints": list(REQUESTED_CHECKPOINTS),
            "selection_objective": "Select the signal and threshold that maximize pooled response F0.5, then precision, fewer false positives, reliable answers, and coverage",
            "precision_priority": "F0.5 weights precision more heavily than recall because unreliable agricultural answers are costlier than abstention",
        },
        "score_distributions": {
            signal: {
                language: score_distributions(prepared[language], signal)
                for language in ("English", "Twi")
            }
            for signal in SIGNAL_PREFERENCE
        },
        "evaluations": evaluations,
        "requested_checkpoint_results": [
            entry
            for entry in evaluations
            if entry["signal"] == winner_signal
            and entry["threshold"] in REQUESTED_CHECKPOINTS
        ],
        "winner": {
            "signal": winner_signal,
            "threshold": winner_threshold,
            "pooled": winner["pooled"],
            "languages": winner["languages"],
            "language_specific_diagnostic_winners": {
                language: {
                    "signal": entry["signal"],
                    "threshold": entry["threshold"],
                    "metrics": entry["languages"][language],
                }
                for language, entry in language_winners.items()
            },
            "selection_key": list(selection_key(winner)),
            "deployment_assessment": "Conservative diagnostic threshold only; its very low coverage means it must not be integrated without TODO 14 uncertain/off-topic routing",
            "decisions": {
                language: detailed_decisions(
                    prepared[language], winner_signal, winner_threshold
                )
                for language in ("English", "Twi")
            },
        },
    }
    config = {
        "status": "experimental_not_integrated",
        "retrieval_architecture": hybrid_config["selected_architecture"],
        "retrieval_weights": hybrid_config["weights"],
        "confidence_signal": winner_signal,
        "threshold": winner_threshold,
        "score_name": winner_signal,
        "is_probability": False,
        "acceptance_rule": f"{winner_signal} >= threshold",
        "selection_objective": "pooled_response_f0_5_with_precision_priority_across_candidate_signals",
        "validation_metrics": winner["pooled"],
        "deployment_ready": False,
        "limitation": "The zero-observed-false-positive threshold has very low coverage because supported and unsupported score distributions overlap",
        "source_report": str(OUTPUT_FILE).replace("\\", "/"),
        "next_step": "TODO 14 should use this answer threshold while separating uncertain agricultural and clearly unrelated inputs",
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_FILE.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    with WINNER_FILE.open("w", encoding="utf-8") as handle:
        json.dump(config, handle, ensure_ascii=False, indent=2)
    print(f"Selected confidence signal: {winner_signal}")
    print(f"Selected threshold: {winner_threshold:.2f}")
    print(
        f"Pooled precision={winner['pooled']['response_precision']:.2%}, "
        f"recall={winner['pooled']['response_recall']:.2%}, "
        f"coverage={winner['pooled']['coverage']:.2%}, "
        f"false positives={winner['pooled']['false_positives_unreliable_answers']}"
    )
    print(f"Saved: {OUTPUT_FILE}")
    print(f"Saved: {WINNER_FILE}")


if __name__ == "__main__":
    main()
