"""Execute TODO 35's 70 backend presentation cases; browser executes 10 TTS cases."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import app as agribot


BASE_DIR = Path(__file__).resolve().parent
SET_PATH = BASE_DIR / "data" / "evaluation" / "final_presentation_test_set.json"
REPORT_PATH = BASE_DIR / "models" / "presentation_test_results.json"
EXPECTED_COUNTS = {
    "english_question": 20,
    "twi_question": 20,
    "paraphrased_question": 10,
    "off_topic_question": 10,
    "topic_selection": 10,
    "tts": 10,
}


def load_set():
    with SET_PATH.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if data.get("schema_version") != 1 or data.get("todo") != 35:
        raise ValueError("Unexpected presentation schema")
    if data.get("case_count") != 80 or data.get("group_counts") != EXPECTED_COUNTS:
        raise ValueError("Presentation group counts are incomplete")
    cases = data.get("cases", [])
    if len(cases) != 80 or len({case.get("id") for case in cases}) != 80:
        raise ValueError("Presentation cases must contain 80 unique IDs")
    return data


def evaluate_backend(client=None):
    data = load_set()
    agribot.app.config.update(TESTING=True)
    client = client or agribot.app.test_client()
    results = []
    for case in data["cases"]:
        if case["group"] == "tts":
            results.append({"id": case["id"], "group": "tts", "status": "requires_browser", "passed": None})
            continue
        failures = []
        if case["group"] == "topic_selection":
            response = client.post(
                "/api/topic-suggestions",
                json={"topic": case["topic"], "lang": case["language"]},
            )
            payload = response.get_json() or {}
            actual_ids = [item.get("id") for item in payload.get("suggestions", [])]
            if response.status_code != 200:
                failures.append(f"HTTP {response.status_code}")
            if actual_ids != case["expected_suggestion_ids"]:
                failures.append("topic suggestions do not match the canonical linkage")
            actual = {"status": response.status_code, "suggestion_ids": actual_ids}
        else:
            response = client.post(
                "/api/chat",
                json={"message": case["message"], "language": case["language"]},
            )
            payload = response.get_json() or {}
            if response.status_code != 200:
                failures.append(f"HTTP {response.status_code}")
            if payload.get("language") != case["language"]:
                failures.append("response language mismatch")
            expected_type = case.get("expected_type")
            expected_state = case.get("expected_state")
            if expected_type and payload.get("type") != expected_type:
                failures.append(f"expected type {expected_type}, got {payload.get('type')}")
            if expected_state and payload.get("routing_state") != expected_state:
                failures.append(f"expected state {expected_state}, got {payload.get('routing_state')}")
            if case.get("allowed_types") and payload.get("type") not in case["allowed_types"]:
                failures.append("response type is outside allowed presentation behavior")
            if case.get("allowed_states") and payload.get("routing_state") not in case["allowed_states"]:
                failures.append("routing state is outside allowed presentation behavior")
            if "expected_text" in case and payload.get("text") != case["expected_text"]:
                failures.append("canonical answer text mismatch")
            if "expected_record_id" in case and payload.get("record_id") != case["expected_record_id"]:
                failures.append("canonical record ID mismatch")
            actual = {
                "status": response.status_code,
                "type": payload.get("type"),
                "routing_state": payload.get("routing_state"),
                "record_id": payload.get("record_id"),
            }
        results.append({"id": case["id"], "group": case["group"], "passed": not failures, "failures": failures, "actual": actual})

    backend = [result for result in results if result["group"] != "tts"]
    backend_failed = [result for result in backend if not result["passed"]]
    return {
        "schema_version": 1,
        "todo": 35,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "test_set": "data/evaluation/final_presentation_test_set.json",
        "summary": {
            "total_cases": 80,
            "backend_cases": 70,
            "backend_passed": len(backend) - len(backend_failed),
            "backend_failed": len(backend_failed),
            "tts_cases": 10,
            "tts_passed": 0,
            "tts_failed": 0,
            "tts_pending_browser": 10,
            "total_passed": len(backend) - len(backend_failed),
            "complete": False,
        },
        "results": results,
    }


def main():
    report = evaluate_backend()
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = report["summary"]
    print(f"Presentation backend: {summary['backend_passed']}/{summary['backend_cases']} passed; TTS browser cases pending={summary['tts_pending_browser']}")
    print(f"Report: {REPORT_PATH}")
    if summary["backend_failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
