import json
import sys
from pathlib import Path

import joblib
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity


# ============================================================
# FILES
# ============================================================

MODEL_DIR = Path("models")

ENGLISH_MODEL = MODEL_DIR / "english_model.joblib"
TWI_MODEL = MODEL_DIR / "twi_model.joblib"

VALIDATION_FILE = Path("data/splits/validation.json")

OUTPUT_FILE = MODEL_DIR / "answerability_report.json"


# ============================================================
# SETTINGS
# ============================================================

TOP_K = 3

# Ensure English and Twi review text can be printed on Windows terminals whose
# inherited code page cannot represent Akan characters such as ɛ and ɔ.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# These are REVIEW bands, not final confidence thresholds.
# They help us organize the validation set for inspection.
REVIEW_HIGH = 0.60
REVIEW_MEDIUM = 0.40


# ============================================================
# LOADERS
# ============================================================

def load_json(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_model(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"Model not found: {path}")

    return joblib.load(path)


# ============================================================
# RETRIEVE TOP MATCHES
# ============================================================

def get_matches(model, question, top_k=TOP_K):
    vectorizer = model["vectorizer"]
    matrix = model["matrix"]

    questions = model["questions"]
    answers = model["answers"]
    ids = model["ids"]
    categories = model["categories"]

    query_vector = vectorizer.transform([question])

    scores = cosine_similarity(
        query_vector,
        matrix
    )[0]

    top_indices = np.argsort(scores)[::-1][:top_k]

    matches = []

    for rank, idx in enumerate(top_indices, start=1):
        matches.append({
            "rank": rank,
            "train_id": ids[idx],
            "question": questions[idx],
            "answer": answers[idx],
            "category": categories[idx],
            "similarity": float(scores[idx]),
        })

    return matches


# ============================================================
# CLASSIFY MATCH STRENGTH
# ============================================================

def classify_strength(score):
    if score >= REVIEW_HIGH:
        return "Strong candidate"

    if score >= REVIEW_MEDIUM:
        return "Possible candidate"

    return "Weak candidate"


# ============================================================
# CATEGORY CHECK
# ============================================================

def same_category(validation_category, training_category):
    if not validation_category:
        return False

    if not training_category:
        return False

    return (
        str(validation_category).strip().lower()
        == str(training_category).strip().lower()
    )


# ============================================================
# ANALYZE ONE LANGUAGE
# ============================================================

def analyze_language(
    model,
    validation_data,
    question_field,
    answer_field,
    language_name,
):
    results = []

    for record in validation_data:
        question = str(record[question_field]).strip()
        validation_category = record.get(
            "category",
            "Unknown"
        )

        matches = get_matches(
            model,
            question,
            TOP_K
        )

        for match in matches:
            match["category_match"] = same_category(
                validation_category,
                match["category"],
            )
            match["answerability_classification"] = classify_strength(
                match["similarity"]
            )

        top_match = matches[0]

        category_match = same_category(
            validation_category,
            top_match["category"]
        )

        result = {
            "validation_id": record["id"],
            "language": language_name,
            "category": validation_category,
            "question": question,
            "expected_answer": record[answer_field],
            "top_match": top_match,
            "category_match": category_match,
            "strength": classify_strength(
                top_match["similarity"]
            ),
            "top_3_matches": matches,
        }

        results.append(result)

    return results


# ============================================================
# PRINT REVIEW SUMMARY
# ============================================================

def print_summary(results, language):
    print("\n" + "=" * 80)
    print(f"{language.upper()} ANSWERABILITY SUMMARY")
    print("=" * 80)

    total = len(results)

    strong = sum(
        1 for r in results
        if r["strength"] == "Strong candidate"
    )

    possible = sum(
        1 for r in results
        if r["strength"] == "Possible candidate"
    )

    weak = sum(
        1 for r in results
        if r["strength"] == "Weak candidate"
    )

    category_matches = sum(
        1 for r in results
        if r["category_match"]
    )

    print(f"Total validation questions: {total}")
    print(
        f"Strong candidates (>= {REVIEW_HIGH:.2f}): "
        f"{strong}"
    )
    print(
        f"Possible candidates "
        f"({REVIEW_MEDIUM:.2f}–{REVIEW_HIGH - 0.01:.2f}): "
        f"{possible}"
    )
    print(
        f"Weak candidates (< {REVIEW_MEDIUM:.2f}): "
        f"{weak}"
    )

    print(
        f"Top match same category: "
        f"{category_matches}/{total}"
    )

    if total:
        print(
            f"Same-category rate: "
            f"{category_matches / total:.2%}"
        )


# ============================================================
# SHOW ITEMS FOR HUMAN REVIEW
# ============================================================

def print_review_items(results, language, limit=15):
    print("\n" + "=" * 80)
    print(f"{language.upper()} ITEMS REQUIRING REVIEW")
    print("=" * 80)

    # Sort weakest first
    review = sorted(
        results,
        key=lambda r: r["top_match"]["similarity"]
    )

    for i, item in enumerate(review[:limit], start=1):
        print("\n" + "-" * 80)

        print(f"[{i}] Validation ID: {item['validation_id']}")
        print(f"Category: {item['category']}")
        print(f"Strength: {item['strength']}")
        print(f"Category match: {item['category_match']}")

        print(
            f"\nValidation question:\n"
            f"{item['question']}"
        )

        print(
            "\nTop candidate:"
        )

        top = item["top_match"]

        print(
            f"Similarity: {top['similarity']:.4f}"
        )

        print(
            f"Training category: {top['category']}"
        )

        print(
            f"Training question:\n"
            f"{top['question']}"
        )

        print(
            f"Training answer:\n"
            f"{top['answer']}"
        )

        print("\nOther candidates:")

        for match in item["top_3_matches"][1:]:
            print(
                f"  {match['rank']}. "
                f"{match['similarity']:.4f} | "
                f"{match['category']} | "
                f"{match['question']}"
            )


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 80)
    print("AgriBotGH ANSWERABILITY ANALYSIS")
    print("=" * 80)

    validation_data = load_json(
        VALIDATION_FILE
    )

    english_model = load_model(
        ENGLISH_MODEL
    )

    twi_model = load_model(
        TWI_MODEL
    )

    print(
        f"\nValidation records: "
        f"{len(validation_data)}"
    )

    # --------------------------------------------------------
    # English
    # --------------------------------------------------------

    print("\nAnalyzing English...")

    english_results = analyze_language(
        model=english_model,
        validation_data=validation_data,
        question_field="question_en",
        answer_field="answer_en",
        language_name="English",
    )

    print_summary(
        english_results,
        "English"
    )

    print_review_items(
        english_results,
        "English"
    )

    # --------------------------------------------------------
    # Twi
    # --------------------------------------------------------

    print("\nAnalyzing Twi...")

    twi_results = analyze_language(
        model=twi_model,
        validation_data=validation_data,
        question_field="question_twi",
        answer_field="answer_twi",
        language_name="Twi",
    )

    print_summary(
        twi_results,
        "Twi"
    )

    print_review_items(
        twi_results,
        "Twi"
    )

    # --------------------------------------------------------
    # SAVE REPORT
    # --------------------------------------------------------

    report = {
        "review_thresholds": {
            "strong": REVIEW_HIGH,
            "possible": REVIEW_MEDIUM,
        },
        "validation_records": len(validation_data),
        "english": english_results,
        "twi": twi_results,
    }

    with OUTPUT_FILE.open(
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            report,
            f,
            ensure_ascii=False,
            indent=2,
        )

    print("\n" + "=" * 80)
    print("ANSWERABILITY ANALYSIS COMPLETE")
    print("=" * 80)

    print(
        f"\nFull report saved to:\n"
        f"{OUTPUT_FILE}"
    )

    print(
        "\nIMPORTANT:"
        "\nThe strong/possible/weak bands are for manual review."
        "\nThey are NOT the final chatbot confidence thresholds."
    )


if __name__ == "__main__":
    main()
