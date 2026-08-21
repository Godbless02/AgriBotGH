"""Build TODO 15 suggestions directly from the canonical 563-record dataset."""

import ast
import json
import sys
from pathlib import Path


APP_FILE = Path("app.py")
DATA_FILE = Path("data/agribotgh_dataset_bilingual_563.json")
OUTPUT_FILE = Path("models/suggestion_links.json")
SUGGESTIONS_PER_TOPIC = 5

TOPIC_CATEGORY_MAP = {
    "Soil & Land Preparation": ("Soil & Land Preparation",),
    "Fertilizer & Nutrients": ("Fertilizer & Nutrients",),
    "Maize": ("Maize",),
    "Cassava": ("Cassava",),
    "Plantain & Banana": ("Plantain & Banana",),
    "Yam": ("Yam",),
    "Tomatoes": ("Tomato",),
    "Pepper": ("Pepper",),
    "Onion": ("Onion",),
    "Carrot": ("Carrot",),
    "Garden Eggs": ("Garden Eggs",),
    "Palm Oil & Coconut": ("Oil Palm & Coconut", "Palm & Coconut"),
    "Groundnut & Legumes": ("Groundnut & Legumes",),
    "Rice": ("Rice Farming",),
    "Cocoa": ("Cocoa Farming",),
    "Other Vegetables": ("Cucumber Farming", "Okra Farming", "Watermelon Farming"),
    "Pest & Disease Control": ("Pest & Disease Control",),
    "Irrigation & Water": ("Irrigation & Water",),
    "Harvesting & Storage": ("Harvesting & Storage", "Post-Harvest & Food Safety"),
    "Fish Farming": ("Fish Farming",),
    "Poultry Farming": ("Poultry Farming",),
    "Goat Farming": ("Goat Rearing",),
    "Sheep Farming": ("Sheep Rearing",),
    "Cattle Farming": ("Cattle Rearing",),
    "Business & Marketing": ("Business & Marketing", "Farm Business Planning"),
    "Climate & Weather": ("Climate-Smart Farming",),
    "Farm Management": (
        "Farm Management & General",
        "Farm Mechanization & Tools",
        "Farm Records & Extension",
    ),
}

SPECIAL_RECORD_IDS = {
    "Cocoyam": (235, 236, 316, 350),
}

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def load_topic_names():
    tree = ast.parse(APP_FILE.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "TOPICS"
            for target in node.targets
        ):
            return list(ast.literal_eval(node.value))
    raise ValueError("TOPICS dictionary was not found in app.py")


def round_robin_records(records, categories, limit):
    buckets = [
        sorted(
            (record for record in records if record["category"] == category),
            key=lambda record: record["id"],
        )
        for category in categories
    ]
    selected = []
    position = 0
    while len(selected) < limit and any(position < len(bucket) for bucket in buckets):
        for bucket in buckets:
            if position < len(bucket) and len(selected) < limit:
                selected.append(bucket[position])
        position += 1
    return selected


def main():
    records = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    topic_names = load_topic_names()
    records_by_id = {record["id"]: record for record in records}
    if len(records_by_id) != len(records):
        raise ValueError("Canonical dataset IDs must be unique")
    mapped_topics = set(TOPIC_CATEGORY_MAP) | set(SPECIAL_RECORD_IDS)
    if mapped_topics != set(topic_names):
        raise ValueError(
            "Topic mapping mismatch: "
            + json.dumps({
                "missing": sorted(set(topic_names) - mapped_topics),
                "extra": sorted(mapped_topics - set(topic_names)),
            })
        )

    links = {}
    category_counts = {}
    for topic in topic_names:
        if topic in SPECIAL_RECORD_IDS:
            selected = [records_by_id[record_id] for record_id in SPECIAL_RECORD_IDS[topic]]
            selection = "explicit_canonical_record_ids"
        else:
            categories = TOPIC_CATEGORY_MAP[topic]
            selected = round_robin_records(records, categories, SUGGESTIONS_PER_TOPIC)
            selection = "deterministic_category_round_robin_by_record_id"
        if not selected:
            raise ValueError(f"No canonical records available for topic: {topic}")
        links[topic] = [
            {
                "position": position,
                "record_id": f"qa-{record['id']:04d}",
                "dataset_id": record["id"],
                "category": record["category"],
                "suggestion_en": record["question_en"],
                "suggestion_tw": record["question_twi"],
                "selection": selection,
            }
            for position, record in enumerate(selected)
        ]
        category_counts[topic] = {
            category: sum(record["category"] == category for record in selected)
            for category in sorted({record["category"] for record in selected})
        }

    report = {
        "methodology": {
            "canonical_dataset": str(DATA_FILE).replace("\\", "/"),
            "dataset_records": len(records),
            "stable_record_id": "qa- followed by the zero-padded canonical dataset ID",
            "suggestion_text": "Exact question_en/question_twi from the linked canonical record",
            "selection": "Up to five deterministic records per UI topic; multi-category topics use round-robin selection",
            "fuzzy_linking": False,
            "legacy_dataset_used": False,
        },
        "summary": {
            "topics": len(links),
            "suggestion_pairs": sum(len(items) for items in links.values()),
            "unique_record_ids": len({
                item["record_id"] for items in links.values() for item in items
            }),
            "review_required": 0,
        },
        "selected_category_counts": category_counts,
        "links": links,
    }
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    print(f"Saved: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
