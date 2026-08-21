import json
from pathlib import Path

import joblib
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity


# ============================================================
# PATHS
# ============================================================

MODEL_DIR = Path("models")

ENGLISH_MODEL_FILE = MODEL_DIR / "english_model.joblib"
TWI_MODEL_FILE = MODEL_DIR / "twi_model.joblib"

VALIDATION_FILE = Path("data/splits/validation.json")

OUTPUT_FILE = MODEL_DIR / "retrieval_candidates.json"


# ============================================================
# SETTINGS
# ============================================================

TOP_K = 3

# Similarity thresholds we want to inspect later.
THRESHOLDS = [
    0.50,
    0.55,
    0.60,
    0.65,
    0.70,
    0.75,
    0.80,
    0.85,
]


# ============================================================
# LOADERS
# ============================================================

def load_model(path: Path):
    if not path.exists():
        raise FileNotFoundError(
            f"Model file not found: {path}"
        )

    return joblib.load(path)


def load_validation_data():
    if not VALIDATION_FILE.exists():
        raise FileNotFoundError(
            f"Validation file not found: {VALIDATION_FILE}"
        )

    with VALIDATION_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)


# ============================================================
# TOP-K RETRIEVAL
# ============================================================

def get_top_matches(model, question, top_k=3):
    """
    Retrieve the top-k most similar training questions.
    """

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

    # Get indices of highest scores.
    top_indices = np.argsort(scores)[::-1][:top_k]

    matches = []

    for rank, index in enumerate(top_indices, start=1):

        matches.append({
            "rank": rank,
            "train_id": ids[index],
            "question": questions[index],
            "answer": answers[index],
            "category": categories[index],
            "similarity": float(scores[index]),
        })

    return matches


# ============================================================
# PRINT MATCHES
# ============================================================

def print_match(index, language, validation_record, matches):
    question_field = (
        "question_en"
        if language == "English"
        else "question_twi"
    )

    answer_field = (
        "answer_en"
        if language == "English"
        else "answer_twi"
    )

    validation_question = validation_record[question_field]
    expected_answer = validation_record[answer_field]

    print("\n" + "=" * 80)
    print(
        f"{language.upper()} VALIDATION RECORD #{index}"
    )
    print("=" * 80)

    print(f"Validation ID: {validation_record['id']}")
    print(f"\nQuestion:\n{validation_question}")

    print("\nExpected answer:")
    print(expected_answer)

    print("\nTop matches from training set:")

    for match in matches:
        print("\n" + "-" * 70)
        print(f"Rank:       {match['rank']}")
        print(f"Train ID:   {match['train_id']}")
        print(f"Similarity: {match['similarity']:.4f}")
        print(f"Category:   {match['category']}")
        print(f"Question:   {match['question']}")
        print(f"Answer:     {match['answer']}")


# ============================================================
# BUILD RETRIEVAL REPORT
# ============================================================

def evaluate_language(model, validation_data, language):

    question_field = (
        "question_en"
        if language == "English"
        else "question_twi"
    )

    answer_field = (
        "answer_en"
        if language == "English"
        else "answer_twi"
    )

    all_results = []

    for record in validation_data:

        question = str(
            record[question_field]
        ).strip()

        matches = get_top_matches(
            model=model,
            question=question,
            top_k=TOP_K,
        )

        result = {
            "validation_id": record["id"],
            "question": question,
            "expected_answer": record[answer_field],
            "category": record.get(
                "category",
                "General Agriculture"
            ),
            "matches": matches,
        }

        all_results.append(result)

    return all_results


# ============================================================
# THRESHOLD STATISTICS
# ============================================================

def calculate_threshold_stats(results, language):

    print("\n" + "=" * 80)
    print(f"{language.upper()} SIMILARITY DISTRIBUTION")
    print("=" * 80)

    top_scores = [
        item["matches"][0]["similarity"]
        for item in results
        if item["matches"]
    ]

    if not top_scores:
        return {}

    top_scores_np = np.array(top_scores)

    print(
        f"Minimum top-1 similarity: "
        f"{top_scores_np.min():.4f}"
    )

    print(
        f"Maximum top-1 similarity: "
        f"{top_scores_np.max():.4f}"
    )

    print(
        f"Average top-1 similarity: "
        f"{top_scores_np.mean():.4f}"
    )

    print(
        f"Median top-1 similarity: "
        f"{np.median(top_scores_np):.4f}"
    )

    print("\nCoverage by threshold:")

    stats = {}

    for threshold in THRESHOLDS:

        accepted = sum(
            1
            for score in top_scores
            if score >= threshold
        )

        coverage = (
            accepted / len(top_scores)
            if top_scores
            else 0
        )

        stats[str(threshold)] = {
            "accepted": accepted,
            "total": len(top_scores),
            "coverage": coverage,
        }

        print(
            f"Threshold {threshold:.2f}: "
            f"{accepted}/{len(top_scores)} "
            f"({coverage:.2%}) accepted"
        )

    return stats


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 80)
    print("AgriBotGH TOP-3 RETRIEVAL EVALUATION")
    print("=" * 80)

    # --------------------------------------------------------
    # Load data/models
    # --------------------------------------------------------

    validation_data = load_validation_data()

    english_model = load_model(
        ENGLISH_MODEL_FILE
    )

    twi_model = load_model(
        TWI_MODEL_FILE
    )

    print(
        f"\nValidation records: "
        f"{len(validation_data)}"
    )

    # --------------------------------------------------------
    # English evaluation
    # --------------------------------------------------------

    print("\nGenerating English candidates...")

    english_results = evaluate_language(
        model=english_model,
        validation_data=validation_data,
        language="English",
    )

    english_stats = calculate_threshold_stats(
        english_results,
        "English",
    )

    # --------------------------------------------------------
    # Twi evaluation
    # --------------------------------------------------------

    print("\nGenerating Twi candidates...")

    twi_results = evaluate_language(
        model=twi_model,
        validation_data=validation_data,
        language="Twi",
    )

    twi_stats = calculate_threshold_stats(
        twi_results,
        "Twi",
    )

    # --------------------------------------------------------
    # Save full report
    # --------------------------------------------------------

    report = {
        "validation_records": len(validation_data),
        "top_k": TOP_K,

        "english": {
            "threshold_statistics": english_stats,
            "results": english_results,
        },

        "twi": {
            "threshold_statistics": twi_stats,
            "results": twi_results,
        },
    }

    MODEL_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

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

    # --------------------------------------------------------
    # Print sample results
    # --------------------------------------------------------

    print("\n" + "=" * 80)
    print("SAMPLE ENGLISH RESULTS")
    print("=" * 80)

    for index, result in enumerate(
        english_results[:5],
        start=1
    ):

        print(
            f"\n[{index}] "
            f"{result['question']}"
        )

        for match in result["matches"]:

            print(
                f"   {match['rank']}. "
                f"{match['similarity']:.4f} - "
                f"{match['question']}"
            )

    print("\n" + "=" * 80)
    print("SAMPLE TWI RESULTS")
    print("=" * 80)

    for index, result in enumerate(
        twi_results[:5],
        start=1
    ):

        print(
            f"\n[{index}] "
            f"{result['question']}"
        )

        for match in result["matches"]:

            print(
                f"   {match['rank']}. "
                f"{match['similarity']:.4f} - "
                f"{match['question']}"
            )

    print("\n" + "=" * 80)
    print("EVALUATION COMPLETE")
    print("=" * 80)

    print(
        f"\nFull report saved to:\n"
        f"{OUTPUT_FILE}"
    )


if __name__ == "__main__":
    main()