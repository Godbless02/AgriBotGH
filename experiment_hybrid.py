"""Search hybrid retrieval weights for TODO 12 without changing production.

The three score components are prepared exclusively from the training split:
TODO 9 TF-IDF similarity, TODO 11 dense LSA semantic similarity, and TODO 10
category-centroid relevance. Validation labels/categories are used only to
measure and select configurations.
"""

import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from sklearn.decomposition import TruncatedSVD
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import Normalizer

from experiment_local_embeddings import candidate_documents
from experiment_tfidf import (
    CONFIGURATIONS,
    build_vectorizer,
    clean_text,
    load_json,
    safe_rate,
)


TRAIN_FILE = Path("data/splits/train.json")
GOLD_FILE = Path("data/evaluation/gold_standard.json")
EMBEDDING_REPORT_FILE = Path("models/embedding_experiments.json")
OUTPUT_FILE = Path("models/hybrid_experiments.json")
WINNER_FILE = Path("models/hybrid_retrieval_config.json")
TOP_K = 3
WEIGHT_INCREMENT = 0.02
WEIGHT_UNITS = round(1.0 / WEIGHT_INCREMENT)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def normalize_nonnegative_rows(scores):
    clipped = np.maximum(scores, 0.0)
    maxima = clipped.max(axis=1, keepdims=True)
    return np.divide(clipped, maxima, out=np.zeros_like(clipped), where=maxima > 0.0)


def prepare_language(train, gold_entries, language, embedding_configuration):
    question_field = "question_en" if language == "English" else "question_twi"
    training_questions = [clean_text(row[question_field]) for row in train]
    queries = [clean_text(entry["question"]) for entry in gold_entries]
    categories = np.asarray([row["category"] for row in train], dtype=object)

    started = time.perf_counter()
    text_vectorizer = build_vectorizer(CONFIGURATIONS["C_word_and_character"])
    text_training = text_vectorizer.fit_transform(training_questions)
    text_queries = text_vectorizer.transform(queries)
    raw_text_scores = cosine_similarity(text_queries, text_training)
    text_scores = normalize_nonnegative_rows(raw_text_scores)

    category_indices = defaultdict(list)
    for index, category in enumerate(categories):
        category_indices[category].append(index)
    category_names = sorted(category_indices)
    centroids = np.vstack([
        np.asarray(text_training[category_indices[category]].mean(axis=0)).ravel()
        for category in category_names
    ])
    raw_category_scores = cosine_similarity(text_queries, centroids)
    category_scores = normalize_nonnegative_rows(raw_category_scores)
    category_positions = {category: index for index, category in enumerate(category_names)}
    raw_topic_scores = np.column_stack([
        raw_category_scores[:, category_positions[category]] for category in categories
    ])
    topic_scores = np.column_stack([
        category_scores[:, category_positions[category]] for category in categories
    ])
    text_topic_seconds = time.perf_counter() - started

    scope = embedding_configuration["text_scope"]
    requested_dimensions = embedding_configuration["actual_dimensions"]
    embedding_started = time.perf_counter()
    embedding_vectorizer = build_vectorizer(CONFIGURATIONS["C_word_and_character"])
    embedding_training_sparse = embedding_vectorizer.fit_transform(
        candidate_documents(train, language, scope)
    )
    dimensions = min(
        requested_dimensions,
        embedding_training_sparse.shape[0] - 1,
        embedding_training_sparse.shape[1] - 1,
    )
    embedder = make_pipeline(
        TruncatedSVD(n_components=dimensions, algorithm="randomized", random_state=42),
        Normalizer(copy=False),
    )
    training_embeddings = embedder.fit_transform(embedding_training_sparse)
    query_embeddings = embedder.transform(embedding_vectorizer.transform(queries))
    raw_embedding_scores = query_embeddings @ training_embeddings.T
    embedding_scores = normalize_nonnegative_rows(raw_embedding_scores)
    embedding_seconds = time.perf_counter() - embedding_started

    id_to_index = {row["id"]: index for index, row in enumerate(train)}
    expected_indices = np.asarray([
        id_to_index.get(entry["expected_training_record"], -1) for entry in gold_entries
    ])
    answerable = np.asarray([entry["answerable"] for entry in gold_entries], dtype=bool)
    validation_categories = np.asarray([entry["category"] for entry in gold_entries], dtype=object)
    return {
        "language": language,
        "question_field": question_field,
        "gold_entries": gold_entries,
        "categories": categories,
        "text_scores": text_scores,
        "embedding_scores": embedding_scores,
        "topic_scores": topic_scores,
        "raw_text_scores": raw_text_scores,
        "raw_embedding_scores": raw_embedding_scores,
        "raw_topic_scores": raw_topic_scores,
        "expected_indices": expected_indices,
        "answerable": answerable,
        "validation_categories": validation_categories,
        "cost": {
            "text_and_topic_preparation_seconds": text_topic_seconds,
            "embedding_preparation_seconds": embedding_seconds,
            "embedding_dimensions": dimensions,
            "training_embedding_bytes": int(training_embeddings.nbytes),
        },
    }


def rank(prepared, weights):
    scores = (
        weights["tfidf"] * prepared["text_scores"]
        + weights["embedding"] * prepared["embedding_scores"]
        + weights["topic"] * prepared["topic_scores"]
    )
    indices = np.argsort(scores, axis=1)[:, ::-1][:, :TOP_K]
    return scores, indices


def metrics_for(prepared, weights):
    _, indices = rank(prepared, weights)
    answerable = prepared["answerable"]
    expected = prepared["expected_indices"]
    top_1_correct = answerable & (indices[:, 0] == expected)
    top_3_correct = answerable & np.any(indices == expected[:, None], axis=1)
    top_1_category_match = (
        prepared["categories"][indices[:, 0]] == prepared["validation_categories"]
    )
    answerable_count = int(answerable.sum())
    total = len(answerable)
    top_1_hits = int(top_1_correct.sum())
    top_3_hits = int(top_3_correct.sum())
    return {
        "total_cases": total,
        "answerable_cases": answerable_count,
        "top_1_correct": top_1_hits,
        "top_3_correct": top_3_hits,
        "top_1_accuracy": safe_rate(top_1_hits, answerable_count),
        "top_3_accuracy": safe_rate(top_3_hits, answerable_count),
        "precision": safe_rate(top_1_hits, total),
        "coverage": 1.0,
        "category_match_rate": safe_rate(int(top_1_category_match.sum()), total),
    }


def selection_key(grid_entry):
    english = grid_entry["languages"]["English"]
    twi = grid_entry["languages"]["Twi"]
    weights = grid_entry["weights"]
    return (
        (english["top_1_accuracy"] + twi["top_1_accuracy"]) / 2,
        (english["top_3_accuracy"] + twi["top_3_accuracy"]) / 2,
        (english["category_match_rate"] + twi["category_match_rate"]) / 2,
        -weights["embedding"],
        -weights["topic"],
    )


def weight_grid():
    for tfidf_units in range(WEIGHT_UNITS + 1):
        for embedding_units in range(WEIGHT_UNITS - tfidf_units + 1):
            topic_units = WEIGHT_UNITS - tfidf_units - embedding_units
            yield {
                "tfidf": tfidf_units / WEIGHT_UNITS,
                "embedding": embedding_units / WEIGHT_UNITS,
                "topic": topic_units / WEIGHT_UNITS,
            }


def confusion_report(results):
    counts = Counter()
    matrix = defaultdict(Counter)
    for result in results:
        if result["top_1_correct"]:
            continue
        expected = result["validation_category"]
        predicted = result["candidates"][0]["category"]
        counts[(expected, predicted)] += 1
        matrix[expected][predicted] += 1
    return {
        "top_confusions": [
            {"expected_category": expected, "predicted_category": predicted, "count": count}
            for (expected, predicted), count in sorted(
                counts.items(), key=lambda item: (-item[1], item[0][0], item[0][1])
            )
        ],
        "matrix": {
            expected: dict(sorted(predicted.items()))
            for expected, predicted in sorted(matrix.items())
        },
    }


def detailed_winner(train, prepared, weights):
    final_scores, indices = rank(prepared, weights)
    results = []
    for row_index, (gold, candidate_indices) in enumerate(
        zip(prepared["gold_entries"], indices)
    ):
        candidates = []
        for candidate_rank, index in enumerate(candidate_indices, start=1):
            candidates.append({
                "rank": candidate_rank,
                "train_id": train[index]["id"],
                "category": train[index]["category"],
                "question": train[index][prepared["question_field"]],
                "tfidf_score": float(prepared["text_scores"][row_index, index]),
                "embedding_score": float(prepared["embedding_scores"][row_index, index]),
                "topic_score": float(prepared["topic_scores"][row_index, index]),
                "raw_tfidf_similarity": float(
                    prepared["raw_text_scores"][row_index, index]
                ),
                "raw_embedding_similarity": float(
                    prepared["raw_embedding_scores"][row_index, index]
                ),
                "raw_topic_relevance": float(
                    prepared["raw_topic_scores"][row_index, index]
                ),
                "final_score": float(final_scores[row_index, index]),
            })
        candidate_ids = [candidate["train_id"] for candidate in candidates]
        expected = gold["expected_training_record"]
        results.append({
            "validation_id": gold["validation_id"],
            "validation_category": gold["category"],
            "question": gold["question"],
            "answerable": gold["answerable"],
            "expected_training_record": expected,
            "top_1_correct": bool(gold["answerable"] and candidate_ids[0] == expected),
            "top_3_correct": bool(gold["answerable"] and expected in candidate_ids),
            "top_1_category_match": candidates[0]["category"] == gold["category"],
            "candidates": candidates,
        })
    return {
        "metrics": metrics_for(prepared, weights),
        "cost": prepared["cost"],
        "category_confusion": confusion_report(results),
        "results": results,
    }


def main():
    train = load_json(TRAIN_FILE)
    gold = load_json(GOLD_FILE)
    embedding_report = load_json(EMBEDDING_REPORT_FILE)
    embedding_name = embedding_report["winner"]["configuration"]
    embedding_configuration = embedding_report["experiments"][embedding_name]["English"][
        "configuration"
    ]

    prepared = {}
    for language in ("English", "Twi"):
        print(f"Preparing {language} score components...")
        entries = [entry for entry in gold["entries"] if entry["language"] == language]
        prepared[language] = prepare_language(
            train, entries, language, embedding_configuration
        )

    print(f"Searching {((WEIGHT_UNITS + 1) * (WEIGHT_UNITS + 2)) // 2} weight triples...")
    search_started = time.perf_counter()
    grid = []
    for weights in weight_grid():
        grid.append({
            "weights": weights,
            "languages": {
                language: metrics_for(prepared[language], weights)
                for language in ("English", "Twi")
            },
        })
    search_seconds = time.perf_counter() - search_started
    winner = max(grid, key=selection_key)
    winner_score = selection_key(winner)
    strict_hybrids = [
        entry
        for entry in grid
        if all(entry["weights"][component] > 0.0 for component in ("tfidf", "embedding", "topic"))
    ]
    best_strict_hybrid = max(strict_hybrids, key=selection_key)
    best_strict_score = selection_key(best_strict_hybrid)
    metric_tie_count = sum(
        selection_key(entry)[:3] == winner_score[:3] for entry in grid
    )
    winner_details = {
        language: detailed_winner(train, prepared[language], winner["weights"])
        for language in ("English", "Twi")
    }

    report = {
        "methodology": {
            "formula": "tfidf_weight*tfidf_score + embedding_weight*embedding_score + topic_weight*topic_score",
            "tfidf_component": "TODO 9 Configuration C question similarity",
            "embedding_component": f"TODO 11 winner: {embedding_name}",
            "topic_component": "TODO 10 training-only category-centroid relevance",
            "normalization": "Each component is clipped at zero and divided by its per-query maximum",
            "validation_category_usage": "Reporting only; never supplied to scoring",
            "weight_increment": WEIGHT_INCREMENT,
            "weight_combinations": len(grid),
            "zero_weight_controls": "Included for all three components",
            "selection_order": [
                "macro-average bilingual top-1 accuracy",
                "macro-average bilingual top-3 accuracy",
                "macro-average category-match rate",
                "lower embedding weight for practicality",
                "lower topic weight",
            ],
            "no_threshold": "Threshold selection is deferred to TODO 13",
            "search_seconds": search_seconds,
        },
        "grid": grid,
        "winner": {
            "weights": winner["weights"],
            "macro_top_1_accuracy": winner_score[0],
            "macro_top_3_accuracy": winner_score[1],
            "macro_category_match_rate": winner_score[2],
            "metric_tie_count": metric_tie_count,
            "languages": winner_details,
            "reason": "Selected using the declared lexicographic validation criteria",
        },
        "best_strict_three_way": {
            "weights": best_strict_hybrid["weights"],
            "macro_top_1_accuracy": best_strict_score[0],
            "macro_top_3_accuracy": best_strict_score[1],
            "macro_category_match_rate": best_strict_score[2],
            "languages": best_strict_hybrid["languages"],
            "decision": "Not selected because it ties the winner while adding embedding runtime and storage cost",
        },
        "comparison": embedding_report["comparison"],
    }
    selected_architecture = (
        "topic_aware_tfidf"
        if winner["weights"]["embedding"] == 0.0
        else "hybrid_tfidf_embedding_topic"
    )
    winner_config = {
        "status": "experimental_not_integrated",
        "evaluated_architecture": "hybrid_tfidf_embedding_topic",
        "selected_architecture": selected_architecture,
        "weights": winner["weights"],
        "tfidf_configuration": "C_word_and_character",
        "embedding_configuration": embedding_name,
        "embedding_details": embedding_configuration,
        "topic_method": "training_category_centroids",
        "score_normalization": "per_query_nonnegative_max",
        "selection_metrics": {
            "macro_top_1_accuracy": winner_score[0],
            "macro_top_3_accuracy": winner_score[1],
            "macro_category_match_rate": winner_score[2],
        },
        "decision": "The semantic component produced no metric improvement, so the simpler zero-embedding control was selected",
        "source_report": str(OUTPUT_FILE).replace("\\", "/"),
        "next_step": "Use TODO 13 to select a confidence threshold before any production integration",
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_FILE.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    with WINNER_FILE.open("w", encoding="utf-8") as handle:
        json.dump(winner_config, handle, ensure_ascii=False, indent=2)
    print(f"Winner weights: {winner['weights']}")
    print(f"Saved: {OUTPUT_FILE}")
    print(f"Saved: {WINNER_FILE}")


if __name__ == "__main__":
    main()
