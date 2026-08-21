"""Evaluate TODO 29 response design and TODO 30 agricultural safety handling."""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import app as agribot
from evaluate_agriculture_edge_cases import evaluate_edge_cases
from evaluate_language_separation import evaluate_language_separation
from evaluate_off_topic_questions import evaluate_challenge


BASE_DIR = Path(__file__).resolve().parent
REPORT_PATH = BASE_DIR / "models" / "response_quality_results.json"
PLACEHOLDER_PATTERN = re.compile(r"\b(?:todo|lorem ipsum|insert answer|tbd)\b|\?\?\?", re.I)
ACTION_PATTERN_EN = re.compile(
    r"\b(?:use|apply|plant|remove|keep|check|contact|consult|avoid|store|record|"
    r"monitor|water|feed|clean|wear|follow|ask|seek|test)\b",
    re.I,
)
ACTION_PATTERN_TW = re.compile(
    r"\b(?:fa|de|to|yi|hwɛ|bisa|kora|siesie|guina|gye|di|ka|hware|twa)\b",
    re.I | re.UNICODE,
)


def words(text):
    return re.findall(r"\b[\wɛɔƐƆ'-]+\b", str(text), flags=re.UNICODE)


def audit_canonical_answers(client):
    details = []
    high_risk = []
    lengths = {"English": [], "Twi": []}
    actionable = Counter()
    blockers = []

    for record in agribot.CANONICAL_RECORDS:
        for language, code, question_field, answer_field, action_pattern in (
            ("English", "en", "question_en", "answer_en", ACTION_PATTERN_EN),
            ("Twi", "tw", "question_twi", "answer_twi", ACTION_PATTERN_TW),
        ):
            question = record[question_field]
            answer = record[answer_field]
            word_count = len(words(answer))
            lengths[language].append(word_count)
            is_actionable = bool(action_pattern.search(answer))
            actionable[language] += is_actionable
            failures = []
            if not answer.strip():
                failures.append("empty answer")
            if word_count > 350:
                failures.append("answer exceeds 350 words")
            if PLACEHOLDER_PATTERN.search(answer):
                failures.append("placeholder text detected")
            if "<script" in answer.casefold():
                failures.append("executable HTML detected")
            if failures:
                blockers.append({
                    "record_id": record["id"],
                    "language": language,
                    "failures": failures,
                })

            risky = bool(
                agribot.HIGH_RISK_AGRICULTURE_PATTERN.search(f"{question} {answer}")
            )
            if risky:
                response = client.post(
                    "/api/chat", json={"message": question, "language": code}
                )
                payload = response.get_json() or {}
                notice = payload.get("safety_notice", "")
                notice_ok = (
                    response.status_code == 200
                    and payload.get("safety_classification")
                    == "high_risk_agricultural_guidance"
                    and bool(notice)
                    and (
                        (code == "en" and "label" in notice.casefold() and "consult" in notice.casefold())
                        or (code == "tw" and "mofa" in notice.casefold() and "aduru" in notice.casefold())
                    )
                )
                high_risk.append({
                    "record_id": record["id"],
                    "category": record["category"],
                    "language": language,
                    "notice_present": notice_ok,
                })

            details.append({
                "record_id": record["id"],
                "category": record["category"],
                "language": language,
                "word_count": word_count,
                "actionable_language_detected": is_actionable,
                "high_risk": risky,
                "passed_structural_quality": not failures,
            })

    missing_notices = [item for item in high_risk if not item["notice_present"]]
    length_summary = {
        language: {
            "minimum_words": min(values),
            "maximum_words": max(values),
            "average_words": round(sum(values) / len(values), 2),
            "actionable_answers": actionable[language],
            "total_answers": len(values),
        }
        for language, values in lengths.items()
    }
    return details, blockers, high_risk, missing_notices, length_summary


def evaluate_response_quality(client=None):
    agribot.app.config.update(TESTING=True)
    client = client or agribot.app.test_client()
    details, blockers, high_risk, missing_notices, length_summary = (
        audit_canonical_answers(client)
    )
    edge = evaluate_edge_cases(client)
    off_topic = evaluate_challenge(client)
    language = evaluate_language_separation(client)
    passed = (
        not blockers
        and not missing_notices
        and edge["summary"]["failed"] == 0
        and off_topic["summary"]["failed"] == 0
        and language["summary"]["failed"] == 0
    )
    return {
        "schema_version": 1,
        "todos": [29, 30],
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "passed": passed,
            "canonical_answers_audited": len(details),
            "structural_quality_blockers": len(blockers),
            "high_risk_answers": len(high_risk),
            "high_risk_notices_present": len(high_risk) - len(missing_notices),
            "high_risk_notice_coverage": (
                (len(high_risk) - len(missing_notices)) / len(high_risk)
                if high_risk
                else 1.0
            ),
            "agricultural_edge_cases_passed": edge["summary"]["passed"],
            "off_topic_cases_passed": off_topic["summary"]["passed"],
            "language_cases_passed": language["summary"]["passed"],
        },
        "answer_length_and_actionability": length_summary,
        "structural_blockers": blockers,
        "missing_safety_notices": missing_notices,
        "high_risk_details": high_risk,
        "canonical_answer_details": details,
        "policy": {
            "strong_answer": "Canonical answer plus a safety notice when high-risk terms are detected.",
            "uncertain_agriculture": "State B disclosure, clarification request, and canonical suggestions; no fabricated answer.",
            "off_topic": "State C agricultural scope explanation and topic recovery path; no agricultural answer.",
            "human_review_limit": (
                "Automated checks measure structure, routing, language, and safety-notice coverage. "
                "Agronomic correctness and Twi naturalness still require qualified human review."
            ),
        },
    }


def main():
    report = evaluate_response_quality()
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    summary = report["summary"]
    print(
        f"Response quality: answers={summary['canonical_answers_audited']}, "
        f"blockers={summary['structural_quality_blockers']}, "
        f"high-risk safety coverage={summary['high_risk_notice_coverage']:.2%}"
    )
    print(
        f"Behavior suites: agriculture={summary['agricultural_edge_cases_passed']}/32, "
        f"off-topic={summary['off_topic_cases_passed']}/48, "
        f"language={summary['language_cases_passed']}/80"
    )
    print(f"Report: {REPORT_PATH}")
    if not summary["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
