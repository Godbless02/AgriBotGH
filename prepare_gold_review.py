"""Prepare bilingual candidate evidence for manual gold-standard review.

This script does not decide whether a validation item is answerable. It ranks
same-category training records using the validation question and reference
answer in both languages so a reviewer can inspect candidates beyond the
baseline retriever's question-only top three.
"""

import json
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


TRAIN_FILE = Path("data/splits/train.json")
VALIDATION_FILE = Path("data/splits/validation.json")
OUTPUT_FILE = Path("models/gold_review_candidates.json")
TOP_K = 8


def load_json(path):
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def similarity_scores(query, documents):
    corpus = [query, *documents]
    matrix = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True).fit_transform(corpus)
    return cosine_similarity(matrix[0], matrix[1:])[0]


def main():
    train = load_json(TRAIN_FILE)
    validation = load_json(VALIDATION_FILE)
    review_items = []

    for item in validation:
        candidates = [row for row in train if row["category"] == item["category"]]
        if not candidates:
            candidates = train

        evidence_fields = (
            ("question_en", 0.15),
            ("answer_en", 0.35),
            ("question_twi", 0.15),
            ("answer_twi", 0.35),
        )
        combined = np.zeros(len(candidates), dtype=float)
        field_scores = {}
        for field, weight in evidence_fields:
            scores = similarity_scores(item[field], [row[field] for row in candidates])
            field_scores[field] = scores
            combined += weight * scores

        best_indices = np.argsort(combined)[::-1][:TOP_K]
        ranked = []
        for rank, index in enumerate(best_indices, start=1):
            row = candidates[int(index)]
            ranked.append({
                "rank": rank,
                "train_id": row["id"],
                "category": row["category"],
                "question_en": row["question_en"],
                "answer_en": row["answer_en"],
                "question_twi": row["question_twi"],
                "answer_twi": row["answer_twi"],
                "evidence": {
                    "combined": float(combined[index]),
                    **{
                        field: float(scores[index])
                        for field, scores in field_scores.items()
                    },
                },
            })

        review_items.append({
            "validation_id": item["id"],
            "category": item["category"],
            "question_en": item["question_en"],
            "answer_en": item["answer_en"],
            "question_twi": item["question_twi"],
            "answer_twi": item["answer_twi"],
            "candidates": ranked,
        })

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_FILE.open("w", encoding="utf-8") as handle:
        json.dump(
            {
                "purpose": "Review evidence only; not automatic gold labels.",
                "validation_records": len(review_items),
                "top_k": TOP_K,
                "items": review_items,
            },
            handle,
            ensure_ascii=False,
            indent=2,
        )
    print(f"Wrote {len(review_items)} review items to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
