"""Evaluate saved retrieval models against the manually curated gold standard.

Correctness is based on gold-standard training-record mappings. Validation IDs
are used only to join questions to their gold labels; they are never compared
with training IDs as a correctness criterion.
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import joblib
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity


MODEL_DIR = Path("models")
GOLD_FILE = Path("data/evaluation/gold_standard.json")
OUTPUT_FILE = MODEL_DIR / "retrieval_evaluation.json"
TOP_K = 3

LANGUAGES = {
    "English": MODEL_DIR / "english_model.joblib",
    "Twi": MODEL_DIR / "twi_model.joblib",
}

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def load_json(path):
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_model(path):
    if not path.exists():
        raise FileNotFoundError(path)
    model = joblib.load(path)
    required = {"vectorizer", "matrix", "questions", "answers", "ids", "categories"}
    missing = required - set(model)
    if missing:
        raise ValueError(f"{path} is missing fields: {sorted(missing)}")
    lengths = {len(model[key]) for key in ("questions", "answers", "ids", "categories")}
    if lengths != {model["matrix"].shape[0]}:
        raise ValueError(f"{path} contains inconsistent training artifact lengths")
    return model


def retrieve(model, question, top_k=TOP_K):
    query = model["vectorizer"].transform([question])
    scores = cosine_similarity(query, model["matrix"])[0]
    indices = np.argsort(scores)[::-1][:top_k]
    return [
        {
            "rank": rank,
            "train_id": model["ids"][index],
            "category": model["categories"][index],
            "question": model["questions"][index],
            "similarity": float(scores[index]),
        }
        for rank, index in enumerate(indices, start=1)
    ]


def safe_rate(numerator, denominator):
    return numerator / denominator if denominator else 0.0


def confusion_report(results):
    all_errors = Counter()
    answerable_errors = Counter()
    matrix = defaultdict(Counter)

    for result in results:
        if result["top_1_correct"]:
            continue
        expected = result["validation_category"]
        predicted = result["candidates"][0]["category"]
        matrix[expected][predicted] += 1
        all_errors[(expected, predicted)] += 1
        if result["answerable"]:
            answerable_errors[(expected, predicted)] += 1

    def rows(counter):
        return [
            {"expected_category": expected, "predicted_category": predicted, "count": count}
            for (expected, predicted), count in sorted(
                counter.items(), key=lambda item: (-item[1], item[0][0], item[0][1])
            )
        ]

    return {
        "all_incorrect_top_1": rows(all_errors),
        "answerable_incorrect_top_1": rows(answerable_errors),
        "matrix": {
            expected: dict(sorted(predictions.items()))
            for expected, predictions in sorted(matrix.items())
        },
    }


def evaluate_language(language, model, gold_entries):
    results = []
    for gold in gold_entries:
        candidates = retrieve(model, gold["question"])
        candidate_ids = [candidate["train_id"] for candidate in candidates]
        expected_id = gold["expected_training_record"]
        top_1_correct = bool(gold["answerable"] and candidate_ids[0] == expected_id)
        top_3_correct = bool(gold["answerable"] and expected_id in candidate_ids)
        expected_rank = candidate_ids.index(expected_id) + 1 if top_3_correct else None
        results.append({
            "validation_id": gold["validation_id"],
            "language": language,
            "validation_category": gold["category"],
            "question": gold["question"],
            "answerable": gold["answerable"],
            "expected_training_record": expected_id,
            "top_1_correct": top_1_correct,
            "top_3_correct": top_3_correct,
            "expected_rank": expected_rank,
            "top_1_category_match": candidates[0]["category"] == gold["category"],
            "candidates": candidates,
        })

    total = len(results)
    answerable = sum(result["answerable"] for result in results)
    unsupported = total - answerable
    top_1_hits = sum(result["top_1_correct"] for result in results)
    top_3_hits = sum(result["top_3_correct"] for result in results)
    category_matches = sum(result["top_1_category_match"] for result in results)
    answerable_category_matches = sum(
        result["top_1_category_match"] for result in results if result["answerable"]
    )
    similarities = [result["candidates"][0]["similarity"] for result in results]

    # This baseline always returns a candidate and has no abstention mechanism.
    returned = total
    unsupported_returns = unsupported
    metrics = {
        "total_cases": total,
        "answerable_cases": answerable,
        "unsupported_cases": unsupported,
        "top_1_correct": top_1_hits,
        "top_3_correct": top_3_hits,
        "top_1_accuracy": safe_rate(top_1_hits, answerable),
        "top_3_accuracy": safe_rate(top_3_hits, answerable),
        "precision": safe_rate(top_1_hits, returned),
        "coverage": safe_rate(returned, total),
        "gold_answerable_rate": safe_rate(answerable, total),
        "unsupported_false_positive_rate": safe_rate(unsupported_returns, unsupported),
        "average_top_1_similarity": float(np.mean(similarities)) if similarities else 0.0,
        "median_top_1_similarity": float(np.median(similarities)) if similarities else 0.0,
        "category_match_rate": safe_rate(category_matches, total),
        "answerable_category_match_rate": safe_rate(answerable_category_matches, answerable),
    }
    return {
        "metrics": metrics,
        "category_confusion": confusion_report(results),
        "results": results,
    }


def main():
    gold = load_json(GOLD_FILE)
    entries = gold.get("entries", [])
    if not entries:
        raise ValueError("Gold standard contains no entries")

    report = {
        "evaluation_method": {
            "correctness": "Gold-standard expected_training_record mapping.",
            "top_1_accuracy": "Correct top-1 retrievals divided by gold-answerable cases.",
            "top_3_accuracy": "Gold record present in top 3 divided by gold-answerable cases.",
            "precision": "Correct top-1 retrievals divided by all returned top-1 predictions.",
            "coverage": "Cases receiving a prediction divided by all cases.",
            "category_match_rate": "Top-1 category equals validation category, independent of correctness.",
            "baseline_abstention": "None; therefore baseline coverage and unsupported false-positive rate are 100%.",
        },
        "gold_standard": str(GOLD_FILE),
        "top_k": TOP_K,
        "languages": {},
    }

    for language, model_path in LANGUAGES.items():
        language_entries = [entry for entry in entries if entry["language"] == language]
        if len(language_entries) != gold["validation_records"]:
            raise ValueError(f"Expected {gold['validation_records']} {language} cases")
        report["languages"][language] = evaluate_language(
            language, load_model(model_path), language_entries
        )

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_FILE.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)

    for language, section in report["languages"].items():
        metrics = section["metrics"]
        print(f"\n{language}")
        print(f"  Top-1 accuracy: {metrics['top_1_accuracy']:.2%}")
        print(f"  Top-3 accuracy: {metrics['top_3_accuracy']:.2%}")
        print(f"  Precision: {metrics['precision']:.2%}")
        print(f"  Coverage: {metrics['coverage']:.2%}")
        print(f"  Average similarity: {metrics['average_top_1_similarity']:.4f}")
        print(f"  Category-match rate: {metrics['category_match_rate']:.2%}")
    print(f"\nSaved: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
