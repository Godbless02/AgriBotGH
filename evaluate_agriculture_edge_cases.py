"""Validate and execute TODO 24's bilingual agricultural edge-case set."""

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
EDGE_PATH = BASE_DIR / "data" / "evaluation" / "agriculture_edge_cases.json"
CANONICAL_PATH = BASE_DIR / "data" / "agribotgh_dataset_bilingual_563.json"
REPORT_PATH = BASE_DIR / "models" / "agriculture_edge_case_results.json"
EXPECTED_EDGE_TYPES = {
    "vague", "incomplete", "spelling_error", "colloquial", "short",
    "long", "paraphrase", "multiple_topics",
}
REQUIRED_FIELDS = {
    "id", "pair_id", "language", "edge_type", "question",
    "allowed_types", "allowed_states", "allow_answer",
}

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as source:
        return json.load(source)


def normalize_question(value: str) -> str:
    return " ".join(re.sub(r"[^\wɛɔƐƆ]+", " ", value.casefold()).split())


def validate_edge_dataset(data: Any, canonical: Any) -> None:
    if not isinstance(data, dict) or not isinstance(data.get("cases"), list):
        raise ValueError("Agricultural edge-case file must contain a cases array")
    cases = data["cases"]
    if data.get("schema_version") != 1 or data.get("todo") != 24:
        raise ValueError("Unexpected agricultural edge-case schema")
    if data.get("case_count") != len(cases) or data.get("pair_count") * 2 != len(cases):
        raise ValueError("Declared edge-case counts do not match the cases")
    if set(data.get("edge_types", [])) != EXPECTED_EDGE_TYPES:
        raise ValueError("The edge-case catalogue does not cover all TODO 24 types")

    ids = [item.get("id") for item in cases]
    normalized = [normalize_question(str(item.get("question", ""))) for item in cases]
    if len(set(ids)) != len(ids) or len(set(normalized)) != len(normalized):
        raise ValueError("Edge-case IDs and normalized questions must be unique")
    canonical_questions = {
        normalize_question(record[field])
        for record in canonical
        for field in ("question_en", "question_twi")
    }
    overlap = set(normalized) & canonical_questions
    if overlap:
        raise ValueError(f"Edge cases must not use exact canonical questions: {sorted(overlap)}")

    pairs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in cases:
        missing = REQUIRED_FIELDS - set(item)
        if missing:
            raise ValueError(f"{item.get('id')} is missing fields: {sorted(missing)}")
        if item["language"] not in {"English", "Twi"}:
            raise ValueError(f"{item['id']} has an invalid language")
        if item["edge_type"] not in EXPECTED_EDGE_TYPES:
            raise ValueError(f"{item['id']} has an invalid edge type")
        if not item["question"].strip() or not item["allowed_types"]:
            raise ValueError(f"{item['id']} has an empty question or behavior set")
        if "off_topic" in item["allowed_types"] or "C" in item["allowed_states"]:
            raise ValueError(f"{item['id']} must not permit an off-topic outcome")
        if item["allow_answer"]:
            raise ValueError(f"{item['id']} must not permit a confident answer")
        pairs[item["pair_id"]].append(item)

    if len(pairs) != data["pair_count"]:
        raise ValueError("Pair count does not match unique pair IDs")
    for pair_id, pair in pairs.items():
        if len(pair) != 2 or {item["language"] for item in pair} != {"English", "Twi"}:
            raise ValueError(f"{pair_id} must contain one English and one Twi case")
        if len({item["edge_type"] for item in pair}) != 1:
            raise ValueError(f"{pair_id} must use the same edge type in both languages")

    language_counts = Counter(item["language"] for item in cases)
    type_counts = Counter(item["edge_type"] for item in cases)
    if language_counts != {"English": data["pair_count"], "Twi": data["pair_count"]}:
        raise ValueError("English and Twi edge-case counts must be balanced")
    if set(type_counts.values()) != {4}:
        raise ValueError("Every edge type must have exactly two bilingual pairs")


def evaluate_edge_cases(client=None) -> dict[str, Any]:
    edge_data = load_json(EDGE_PATH)
    validate_edge_dataset(edge_data, load_json(CANONICAL_PATH))
    agribot.app.config.update(TESTING=True)
    client = client or agribot.app.test_client()
    results = []

    for item in edge_data["cases"]:
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
        response_type = payload.get("type")
        state = payload.get("routing_state")
        if response_type not in item["allowed_types"]:
            failures.append(
                f"type was {response_type!r}, allowed {item['allowed_types']}"
            )
        if state not in item["allowed_states"]:
            failures.append(f"state was {state!r}, allowed {item['allowed_states']}")
        if response_type == "answer" and not item["allow_answer"]:
            failures.append("ambiguous edge case received an unapproved confident answer")
        if response_type == "off_topic" or state == "C":
            failures.append("agricultural edge case was incorrectly rejected as unrelated")
        if not isinstance(payload.get("text"), str) or not payload["text"].strip():
            failures.append("response text is missing")
        if response_type == "low_confidence":
            if not isinstance(payload.get("suggestions"), list) or not payload["suggestions"]:
                failures.append("State B response has no safe suggestions")
        if response_type == "topics":
            if not isinstance(payload.get("topics"), list) or len(payload["topics"]) != 28:
                failures.append("vague response does not provide all 28 topics")

        results.append(
            {
                **item,
                "actual": {
                    "http_status": response.status_code,
                    "response_type": response_type,
                    "routing_state": state,
                    "source": payload.get("source"),
                    "domain_score": payload.get("domain_score"),
                    "domain_signal": payload.get("domain_signal"),
                    "suggestion_count": len(payload.get("suggestions", []))
                    if isinstance(payload.get("suggestions"), list)
                    else 0,
                    "elapsed_ms": round(elapsed_ms, 3),
                },
                "passed": not failures,
                "failures": failures,
            }
        )

    failed = [result for result in results if not result["passed"]]
    type_counts = Counter(result["edge_type"] for result in results)
    type_passed = Counter(result["edge_type"] for result in results if result["passed"])
    language_counts = Counter(result["language"] for result in results)
    language_passed = Counter(result["language"] for result in results if result["passed"])
    response_distribution = Counter(
        f"{result['actual']['response_type']}/{result['actual']['routing_state']}"
        for result in results
    )
    return {
        "schema_version": 1,
        "todo": 24,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "edge_case_file": EDGE_PATH.relative_to(BASE_DIR).as_posix(),
        "active_model": agribot.RETRIEVAL_RUNTIME.metadata["semantic_version"],
        "summary": {
            "total": len(results),
            "passed": len(results) - len(failed),
            "failed": len(failed),
            "stable_response_rate": (len(results) - len(failed)) / len(results),
            "off_topic_errors": sum(
                result["actual"]["routing_state"] == "C" for result in results
            ),
            "unapproved_answers": sum(
                result["actual"]["response_type"] == "answer" for result in results
            ),
        },
        "response_distribution": dict(sorted(response_distribution.items())),
        "groups": {
            "edge_type": {
                edge_type: {"total": total, "passed": type_passed[edge_type]}
                for edge_type, total in sorted(type_counts.items())
            },
            "language": {
                language: {"total": total, "passed": language_passed[language]}
                for language, total in sorted(language_counts.items())
            },
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
    report = evaluate_edge_cases()
    write_report(report, args.output)
    for result in report["results"]:
        marker = "PASS" if result["passed"] else "FAIL"
        print(
            f"[{marker}] {result['id']} ({result['edge_type']}): "
            f"{result['actual']['response_type']}/{result['actual']['routing_state']}"
        )
        for failure in result["failures"]:
            print(f"       {failure}")
    summary = report["summary"]
    print(
        f"\nResult: {summary['passed']}/{summary['total']} stable; "
        f"off-topic errors={summary['off_topic_errors']}; "
        f"unapproved answers={summary['unapproved_answers']}"
    )
    print(f"Report: {args.output}")
    if summary["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
