"""Opt-in live evaluation of Gemini's narrow retrieval assistance role."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from retrieval_assistance import attempt_retrieval_assistance
from retrieval_runtime import RetrievalRuntime
from services.gemini_service import GeminiService


BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "data" / "agribotgh_dataset_bilingual_563.json"
CASES_FILE = BASE_DIR / "data" / "evaluation" / "gemini_retrieval_cases.json"
OUTPUT_FILE = BASE_DIR / "models" / "gemini_assistance_evaluation.json"


def main() -> int:
    cases = json.loads(CASES_FILE.read_text(encoding="utf-8"))
    runtime = RetrievalRuntime(BASE_DIR, DATA_FILE)
    service = GeminiService()
    availability = service.availability()
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": DATA_FILE.relative_to(BASE_DIR).as_posix(),
        "dataset_records": 563,
        "model": service.model,
        "case_count": len(cases),
        "status": "completed" if service.available else "skipped",
        "skip_reason": None if service.available else availability["reason"],
        "results": [],
    }
    if service.available:
        for case in cases:
            original = runtime.retrieve(case["query"], case["language"])
            assistance = attempt_retrieval_assistance(
                case["query"], case["language"], original, runtime, service
            )
            selected = assistance["selected_retrieval"]
            selected_id = selected["candidates"][0]["id"]
            second = assistance["interpreted_retrieval"]
            report["results"].append({
                "case_id": case["case_id"],
                "language": case["language"],
                "original_question": case["query"],
                "expected_record_id": case["expected_record_id"],
                "initial_state": original["state"],
                "original_retrieval_match": original["candidates"][0]["id"],
                "original_similarity": assistance["original_score"],
                "called": assistance["called"],
                "interpreted_query": assistance["interpreted_query"],
                "second_retrieval_match": (
                    second["candidates"][0]["id"] if second else None
                ),
                "second_similarity": assistance["interpreted_score"],
                "accepted": assistance["accepted"],
                "reason": assistance["reason"],
                "selected_record_id": selected_id,
                "final_selected_answer_source": (
                    "canonical_dataset" if selected["state"] == "A"
                    else "safe_local_fallback"
                ),
                "correct": (
                    selected["state"] == "A"
                    and selected_id == case["expected_record_id"]
                ),
            })
        report["accepted_count"] = sum(item["accepted"] for item in report["results"])
        report["correct_count"] = sum(item["correct"] for item in report["results"])
        report["correct_rate"] = report["correct_count"] / len(cases)

    OUTPUT_FILE.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Gemini evaluation {report['status']}: {OUTPUT_FILE}")
    if report["status"] == "skipped":
        print("Set GEMINI_API_KEY to run the live cases; no provider call was made.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
