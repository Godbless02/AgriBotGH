"""Run TODO 33's live Flask/model integration regression matrix."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import app as agribot
from evaluate_agriculture_edge_cases import evaluate_edge_cases
from evaluate_language_separation import evaluate_language_separation
from evaluate_off_topic_questions import evaluate_challenge


BASE_DIR = Path(__file__).resolve().parent
REPORT_PATH = BASE_DIR / "models" / "integration_regression_results.json"


def evaluate_integration(client=None):
    agribot.app.config.update(TESTING=True)
    client = client or agribot.app.test_client()
    checks = []

    def record(name, passed, evidence):
        checks.append({"name": name, "passed": bool(passed), "evidence": evidence})

    health_response = client.get("/api/health")
    health = health_response.get_json() or {}
    record(
        "frozen_model_health",
        health_response.status_code == 200
        and health.get("model_frozen") is True
        and health.get("semantic_version") == agribot.RETRIEVAL_RUNTIME.metadata["semantic_version"]
        and health.get("freeze_id") == agribot.FINAL_MODEL_FREEZE["freeze_id"],
        health,
    )

    language = evaluate_language_separation(client)
    record("english_twi_and_exact_questions", language["summary"]["failed"] == 0, language["summary"])
    edge = evaluate_edge_cases(client)
    record("paraphrase_and_low_confidence", edge["summary"]["failed"] == 0, edge["summary"])
    off_topic = evaluate_challenge(client)
    record("off_topic", off_topic["summary"]["failed"] == 0, off_topic["summary"])

    topic_response = client.post(
        "/api/topic-suggestions", json={"topic": "Maize", "lang": "en"}
    )
    topic = topic_response.get_json() or {}
    suggestion = (topic.get("suggestions") or [{}])[0]
    clicked_response = client.post(
        "/api/chat",
        json={
            "message": suggestion.get("text", ""),
            "language": "en",
            "suggestion_id": suggestion.get("id"),
        },
    )
    clicked = clicked_response.get_json() or {}
    record(
        "topic_selection_and_suggestion",
        topic_response.status_code == 200
        and len(topic.get("suggestions", [])) > 0
        and clicked_response.status_code == 200
        and clicked.get("source") == "retrieval_v1",
        {"topic": topic.get("topic"), "suggestion_id": suggestion.get("id"), "clicked_source": clicked.get("source")},
    )

    risk_record = agribot.CANONICAL_RECORDS[1]
    risk = client.post(
        "/api/chat",
        json={"message": risk_record["question_en"], "language": "en"},
    ).get_json()
    record(
        "high_risk_safety_layer",
        risk.get("text") == risk_record["answer_en"] and bool(risk.get("safety_notice")),
        {"classification": risk.get("safety_classification"), "notice": risk.get("safety_notice")},
    )

    frontend_source = (BASE_DIR / "app.js").read_text(encoding="utf-8")
    browser_contracts = {
        "history_language_bound": "responseLang" in frontend_source and "sess.lang" in frontend_source,
        "manual_tts": "speakBotResponse" in frontend_source and "speechSynthesis.speak" in frontend_source,
        "responsive_suite": (BASE_DIR / "tests" / "responsive.spec.js").exists(),
        "browser_tests_required": True,
    }
    record("browser_contracts_present", all(browser_contracts.values()), browser_contracts)

    failed = [check for check in checks if not check["passed"]]
    return {
        "schema_version": 1,
        "todo": 33,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "active_model": health.get("model_version"),
        "freeze_id": health.get("freeze_id"),
        "summary": {"total_checks": len(checks), "passed": len(checks) - len(failed), "failed": len(failed)},
        "checks": checks,
        "browser_verification": "Run npm test; Python checks confirm contracts exist but do not substitute for Playwright.",
    }


def main():
    report = evaluate_integration()
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = report["summary"]
    print(f"Integration regression: {summary['passed']}/{summary['total_checks']} checks passed")
    print(f"Report: {REPORT_PATH}")
    if summary["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
