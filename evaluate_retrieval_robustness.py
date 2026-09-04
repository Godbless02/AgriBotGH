"""Benchmark production retrieval on paraphrases and negative controls."""

import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import joblib
from sklearn.metrics.pairwise import cosine_similarity

from experiment_tfidf import CONFIGURATIONS, build_vectorizer
from query_normalization import normalize_query


BASE_DIR = Path(__file__).resolve().parent
DATASET_FILE = BASE_DIR / "data" / "agribotgh_dataset_bilingual_563.json"
TRAIN_FILE = BASE_DIR / "data" / "splits" / "train.json"
GOLD_FILE = BASE_DIR / "data" / "evaluation" / "gold_standard.json"
PARAPHRASE_FILE = BASE_DIR / "data" / "evaluation" / "retrieval_paraphrase_cases.json"
OFF_TOPIC_FILES = (
    BASE_DIR / "data" / "evaluation" / "off_topic_cases.json",
    BASE_DIR / "data" / "evaluation" / "off_topic_questions.json",
)
EDGE_FILE = BASE_DIR / "data" / "evaluation" / "agriculture_edge_cases.json"
OUTPUT_FILE = BASE_DIR / "models" / "retrieval_robustness_experiments.json"
BASELINE_DIR = BASE_DIR / "models" / "production" / "1.0.1"
THRESHOLDS = (0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75)
MIN_MARGIN = 0.05
WEIGHTS = {"tfidf": 0.38, "topic": 0.62}
DOMAIN = {
    "English": {"text_weight": 0.45, "topic_weight": 0.55, "threshold": 0.22},
    "Twi": {"text_weight": 0.25, "topic_weight": 0.75, "threshold": 0.22},
}


def load_json(path):
    with path.open("r", encoding="utf-8") as source:
        return json.load(source)


class CandidateIndex:
    def __init__(self, records, language, configuration):
        self.records = records
        self.language = language
        self.question_field = "question_en" if language == "English" else "question_twi"
        questions = [normalize_query(row[self.question_field], language) for row in records]
        self.vectorizer = build_vectorizer(configuration)
        self.matrix = self.vectorizer.fit_transform(questions)
        grouped = defaultdict(list)
        for index, record in enumerate(records):
            grouped[record["category"]].append(index)
        self.category_names = sorted(grouped)
        self.category_positions = {
            category: position for position, category in enumerate(self.category_names)
        }
        self.centroids = np.vstack([
            np.asarray(self.matrix[grouped[category]].mean(axis=0)).ravel()
            for category in self.category_names
        ])

    @staticmethod
    def normalize_nonnegative(values):
        clipped = np.maximum(values, 0.0)
        maximum = float(clipped.max()) if clipped.size else 0.0
        return clipped / maximum if maximum else np.zeros_like(clipped)

    def retrieve(self, question):
        normalized = normalize_query(question, self.language)
        query = self.vectorizer.transform([normalized])
        raw_text = cosine_similarity(query, self.matrix)[0]
        normalized_text = self.normalize_nonnegative(raw_text)
        raw_categories = cosine_similarity(query, self.centroids)[0]
        normalized_categories = self.normalize_nonnegative(raw_categories)
        raw_topic = np.asarray([
            raw_categories[self.category_positions[row["category"]]]
            for row in self.records
        ])
        normalized_topic = np.asarray([
            normalized_categories[self.category_positions[row["category"]]]
            for row in self.records
        ])
        final = WEIGHTS["tfidf"] * normalized_text + WEIGHTS["topic"] * normalized_topic
        indices = np.argsort(final)[::-1][:3]
        candidates = []
        for rank, index in enumerate(indices, 1):
            record = self.records[int(index)]
            candidates.append({
                "rank": rank,
                "record_id": record["id"],
                "question": record[self.question_field],
                "category": record["category"],
                "raw_similarity": float(raw_text[index]),
                "final_score": float(final[index]),
            })
        domain_config = DOMAIN[self.language]
        domain_score = float(
            domain_config["text_weight"] * raw_text.max()
            + domain_config["topic_weight"] * raw_categories.max()
        )
        return {
            "normalized_query": normalized,
            "domain_score": domain_score,
            "agricultural": domain_score >= domain_config["threshold"],
            "raw_margin": candidates[0]["raw_similarity"] - candidates[1]["raw_similarity"],
            "candidates": candidates,
        }


def validation_metrics(index, entries):
    results = []
    for entry in entries:
        retrieval = index.retrieve(entry["question"])
        ids = [candidate["record_id"] for candidate in retrieval["candidates"]]
        expected = entry["expected_training_record"]
        results.append({
            "answerable": entry["answerable"],
            "top_1_correct": bool(entry["answerable"] and ids[0] == expected),
            "top_3_correct": bool(entry["answerable"] and expected in ids),
        })
    answerable = sum(item["answerable"] for item in results)
    top_1 = sum(item["top_1_correct"] for item in results)
    top_3 = sum(item["top_3_correct"] for item in results)
    return {
        "answerable_cases": answerable,
        "top_1_accuracy": top_1 / answerable if answerable else 0.0,
        "top_3_accuracy": top_3 / answerable if answerable else 0.0,
    }


def retrieve_saved_artifact(artifact, question):
    query_text = " ".join(str(question or "").strip().lower().split())
    query = artifact["vectorizer"].transform([query_text])
    raw_text = cosine_similarity(query, artifact["matrix"])[0]
    normalized_text = CandidateIndex.normalize_nonnegative(raw_text)
    raw_categories = cosine_similarity(query, artifact["category_centroids"])[0]
    normalized_categories = CandidateIndex.normalize_nonnegative(raw_categories)
    category_positions = {
        category: position for position, category in enumerate(artifact["category_names"])
    }
    raw_topic = np.asarray([
        raw_categories[category_positions[row["category"]]]
        for row in artifact["records"]
    ])
    normalized_topic = np.asarray([
        normalized_categories[category_positions[row["category"]]]
        for row in artifact["records"]
    ])
    weights = artifact["configuration"]["weights"]
    final = weights["tfidf"] * normalized_text + weights["topic"] * normalized_topic
    indices = np.argsort(final)[::-1][:3]
    candidates = [
        {
            "rank": rank,
            "record_id": artifact["records"][int(index)]["id"],
            "question": artifact["records"][int(index)]["question"],
            "raw_similarity": float(raw_text[index]),
            "final_score": float(final[index]),
        }
        for rank, index in enumerate(indices, 1)
    ]
    legacy_margin = candidates[0]["final_score"] - candidates[1]["final_score"]
    return {
        "normalized_query": query_text,
        "candidates": candidates,
        "legacy_margin": legacy_margin,
        "accepted": bool(
            raw_text.max() >= 1.0 - 1e-12
            or legacy_margin >= artifact["configuration"]["answer_confidence"]["threshold"]
        ),
    }


def main():
    canonical = load_json(DATASET_FILE)
    train = load_json(TRAIN_FILE)
    gold = load_json(GOLD_FILE)["entries"]
    paraphrases = load_json(PARAPHRASE_FILE)["cases"]
    negatives = []
    for path in OFF_TOPIC_FILES:
        negatives.extend(load_json(path)["cases"])
    negatives.extend(load_json(EDGE_FILE)["cases"])

    baseline_artifacts = {
        "English": joblib.load(BASELINE_DIR / "english.joblib"),
        "Twi": joblib.load(BASELINE_DIR / "twi.joblib"),
    }
    baseline_results = []
    for case in paraphrases:
        retrieval = retrieve_saved_artifact(
            baseline_artifacts[case["language"]], case["question"]
        )
        acceptable_ids = case.get(
            "acceptable_record_ids", [case.get("expected_record_id")]
        )
        top_ids = [candidate["record_id"] for candidate in retrieval["candidates"]]
        baseline_results.append({
            **case,
            "acceptable_record_ids": acceptable_ids,
            **retrieval,
            "top_1_correct": top_ids[0] in acceptable_ids,
            "top_3_correct": bool(set(top_ids) & set(acceptable_ids)),
        })

    experiments = {}
    for name, configuration in CONFIGURATIONS.items():
        language_indexes = {
            language: CandidateIndex(canonical, language, configuration)
            for language in ("English", "Twi")
        }
        train_indexes = {
            language: CandidateIndex(train, language, configuration)
            for language in ("English", "Twi")
        }
        validation = {
            language: validation_metrics(
                train_indexes[language],
                [entry for entry in gold if entry["language"] == language],
            )
            for language in ("English", "Twi")
        }
        positive_results = []
        for case in paraphrases:
            retrieval = language_indexes[case["language"]].retrieve(case["question"])
            acceptable_ids = case.get(
                "acceptable_record_ids", [case.get("expected_record_id")]
            )
            positive_results.append({
                **case,
                "acceptable_record_ids": acceptable_ids,
                **retrieval,
                "top_1_correct": retrieval["candidates"][0]["record_id"]
                in acceptable_ids,
                "top_3_correct": bool(set(acceptable_ids)
                & set(
                    candidate["record_id"]
                    for candidate in retrieval["candidates"]
                )),
            })
        negative_results = []
        for case in negatives:
            language = case["language"]
            retrieval = language_indexes[language].retrieve(case["question"])
            negative_results.append({"id": case["id"], "language": language, **retrieval})

        threshold_results = []
        for threshold in THRESHOLDS:
            accepted_positive = [
                item for item in positive_results
                if item["agricultural"]
                and item["candidates"][0]["raw_similarity"] >= threshold
                and item["raw_margin"] >= MIN_MARGIN
            ]
            accepted_negative = [
                item for item in negative_results
                if item["agricultural"]
                and item["candidates"][0]["raw_similarity"] >= threshold
                and item["raw_margin"] >= MIN_MARGIN
            ]
            correct_accepts = sum(item["top_1_correct"] for item in accepted_positive)
            threshold_results.append({
                "threshold": threshold,
                "minimum_raw_margin": MIN_MARGIN,
                "positive_coverage": len(accepted_positive) / len(positive_results),
                "correct_positive_coverage": correct_accepts / len(positive_results),
                "accepted_positive": len(accepted_positive),
                "correct_accepted_positive": correct_accepts,
                "incorrect_accepted_positive": len(accepted_positive) - correct_accepts,
                "negative_false_accepts": len(accepted_negative),
                "negative_cases": len(negative_results),
            })
        experiments[name] = {
            "configuration": configuration,
            "validation": validation,
            "paraphrase": {
                "cases": len(positive_results),
                "top_1_accuracy": sum(x["top_1_correct"] for x in positive_results)
                / len(positive_results),
                "top_3_accuracy": sum(x["top_3_correct"] for x in positive_results)
                / len(positive_results),
                "results": positive_results,
            },
            "negative_cases": len(negative_results),
            "thresholds": threshold_results,
        }

    report = {
        "schema_version": 1,
        "production_index_records": len(canonical),
        "selection_validation_records": len(train),
        "top_k": 3,
        "confidence_rule_tested": "agricultural AND raw_similarity >= threshold AND raw_margin >= 0.05",
        "active_v1_0_1_baseline": {
            "production_index_records": len(baseline_artifacts["English"]["records"]),
            "cases": len(baseline_results),
            "top_1_accuracy": sum(x["top_1_correct"] for x in baseline_results)
            / len(baseline_results),
            "top_3_accuracy": sum(x["top_3_correct"] for x in baseline_results)
            / len(baseline_results),
            "accepted_coverage": sum(x["accepted"] for x in baseline_results)
            / len(baseline_results),
            "correct_accepted_coverage": sum(
                x["accepted"] and x["top_1_correct"] for x in baseline_results
            ) / len(baseline_results),
            "results": baseline_results,
        },
        "experiments": experiments,
    }
    OUTPUT_FILE.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for name, experiment in experiments.items():
        print(name)
        print("  validation:", experiment["validation"])
        print(
            "  paraphrase top-1/top-3:",
            f"{experiment['paraphrase']['top_1_accuracy']:.2%}/",
            f"{experiment['paraphrase']['top_3_accuracy']:.2%}",
        )
        selected = next(x for x in experiment["thresholds"] if x["threshold"] == 0.50)
        print("  threshold 0.50:", selected)
    print(f"Report: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
