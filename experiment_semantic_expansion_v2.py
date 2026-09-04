"""Compare local semantic-expansion retrieval configurations on fresh cases."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

from experiment_tfidf import CONFIGURATIONS, build_vectorizer
from query_normalization import normalize_query
from retrieval_semantics import entity_compatibility, expand_semantic_text, extract_entities


BASE_DIR = Path(__file__).resolve().parent
DATASET = BASE_DIR / "data/agribotgh_dataset_bilingual_563.json"
CASES = BASE_DIR / "data/evaluation/retrieval_challenge_v2.json"
OUTPUT = BASE_DIR / "models/semantic_expansion_v2_experiments.json"


def normalize(values):
    maximum = float(values.max()) if values.size else 0.0
    return values / maximum if maximum > 0 else np.zeros_like(values)


class Index:
    def __init__(self, records, language, scope, expanded):
        self.records = records
        self.language = language
        qfield = "question_en" if language == "English" else "question_twi"
        afield = "answer_en" if language == "English" else "answer_twi"
        self.base_questions = [normalize_query(r[qfield], language) for r in records]
        questions = [
            expand_semantic_text(q, language) if expanded else q
            for q in self.base_questions
        ]
        if scope == "question_answer":
            documents = [
                f"{question} {expand_semantic_text(r[afield], language) if expanded else normalize_query(r[afield], language)}"
                for question, r in zip(questions, records)
            ]
        else:
            documents = questions
        self.vectorizer = build_vectorizer(CONFIGURATIONS["C_word_and_character"])
        self.matrix = self.vectorizer.fit_transform(documents)
        groups = defaultdict(list)
        for index, record in enumerate(records):
            groups[record["category"]].append(index)
        self.category_names = sorted(groups)
        self.category_positions = {name: index for index, name in enumerate(self.category_names)}
        self.centroids = np.vstack([
            np.asarray(self.matrix[groups[name]].mean(axis=0)).ravel()
            for name in self.category_names
        ])
        self.entities = [extract_entities(r[qfield], language) for r in records]
        self.expanded = expanded

    def rank(self, question, topic_weight, entity_mode):
        base = normalize_query(question, self.language)
        query_text = expand_semantic_text(base, self.language) if self.expanded else base
        query = self.vectorizer.transform([query_text])
        raw = cosine_similarity(query, self.matrix)[0]
        text = normalize(raw)
        category_raw = cosine_similarity(query, self.centroids)[0]
        category = normalize(category_raw)
        topic = np.asarray([
            category[self.category_positions[r["category"]]] for r in self.records
        ])
        score = (1 - topic_weight) * text + topic_weight * topic
        query_entities = extract_entities(base, self.language)
        compatibility = np.asarray([
            entity_compatibility(query_entities, candidate) for candidate in self.entities
        ])
        if entity_mode == "soft":
            score *= 0.5 + 0.5 * compatibility
        elif entity_mode == "strong":
            score *= 0.2 + 0.8 * compatibility
        return int(np.argmax(score))


def main():
    records = json.loads(DATASET.read_text(encoding="utf-8"))
    positives = json.loads(CASES.read_text(encoding="utf-8"))["positive_cases"]
    configs = []
    for expanded in (False, True):
        for scope in ("question", "question_answer"):
            indexes = {
                language: Index(records, language, scope, expanded)
                for language in ("English", "Twi")
            }
            for topic_weight in (0.0, 0.2, 0.4, 0.62):
                for entity_mode in ("none", "soft", "strong"):
                    results = []
                    for case in positives:
                        index = indexes[case["language"]].rank(
                            case["question"], topic_weight, entity_mode
                        )
                        record_id = records[index]["id"]
                        results.append({
                            "id": case["id"], "language": case["language"],
                            "record_id": record_id,
                            "correct": record_id in case["acceptable_record_ids"],
                        })
                    languages = {}
                    for language in ("English", "Twi"):
                        selected = [x for x in results if x["language"] == language]
                        languages[language] = {
                            "correct": sum(x["correct"] for x in selected),
                            "cases": len(selected),
                            "accuracy": sum(x["correct"] for x in selected) / len(selected),
                        }
                    configs.append({
                        "expanded": expanded, "scope": scope,
                        "topic_weight": topic_weight, "entity_mode": entity_mode,
                        "languages": languages, "results": results,
                        "macro_accuracy": sum(x["accuracy"] for x in languages.values()) / 2,
                    })
    configs.sort(key=lambda x: x["macro_accuracy"], reverse=True)
    report = {"schema_version": 1, "configurations": configs, "winner": configs[0]}
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for item in configs[:10]:
        print(
            item["macro_accuracy"], item["expanded"], item["scope"],
            item["topic_weight"], item["entity_mode"], item["languages"]
        )
    print(f"Report: {OUTPUT}")


if __name__ == "__main__":
    main()
