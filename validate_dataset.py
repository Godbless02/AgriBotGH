"""Validate AgriBotGH's sole canonical bilingual dataset.

The validator separates objective release-blocking defects from review warnings.
It never edits the dataset. A machine-readable report is written even when
validation fails so that a failed check remains inspectable.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
DATASET_PATH = BASE_DIR / "data" / "agribotgh_dataset_bilingual_563.json"
REPORT_PATH = BASE_DIR / "data" / "evaluation" / "dataset_quality_report.json"
EXPECTED_RECORDS = 563

REQUIRED_FIELDS = (
    "id",
    "category",
    "question_en",
    "answer_en",
    "question_twi",
    "answer_twi",
)
TEXT_FIELDS = REQUIRED_FIELDS[1:]
QUESTION_FIELDS = ("question_en", "question_twi")

# Category membership is exact, including case and whitespace, to prevent
# accidental aliases from being introduced silently.
CANONICAL_CATEGORIES = frozenset(
    {
        "Beekeeping", "Business & Marketing", "Carrot", "Cassava",
        "Cattle Rearing", "Climate-Smart Farming", "Cocoa Farming",
        "Cucumber Farming", "Farm Business Planning",
        "Farm Management & General", "Farm Mechanization & Tools",
        "Farm Records & Extension", "Fertilizer & Nutrients", "Fish Farming",
        "Garden Eggs", "Goat Rearing", "Grasscutter Farming",
        "Groundnut & Legumes", "Harvesting & Storage", "Irrigation & Water",
        "Maize", "Mushroom Farming", "Oil Palm & Coconut", "Okra Farming",
        "Onion", "Palm & Coconut", "Pepper", "Pest & Disease Control",
        "Pig Farming", "Plantain & Banana", "Post-Harvest & Food Safety",
        "Poultry Farming", "Rabbit Farming", "Rice Farming", "Sheep Rearing",
        "Snail Farming", "Soil & Land Preparation", "Tomato",
        "Watermelon Farming", "Yam",
    }
)

# Identified during TODO 19's manual audit. These are review warnings, not
# automatic rewrites: category changes need versioned retraining and evaluation.
MANUAL_CATEGORY_REVIEW = {
    9: "Green manure guidance is labelled Cattle Rearing.",
    15: "Soil compaction guidance is labelled Poultry Farming.",
    43: "Bean rust guidance is labelled Irrigation & Water.",
    85: "Farm profit calculation is labelled Soil & Land Preparation.",
    291: "Poultry brooder guidance is labelled Soil & Land Preparation.",
    318: "Garden egg pest guidance is labelled Pepper.",
}

CONTROL_CHARACTER_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
MOJIBAKE_MARKERS = ("Ã", "Â", "â€", "ï¿½", "�")
NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
TOKEN_RE = re.compile(r"[^\wɛɔƐƆ]+", re.UNICODE)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(TOKEN_RE.sub(" ", normalized).split())


def _issue(code: str, message: str, record_ids: list[int] | None = None) -> dict[str, Any]:
    issue: dict[str, Any] = {"code": code, "message": message}
    if record_ids:
        issue["record_ids"] = record_ids
    return issue


def _duplicate_groups(values: list[tuple[int, str]]) -> list[dict[str, Any]]:
    groups: dict[str, list[int]] = defaultdict(list)
    for record_id, value in values:
        if value:
            groups[normalize_text(value)].append(record_id)
    return [
        {"normalized_text": text, "record_ids": ids}
        for text, ids in sorted(groups.items())
        if len(ids) > 1
    ]


def _cosine(left: Counter[str], right: Counter[str]) -> float:
    numerator = sum(value * right.get(token, 0) for token, value in left.items())
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if not left_norm or not right_norm:
        return 0.0
    return numerator / (left_norm * right_norm)


def _question_features(question: str) -> Counter[str]:
    tokens = normalize_text(question).split()
    features = tokens + [f"{left} {right}" for left, right in zip(tokens, tokens[1:])]
    return Counter(features)


def _near_duplicate_pairs(
    values: list[tuple[int, str]], threshold: float = 0.82
) -> list[dict[str, Any]]:
    """Return close wording matches for review, excluding exact duplicates."""

    features = [(record_id, text, _question_features(text)) for record_id, text in values]
    pairs = []
    for position, (left_id, left_text, left_features) in enumerate(features):
        for right_id, right_text, right_features in features[position + 1 :]:
            if normalize_text(left_text) == normalize_text(right_text):
                continue
            similarity = _cosine(left_features, right_features)
            if similarity >= threshold:
                pairs.append(
                    {"record_ids": [left_id, right_id], "similarity": round(similarity, 3)}
                )
    return sorted(pairs, key=lambda item: (-item["similarity"], item["record_ids"]))


def validate_records(
    data: Any,
    *,
    expected_count: int | None = EXPECTED_RECORDS,
    dataset_path: str = "data/agribotgh_dataset_bilingual_563.json",
    dataset_sha256: str | None = None,
) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    if not isinstance(data, list):
        errors.append(_issue("invalid_root", "The dataset root must be a JSON array."))
        data = []

    if expected_count is not None and len(data) != expected_count:
        errors.append(
            _issue("unexpected_record_count", f"Expected {expected_count} records, found {len(data)}.")
        )

    ids: list[int] = []
    category_counts: Counter[str] = Counter()
    question_values: dict[str, list[tuple[int, str]]] = {
        field: [] for field in QUESTION_FIELDS
    }
    numeric_pairing_review: list[dict[str, Any]] = []

    for position, record in enumerate(data, start=1):
        if not isinstance(record, dict):
            errors.append(
                _issue("invalid_record", f"Record at array position {position} is not an object.")
            )
            continue

        raw_id = record.get("id")
        record_id = raw_id if isinstance(raw_id, int) and not isinstance(raw_id, bool) else None
        issue_ids = [record_id] if record_id is not None else None

        missing = [field for field in REQUIRED_FIELDS if field not in record]
        if missing:
            errors.append(
                _issue(
                    "missing_fields",
                    f"Record at position {position} is missing: {', '.join(missing)}.",
                    issue_ids,
                )
            )

        unexpected = sorted(set(record) - set(REQUIRED_FIELDS))
        if unexpected:
            errors.append(
                _issue("unexpected_fields", f"Unexpected fields: {', '.join(unexpected)}.", issue_ids)
            )

        if record_id is None or record_id <= 0:
            errors.append(
                _issue("invalid_id", f"Record at position {position} needs a positive integer ID.")
            )
        else:
            ids.append(record_id)

        for field in TEXT_FIELDS:
            value = record.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(
                    _issue("empty_or_non_string", f"{field} must be a non-empty string.", issue_ids)
                )
                continue
            if value != value.strip():
                errors.append(
                    _issue("outer_whitespace", f"{field} has outer whitespace.", issue_ids)
                )
            if unicodedata.normalize("NFC", value) != value:
                errors.append(
                    _issue("non_nfc_unicode", f"{field} is not NFC-normalized.", issue_ids)
                )
            if CONTROL_CHARACTER_RE.search(value):
                errors.append(
                    _issue("control_character", f"{field} contains a control character.", issue_ids)
                )
            if any(marker in value for marker in MOJIBAKE_MARKERS):
                errors.append(
                    _issue("mojibake", f"{field} has a likely encoding-corruption marker.", issue_ids)
                )

        if record_id is None:
            continue

        category = record.get("category")
        if isinstance(category, str) and category:
            category_counts[category] += 1
            if category not in CANONICAL_CATEGORIES:
                errors.append(_issue("unknown_category", f"Unknown category: {category!r}.", [record_id]))

        for field in QUESTION_FIELDS:
            question = record.get(field)
            if isinstance(question, str) and question.strip():
                question_values[field].append((record_id, question))
                if not question.rstrip().endswith("?"):
                    errors.append(
                        _issue("question_punctuation", f"{field} must end with '?'.", [record_id])
                    )

        for language in ("en", "twi"):
            answer = record.get(f"answer_{language}")
            if isinstance(answer, str) and len(answer.split()) < 8:
                errors.append(
                    _issue("answer_too_short", f"answer_{language} has fewer than eight words.", [record_id])
                )

        for left_field, right_field in (
            ("question_en", "question_twi"),
            ("answer_en", "answer_twi"),
        ):
            left = record.get(left_field)
            right = record.get(right_field)
            if (
                isinstance(left, str)
                and isinstance(right, str)
                and normalize_text(left) == normalize_text(right)
            ):
                errors.append(
                    _issue(
                        "identical_language_pair",
                        f"{left_field} and {right_field} are identical after normalization.",
                        [record_id],
                    )
                )

        numeric_differences = {}
        for pair_name, left_field, right_field in (
            ("question", "question_en", "question_twi"),
            ("answer", "answer_en", "answer_twi"),
        ):
            left_numbers = NUMBER_RE.findall(str(record.get(left_field, "")))
            right_numbers = NUMBER_RE.findall(str(record.get(right_field, "")))
            if Counter(left_numbers) != Counter(right_numbers):
                numeric_differences[pair_name] = {
                    "english": left_numbers,
                    "twi": right_numbers,
                }
        if numeric_differences:
            numeric_pairing_review.append({"record_id": record_id, "differences": numeric_differences})

    duplicate_ids = sorted(record_id for record_id, count in Counter(ids).items() if count > 1)
    if duplicate_ids:
        errors.append(_issue("duplicate_ids", "Record IDs must be unique.", duplicate_ids))

    if len(ids) == len(data) and len(set(ids)) == len(data):
        if ids != list(range(1, len(data) + 1)):
            errors.append(_issue("non_sequential_ids", "IDs must be ordered and contiguous from 1 to N."))

    duplicate_questions: dict[str, list[dict[str, Any]]] = {}
    near_duplicates: dict[str, list[dict[str, Any]]] = {}
    for field, values in question_values.items():
        duplicates = _duplicate_groups(values)
        duplicate_questions[field] = duplicates
        if duplicates:
            errors.append(
                _issue(
                    "duplicate_questions",
                    f"{field} contains {len(duplicates)} normalized duplicate group(s).",
                    sorted({item for group in duplicates for item in group["record_ids"]}),
                )
            )
        near_duplicates[field] = _near_duplicate_pairs(values)

    if numeric_pairing_review:
        warnings.append(
            _issue(
                "numeric_pairing_review",
                f"{len(numeric_pairing_review)} English/Twi pair(s) use different numeric tokens.",
                [item["record_id"] for item in numeric_pairing_review],
            )
        )

    active_ids = set(ids)
    category_review = [
        {"record_id": record_id, "reason": reason}
        for record_id, reason in MANUAL_CATEGORY_REVIEW.items()
        if record_id in active_ids
    ]
    if category_review:
        warnings.append(
            _issue(
                "manual_category_review",
                f"{len(category_review)} category assignment(s) need expert review before retraining.",
                [item["record_id"] for item in category_review],
            )
        )

    taxonomy_aliases = []
    if category_counts.get("Palm & Coconut") and category_counts.get("Oil Palm & Coconut"):
        taxonomy_aliases.append(["Palm & Coconut", "Oil Palm & Coconut"])
        warnings.append(
            _issue(
                "category_alias_review",
                "Palm & Coconut and Oil Palm & Coconut may be the same taxonomy concept.",
            )
        )

    near_duplicate_count = sum(len(pairs) for pairs in near_duplicates.values())
    if near_duplicate_count:
        warnings.append(
            _issue(
                "near_duplicate_review",
                f"{near_duplicate_count} close-wording question pair(s) need semantic review.",
            )
        )

    blocking_schema_codes = {
        "invalid_root", "invalid_record", "missing_fields", "unexpected_fields",
        "empty_or_non_string",
    }
    return {
        "schema_version": 1,
        "todo": 20,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset": {
            "path": dataset_path,
            "sha256": dataset_sha256,
            "record_count": len(data),
            "expected_record_count": expected_count,
            "category_count": len(category_counts),
        },
        "status": "failed" if errors else ("passed_with_review_warnings" if warnings else "passed"),
        "blocking_error_count": len(errors),
        "review_warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
        "checks": {
            "required_schema": not any(item["code"] in blocking_schema_codes for item in errors),
            "ids_unique_sequential": not any(item["code"] in {"invalid_id", "duplicate_ids", "non_sequential_ids"} for item in errors),
            "unicode_and_whitespace_integrity": not any(item["code"] in {"outer_whitespace", "non_nfc_unicode", "control_character", "mojibake"} for item in errors),
            "canonical_category_labels": not any(item["code"] == "unknown_category" for item in errors),
            "question_and_answer_shape": not any(item["code"] in {"question_punctuation", "answer_too_short"} for item in errors),
            "no_normalized_duplicate_questions": not any(item["code"] == "duplicate_questions" for item in errors),
            "bilingual_fields_present_and_distinct": not any(item["code"] == "identical_language_pair" for item in errors),
        },
        "category_counts": dict(sorted(category_counts.items())),
        "duplicate_question_groups": duplicate_questions,
        "near_duplicate_candidates": near_duplicates,
        "numeric_pairing_review": numeric_pairing_review,
        "manual_category_review": category_review,
        "taxonomy_alias_review": taxonomy_aliases,
        "limitations": [
            "Automated checks cannot certify translation meaning; native Twi review is still required.",
            "Near-duplicate similarity identifies review candidates and does not prove redundancy.",
            "Agricultural correctness and high-risk advice require separate domain-expert review.",
        ],
    }


def validate_dataset(path: Path = DATASET_PATH) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as source:
            data = json.load(source)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {
            "schema_version": 1,
            "todo": 20,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "dataset": {"path": str(path), "sha256": None, "record_count": None},
            "status": "failed",
            "blocking_error_count": 1,
            "review_warning_count": 0,
            "errors": [_issue("dataset_read_error", str(exc))],
            "warnings": [],
        }

    try:
        relative_path = path.resolve().relative_to(BASE_DIR).as_posix()
    except ValueError:
        relative_path = str(path.resolve())
    return validate_records(
        data,
        expected_count=EXPECTED_RECORDS,
        dataset_path=relative_path,
        dataset_sha256=sha256_file(path),
    )


def _print_report(report: dict[str, Any]) -> None:
    print(f"Total records: {report['dataset'].get('record_count')}")
    print("\n--- TODO 20 DATASET QUALITY RESULTS ---")
    print(f"Status: {report['status']}")
    print(f"Blocking errors: {report['blocking_error_count']}")
    print(f"Review warnings: {report['review_warning_count']}")
    for name, passed in report.get("checks", {}).items():
        print(f"{name}: {'PASS' if passed else 'FAIL'}")
    if report["errors"]:
        print("\nBlocking errors:")
        for item in report["errors"]:
            print(f"- {item['code']}: {item['message']}")
    if report["warnings"]:
        print("\nReview warnings:")
        for item in report["warnings"]:
            print(f"- {item['code']}: {item['message']}")


def main() -> None:
    report = validate_dataset()
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with REPORT_PATH.open("w", encoding="utf-8", newline="\n") as target:
        json.dump(report, target, ensure_ascii=False, indent=2)
        target.write("\n")
    _print_report(report)
    print(f"\nReport: {REPORT_PATH.relative_to(BASE_DIR).as_posix()}")
    if report["blocking_error_count"]:
        raise SystemExit("\nDataset validation failed.")
    print("\nDataset validation passed. Review warnings are documented and were not hidden.")


if __name__ == "__main__":
    main()
