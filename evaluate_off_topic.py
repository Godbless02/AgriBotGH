"""Build and evaluate the TODO 14 three-state query router.

State A returns a strong answer, State B keeps agricultural-looking but
uncertain questions in-domain, and State C rejects clearly unrelated input.
Everything remains experimental until the explicit Flask integration step.
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from experiment_hybrid import prepare_language, rank
from experiment_tfidf import load_json, safe_rate


TRAIN_FILE = Path("data/splits/train.json")
GOLD_FILE = Path("data/evaluation/gold_standard.json")
OFF_TOPIC_FILE = Path("data/evaluation/off_topic_cases.json")
HYBRID_CONFIG_FILE = Path("models/hybrid_retrieval_config.json")
THRESHOLD_CONFIG_FILE = Path("models/confidence_threshold_config.json")
OUTPUT_FILE = Path("models/off_topic_experiments.json")
CONFIG_FILE = Path("models/off_topic_config.json")
DOMAIN_BLEND_VALUES = tuple(index / 20 for index in range(21))
DOMAIN_THRESHOLDS = tuple(index / 100 for index in range(61))
STATES = ("A", "B", "C")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def gold_cases(entries, language):
    language_entries = sorted(
        (entry for entry in entries if entry["language"] == language),
        key=lambda entry: entry["validation_id"],
    )
    cases = []
    for index, entry in enumerate(language_entries):
        cases.append({
            **entry,
            "case_id": f"gold_{language.lower()}_{entry['validation_id']}",
            "split": "development" if index % 2 == 0 else "test",
            "gold_state": "A" if entry["answerable"] else "B",
            "source": "agricultural_gold_standard",
        })
    return cases


def unrelated_cases(entries, language):
    return [
        {
            "validation_id": entry["id"],
            "case_id": entry["id"],
            "split": entry["split"],
            "language": language,
            "question": entry["question"],
            "category": "Off-topic",
            "expected_training_record": None,
            "answerable": False,
            "gold_state": "C",
            "source": "curated_off_topic_challenge",
        }
        for entry in entries
        if entry["language"] == language
    ]


def exact_known_cases(train, language, count=12):
    question_field = "question_en" if language == "English" else "question_twi"
    indices = np.linspace(0, len(train) - 1, num=count, dtype=int)
    return [
        {
            "validation_id": f"known_{language.lower()}_{train[index]['id']}",
            "case_id": f"known_{language.lower()}_{train[index]['id']}",
            "split": "sanity",
            "language": language,
            "question": train[index][question_field],
            "category": train[index]["category"],
            "expected_training_record": train[index]["id"],
            "answerable": True,
            "gold_state": "A",
            "source": "exact_known_training_question_sanity_check",
        }
        for index in indices
    ]


def domain_metrics(scores, gold_agriculture, threshold):
    predicted_agriculture = scores >= threshold
    agriculture_true = int(np.sum(predicted_agriculture & gold_agriculture))
    agriculture_false_negative = int(np.sum(~predicted_agriculture & gold_agriculture))
    off_topic_true = int(np.sum(~predicted_agriculture & ~gold_agriculture))
    off_topic_false_negative = int(np.sum(predicted_agriculture & ~gold_agriculture))
    agriculture_count = int(np.sum(gold_agriculture))
    off_topic_count = int(np.sum(~gold_agriculture))
    predicted_off_topic = int(np.sum(~predicted_agriculture))
    agriculture_recall = safe_rate(agriculture_true, agriculture_count)
    off_topic_recall = safe_rate(off_topic_true, off_topic_count)
    return {
        "threshold": threshold,
        "agriculture_true": agriculture_true,
        "agriculture_false_negative": agriculture_false_negative,
        "off_topic_true": off_topic_true,
        "off_topic_false_negative": off_topic_false_negative,
        "agriculture_recall": agriculture_recall,
        "off_topic_recall": off_topic_recall,
        "off_topic_precision": safe_rate(off_topic_true, predicted_off_topic),
        "balanced_accuracy": (agriculture_recall + off_topic_recall) / 2,
        "agriculture_weighted_accuracy": (2 * agriculture_recall + off_topic_recall) / 3,
    }


def domain_selection_key(entry):
    metrics = entry["metrics"]
    return (
        metrics["agriculture_weighted_accuracy"],
        metrics["balanced_accuracy"],
        metrics["off_topic_precision"],
        metrics["agriculture_recall"],
        -entry["threshold"],
        entry["text_weight"],
    )


def select_domain_configuration(max_text_scores, max_topic_scores, cases):
    development = np.asarray([case["split"] == "development" for case in cases])
    gold_agriculture = np.asarray([case["gold_state"] != "C" for case in cases])
    experiments = []
    for text_weight in DOMAIN_BLEND_VALUES:
        topic_weight = 1.0 - text_weight
        scores = text_weight * max_text_scores + topic_weight * max_topic_scores
        for threshold in DOMAIN_THRESHOLDS:
            experiments.append({
                "text_weight": text_weight,
                "topic_weight": topic_weight,
                "threshold": threshold,
                "metrics": domain_metrics(
                    scores[development], gold_agriculture[development], threshold
                ),
            })
    winner = max(experiments, key=domain_selection_key)
    return winner, experiments


def classification_metrics(gold_states, predicted_states):
    matrix = {state: Counter() for state in STATES}
    for gold, predicted in zip(gold_states, predicted_states):
        matrix[gold][predicted] += 1
    per_state = {}
    for state in STATES:
        true_positive = matrix[state][state]
        predicted_count = sum(matrix[gold][state] for gold in STATES)
        gold_count = sum(matrix[state].values())
        precision = safe_rate(true_positive, predicted_count)
        recall = safe_rate(true_positive, gold_count)
        per_state[state] = {
            "support": gold_count,
            "predicted": predicted_count,
            "correct": true_positive,
            "precision": precision,
            "recall": recall,
            "f1": safe_rate(2 * precision * recall, precision + recall),
        }
    return {
        "total": len(gold_states),
        "correct": sum(gold == predicted for gold, predicted in zip(gold_states, predicted_states)),
        "accuracy": safe_rate(
            sum(gold == predicted for gold, predicted in zip(gold_states, predicted_states)),
            len(gold_states),
        ),
        "macro_f1": float(np.mean([per_state[state]["f1"] for state in STATES])),
        "per_state": per_state,
        "confusion_matrix": {
            gold: {predicted: matrix[gold][predicted] for predicted in STATES}
            for gold in STATES
        },
    }


def route_cases(train, prepared, cases, retrieval_weights, answer_threshold, domain_config):
    final_scores, indices = rank(prepared, retrieval_weights)
    answer_signal = final_scores[np.arange(len(cases)), indices[:, 0]] - final_scores[
        np.arange(len(cases)), indices[:, 1]
    ]
    max_text = np.max(prepared["raw_text_scores"], axis=1)
    max_topic = np.max(prepared["raw_topic_scores"], axis=1)
    domain_score = (
        domain_config["text_weight"] * max_text
        + domain_config["topic_weight"] * max_topic
    )
    predicted_states = []
    details = []
    for row_index, case in enumerate(cases):
        agricultural = bool(domain_score[row_index] >= domain_config["threshold"])
        exact_known_match = bool(max_text[row_index] >= 1.0 - 1e-12)
        if not agricultural:
            predicted_state = "C"
            response_action = "agriculture_only_response"
        elif exact_known_match or answer_signal[row_index] >= answer_threshold:
            predicted_state = "A"
            response_action = "return_answer"
        else:
            predicted_state = "B"
            response_action = "ask_for_detail_and_offer_relevant_suggestions"
        predicted_states.append(predicted_state)
        top_index = int(indices[row_index, 0])
        top_id = train[top_index]["id"]
        details.append({
            "case_id": case["case_id"],
            "split": case["split"],
            "language": prepared["language"],
            "source": case["source"],
            "question": case["question"],
            "gold_state": case["gold_state"],
            "predicted_state": predicted_state,
            "state_correct": predicted_state == case["gold_state"],
            "response_action": response_action,
            "domain_score": float(domain_score[row_index]),
            "domain_threshold": domain_config["threshold"],
            "answer_confidence_signal": float(answer_signal[row_index]),
            "answer_threshold": answer_threshold,
            "exact_known_match": exact_known_match,
            "top_train_id": top_id,
            "top_category": train[top_index]["category"],
            "top_1_correct": bool(
                case["answerable"] and top_id == case["expected_training_record"]
            ),
        })
    return predicted_states, details, max_text, max_topic


def evaluate_split(details, split):
    selected = [detail for detail in details if detail["split"] == split]
    metrics = classification_metrics(
        [detail["gold_state"] for detail in selected],
        [detail["predicted_state"] for detail in selected],
    )
    state_a = [detail for detail in selected if detail["predicted_state"] == "A"]
    reliable = [detail for detail in state_a if detail["top_1_correct"]]
    unsafe = [detail for detail in state_a if not detail["top_1_correct"]]
    metrics["answer_safety"] = {
        "answers_returned": len(state_a),
        "reliable_answers": len(reliable),
        "unsafe_answers": len(unsafe),
        "response_precision": safe_rate(len(reliable), len(state_a)),
    }
    return metrics


def main():
    train = load_json(TRAIN_FILE)
    gold = load_json(GOLD_FILE)
    off_topic = load_json(OFF_TOPIC_FILE)
    hybrid_config = load_json(HYBRID_CONFIG_FILE)
    threshold_config = load_json(THRESHOLD_CONFIG_FILE)
    embedding_name = hybrid_config["embedding_configuration"]
    embedding_report = load_json(Path("models/embedding_experiments.json"))
    embedding_configuration = embedding_report["experiments"][embedding_name]["English"][
        "configuration"
    ]

    languages = {}
    all_details = []
    for language in ("English", "Twi"):
        cases = (
            gold_cases(gold["entries"], language)
            + unrelated_cases(off_topic["cases"], language)
            + exact_known_cases(train, language)
        )
        prepared = prepare_language(train, cases, language, embedding_configuration)
        _, provisional_indices = rank(prepared, hybrid_config["weights"])
        del provisional_indices
        max_text = np.max(prepared["raw_text_scores"], axis=1)
        max_topic = np.max(prepared["raw_topic_scores"], axis=1)
        domain_winner, domain_experiments = select_domain_configuration(
            max_text, max_topic, cases
        )
        predicted_states, details, _, _ = route_cases(
            train,
            prepared,
            cases,
            hybrid_config["weights"],
            threshold_config["threshold"],
            domain_winner,
        )
        del predicted_states
        all_details.extend(details)
        languages[language] = {
            "domain_search": {
                "configurations_tested": len(domain_experiments),
                "winner": domain_winner,
            },
            "development_metrics": evaluate_split(details, "development"),
            "test_metrics": evaluate_split(details, "test"),
            "exact_known_sanity_metrics": evaluate_split(details, "sanity"),
            "details": details,
        }

    test_details = [detail for detail in all_details if detail["split"] == "test"]
    pooled_test = classification_metrics(
        [detail["gold_state"] for detail in test_details],
        [detail["predicted_state"] for detail in test_details],
    )
    returned = [detail for detail in test_details if detail["predicted_state"] == "A"]
    reliable = [detail for detail in returned if detail["top_1_correct"]]
    pooled_test["answer_safety"] = {
        "answers_returned": len(returned),
        "reliable_answers": len(reliable),
        "unsafe_answers": len(returned) - len(reliable),
        "response_precision": safe_rate(len(reliable), len(returned)),
    }
    report = {
        "methodology": {
            "states": {
                "A": "Dataset-supported agricultural question passing the conservative answer-confidence gate",
                "B": "Agricultural-looking question below the answer-confidence gate",
                "C": "Clearly unrelated question below the agriculture-domain threshold",
            },
            "gold_state_labels": "Gold answerable -> A; gold unsupported agricultural -> B; curated unrelated -> C",
            "domain_score": "Language-specific blend of maximum raw TF-IDF question similarity and maximum raw category-centroid relevance",
            "domain_selection": "Development-only search maximizing 2:1 agriculture-recall-weighted balanced accuracy",
            "answer_gate": {
                "signal": threshold_config["confidence_signal"],
                "threshold": threshold_config["threshold"],
                "exact_match_override": "Maximum raw TF-IDF cosine similarity >= 1 - 1e-12",
                "note": "Applied only after a query is classified as agricultural",
            },
            "exact_known_sanity_check": "Twelve training questions per language verify that State A remains reachable for exact supported input; these cases are excluded from threshold/domain selection and held-out metrics",
            "production_integration": "Deferred to TODO 17",
        },
        "languages": languages,
        "pooled_test": pooled_test,
    }
    config = {
        "status": "experimental_not_integrated",
        "router": "three_state_agriculture_router",
        "states": {
            "A": "return_answer",
            "B": "uncertain_agriculture_rephrase_and_suggestions",
            "C": "agriculture_only_response",
        },
        "domain_detection": {
            language: languages[language]["domain_search"]["winner"]
            for language in ("English", "Twi")
        },
        "answer_confidence": {
            "signal": threshold_config["confidence_signal"],
            "threshold": threshold_config["threshold"],
            "exact_match_override": "max_raw_tfidf_similarity >= 1 - 1e-12",
        },
        "test_metrics": pooled_test,
        "todo_13_reassessment": "Do not lower the answer threshold yet: held-out score overlap would trade abstention for unreliable answers. Reassess after retrieval improvements or calibrated confidence features",
        "source_report": str(OUTPUT_FILE).replace("\\", "/"),
        "next_step": "TODO 15 suggestion IDs, then TODO 17 production integration after all behavior is validated",
    }
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_FILE.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    with CONFIG_FILE.open("w", encoding="utf-8") as handle:
        json.dump(config, handle, ensure_ascii=False, indent=2)
    print(
        f"Pooled test accuracy={pooled_test['accuracy']:.2%}, "
        f"macro-F1={pooled_test['macro_f1']:.2%}, "
        f"unsafe answers={pooled_test['answer_safety']['unsafe_answers']}"
    )
    print(f"Saved: {OUTPUT_FILE}")
    print(f"Saved: {CONFIG_FILE}")


if __name__ == "__main__":
    main()
