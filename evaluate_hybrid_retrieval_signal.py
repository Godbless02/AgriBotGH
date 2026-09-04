"""Grid-test TF-IDF plus IDF-weighted query-term coverage before production use."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

from evaluate_retrieval_robustness import (
    DATASET_FILE,
    DOMAIN,
    EDGE_FILE,
    GOLD_FILE,
    OFF_TOPIC_FILES,
    PARAPHRASE_FILE,
    THRESHOLDS,
    TRAIN_FILE,
    WEIGHTS,
    load_json,
)
from experiment_tfidf import CONFIGURATIONS, build_vectorizer
from query_normalization import normalize_query
from retrieval_signals import (
    build_term_coverage_context,
    substantive_query_term_count,
    weighted_query_term_coverage,
)


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_FILE = BASE_DIR / "models" / "retrieval_hybrid_signal_experiments.json"
COVERAGE_WEIGHTS = (0.0, 0.15, 0.25, 0.35, 0.45, 0.55)
MARGINS = (0.03, 0.05, 0.08, 0.10)
SUPPLEMENTAL_SIMILARITIES = (0.25, 0.30, 0.35, 0.40)
SUPPLEMENTAL_COVERAGES = (0.55, 0.60, 0.70, 0.75, 0.80, 0.85)
SUPPLEMENTAL_MARGINS = (0.05, 0.08, 0.10)
SUPPLEMENTAL_TERM_COUNTS = (2, 3)
EXTRA_NEGATIVES = (
    {"id": "hybrid_neg_en_capital", "language": "English", "question": "What is the capital of France?"},
    {"id": "hybrid_neg_en_joke", "language": "English", "question": "Tell me a joke."},
    {"id": "hybrid_neg_tw_capital", "language": "Twi", "question": "France ahenkurow ne d\u025bn?"},
    {"id": "hybrid_neg_tw_joke", "language": "Twi", "question": "Ka aseres\u025bm bi kyer\u025b me."},
)


class HybridIndex:
    def __init__(self, records, language, coverage_weight):
        self.records = records
        self.language = language
        self.coverage_weight = coverage_weight
        self.question_field = "question_en" if language == "English" else "question_twi"
        self.questions = [
            normalize_query(record[self.question_field], language) for record in records
        ]
        self.vectorizer = build_vectorizer(CONFIGURATIONS["C_word_and_character"])
        self.matrix = self.vectorizer.fit_transform(self.questions)
        self.coverage_context = build_term_coverage_context(
            self.vectorizer, self.questions, language
        )
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
    def normalize(values):
        maximum = float(values.max()) if values.size else 0.0
        return values / maximum if maximum > 0 else np.zeros_like(values)

    def retrieve(self, question):
        normalized = normalize_query(question, self.language)
        query = self.vectorizer.transform([normalized])
        raw_text = cosine_similarity(query, self.matrix)[0]
        coverage = weighted_query_term_coverage(normalized, self.coverage_context)
        evidence = (
            (1.0 - self.coverage_weight) * raw_text
            + self.coverage_weight * coverage
        )
        raw_categories = cosine_similarity(query, self.centroids)[0]
        normalized_categories = self.normalize(raw_categories)
        normalized_evidence = self.normalize(evidence)
        topic = np.asarray([
            normalized_categories[self.category_positions[record["category"]]]
            for record in self.records
        ])
        final = WEIGHTS["tfidf"] * normalized_evidence + WEIGHTS["topic"] * topic
        ranked = np.argsort(final)[::-1]
        exact = np.flatnonzero(raw_text >= 1.0 - 1e-12)
        if exact.size:
            selected = int(exact[np.argmax(final[exact])])
            ranked = np.concatenate((np.asarray([selected]), ranked[ranked != selected]))
        indices = ranked[:3]
        candidates = [
            {
                "rank": rank,
                "record_id": self.records[int(index)]["id"],
                "question": self.records[int(index)][self.question_field],
                "raw_tfidf_similarity": float(raw_text[index]),
                "term_coverage": float(coverage[index]),
                "evidence_score": float(evidence[index]),
                "final_score": float(final[index]),
            }
            for rank, index in enumerate(indices, 1)
        ]
        config = DOMAIN[self.language]
        domain_score = float(
            config["text_weight"] * raw_text.max()
            + config["topic_weight"] * raw_categories.max()
        )
        return {
            "normalized_query": normalized,
            "agricultural": domain_score >= config["threshold"],
            "domain_score": domain_score,
            "evidence_margin": candidates[0]["evidence_score"] - candidates[1]["evidence_score"],
            "substantive_query_terms": substantive_query_term_count(
                normalized, self.coverage_context
            ),
            "candidates": candidates,
        }


def evaluate_cases(indexes, cases, labelled):
    results = []
    for case in cases:
        result = indexes[case["language"]].retrieve(case["question"])
        item = {**case, **result}
        if labelled:
            acceptable = case.get("acceptable_record_ids", [case.get("expected_record_id")])
            ids = [candidate["record_id"] for candidate in result["candidates"]]
            item["acceptable_record_ids"] = acceptable
            item["top_1_correct"] = ids[0] in acceptable
            item["top_3_correct"] = bool(set(ids) & set(acceptable))
        results.append(item)
    return results


def main():
    canonical = load_json(DATASET_FILE)
    train = load_json(TRAIN_FILE)
    gold = load_json(GOLD_FILE)["entries"]
    positives = load_json(PARAPHRASE_FILE)["cases"]
    positives.append({
        "id": "para_en_maize_grow_requested",
        "language": "English",
        "question": "How do I grow maize?",
        "acceptable_record_ids": [282],
        "review_note": "Nearest dataset answer that directly contains the grow-maize intent; dataset has no general maize-growing overview.",
    })
    negatives = []
    for path in OFF_TOPIC_FILES:
        negatives.extend(load_json(path)["cases"])
    negatives.extend(load_json(EDGE_FILE)["cases"])
    negatives.extend(EXTRA_NEGATIVES)

    experiments = []
    for coverage_weight in COVERAGE_WEIGHTS:
        full_indexes = {
            language: HybridIndex(canonical, language, coverage_weight)
            for language in ("English", "Twi")
        }
        train_indexes = {
            language: HybridIndex(train, language, coverage_weight)
            for language in ("English", "Twi")
        }
        positive_results = evaluate_cases(full_indexes, positives, True)
        negative_results = evaluate_cases(full_indexes, negatives, False)
        validation = {}
        for language in ("English", "Twi"):
            language_gold = [entry for entry in gold if entry["language"] == language]
            cases = [{
                "language": language,
                "question": entry["question"],
                "acceptable_record_ids": [entry["expected_training_record"]],
                "answerable": entry["answerable"],
            } for entry in language_gold]
            results = evaluate_cases({language: train_indexes[language]}, cases, True)
            answerable = [item for item in results if item["answerable"]]
            validation[language] = {
                "answerable_cases": len(answerable),
                "top_1_accuracy": sum(x["top_1_correct"] for x in answerable) / len(answerable),
                "top_3_accuracy": sum(x["top_3_correct"] for x in answerable) / len(answerable),
            }
        gates = []
        for threshold in THRESHOLDS:
            for margin in MARGINS:
                accepted_positive = [
                    item for item in positive_results
                    if item["agricultural"]
                    and item["candidates"][0]["evidence_score"] >= threshold
                    and item["evidence_margin"] >= margin
                ]
                accepted_negative = [
                    item for item in negative_results
                    if item["agricultural"]
                    and item["candidates"][0]["evidence_score"] >= threshold
                    and item["evidence_margin"] >= margin
                ]
                correct = sum(item["top_1_correct"] for item in accepted_positive)
                gates.append({
                    "threshold": threshold,
                    "minimum_margin": margin,
                    "accepted_positive": len(accepted_positive),
                    "correct_accepted_positive": correct,
                    "incorrect_accepted_positive": len(accepted_positive) - correct,
                    "positive_coverage": len(accepted_positive) / len(positive_results),
                    "response_precision": correct / len(accepted_positive) if accepted_positive else 0.0,
                    "negative_false_accepts": len(accepted_negative),
                    "negative_cases": len(negative_results),
                })
        grow = next(item for item in positive_results if item["id"] == "para_en_maize_grow_requested")
        experiments.append({
            "coverage_weight": coverage_weight,
            "similarity_weight": 1.0 - coverage_weight,
            "validation": validation,
            "paraphrase": {
                "cases": len(positive_results),
                "top_1_accuracy": sum(x["top_1_correct"] for x in positive_results) / len(positive_results),
                "top_3_accuracy": sum(x["top_3_correct"] for x in positive_results) / len(positive_results),
            },
            "grow_maize_result": grow,
            "gates": gates,
        })

    # Ranking quality is best with the original similarity signal. Test term
    # coverage only as a secondary acceptance gate, never as a ranking blend.
    baseline = next(item for item in experiments if item["coverage_weight"] == 0.0)
    baseline_positive = evaluate_cases(
        {
            language: HybridIndex(canonical, language, 0.0)
            for language in ("English", "Twi")
        },
        positives,
        True,
    )
    baseline_negative = evaluate_cases(
        {
            language: HybridIndex(canonical, language, 0.0)
            for language in ("English", "Twi")
        },
        negatives,
        False,
    )
    supplemental_gates = []
    for similarity in SUPPLEMENTAL_SIMILARITIES:
        for coverage in SUPPLEMENTAL_COVERAGES:
            for margin in SUPPLEMENTAL_MARGINS:
                for minimum_terms in SUPPLEMENTAL_TERM_COUNTS:
                    def accepted(item):
                        top = item["candidates"][0]
                        base = (
                            top["raw_tfidf_similarity"] >= 0.50
                            and item["evidence_margin"] >= 0.05
                        )
                        supplemental = (
                            top["raw_tfidf_similarity"] >= similarity
                            and top["term_coverage"] >= coverage
                            and item["evidence_margin"] >= margin
                            and item["substantive_query_terms"] >= minimum_terms
                        )
                        return item["agricultural"] and (base or supplemental)

                    accepted_positive = [x for x in baseline_positive if accepted(x)]
                    accepted_negative = [x for x in baseline_negative if accepted(x)]
                    correct = sum(x["top_1_correct"] for x in accepted_positive)
                    supplemental_gates.append({
                        "base_similarity_threshold": 0.50,
                        "base_minimum_margin": 0.05,
                        "supplemental_similarity_threshold": similarity,
                        "supplemental_term_coverage_threshold": coverage,
                        "supplemental_minimum_margin": margin,
                        "supplemental_minimum_substantive_terms": minimum_terms,
                        "accepted_positive": len(accepted_positive),
                        "correct_accepted_positive": correct,
                        "incorrect_accepted_positive": len(accepted_positive) - correct,
                        "positive_coverage": len(accepted_positive) / len(baseline_positive),
                        "response_precision": correct / len(accepted_positive) if accepted_positive else 0.0,
                        "negative_false_accepts": len(accepted_negative),
                        "negative_false_accept_ids": [x["id"] for x in accepted_negative],
                    })

    grow_baseline = next(
        item for item in baseline_positive
        if item["id"] == "para_en_maize_grow_requested"
    )
    safe_supplemental = [
        gate for gate in supplemental_gates
        if gate["negative_false_accepts"] == 0
        and gate["incorrect_accepted_positive"] == 0
        and grow_baseline["agricultural"]
        and grow_baseline["candidates"][0]["raw_tfidf_similarity"]
            >= gate["supplemental_similarity_threshold"]
        and grow_baseline["candidates"][0]["term_coverage"]
            >= gate["supplemental_term_coverage_threshold"]
        and grow_baseline["evidence_margin"]
            >= gate["supplemental_minimum_margin"]
        and grow_baseline["substantive_query_terms"]
            >= gate["supplemental_minimum_substantive_terms"]
    ]
    supplemental_selection = max(
        safe_supplemental,
        key=lambda gate: (
            gate["correct_accepted_positive"],
            gate["supplemental_similarity_threshold"],
            gate["supplemental_term_coverage_threshold"],
            gate["supplemental_minimum_margin"],
            gate["supplemental_minimum_substantive_terms"],
        ),
        default=None,
    )

    eligible = [
        (experiment, gate)
        for experiment in experiments
        for gate in experiment["gates"]
        if gate["negative_false_accepts"] == 0
        and gate["incorrect_accepted_positive"] == 0
        and experiment["grow_maize_result"]["agricultural"]
        and experiment["grow_maize_result"]["candidates"][0]["evidence_score"] >= gate["threshold"]
        and experiment["grow_maize_result"]["evidence_margin"] >= gate["minimum_margin"]
    ]
    selection = None
    if eligible:
        selected_experiment, selected_gate = max(
            eligible,
            key=lambda pair: (
                pair[1]["correct_accepted_positive"],
                pair[0]["paraphrase"]["top_1_accuracy"],
                -pair[0]["coverage_weight"],
            ),
        )
        selection = {
            "coverage_weight": selected_experiment["coverage_weight"],
            "similarity_weight": selected_experiment["similarity_weight"],
            "gate": selected_gate,
            "validation": selected_experiment["validation"],
            "paraphrase": selected_experiment["paraphrase"],
            "grow_maize_result": selected_experiment["grow_maize_result"],
        }
    report = {
        "schema_version": 1,
        "signal": "weighted TF-IDF/character similarity plus IDF-weighted query-term coverage",
        "production_records": len(canonical),
        "positive_cases": len(positives),
        "negative_cases": len(negatives),
        "experiments": experiments,
        "selection": selection,
        "ranking_decision": {
            "selected_coverage_weight": 0.0,
            "reason": "Coverage blending reduced held-out top-1 accuracy; production ranking remains unchanged.",
            "validation": baseline["validation"],
        },
        "supplemental_acceptance": {
            "selection": supplemental_selection,
            "grow_maize_result": grow_baseline,
            "gates": supplemental_gates,
        },
    }
    OUTPUT_FILE.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if selection is None:
        print("No tested hybrid configuration safely accepted the broad grow-maize query.")
        for experiment in experiments:
            grow = experiment["grow_maize_result"]
            safest = [gate for gate in experiment["gates"] if gate["negative_false_accepts"] == 0 and gate["incorrect_accepted_positive"] == 0]
            print(
                f"coverage={experiment['coverage_weight']:.2f} "
                f"grow_score={grow['candidates'][0]['evidence_score']:.4f} "
                f"grow_margin={grow['evidence_margin']:.4f} "
                f"safe_gates={len(safest)}"
            )
    else:
        print(json.dumps(selection, ensure_ascii=False, indent=2))
    print("Supplemental selection:")
    print(json.dumps(supplemental_selection, ensure_ascii=False, indent=2))
    print(f"Report: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
