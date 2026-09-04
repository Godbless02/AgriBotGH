"""Evaluate fresh non-canonical paraphrases and ambiguous farming controls."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import app as agribot


BASE_DIR = Path(__file__).resolve().parent
CASE_FILE = BASE_DIR / "data/evaluation/retrieval_challenge_v2.json"
OUTPUT_FILE = BASE_DIR / "models/retrieval_challenge_v2_results.json"


def evaluate():
    cases = json.loads(CASE_FILE.read_text(encoding="utf-8"))
    client = agribot.app.test_client()
    positive_results = []
    for case in cases["positive_cases"]:
        code = "tw" if case["language"] == "Twi" else "en"
        runtime = agribot.RETRIEVAL_RUNTIME.retrieve(case["question"], code)
        response = client.post(
            "/api/chat", json={"message": case["question"], "language": code}
        ).get_json()
        candidate = runtime["candidates"][0]
        top_correct = candidate["id"] in case["acceptable_record_ids"]
        answered_correctly = (
            response.get("routing_state") == "A"
            and int(response["record_id"].split("-")[1])
                in case["acceptable_record_ids"]
        )
        positive_results.append({
            **case,
            "state": response.get("routing_state"),
            "top_record_id": candidate["id"],
            "top_correct": top_correct,
            "answered_correctly": answered_correctly,
            "unsafe_answer": response.get("routing_state") == "A" and not answered_correctly,
            "raw_similarity": candidate["raw_tfidf_similarity"],
            "term_coverage": candidate["weighted_query_term_coverage"],
            "raw_margin": runtime["raw_similarity_margin"],
            "match_level": runtime["match_level"],
        })

    ambiguous_results = []
    for case in cases["ambiguous_agriculture_cases"]:
        code = "tw" if case["language"] == "Twi" else "en"
        response = client.post(
            "/api/chat", json={"message": case["question"], "language": code}
        ).get_json()
        ambiguous_results.append({
            **case,
            "state": response.get("routing_state"),
            "type": response.get("type"),
            "record_id": response.get("record_id"),
            "safe_uncertain": response.get("routing_state") in {"B", "D"},
        })

    languages = {}
    for language in ("English", "Twi"):
        selected = [x for x in positive_results if x["language"] == language]
        languages[language] = {
            "cases": len(selected),
            "top_1_correct": sum(x["top_correct"] for x in selected),
            "top_1_accuracy": sum(x["top_correct"] for x in selected) / len(selected),
            "correct_answers": sum(x["answered_correctly"] for x in selected),
            "answer_coverage": sum(x["answered_correctly"] for x in selected) / len(selected),
            "unsafe_answers": sum(x["unsafe_answer"] for x in selected),
            "states": dict(Counter(x["state"] for x in selected)),
        }
    report = {
        "schema_version": 1,
        "active_model": agribot.RETRIEVAL_RUNTIME.metadata["model_version"],
        "case_file": str(CASE_FILE.relative_to(BASE_DIR)).replace("\\", "/"),
        "languages": languages,
        "ambiguous_agriculture": {
            "cases": len(ambiguous_results),
            "safe_uncertain": sum(x["safe_uncertain"] for x in ambiguous_results),
            "unsafe_answers": sum(x["state"] == "A" for x in ambiguous_results),
            "incorrect_off_topic": sum(x["state"] == "C" for x in ambiguous_results),
        },
        "positive_results": positive_results,
        "ambiguous_results": ambiguous_results,
    }
    OUTPUT_FILE.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def main():
    report = evaluate()
    for language, metrics in report["languages"].items():
        print(
            f"{language}: top-1 {metrics['top_1_correct']}/{metrics['cases']}; "
            f"correct answers {metrics['correct_answers']}/{metrics['cases']}; "
            f"unsafe={metrics['unsafe_answers']}"
        )
    ambiguous = report["ambiguous_agriculture"]
    print(
        f"Ambiguous agriculture: safe B/D={ambiguous['safe_uncertain']}/{ambiguous['cases']}; "
        f"unsafe A={ambiguous['unsafe_answers']}; incorrect C={ambiguous['incorrect_off_topic']}"
    )
    print(f"Report: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
