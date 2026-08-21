"""Evaluate soft topic-aware scoring on the winning TF-IDF representation.

Topic relevance is inferred from each query and category centroids built only
from training questions. Validation categories are used solely for reporting,
never as retrieval inputs. Saved/live model artifacts are not modified.
"""

import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

from experiment_tfidf import (
    CONFIGURATIONS,
    build_vectorizer,
    clean_text,
    load_json,
    safe_rate,
)


TRAIN_FILE = Path("data/splits/train.json")
GOLD_FILE = Path("data/evaluation/gold_standard.json")
OUTPUT_FILE = Path("models/topic_aware_experiments.json")
TOP_K = 3
TOPIC_WEIGHTS = [
    0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45,
    0.50, 0.55, 0.60, 0.61, 0.62, 0.63, 0.64, 0.65, 0.66, 0.67,
    0.68, 0.69, 0.70, 0.75, 0.80, 0.85, 0.90,
]

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def prepare_language(train, language):
    field = "question_en" if language == "English" else "question_twi"
    questions = [clean_text(row[field]) for row in train]
    vectorizer = build_vectorizer(CONFIGURATIONS["C_word_and_character"])
    matrix = vectorizer.fit_transform(questions)

    category_indices = defaultdict(list)
    for index, row in enumerate(train):
        category_indices[row["category"]].append(index)
    category_names = sorted(category_indices)
    centroids = np.vstack(
        [
            np.asarray(matrix[category_indices[category]].mean(axis=0)).ravel()
            for category in category_names
        ]
    )
    category_position = {category: index for index, category in enumerate(category_names)}
    return {
        "field": field,
        "vectorizer": vectorizer,
        "matrix": matrix,
        "category_names": category_names,
        "category_position": category_position,
        "centroids": centroids,
    }


def normalize(scores):
    maximum = float(np.max(scores)) if len(scores) else 0.0
    return scores / maximum if maximum > 0.0 else np.zeros_like(scores)


def evaluate_weight(train, prepared, gold_entries, topic_weight):
    text_weight = 1.0 - topic_weight
    vectorizer = prepared["vectorizer"]
    matrix = prepared["matrix"]
    categories = [row["category"] for row in train]
    ids = [row["id"] for row in train]
    results = []
    retrieval_times = []

    for gold in gold_entries:
        started = time.perf_counter()
        query = vectorizer.transform([clean_text(gold["question"])])
        raw_text_scores = cosine_similarity(query, matrix)[0]
        text_scores = normalize(raw_text_scores)
        raw_topic_scores = cosine_similarity(query, prepared["centroids"])[0]
        topic_scores = normalize(raw_topic_scores)
        row_topic_scores = np.array(
            [topic_scores[prepared["category_position"][category]] for category in categories]
        )
        final_scores = text_weight * text_scores + topic_weight * row_topic_scores
        indices = np.argsort(final_scores)[::-1][:TOP_K]
        retrieval_times.append(time.perf_counter() - started)

        predicted_topic_index = int(np.argmax(topic_scores))
        predicted_topic = prepared["category_names"][predicted_topic_index]
        candidates = [
            {
                "rank": rank,
                "train_id": ids[index],
                "category": categories[index],
                "text_similarity": float(raw_text_scores[index]),
                "normalized_text_score": float(text_scores[index]),
                "topic_relevance": float(row_topic_scores[index]),
                "final_score": float(final_scores[index]),
            }
            for rank, index in enumerate(indices, start=1)
        ]
        candidate_ids = [candidate["train_id"] for candidate in candidates]
        expected = gold["expected_training_record"]
        results.append({
            "validation_id": gold["validation_id"],
            "answerable": gold["answerable"],
            "expected_training_record": expected,
            "validation_category": gold["category"],
            "predicted_topic": predicted_topic,
            "topic_prediction_correct": predicted_topic == gold["category"],
            "top_1_correct": bool(gold["answerable"] and candidate_ids[0] == expected),
            "top_3_correct": bool(gold["answerable"] and expected in candidate_ids),
            "top_1_category_match": candidates[0]["category"] == gold["category"],
            "candidates": candidates,
        })

    answerable = sum(result["answerable"] for result in results)
    top_1_hits = sum(result["top_1_correct"] for result in results)
    top_3_hits = sum(result["top_3_correct"] for result in results)
    return {
        "weights": {"text": text_weight, "topic": topic_weight},
        "metrics": {
            "total_cases": len(results),
            "answerable_cases": answerable,
            "top_1_correct": top_1_hits,
            "top_3_correct": top_3_hits,
            "top_1_accuracy": safe_rate(top_1_hits, answerable),
            "top_3_accuracy": safe_rate(top_3_hits, answerable),
            "precision": safe_rate(top_1_hits, len(results)),
            "coverage": 1.0,
            "category_match_rate": safe_rate(
                sum(result["top_1_category_match"] for result in results), len(results)
            ),
            "topic_prediction_accuracy": safe_rate(
                sum(result["topic_prediction_correct"] for result in results), len(results)
            ),
            "average_retrieval_seconds": float(np.mean(retrieval_times)),
        },
        "results": results,
    }


def selection_key(item):
    topic_weight, languages = item
    english = languages["English"]["metrics"]
    twi = languages["Twi"]["metrics"]
    return (
        (english["top_1_accuracy"] + twi["top_1_accuracy"]) / 2,
        (english["top_3_accuracy"] + twi["top_3_accuracy"]) / 2,
        (english["category_match_rate"] + twi["category_match_rate"]) / 2,
        -topic_weight,
    )


def main():
    train = load_json(TRAIN_FILE)
    gold = load_json(GOLD_FILE)
    prepared = {
        language: prepare_language(train, language)
        for language in ("English", "Twi")
    }
    experiments = {}

    for topic_weight in TOPIC_WEIGHTS:
        key = f"topic_{topic_weight:.2f}"
        print(f"Running text={1.0-topic_weight:.2f}, topic={topic_weight:.2f}...")
        languages = {}
        for language in ("English", "Twi"):
            entries = [entry for entry in gold["entries"] if entry["language"] == language]
            languages[language] = evaluate_weight(
                train, prepared[language], entries, topic_weight
            )
            metrics = languages[language]["metrics"]
            print(
                f"  {language}: top-1={metrics['top_1_accuracy']:.2%}, "
                f"top-3={metrics['top_3_accuracy']:.2%}, "
                f"category={metrics['category_match_rate']:.2%}"
            )
        experiments[key] = languages

    weighted_items = [
        (float(key.removeprefix("topic_")), languages)
        for key, languages in experiments.items()
    ]
    winning_weight, winning_languages = max(weighted_items, key=selection_key)
    score = selection_key((winning_weight, winning_languages))
    report = {
        "methodology": {
            "base_representation": "TODO 9 Configuration C: word (1,2) + char_wb (3,5).",
            "topic_source": "Cosine similarity to category centroids built from training questions only.",
            "score_formula": "(1-topic_weight)*normalized_text_score + topic_weight*normalized_topic_relevance",
            "validation_category_usage": "Reporting only; never supplied to retrieval scoring.",
            "weights_tested": TOPIC_WEIGHTS,
            "selection_order": [
                "macro-average bilingual top-1 accuracy",
                "macro-average bilingual top-3 accuracy",
                "macro-average category-match rate",
                "lower topic weight",
            ],
        },
        "experiments": experiments,
        "winner": {
            "text_weight": 1.0 - winning_weight,
            "topic_weight": winning_weight,
            "macro_top_1_accuracy": score[0],
            "macro_top_3_accuracy": score[1],
            "macro_category_match_rate": score[2],
            "reason": "Selected using the declared lexicographic validation criteria.",
        },
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_FILE.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    print(
        f"Winner: text={1.0-winning_weight:.2f}, topic={winning_weight:.2f}"
    )
    print(f"Saved: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
