"""Build TODO 35's deterministic 80-case final presentation set."""

from __future__ import annotations

import json
from pathlib import Path

import app as agribot


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_PATH = BASE_DIR / "data" / "evaluation" / "final_presentation_test_set.json"
OFF_TOPIC_PATH = BASE_DIR / "data" / "evaluation" / "off_topic_questions.json"

PARAPHRASES = [
    ("presentation_para_en_01", "en", "Which fertiliser should I apply to my maize crop?"),
    ("presentation_para_tw_01", "tw", "Ferefere bɛn na mede mma me aburo afuo?"),
    ("presentation_para_en_02", "en", "What is the right season to sow maize in Ghana?"),
    ("presentation_para_tw_02", "tw", "Bere pa bɛn na ɛsɛ sɛ medua aburo wɔ Ghana?"),
    ("presentation_para_en_03", "en", "What signs suggest that pond fish lack oxygen?"),
    ("presentation_para_tw_03", "tw", "Ahohyɛn bɛn na ɛkyerɛ sɛ oxygen sua wɔ apataa tadeɛ mu?"),
    ("presentation_para_en_04", "en", "How can I recognize illness early in my young chickens?"),
    ("presentation_para_tw_04", "tw", "Mɛyɛ dɛn ahu ntɛm sɛ me nkokɔ mma ayare?"),
    ("presentation_para_en_05", "en", "How can crop waste become useful compost for my farm?"),
    ("presentation_para_tw_05", "tw", "Mɛyɛ dɛn de afuo mu nwura ayɛ compost ama m'afuo?"),
]

TTS_CASES = [
    ("presentation_tts_en_01", "en", "Check the soil before planting."),
    ("presentation_tts_en_02", "en", "Keep harvested maize dry and clean."),
    ("presentation_tts_en_03", "en", "Observe your chickens every morning."),
    ("presentation_tts_en_04", "en", "Use clean water in the fish pond."),
    ("presentation_tts_en_05", "en", "Contact an extension officer when unsure."),
    ("presentation_tts_tw_01", "tw", "Hwɛ asase no ansa na woadua aba."),
    ("presentation_tts_tw_02", "tw", "Ma aburo a woatwa no nwo yie."),
    ("presentation_tts_tw_03", "tw", "Hwɛ wo nkokɔ no anɔpa biara."),
    ("presentation_tts_tw_04", "tw", "Fa nsuo pa gu apataa tadeɛ no mu."),
    ("presentation_tts_tw_05", "tw", "Bisa kuayɛ ɔfotufoɔ bere a wo nnim nea wobɛyɛ."),
]


def category_representatives():
    selected = {}
    for record in agribot.CANONICAL_RECORDS:
        selected.setdefault(record["category"], record)
    return list(selected.values())


def build_set():
    cases = []
    representatives = category_representatives()
    for position, record in enumerate(representatives[:20], start=1):
        cases.append({
            "id": f"presentation_en_{position:02d}",
            "group": "english_question",
            "language": "en",
            "message": record["question_en"],
            "expected_type": "answer",
            "expected_state": "A",
            "expected_record_id": f"qa-{record['id']:04d}",
            "expected_text": record["answer_en"],
        })
    for position, record in enumerate(representatives[20:40], start=1):
        cases.append({
            "id": f"presentation_tw_{position:02d}",
            "group": "twi_question",
            "language": "tw",
            "message": record["question_twi"],
            "expected_type": "answer",
            "expected_state": "A",
            "expected_record_id": f"qa-{record['id']:04d}",
            "expected_text": record["answer_twi"],
        })
    for case_id, language, message in PARAPHRASES:
        cases.append({
            "id": case_id,
            "group": "paraphrased_question",
            "language": language,
            "message": message,
            "allowed_types": ["low_confidence"],
            "allowed_states": ["B"],
        })
    with OFF_TOPIC_PATH.open("r", encoding="utf-8") as handle:
        off_topic = json.load(handle)["cases"][:10]
    for position, source in enumerate(off_topic, start=1):
        cases.append({
            "id": f"presentation_off_{position:02d}",
            "group": "off_topic_question",
            "language": "tw" if source["language"] == "Twi" else "en",
            "message": source["question"],
            "expected_type": "off_topic",
            "expected_state": "C",
        })
    for position, topic in enumerate(list(agribot.TOPICS)[:10], start=1):
        cases.append({
            "id": f"presentation_topic_{position:02d}",
            "group": "topic_selection",
            "language": "tw" if position % 2 == 0 else "en",
            "topic": topic,
            "expected_suggestion_ids": [item["id"] for item in agribot.get_suggestions(topic, "tw" if position % 2 == 0 else "en")],
        })
    for case_id, language, message in TTS_CASES:
        cases.append({
            "id": case_id,
            "group": "tts",
            "language": language,
            "message": message,
            "expected_manual_playback": True,
        })
    counts = {group: sum(case["group"] == group for case in cases) for group in {
        "english_question", "twi_question", "paraphrased_question", "off_topic_question", "topic_selection", "tts"
    }}
    if counts != {
        "english_question": 20,
        "twi_question": 20,
        "paraphrased_question": 10,
        "off_topic_question": 10,
        "topic_selection": 10,
        "tts": 10,
    } or len(cases) != 80:
        raise RuntimeError(f"Presentation matrix is incomplete: {counts}")
    return {"schema_version": 1, "todo": 35, "case_count": 80, "group_counts": counts, "cases": cases}


def main():
    payload = build_set()
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Presentation cases: {payload['case_count']} {payload['group_counts']}")
    print(f"Saved: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
