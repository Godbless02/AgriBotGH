"""Create the manually reviewed bilingual retrieval gold standard.

Mappings in REVIEWED_MATCHES were selected by comparing the meaning and answer
coverage of validation items against training records in both languages. A
record is mapped only when its answer can reasonably answer the validation
question; topical or lexical overlap alone is insufficient.
"""

import json
from pathlib import Path


TRAIN_FILE = Path("data/splits/train.json")
VALIDATION_FILE = Path("data/splits/validation.json")
OUTPUT_FILE = Path("data/evaluation/gold_standard.json")


# validation_id: (training_id, manual rationale)
REVIEWED_MATCHES = {
    2: (210, "Same maize fertilizer programme, rates and application timing."),
    6: (201, "Contour planting, cover crops and mulch directly address erosion prevention."),
    17: (209, "The training answer explicitly gives maize planting depth."),
    34: (202, "Same Fall Armyworm definition and control guidance."),
    92: (165, "Directly explains how Ghanaian farmers access government/PFJ support."),
    198: (340, "Directly covers leasing, sharecropping and communal land access in Ghana."),
    203: (40, "Semantically equivalent whitefly identification and control knowledge."),
    206: (302, "Directly covers drainage, raised beds and flood/waterlogging prevention."),
    217: (99, "Defines intercropping and explicitly gives maize with cowpea as an example."),
    257: (183, "Covers the essential decisions and setup for starting a small poultry farm."),
    276: (165, "Explains PFJ registration channels, identification and subsidized inputs."),
    284: (172, "Defines minimum tillage and gives practical direct-planting guidance."),
    306: (86, "Cooperative benefits substantially cover the role of a farmer-based organisation."),
    406: (409, "Moisture management and avoiding flowering stress address misshapen cucumber fruit."),
    477: (476, "Hive placement guidance explicitly includes protection from disturbance."),
    501: (496, "Listing all expected production costs supports calculating seasonal cash needs."),
    508: (124, "Explains produce grading, separation criteria and why separated grades retain value."),
    539: (352, "Directly covers moisture, weed, heat/grazing protection and care of young coconuts."),
}


def load_json(path):
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def main():
    train = load_json(TRAIN_FILE)
    validation = load_json(VALIDATION_FILE)
    train_by_id = {row["id"]: row for row in train}
    validation_ids = {row["id"] for row in validation}

    unknown_validation = set(REVIEWED_MATCHES) - validation_ids
    unknown_training = {
        train_id for train_id, _ in REVIEWED_MATCHES.values()
        if train_id not in train_by_id
    }
    if unknown_validation or unknown_training:
        raise ValueError(
            f"Invalid reviewed mappings; validation={sorted(unknown_validation)}, "
            f"training={sorted(unknown_training)}"
        )

    entries = []
    for record in validation:
        mapping = REVIEWED_MATCHES.get(record["id"])
        for language, question_field in (("English", "question_en"), ("Twi", "question_twi")):
            if mapping:
                train_id, explanation = mapping
                answerable = True
                expected_training_record = train_id
            else:
                answerable = False
                expected_training_record = None
                explanation = (
                    "Manual bilingual review found no training record whose answer "
                    f"adequately covers this {record['category']} question; related "
                    "records were partial, about a different task, or only shared wording."
                )

            entries.append({
                "validation_id": record["id"],
                "category": record["category"],
                "question": record[question_field],
                "language": language,
                "expected_training_record": expected_training_record,
                "answerable": answerable,
                "explanation": explanation,
            })

    output = {
        "methodology": {
            "unit": "One entry per validation question and language.",
            "review_basis": (
                "Manual semantic review of English and Twi questions, reference answers, "
                "same-category candidates and baseline retrieval candidates."
            ),
            "positive_rule": (
                "A training answer must reasonably answer the validation question; "
                "word overlap, category agreement or a partial answer is insufficient."
            ),
            "negative_rule": (
                "answerable=false when required knowledge is absent or available records "
                "cover only part of the requested information."
            ),
        },
        "validation_records": len(validation),
        "language_cases": len(entries),
        "entries": entries,
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_FILE.open("w", encoding="utf-8") as handle:
        json.dump(output, handle, ensure_ascii=False, indent=2)

    answerable = sum(1 for entry in entries if entry["answerable"])
    print(f"Validation records: {len(validation)}")
    print(f"Language cases: {len(entries)}")
    print(f"Answerable cases: {answerable}")
    print(f"Unsupported cases: {len(entries) - answerable}")
    print(f"Saved: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
