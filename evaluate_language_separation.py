"""Evaluate TODO 25 English/Twi retrieval and response separation."""

from __future__ import annotations

import json
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

import app as agribot


BASE_DIR = Path(__file__).resolve().parent
REPORT_PATH = BASE_DIR / "models" / "language_separation_results.json"


def category_representatives():
    """Select one deterministic canonical record from every category."""
    selected = OrderedDict()
    for record in agribot.CANONICAL_RECORDS:
        selected.setdefault(record["category"], record)
    return list(selected.values())


def evaluate_language_separation(client=None):
    agribot.app.config.update(TESTING=True)
    client = client or agribot.app.test_client()
    records_by_id = {record["id"]: record for record in agribot.CANONICAL_RECORDS}
    results = []

    for record in category_representatives():
        for language, code, question_field, answer_field, opposite_answer in (
            ("English", "en", "question_en", "answer_en", "answer_twi"),
            ("Twi", "tw", "question_twi", "answer_twi", "answer_en"),
        ):
            response = client.post(
                "/api/chat",
                json={"message": record[question_field], "language": code},
            )
            payload = response.get_json() or {}
            failures = []
            if response.status_code != 200:
                failures.append(f"HTTP {response.status_code}")
            if payload.get("language") != code:
                failures.append("response language code does not match the request")
            if payload.get("type") != "answer" or payload.get("routing_state") != "A":
                failures.append("exact canonical question did not return State A")
            if payload.get("text") != record[answer_field]:
                failures.append(f"response did not use {answer_field}")
            if record[answer_field] != record[opposite_answer] and payload.get("text") == record[opposite_answer]:
                failures.append("response crossed into the opposite-language answer")

            retrieval = agribot.RETRIEVAL_RUNTIME.retrieve(
                f"Please clarify: {record[question_field]}", code
            )
            if retrieval["language"] != language:
                failures.append("retrieval used the wrong language artifact")
            for candidate in retrieval["candidates"]:
                canonical = records_by_id[candidate["id"]]
                if candidate["question"] != canonical[question_field]:
                    failures.append("candidate question came from the wrong language")
                    break
                if candidate["answer"] != canonical[answer_field]:
                    failures.append("candidate answer came from the wrong language")
                    break

            results.append({
                "record_id": record["id"],
                "category": record["category"],
                "language": language,
                "language_code": code,
                "response_type": payload.get("type"),
                "routing_state": payload.get("routing_state"),
                "retrieval_language": retrieval["language"],
                "top_candidate_id": retrieval["candidates"][0]["id"],
                "passed": not failures,
                "failures": failures,
            })

    invalid = client.post(
        "/api/chat", json={"message": "How do I grow maize?", "language": "fr"}
    )
    invalid_language_rejected = invalid.status_code == 400
    failed = [result for result in results if not result["passed"]]
    return {
        "schema_version": 1,
        "todo": 25,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "canonical_dataset": "data/agribotgh_dataset_bilingual_563.json",
        "categories_tested": len(category_representatives()),
        "summary": {
            "total_language_cases": len(results),
            "passed": len(results) - len(failed),
            "failed": len(failed),
            "english_cases": sum(r["language"] == "English" for r in results),
            "twi_cases": sum(r["language"] == "Twi" for r in results),
            "cross_language_errors": len(failed),
            "invalid_language_rejected": invalid_language_rejected,
        },
        "results": results,
    }


def main():
    report = evaluate_language_separation()
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    summary = report["summary"]
    print(
        f"Language separation: {summary['passed']}/{summary['total_language_cases']} "
        f"passed across {report['categories_tested']} categories; "
        f"cross-language errors={summary['cross_language_errors']}"
    )
    print(f"Invalid language rejected: {summary['invalid_language_rejected']}")
    print(f"Report: {REPORT_PATH}")
    if summary["failed"] or not summary["invalid_language_rejected"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
