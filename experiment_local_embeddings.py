"""Evaluate lightweight project-trained dense sentence embeddings for TODO 11.

This is an isolated fallback for environments where a pretrained multilingual
ONNX model cannot be acquired reliably.  It creates dense latent-semantic
embeddings with TF-IDF followed by TruncatedSVD (LSA), evaluates several
training-text scopes and dimensions, and never changes Flask or production
model artifacts.
"""

import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from sklearn.decomposition import TruncatedSVD
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import Normalizer

from experiment_tfidf import (
    CONFIGURATIONS,
    build_vectorizer,
    clean_text,
    load_json,
    safe_rate,
)


TRAIN_FILE = Path("data/splits/train.json")
GOLD_FILE = Path("data/evaluation/gold_standard.json")
OUTPUT_FILE = Path("models/embedding_experiments.json")
TOP_K = 3
DIMENSIONS = (32, 64, 128, 256)
TEXT_SCOPES = ("question", "question_answer", "bilingual_question_answer")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def candidate_documents(train, language, scope):
    suffix = "en" if language == "English" else "twi"
    other = "twi" if suffix == "en" else "en"
    documents = []
    for row in train:
        parts = [row[f"question_{suffix}"]]
        if scope != "question":
            parts.append(row[f"answer_{suffix}"])
        if scope == "bilingual_question_answer":
            parts.extend((row[f"question_{other}"], row[f"answer_{other}"]))
        documents.append(clean_text(" ".join(parts)))
    return documents


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


def evaluate_configuration(train, gold_entries, language, scope, requested_dimensions):
    documents = candidate_documents(train, language, scope)
    vectorizer = build_vectorizer(CONFIGURATIONS["C_word_and_character"])

    started = time.perf_counter()
    sparse_training = vectorizer.fit_transform(documents)
    dimensions = min(
        requested_dimensions,
        sparse_training.shape[0] - 1,
        sparse_training.shape[1] - 1,
    )
    embedder = make_pipeline(
        TruncatedSVD(n_components=dimensions, algorithm="randomized", random_state=42),
        Normalizer(copy=False),
    )
    training_embeddings = embedder.fit_transform(sparse_training).astype(np.float32)
    fit_seconds = time.perf_counter() - started

    questions = [clean_text(entry["question"]) for entry in gold_entries]
    query_started = time.perf_counter()
    query_embeddings = embedder.transform(vectorizer.transform(questions)).astype(np.float32)
    query_seconds = time.perf_counter() - query_started
    similarities = query_embeddings @ training_embeddings.T

    question_field = "question_en" if language == "English" else "question_twi"
    results = []
    for gold, scores in zip(gold_entries, similarities):
        indices = np.argsort(scores)[::-1][:TOP_K]
        candidates = [
            {
                "rank": rank,
                "train_id": train[index]["id"],
                "category": train[index]["category"],
                "question": train[index][question_field],
                "semantic_similarity": float(scores[index]),
            }
            for rank, index in enumerate(indices, start=1)
        ]
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

    total = len(results)
    answerable = sum(result["answerable"] for result in results)
    top_1_hits = sum(result["top_1_correct"] for result in results)
    top_3_hits = sum(result["top_3_correct"] for result in results)
    top_scores = [result["candidates"][0]["semantic_similarity"] for result in results]
    return {
        "configuration": {
            "text_scope": scope,
            "requested_dimensions": requested_dimensions,
            "actual_dimensions": dimensions,
        },
        "metrics": {
            "total_cases": total,
            "answerable_cases": answerable,
            "top_1_correct": top_1_hits,
            "top_3_correct": top_3_hits,
            "top_1_accuracy": safe_rate(top_1_hits, answerable),
            "top_3_accuracy": safe_rate(top_3_hits, answerable),
            "precision": safe_rate(top_1_hits, total),
            "coverage": 1.0,
            "average_top_1_similarity": float(np.mean(top_scores)),
            "category_match_rate": safe_rate(
                sum(result["top_1_category_match"] for result in results), total
            ),
        },
        "cost": {
            "embedding_dimensions": dimensions,
            "training_embedding_bytes": int(training_embeddings.nbytes),
            "fit_seconds": fit_seconds,
            "query_encoding_seconds": query_seconds,
            "average_query_encoding_seconds": safe_rate(query_seconds, len(questions)),
        },
        "category_confusion": confusion_report(results),
        "results": results,
    }


def selection_key(item):
    name, languages = item
    english = languages["English"]["metrics"]
    twi = languages["Twi"]["metrics"]
    dimensions = languages["English"]["configuration"]["actual_dimensions"]
    return (
        (english["top_1_accuracy"] + twi["top_1_accuracy"]) / 2,
        (english["top_3_accuracy"] + twi["top_3_accuracy"]) / 2,
        (english["category_match_rate"] + twi["category_match_rate"]) / 2,
        -dimensions,
        name,
    )


def main():
    train = load_json(TRAIN_FILE)
    gold = load_json(GOLD_FILE)
    experiments = {}

    for scope in TEXT_SCOPES:
        for dimensions in DIMENSIONS:
            name = f"lsa_{scope}_{dimensions}d"
            print(f"Running {name}...")
            languages = {}
            for language in ("English", "Twi"):
                entries = [entry for entry in gold["entries"] if entry["language"] == language]
                languages[language] = evaluate_configuration(
                    train, entries, language, scope, dimensions
                )
                metrics = languages[language]["metrics"]
                print(
                    f"  {language}: top-1={metrics['top_1_accuracy']:.2%}, "
                    f"top-3={metrics['top_3_accuracy']:.2%}, "
                    f"category={metrics['category_match_rate']:.2%}"
                )
            experiments[name] = languages

    winner_name, winner_languages = max(experiments.items(), key=selection_key)
    winner_key = selection_key((winner_name, winner_languages))
    tfidf = load_json(Path("models/model_experiments.json"))["experiments"]
    topic = load_json(Path("models/topic_aware_experiments.json"))
    report = {
        "status": "completed_with_compatible_local_fallback",
        "methodology": {
            "model_family": "Project-trained latent semantic analysis (TF-IDF + TruncatedSVD)",
            "embedding_type": "Dense L2-normalized sentence/document embeddings",
            "base_features": "TODO 9 Configuration C: word (1,2) + char_wb (3,5)",
            "text_scopes_tested": list(TEXT_SCOPES),
            "dimensions_tested": list(DIMENSIONS),
            "training_data": "Project training split only; no validation labels or categories used for fitting",
            "twi_support": "Learned directly from project Twi text; bilingual variants use aligned English/Twi records",
            "similarity": "Cosine similarity via dot product of L2-normalized dense embeddings",
            "top_k": TOP_K,
            "no_threshold": "TODO 11 compares ranking only; threshold selection occurs later",
            "pretrained_attempt": {
                "model": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
                "backend": "FastEmbed 0.8.0 / ONNX Runtime CPU",
                "outcome": "Not scored because the official model transfer remained incomplete under repeated host/network throttling",
                "integrity_policy": "No metrics are emitted until the complete artifact matches its published SHA-256",
            },
            "selection_order": [
                "macro-average bilingual top-1 accuracy",
                "macro-average bilingual top-3 accuracy",
                "macro-average category-match rate",
                "lower embedding dimensions",
            ],
        },
        "experiments": experiments,
        "winner": {
            "configuration": winner_name,
            "macro_top_1_accuracy": winner_key[0],
            "macro_top_3_accuracy": winner_key[1],
            "macro_category_match_rate": winner_key[2],
            "reason": "Selected using the declared lexicographic validation criteria",
        },
        "comparison": {
            "tfidf_configuration_c": {
                language: tfidf["C_word_and_character"]["languages"][language]["metrics"]
                for language in ("English", "Twi")
            },
            "topic_aware_tfidf": {
                "weights": topic["winner"],
                "metrics": {
                    language: topic["experiments"]["topic_0.62"][language]["metrics"]
                    for language in ("English", "Twi")
                },
            },
        },
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_FILE.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    print(f"Winner: {winner_name}")
    print(f"Saved: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
