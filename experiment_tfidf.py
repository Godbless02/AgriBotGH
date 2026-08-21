"""Compare baseline and improved TF-IDF retrieval configurations.

Experiments are trained in memory and evaluated against the manually curated
gold standard. This script never overwrites the saved Flask/model artifacts.
"""

import json
import re
import sys
import time
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.pipeline import FeatureUnion


TRAIN_FILE = Path("data/splits/train.json")
GOLD_FILE = Path("data/evaluation/gold_standard.json")
OUTPUT_FILE = Path("models/model_experiments.json")
TOP_K = 3

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


CONFIGURATIONS = {
    "A_word_unigram": {
        "description": "Word TF-IDF with unigrams only.",
        "components": [
            {
                "name": "word",
                "analyzer": "word",
                "ngram_range": [1, 1],
                "sublinear_tf": True,
                "min_df": 1,
                "max_df": 1.0,
            }
        ],
    },
    "B_word_unigram_bigram": {
        "description": "Baseline word TF-IDF with unigrams and bigrams.",
        "components": [
            {
                "name": "word",
                "analyzer": "word",
                "ngram_range": [1, 2],
                "sublinear_tf": True,
                "min_df": 1,
                "max_df": 0.95,
            }
        ],
    },
    "C_word_and_character": {
        "description": "Word (1,2) plus character-within-word (3,5) TF-IDF.",
        "components": [
            {
                "name": "word",
                "analyzer": "word",
                "ngram_range": [1, 2],
                "sublinear_tf": True,
                "min_df": 1,
                "max_df": 0.95,
            },
            {
                "name": "character",
                "analyzer": "char_wb",
                "ngram_range": [3, 5],
                "sublinear_tf": True,
                "min_df": 1,
                "max_df": 1.0,
            },
        ],
    },
}


def load_json(path):
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def clean_text(value):
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def build_vectorizer(configuration):
    components = configuration["components"]
    vectorizers = []
    for component in components:
        vectorizers.append(
            (
                component["name"],
                TfidfVectorizer(
                    analyzer=component["analyzer"],
                    ngram_range=tuple(component["ngram_range"]),
                    sublinear_tf=component["sublinear_tf"],
                    min_df=component["min_df"],
                    max_df=component["max_df"],
                ),
            )
        )
    return vectorizers[0][1] if len(vectorizers) == 1 else FeatureUnion(vectorizers)


def safe_rate(numerator, denominator):
    return numerator / denominator if denominator else 0.0


def evaluate(configuration, train, gold_entries, language):
    field = "question_en" if language == "English" else "question_twi"
    training_questions = [clean_text(row[field]) for row in train]
    training_ids = [row["id"] for row in train]
    training_categories = [row["category"] for row in train]

    vectorizer = build_vectorizer(configuration)
    fit_start = time.perf_counter()
    matrix = vectorizer.fit_transform(training_questions)
    fit_seconds = time.perf_counter() - fit_start

    results = []
    retrieval_times = []
    for gold in gold_entries:
        started = time.perf_counter()
        query = vectorizer.transform([clean_text(gold["question"])])
        scores = cosine_similarity(query, matrix)[0]
        indices = np.argsort(scores)[::-1][:TOP_K]
        retrieval_times.append(time.perf_counter() - started)

        candidates = [
            {
                "rank": rank,
                "train_id": training_ids[index],
                "category": training_categories[index],
                "similarity": float(scores[index]),
            }
            for rank, index in enumerate(indices, start=1)
        ]
        ids = [candidate["train_id"] for candidate in candidates]
        expected = gold["expected_training_record"]
        results.append({
            "validation_id": gold["validation_id"],
            "answerable": gold["answerable"],
            "expected_training_record": expected,
            "top_1_correct": bool(gold["answerable"] and ids[0] == expected),
            "top_3_correct": bool(gold["answerable"] and expected in ids),
            "top_1_category_match": candidates[0]["category"] == gold["category"],
            "candidates": candidates,
        })

    answerable = sum(result["answerable"] for result in results)
    top_1_hits = sum(result["top_1_correct"] for result in results)
    top_3_hits = sum(result["top_3_correct"] for result in results)
    top_scores = [result["candidates"][0]["similarity"] for result in results]
    matrix_bytes = matrix.data.nbytes + matrix.indices.nbytes + matrix.indptr.nbytes
    return {
        "metrics": {
            "total_cases": len(results),
            "answerable_cases": answerable,
            "top_1_correct": top_1_hits,
            "top_3_correct": top_3_hits,
            "top_1_accuracy": safe_rate(top_1_hits, answerable),
            "top_3_accuracy": safe_rate(top_3_hits, answerable),
            "precision": safe_rate(top_1_hits, len(results)),
            "coverage": 1.0,
            "average_top_1_similarity": float(np.mean(top_scores)),
            "category_match_rate": safe_rate(
                sum(result["top_1_category_match"] for result in results), len(results)
            ),
        },
        "cost": {
            "feature_count": int(matrix.shape[1]),
            "matrix_nonzero_values": int(matrix.nnz),
            "matrix_storage_bytes": int(matrix_bytes),
            "fit_seconds": fit_seconds,
            "average_retrieval_seconds": float(np.mean(retrieval_times)),
        },
        "results": results,
    }


def selection_key(item):
    _, result = item
    english = result["languages"]["English"]["metrics"]
    twi = result["languages"]["Twi"]["metrics"]
    return (
        (english["top_1_accuracy"] + twi["top_1_accuracy"]) / 2,
        (english["top_3_accuracy"] + twi["top_3_accuracy"]) / 2,
        (english["category_match_rate"] + twi["category_match_rate"]) / 2,
        -sum(
            result["languages"][language]["cost"]["feature_count"]
            for language in ("English", "Twi")
        ),
    )


def main():
    train = load_json(TRAIN_FILE)
    gold = load_json(GOLD_FILE)
    experiments = {}

    for name, configuration in CONFIGURATIONS.items():
        print(f"Running {name}...")
        languages = {}
        for language in ("English", "Twi"):
            entries = [entry for entry in gold["entries"] if entry["language"] == language]
            languages[language] = evaluate(configuration, train, entries, language)
            metrics = languages[language]["metrics"]
            print(
                f"  {language}: top-1={metrics['top_1_accuracy']:.2%}, "
                f"top-3={metrics['top_3_accuracy']:.2%}"
            )
        experiments[name] = {
            "description": configuration["description"],
            "configuration": configuration,
            "languages": languages,
        }

    winner_name, winner = max(experiments.items(), key=selection_key)
    winner_key = selection_key((winner_name, winner))
    report = {
        "methodology": {
            "training_records": len(train),
            "validation_records": gold["validation_records"],
            "top_k": TOP_K,
            "correctness": "Expected training record from data/evaluation/gold_standard.json.",
            "selection_order": [
                "macro-average English/Twi top-1 accuracy",
                "macro-average English/Twi top-3 accuracy",
                "macro-average category-match rate",
                "lower total feature count",
            ],
            "note": "No confidence threshold or topic weighting is used in TODO 9.",
        },
        "experiments": experiments,
        "winner": {
            "configuration": winner_name,
            "macro_top_1_accuracy": winner_key[0],
            "macro_top_3_accuracy": winner_key[1],
            "macro_category_match_rate": winner_key[2],
            "reason": "Selected using the declared lexicographic validation criteria.",
        },
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_FILE.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    print(f"Winner: {winner_name}")
    print(f"Saved: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
