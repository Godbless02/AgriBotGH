r"""TODO 22 final executable model test suite.

Run with::

    .\agribot_env\Scripts\python.exe test_model.py

The suite exercises the live Flask/model contract in both supported languages
and writes an inspectable JSON report. It exits non-zero if any required
behavior fails.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import app as agribot


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_REPORT = BASE_DIR / "models" / "final_model_test_results.json"
VALID_RESPONSE_TYPES = {
    "answer", "low_confidence", "off_topic", "topics", "knowledge_gap"
}

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def case(
    case_id: str,
    group: str,
    language: str,
    message: str | None,
    **expected: Any,
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "group": group,
        "language": language,
        "message": message,
        "expected": expected,
    }


LONG_ENGLISH = "maize " + (
    "crop farming soil water pest disease harvest fertilizer " * 30
)
LONG_TWI = "aburo " + ("afuo nsuo yadeɛ nnuru otwa bere " * 30)

MODEL_CASES = [
    # English required cases.
    case(
        "en_exact_known",
        "exact_known_question",
        "en",
        "What fertilizer is best for maize?",
        status=200,
        response_type="answer",
        state="A",
        source="retrieval_v1",
        record_id="qa-0002",
        canonical_answer=True,
    ),
    case(
        "en_paraphrase",
        "paraphrased_question",
        "en",
        "Which fertiliser should I apply to my maize crop?",
        status=200,
        response_type="answer",
        state="A",
        source="retrieval_v1",
        record_id="qa-0210",
        canonical_answer=True,
    ),
    case(
        "en_agricultural",
        "agricultural_question",
        "en",
        "How should I prepare the soil before planting maize?",
        status=200,
        response_type="answer",
        state="A",
        source="retrieval_v1",
        record_id="qa-0208",
        canonical_answer=True,
    ),
    case(
        "en_unsupported_agriculture",
        "unsupported_agricultural_question",
        "en",
        "How can I grow quinoa successfully near Accra?",
        status=200,
        response_type="knowledge_gap",
        state="D",
        minimum_topics=1,
    ),
    case(
        "en_unrelated",
        "unrelated_question",
        "en",
        "Who won the football match last night?",
        status=200,
        response_type="off_topic",
        state="C",
    ),
    # Twi required cases.
    case(
        "tw_exact_known",
        "exact_known_question",
        "tw",
        "Bere bɛn na ɛyɛ ɔkorɔ sɛ wode aburow to mu wɔ Ghana?",
        status=200,
        response_type="answer",
        state="A",
        source="retrieval_v1",
        record_id="qa-0016",
        canonical_answer=True,
    ),
    case(
        "tw_paraphrase",
        "paraphrased_question",
        "tw",
        "Bere pa bɛn na ɛsɛ sɛ medua aburo wɔ Ghana?",
        status=200,
        response_type="knowledge_gap",
        state="D",
        minimum_topics=1,
    ),
    case(
        "tw_agricultural",
        "agricultural_question",
        "tw",
        "Mɛyɛ dɛn atɔ aburo wɔ m afuo mu?",
        status=200,
        response_type="knowledge_gap",
        state="D",
        minimum_topics=1,
    ),
    case(
        "tw_unsupported_agriculture",
        "unsupported_agricultural_question",
        "tw",
        "Mɛyɛ dɛn adua quinoa wɔ Ghana?",
        status=200,
        response_type="knowledge_gap",
        state="D",
        minimum_topics=1,
    ),
    case(
        "tw_unrelated",
        "unrelated_question",
        "tw",
        "Hena na odii bɔɔlbɔ no mu nkonim anadwo no?",
        status=200,
        response_type="off_topic",
        state="C",
    ),
    # Input-shape and robustness cases.
    case(
        "empty_input",
        "empty_input",
        "en",
        "",
        status=400,
        error="No message provided",
    ),
    case(
        "whitespace_input",
        "empty_input",
        "tw",
        "   ",
        status=400,
        error="No message provided",
    ),
    case(
        "en_extremely_short",
        "extremely_short_input",
        "en",
        "maize",
        status=200,
        response_type="topics",
        topic_count=28,
    ),
    case(
        "tw_extremely_short",
        "extremely_short_input",
        "tw",
        "aburo",
        status=200,
        response_type="topics",
        topic_count=28,
    ),
    case(
        "en_capitalization_punctuation",
        "capitalization_and_punctuation",
        "en",
        "WHAT FERTILIZER IS BEST FOR MAIZE!!!",
        status=200,
        response_type="answer",
        state="A",
        source="retrieval_v1",
        record_id="qa-0002",
        canonical_answer=True,
    ),
    case(
        "tw_capitalization_punctuation",
        "capitalization_and_punctuation",
        "tw",
        "BERE BƐN NA ƐYƐ ƆKORƆ SƐ WODE ABUROW TO MU WƆ GHANA!!!",
        status=200,
        response_type="answer",
        state="A",
        source="retrieval_v1",
        record_id="qa-0016",
        canonical_answer=True,
    ),
    case(
        "en_long_input",
        "very_long_input",
        "en",
        LONG_ENGLISH,
        status=200,
        allowed_response_types=sorted(VALID_RESPONSE_TYPES),
        stability_only=True,
    ),
    case(
        "tw_long_input",
        "very_long_input",
        "tw",
        LONG_TWI,
        status=200,
        allowed_response_types=sorted(VALID_RESPONSE_TYPES),
        stability_only=True,
    ),
    case(
        "mixed_en_twi",
        "mixed_language_input",
        "en",
        "How do I stop mmoawa from damaging my aburo crop?",
        status=200,
        response_type="knowledge_gap",
        state="D",
        minimum_topics=1,
    ),
    case(
        "mixed_twi_en",
        "mixed_language_input",
        "tw",
        "Mɛyɛ dɛn control pests wɔ me maize farm?",
        status=200,
        allowed_response_types=["knowledge_gap", "low_confidence", "off_topic"],
        allowed_states=["D", "B", "C"],
        stability_only=True,
    ),
    case(
        "english_sent_to_twi_channel",
        "language_separation",
        "tw",
        "What fertilizer is best for maize?",
        status=200,
        response_type="off_topic",
        state="C",
    ),
    case(
        "twi_sent_to_english_channel",
        "language_separation",
        "en",
        "Ferefere bɛn na ɛyɛ papa ma aburo?",
        status=200,
        response_type="off_topic",
        state="C",
    ),
]


def evaluate_response(
    definition: dict[str, Any], status_code: int, payload: Any, elapsed_ms: float
) -> dict[str, Any]:
    expected = definition["expected"]
    failures = []
    if status_code != expected["status"]:
        failures.append(f"status expected {expected['status']}, received {status_code}")
    if not isinstance(payload, dict):
        failures.append("response body is not a JSON object")
        payload = {}

    response_type = payload.get("type")
    if "response_type" in expected and response_type != expected["response_type"]:
        failures.append(
            f"type expected {expected['response_type']!r}, received {response_type!r}"
        )
    if "allowed_response_types" in expected and response_type not in expected["allowed_response_types"]:
        failures.append(f"type {response_type!r} is outside the allowed stability set")

    state = payload.get("routing_state")
    if "state" in expected and state != expected["state"]:
        failures.append(f"state expected {expected['state']!r}, received {state!r}")
    if "allowed_states" in expected and state not in expected["allowed_states"]:
        failures.append(f"state {state!r} is outside the allowed stability set")
    if "source" in expected and payload.get("source") != expected["source"]:
        failures.append(
            f"source expected {expected['source']!r}, received {payload.get('source')!r}"
        )
    if (
        "forbidden_source" in expected
        and expected["forbidden_source"] == payload.get("source")
    ):
        failures.append(f"forbidden source {payload.get('source')!r} was used")
    if "record_id" in expected and payload.get("record_id") != expected["record_id"]:
        failures.append(
            f"record expected {expected['record_id']!r}, received {payload.get('record_id')!r}"
        )
    if expected.get("canonical_answer"):
        record = agribot.KNOWN_RECORDS[expected["record_id"]]
        answer_field = "answer_tw" if definition["language"] == "tw" else "answer_en"
        if payload.get("text") != record[answer_field]:
            failures.append("answer text does not match the canonical language record")
    if "minimum_suggestions" in expected:
        suggestions = payload.get("suggestions")
        if not isinstance(suggestions, list) or len(suggestions) < expected["minimum_suggestions"]:
            failures.append("safe follow-up suggestions are missing")
    if "minimum_topics" in expected:
        topics = payload.get("available_topics")
        if not isinstance(topics, list) or len(topics) < expected["minimum_topics"]:
            failures.append("available dataset topics are missing")
    if "topic_count" in expected:
        topics = payload.get("topics")
        if not isinstance(topics, list) or len(topics) != expected["topic_count"]:
            failures.append(
                f"topic count expected {expected['topic_count']}, received "
                f"{len(topics) if isinstance(topics, list) else None}"
            )
    if "error" in expected and payload.get("error") != expected["error"]:
        failures.append(
            f"error expected {expected['error']!r}, received {payload.get('error')!r}"
        )
    if status_code == 200 and response_type not in VALID_RESPONSE_TYPES:
        failures.append(f"successful response has unsupported type {response_type!r}")

    return {
        "case_id": definition["case_id"],
        "group": definition["group"],
        "language": definition["language"],
        "input_length": len(definition["message"] or ""),
        "expected": expected,
        "actual": {
            "status": status_code,
            "type": response_type,
            "routing_state": state,
            "source": payload.get("source"),
            "record_id": payload.get("record_id"),
            "suggestion_count": len(payload.get("suggestions", []))
            if isinstance(payload.get("suggestions"), list)
            else 0,
            "topic_count": len(payload.get("topics", []))
            if isinstance(payload.get("topics"), list)
            else 0,
            "error": payload.get("error"),
            "elapsed_ms": round(elapsed_ms, 3),
        },
        "passed": not failures,
        "failures": failures,
    }


def run_model_tests(client=None) -> dict[str, Any]:
    agribot.app.config.update(TESTING=True)
    client = client or agribot.app.test_client()
    results = []
    for definition in MODEL_CASES:
        started = time.perf_counter()
        response = client.post(
            "/api/chat",
            json={"message": definition["message"], "language": definition["language"]},
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        results.append(
            evaluate_response(definition, response.status_code, response.get_json(), elapsed_ms)
        )

    group_totals = Counter(result["group"] for result in results)
    group_passed = Counter(result["group"] for result in results if result["passed"])
    failures = [result for result in results if not result["passed"]]
    stability_observations = [
        {
            "case_id": result["case_id"],
            "type": result["actual"]["type"],
            "routing_state": result["actual"]["routing_state"],
            "input_length": result["input_length"],
        }
        for result in results
        if result["expected"].get("stability_only")
    ]
    return {
        "schema_version": 1,
        "todo": 22,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "active_model": {
            "display_version": agribot.RETRIEVAL_RUNTIME.metadata["model_version"],
            "semantic_version": agribot.RETRIEVAL_RUNTIME.metadata["semantic_version"],
            "architecture": agribot.RETRIEVAL_RUNTIME.metadata["retrieval_architecture"],
        },
        "summary": {
            "total": len(results),
            "passed": len(results) - len(failures),
            "failed": len(failures),
            "all_passed": not failures,
        },
        "groups": {
            group: {"total": total, "passed": group_passed[group]}
            for group, total in sorted(group_totals.items())
        },
        "stability_observations": stability_observations,
        "known_limitations": [
            "The conservative model routes unresolved agricultural paraphrases through State B to the user-visible State D instead of returning an automatic answer.",
            "Very long keyword-repetition inputs are stability tests only; their routing state is recorded but not treated as proof of semantic quality.",
            "Mixed-language behavior is supported defensively, but automatic cross-language retrieval is intentionally not enabled.",
        ],
        "results": results,
    }


def write_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    report = run_model_tests()
    write_report(report, args.output)

    print("\n" + "=" * 64)
    print("AGRIBOTGH FINAL MODEL TESTS")
    print("=" * 64)
    for result in report["results"]:
        marker = "PASS" if result["passed"] else "FAIL"
        actual = result["actual"]
        print(
            f"[{marker}] {result['case_id']}: status={actual['status']} "
            f"type={actual['type']} state={actual['routing_state']}"
        )
        for failure in result["failures"]:
            print(f"       {failure}")
    summary = report["summary"]
    print(
        f"\nResult: {summary['passed']}/{summary['total']} passed; "
        f"{summary['failed']} failed"
    )
    print(f"Report: {args.output}")
    if not summary["all_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
