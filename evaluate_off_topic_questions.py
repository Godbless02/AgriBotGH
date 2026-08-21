"""Validate and execute TODO 23's independent off-topic challenge set."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import app as agribot


BASE_DIR = Path(__file__).resolve().parent
CHALLENGE_PATH = BASE_DIR / "data" / "evaluation" / "off_topic_questions.json"
LEGACY_PATH = BASE_DIR / "data" / "evaluation" / "off_topic_cases.json"
REPORT_PATH = BASE_DIR / "models" / "off_topic_question_results.json"
REQUIRED_FIELDS = {
    "id", "pair_id", "language", "difficulty", "domain", "question", "expected_state"
}

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as source:
        return json.load(source)


def normalize_question(value: str) -> str:
    return " ".join(re.sub(r"[^\wɛɔƐƆ]+", " ", value.casefold()).split())


def validate_challenge(data: Any, legacy: Any) -> None:
    if not isinstance(data, dict) or not isinstance(data.get("cases"), list):
        raise ValueError("Off-topic challenge must contain a cases array")
    cases = data["cases"]
    if data.get("schema_version") != 1 or data.get("todo") != 23:
        raise ValueError("Unexpected off-topic challenge schema")
    if data.get("case_count") != len(cases) or data.get("pair_count") * 2 != len(cases):
        raise ValueError("Declared off-topic counts do not match the cases")
    if len(cases) < 40:
        raise ValueError("Off-topic challenge must contain at least 40 bilingual cases")

    ids = [item.get("id") for item in cases]
    questions = [normalize_question(str(item.get("question", ""))) for item in cases]
    if len(set(ids)) != len(ids):
        raise ValueError("Off-topic case IDs must be unique")
    if len(set(questions)) != len(questions):
        raise ValueError("Off-topic questions must be unique after normalization")

    pairs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in cases:
        missing = REQUIRED_FIELDS - set(item)
        if missing:
            raise ValueError(f"{item.get('id')} is missing fields: {sorted(missing)}")
        if any(not str(item[field]).strip() for field in REQUIRED_FIELDS):
            raise ValueError(f"{item.get('id')} contains an empty required field")
        if item["language"] not in {"English", "Twi"}:
            raise ValueError(f"{item['id']} has an invalid language")
        if item["difficulty"] not in {"ordinary", "hard_negative"}:
            raise ValueError(f"{item['id']} has an invalid difficulty")
        if item["expected_state"] != "C":
            raise ValueError(f"{item['id']} must be labelled State C")
        pairs[item["pair_id"]].append(item)

    if len(pairs) != data["pair_count"]:
        raise ValueError("Pair IDs are not unique at the intent level")
    for pair_id, pair in pairs.items():
        if len(pair) != 2 or {item["language"] for item in pair} != {"English", "Twi"}:
            raise ValueError(f"{pair_id} must contain exactly one English and one Twi case")
        if len({item["domain"] for item in pair}) != 1:
            raise ValueError(f"{pair_id} language cases must use the same domain")

    legacy_questions = {
        normalize_question(item["question"]) for item in legacy.get("cases", [])
    }
    overlap = sorted(set(questions) & legacy_questions)
    if overlap:
        raise ValueError(f"TODO 23 questions duplicate legacy router cases: {overlap}")

    language_counts = Counter(item["language"] for item in cases)
    difficulty_counts = Counter(item["difficulty"] for item in cases)
    expected_language_count = data["pair_count"]
    if language_counts != {"English": expected_language_count, "Twi": expected_language_count}:
        raise ValueError("English and Twi challenge counts must be balanced")
    if difficulty_counts["ordinary"] != difficulty_counts["hard_negative"]:
        raise ValueError("Ordinary and hard-negative challenge counts must be balanced")


def evaluate_challenge(client=None) -> dict[str, Any]:
    challenge = load_json(CHALLENGE_PATH)
    validate_challenge(challenge, load_json(LEGACY_PATH))
    agribot.app.config.update(TESTING=True)
    client = client or agribot.app.test_client()
    results = []

    for item in challenge["cases"]:
        language_code = "tw" if item["language"] == "Twi" else "en"
        started = time.perf_counter()
        response = client.post(
            "/api/chat", json={"message": item["question"], "language": language_code}
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        payload = response.get_json()
        failures = []
        if response.status_code != 200:
            failures.append(f"HTTP {response.status_code}")
        if not isinstance(payload, dict):
            failures.append("response is not a JSON object")
            payload = {}
        if payload.get("type") != "off_topic":
            failures.append(f"type was {payload.get('type')!r}, expected 'off_topic'")
        if payload.get("routing_state") != "C":
            failures.append(
                f"state was {payload.get('routing_state')!r}, expected 'C'"
            )
        if payload.get("source") != "retrieval_v1":
            failures.append("response did not come from the validated router")
        if payload.get("record_id") is not None:
            failures.append("off-topic response exposed an agricultural answer record")
        if not isinstance(payload.get("topics"), list) or len(payload["topics"]) != 28:
            failures.append("off-topic response did not provide the 28-topic recovery path")
        results.append(
            {
                **item,
                "actual": {
                    "http_status": response.status_code,
                    "response_type": payload.get("type"),
                    "routing_state": payload.get("routing_state"),
                    "domain_score": payload.get("domain_score"),
                    "elapsed_ms": round(elapsed_ms, 3),
                },
                "passed": not failures,
                "failures": failures,
            }
        )

    group_counts: dict[str, Counter[str]] = {
        "language": Counter(),
        "difficulty": Counter(),
    }
    group_passed: dict[str, Counter[str]] = {
        "language": Counter(),
        "difficulty": Counter(),
    }
    for result in results:
        for grouping in group_counts:
            value = result[grouping]
            group_counts[grouping][value] += 1
            if result["passed"]:
                group_passed[grouping][value] += 1

    failed = [result for result in results if not result["passed"]]
    return {
        "schema_version": 1,
        "todo": 23,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "challenge_file": CHALLENGE_PATH.relative_to(BASE_DIR).as_posix(),
        "active_model": agribot.RETRIEVAL_RUNTIME.metadata["semantic_version"],
        "summary": {
            "total": len(results),
            "passed": len(results) - len(failed),
            "failed": len(failed),
            "state_c_recall": (len(results) - len(failed)) / len(results),
            "agricultural_answers_returned": sum(
                result["actual"]["response_type"] == "answer" for result in results
            ),
        },
        "groups": {
            grouping: {
                value: {"total": total, "passed": group_passed[grouping][value]}
                for value, total in sorted(counts.items())
            }
            for grouping, counts in group_counts.items()
        },
        "results": results,
    }


def write_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=REPORT_PATH)
    args = parser.parse_args()
    report = evaluate_challenge()
    write_report(report, args.output)
    for result in report["results"]:
        marker = "PASS" if result["passed"] else "FAIL"
        print(
            f"[{marker}] {result['id']} ({result['difficulty']}): "
            f"{result['actual']['response_type']}/{result['actual']['routing_state']}"
        )
        for failure in result["failures"]:
            print(f"       {failure}")
    summary = report["summary"]
    print(
        f"\nResult: {summary['passed']}/{summary['total']} rejected correctly; "
        f"State-C recall={summary['state_c_recall']:.2%}; "
        f"agricultural answers returned={summary['agricultural_answers_returned']}"
    )
    print(f"Report: {args.output}")
    if summary["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
