"""Grid-test current and semantic-expanded TF-IDF as a retrieval ensemble."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

from experiment_tfidf import CONFIGURATIONS, build_vectorizer
from query_normalization import normalize_query
from retrieval_semantics import expand_semantic_text, extract_entities


BASE = Path(__file__).resolve().parent
DATASET = BASE / "data/agribotgh_dataset_bilingual_563.json"
TRAIN = BASE / "data/splits/train.json"
GOLD = BASE / "data/evaluation/gold_standard.json"
OLD = BASE / "data/evaluation/retrieval_paraphrase_cases.json"
NEW = BASE / "data/evaluation/retrieval_challenge_v2.json"
OUTPUT = BASE / "models/retrieval_ensemble_v2_experiments.json"


def norm(values):
    maximum = float(values.max()) if values.size else 0.0
    return values / maximum if maximum > 0 else np.zeros_like(values)


class EnsembleIndex:
    def __init__(self, records, language):
        self.records = records
        self.language = language
        self.qfield = "question_en" if language == "English" else "question_twi"
        questions = [normalize_query(r[self.qfield], language) for r in records]
        self.base_vectorizer = build_vectorizer(CONFIGURATIONS["C_word_and_character"])
        self.base_matrix = self.base_vectorizer.fit_transform(questions)
        self.semantic_vectorizer = build_vectorizer(CONFIGURATIONS["C_word_and_character"])
        self.semantic_matrix = self.semantic_vectorizer.fit_transform([
            expand_semantic_text(q, language) for q in questions
        ])
        groups = defaultdict(list)
        for index, record in enumerate(records):
            groups[record["category"]].append(index)
        self.categories = sorted(groups)
        self.positions = {name:index for index,name in enumerate(self.categories)}
        self.centroids = np.vstack([
            np.asarray(self.base_matrix[groups[name]].mean(axis=0)).ravel()
            for name in self.categories
        ])
        self.entities = [extract_entities(q, language) for q in questions]

    def rank(self, question, semantic_weight, topic_weight):
        normalized = normalize_query(question, self.language)
        base_query = self.base_vectorizer.transform([normalized])
        base_raw = cosine_similarity(base_query, self.base_matrix)[0]
        category = norm(cosine_similarity(base_query, self.centroids)[0])
        topic = np.asarray([category[self.positions[r["category"]]] for r in self.records])
        base = (1-topic_weight)*norm(base_raw)+topic_weight*topic
        semantic_query = self.semantic_vectorizer.transform([
            expand_semantic_text(normalized, self.language)
        ])
        semantic = norm(cosine_similarity(semantic_query,self.semantic_matrix)[0])
        score = (1-semantic_weight)*norm(base)+semantic_weight*semantic
        query_entities = extract_entities(normalized,self.language)
        if query_entities:
            compatibility = np.asarray([
                1.0 if not candidate or query_entities & candidate else 0.2
                for candidate in self.entities
            ])
            score *= compatibility
        return int(np.argmax(score))


def ids(case):
    return case.get("acceptable_record_ids",[case.get("expected_record_id")])


def main():
    records=json.loads(DATASET.read_text(encoding="utf-8"))
    train=json.loads(TRAIN.read_text(encoding="utf-8"))
    positives=json.loads(OLD.read_text(encoding="utf-8"))["cases"]+json.loads(NEW.read_text(encoding="utf-8"))["positive_cases"]
    gold=json.loads(GOLD.read_text(encoding="utf-8"))["entries"]
    full={lang:EnsembleIndex(records,lang) for lang in ("English","Twi")}
    training={lang:EnsembleIndex(train,lang) for lang in ("English","Twi")}
    configs=[]
    for semantic_weight in (0.0,0.2,0.35,0.5,0.65,0.8,1.0):
        for topic_weight in (0.0,0.2,0.4,0.62):
            challenge={}
            validation={}
            details=[]
            for language in ("English","Twi"):
                selected=[x for x in positives if x["language"]==language]
                actual=[full[language].rank(x["question"],semantic_weight,topic_weight) for x in selected]
                correct=sum(records[index]["id"] in ids(case) for index,case in zip(actual,selected))
                challenge[language]={"cases":len(selected),"correct":correct,"accuracy":correct/len(selected)}
                details.extend({"id":case["id"],"language":language,"record_id":records[index]["id"],"correct":records[index]["id"] in ids(case)} for index,case in zip(actual,selected))
                held=[x for x in gold if x["language"]==language and x["answerable"]]
                held_actual=[training[language].rank(x["question"],semantic_weight,topic_weight) for x in held]
                held_correct=sum(train[index]["id"]==case["expected_training_record"] for index,case in zip(held_actual,held))
                validation[language]={"cases":len(held),"correct":held_correct,"accuracy":held_correct/len(held)}
            configs.append({
                "semantic_weight":semantic_weight,"topic_weight":topic_weight,
                "challenge":challenge,"validation":validation,"details":details,
                "challenge_macro":sum(x["accuracy"] for x in challenge.values())/2,
                "validation_macro":sum(x["accuracy"] for x in validation.values())/2,
                "combined":0.7*(sum(x["accuracy"] for x in challenge.values())/2)+0.3*(sum(x["accuracy"] for x in validation.values())/2),
            })
    configs.sort(key=lambda x:(x["combined"],x["challenge_macro"],x["validation_macro"]),reverse=True)
    report={"schema_version":1,"configurations":configs,"winner":configs[0]}
    OUTPUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    for x in configs[:10]: print(x["semantic_weight"],x["topic_weight"],round(x["challenge_macro"],3),round(x["validation_macro"],3),round(x["combined"],3),x["challenge"],x["validation"])
    print(f"Report: {OUTPUT}")


if __name__=="__main__": main()
