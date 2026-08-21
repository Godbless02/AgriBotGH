"""Evaluate an isolated multilingual sentence-embedding retriever.

The experiment uses a local ONNX model cache and never changes Flask or the
saved TF-IDF artifacts. Twi quality is determined empirically from the gold
standard because the selected model does not claim explicit Twi training.
"""

import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from fastembed import TextEmbedding

from experiment_tfidf import clean_text, load_json, safe_rate


TRAIN_FILE = Path("data/splits/train.json")
GOLD_FILE = Path("data/evaluation/gold_standard.json")
OUTPUT_FILE = Path("models/embedding_experiments.json")
MODEL_CACHE = Path(os.getenv("AGRIBOT_EMBEDDING_CACHE", "models/embedding_cache"))
MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
TOP_K = 3
BATCH_SIZE = 32

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def normalize_rows(matrix):
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.maximum(norms, 1e-12)


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


def encode(model, texts):
    return normalize_rows(
        np.asarray(list(model.embed(texts, batch_size=BATCH_SIZE)), dtype=np.float32)
    )


def evaluate_language(model, train, gold_entries, language):
    field = "question_en" if language == "English" else "question_twi"
    passages = [clean_text(row[field]) for row in train]
    questions = [clean_text(entry["question"]) for entry in gold_entries]

    train_started = time.perf_counter()
    training_embeddings = encode(model, passages)
    training_seconds = time.perf_counter() - train_started
    query_started = time.perf_counter()
    query_embeddings = encode(model, questions)
    query_seconds = time.perf_counter() - query_started

    similarities = query_embeddings @ training_embeddings.T
    results = []
    for gold, scores in zip(gold_entries, similarities):
        indices = np.argsort(scores)[::-1][:TOP_K]
        candidates = [
            {
                "rank": rank,
                "train_id": train[index]["id"],
                "category": train[index]["category"],
                "question": train[index][field],
                "semantic_similarity": float(scores[index]),
            }
            for rank, index in enumerate(indices, start=1)
        ]
        ids = [candidate["train_id"] for candidate in candidates]
        expected = gold["expected_training_record"]
        results.append({
            "validation_id": gold["validation_id"],
            "validation_category": gold["category"],
            "question": gold["question"],
            "answerable": gold["answerable"],
            "expected_training_record": expected,
            "top_1_correct": bool(gold["answerable"] and ids[0] == expected),
            "top_3_correct": bool(gold["answerable"] and expected in ids),
            "top_1_category_match": candidates[0]["category"] == gold["category"],
            "candidates": candidates,
        })

    total = len(results)
    answerable = sum(result["answerable"] for result in results)
    top_1_hits = sum(result["top_1_correct"] for result in results)
    top_3_hits = sum(result["top_3_correct"] for result in results)
    top_scores = [result["candidates"][0]["semantic_similarity"] for result in results]
    return {
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
            "embedding_dimensions": int(training_embeddings.shape[1]),
            "training_embedding_bytes": int(training_embeddings.nbytes),
            "training_encoding_seconds": training_seconds,
            "query_encoding_seconds": query_seconds,
            "average_query_encoding_seconds": safe_rate(query_seconds, len(questions)),
        },
        "category_confusion": confusion_report(results),
        "results": results,
    }


def main():
    train = load_json(TRAIN_FILE)
    gold = load_json(GOLD_FILE)
    MODEL_CACHE.mkdir(parents=True, exist_ok=True)

    load_started = time.perf_counter()
    model = TextEmbedding(model_name=MODEL_NAME, cache_dir=str(MODEL_CACHE))
    load_seconds = time.perf_counter() - load_started
    languages = {}
    for language in ("English", "Twi"):
        print(f"Evaluating {language} embeddings...")
        entries = [entry for entry in gold["entries"] if entry["language"] == language]
        languages[language] = evaluate_language(model, train, entries, language)
        metrics = languages[language]["metrics"]
        print(
            f"  top-1={metrics['top_1_accuracy']:.2%}, "
            f"top-3={metrics['top_3_accuracy']:.2%}, "
            f"category={metrics['category_match_rate']:.2%}"
        )

    tfidf = load_json(Path("models/model_experiments.json"))["experiments"]
    topic = load_json(Path("models/topic_aware_experiments.json"))
    report = {
        "methodology": {
            "model": MODEL_NAME,
            "backend": "FastEmbed 0.8.0 / ONNX Runtime CPU",
            "model_language_claim": "Multilingual (50 languages); Twi is not explicitly listed.",
            "twi_decision_rule": "Judge suitability only from the held-out Twi gold-standard metrics.",
            "similarity": "Cosine similarity of L2-normalized dense embeddings.",
            "top_k": TOP_K,
            "no_threshold": "TODO 11 compares retrieval ranking only; threshold selection occurs later.",
        },
        "model_load_seconds": load_seconds,
        "languages": languages,
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
    print(f"Saved: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
