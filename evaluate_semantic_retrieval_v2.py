"""Calibrate semantic-expanded TF-IDF on positives, negatives, and ambiguity."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

from evaluate_retrieval_robustness import EDGE_FILE, OFF_TOPIC_FILES, load_json
from experiment_tfidf import CONFIGURATIONS, build_vectorizer
from query_normalization import normalize_query
from retrieval_semantics import entity_compatibility, expand_semantic_text, extract_entities


BASE_DIR = Path(__file__).resolve().parent
DATASET = BASE_DIR / "data/agribotgh_dataset_bilingual_563.json"
TRAIN = BASE_DIR / "data/splits/train.json"
GOLD = BASE_DIR / "data/evaluation/gold_standard.json"
OLD_POSITIVES = BASE_DIR / "data/evaluation/retrieval_paraphrase_cases.json"
NEW_CASES = BASE_DIR / "data/evaluation/retrieval_challenge_v2.json"
OUTPUT = BASE_DIR / "models/semantic_retrieval_v2_evaluation.json"


class SemanticIndex:
    def __init__(self, records, language):
        self.records = records
        self.language = language
        self.qfield = "question_en" if language == "English" else "question_twi"
        self.questions = [normalize_query(r[self.qfield], language) for r in records]
        documents = [expand_semantic_text(q, language) for q in self.questions]
        self.vectorizer = build_vectorizer(CONFIGURATIONS["C_word_and_character"])
        self.matrix = self.vectorizer.fit_transform(documents)
        self.entities = [extract_entities(q, language) for q in self.questions]

    def retrieve(self, question):
        normalized = normalize_query(question, self.language)
        expanded = expand_semantic_text(normalized, self.language)
        raw = cosine_similarity(self.vectorizer.transform([expanded]), self.matrix)[0]
        query_entities = extract_entities(normalized, self.language)
        compatibility = np.asarray([
            entity_compatibility(query_entities, candidate) for candidate in self.entities
        ])
        scores = raw * (0.2 + 0.8 * compatibility)
        ranked = np.argsort(scores)[::-1]
        top = int(ranked[0])
        second = int(ranked[1])
        candidate_entities = self.entities[top]
        specificity_safe = not (
            (not query_entities and candidate_entities)
            or (query_entities and candidate_entities and not query_entities & candidate_entities)
        )
        return {
            "record_id": self.records[top]["id"],
            "question": self.records[top][self.qfield],
            "similarity": float(raw[top]),
            "retrieval_score": float(scores[top]),
            "margin": float(scores[top] - scores[second]),
            "specificity_safe": specificity_safe,
            "query_entities": sorted(query_entities),
            "candidate_entities": sorted(candidate_entities),
        }


def acceptable_ids(case):
    return case.get("acceptable_record_ids", [case.get("expected_record_id")])


def main():
    canonical = load_json(DATASET)
    train = load_json(TRAIN)
    new = load_json(NEW_CASES)
    old = load_json(OLD_POSITIVES)["cases"]
    positives = old + new["positive_cases"]
    negatives = []
    for path in OFF_TOPIC_FILES:
        negatives.extend(load_json(path)["cases"])
    negatives.extend(load_json(EDGE_FILE)["cases"])
    negatives.extend([
        {"id":"v2_neg_capital","language":"English","question":"What is the capital of France?"},
        {"id":"v2_neg_joke","language":"English","question":"Tell me a joke."},
        {"id":"v2_neg_bitcoin","language":"English","question":"How can I start Bitcoin farming?"},
        {"id":"v2_neg_server","language":"English","question":"How do I maintain a server farm?"},
    ])
    indexes = {language: SemanticIndex(canonical, language) for language in ("English", "Twi")}
    positive_results = []
    for case in positives:
        result = indexes[case["language"]].retrieve(case["question"])
        positive_results.append({
            **case, **result,
            "correct": result["record_id"] in acceptable_ids(case),
        })
    negative_results = [
        {**case, **indexes[case["language"]].retrieve(case["question"])}
        for case in negatives
    ]
    ambiguous_results = [
        {**case, **indexes[case["language"]].retrieve(case["question"])}
        for case in new["ambiguous_agriculture_cases"]
    ]

    training_indexes = {language: SemanticIndex(train, language) for language in ("English", "Twi")}
    validation = {}
    gold_entries = load_json(GOLD)["entries"]
    for language in ("English", "Twi"):
        answerable = [x for x in gold_entries if x["language"] == language and x["answerable"]]
        results = [training_indexes[language].retrieve(x["question"]) for x in answerable]
        correct = sum(
            result["record_id"] == case["expected_training_record"]
            for result, case in zip(results, answerable)
        )
        validation[language] = {"cases":len(answerable),"correct":correct,"top_1_accuracy":correct/len(answerable)}

    gates = []
    for threshold in (0.25,0.30,0.35,0.40,0.45,0.50,0.55,0.60,0.65,0.70,0.75):
        for margin in (0.02,0.03,0.05,0.08,0.10,0.15):
            def accepted(item):
                return item["specificity_safe"] and item["retrieval_score"] >= threshold and item["margin"] >= margin
            accepted_positive = [x for x in positive_results if accepted(x)]
            incorrect = [x for x in accepted_positive if not x["correct"]]
            false_negative = [x for x in negative_results if accepted(x)]
            unsafe_ambiguous = [x for x in ambiguous_results if accepted(x)]
            correct = len(accepted_positive) - len(incorrect)
            gates.append({
                "threshold":threshold,"minimum_margin":margin,
                "correct_answers":correct,"accepted_positive":len(accepted_positive),
                "incorrect_positive_answers":len(incorrect),
                "negative_false_accepts":len(false_negative),
                "ambiguous_false_answers":len(unsafe_ambiguous),
                "precision":correct/len(accepted_positive) if accepted_positive else 0.0,
                "coverage":correct/len(positive_results),
                "incorrect_positive_ids":[x["id"] for x in incorrect],
                "negative_false_accept_ids":[x["id"] for x in false_negative],
                "ambiguous_false_answer_ids":[x["id"] for x in unsafe_ambiguous],
            })
    safe = [x for x in gates if x["incorrect_positive_answers"] == 0 and x["negative_false_accepts"] == 0 and x["ambiguous_false_answers"] == 0]
    selection = max(safe,key=lambda x:(x["correct_answers"],x["threshold"],x["minimum_margin"]),default=None)
    report = {
        "schema_version":1,"architecture":"semantic-expanded word+character TF-IDF with entity compatibility",
        "positive_cases":len(positive_results),"negative_cases":len(negative_results),
        "ambiguous_cases":len(ambiguous_results),"validation":validation,
        "ranking":{
            language:{
                "cases":sum(x["language"]==language for x in positive_results),
                "correct":sum(x["language"]==language and x["correct"] for x in positive_results),
            } for language in ("English","Twi")
        },
        "selection":selection,"gates":gates,
        "positive_results":positive_results,"negative_results":negative_results,
        "ambiguous_results":ambiguous_results,
    }
    OUTPUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"ranking":report["ranking"],"validation":validation,"selection":selection},indent=2))
    print(f"Report: {OUTPUT}")


if __name__ == "__main__":
    main()
