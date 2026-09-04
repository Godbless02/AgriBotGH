"""Validate a saved retrieval candidate without changing the active manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib

from retrieval_runtime import RetrievalRuntime, sha256_file


BASE_DIR = Path(__file__).resolve().parent
DATASET = BASE_DIR / "data" / "agribotgh_dataset_bilingual_563.json"
CHALLENGE = BASE_DIR / "data" / "evaluation" / "retrieval_challenge_v2.json"
REQUIRED_MAIZE_CASES = (
    "For maize what fertilizer is best",
    "Which fertilizer is best for maize?",
    "Which fertilizer should I use for maize?",
    "What is the best fertilizer for maize?",
    "For maize what fertilizer should I use?",
    "For maize what is the best fertilizer it?",
)


def load_candidate(version: str) -> RetrievalRuntime:
    version_dir = BASE_DIR / "models" / "production" / version
    with (version_dir / "model_metadata.json").open(encoding="utf-8") as handle:
        metadata = json.load(handle)
    if metadata["semantic_version"] != version:
        raise RuntimeError("Candidate metadata version mismatch")
    if metadata["canonical_dataset_sha256"] != sha256_file(DATASET):
        raise RuntimeError("Candidate was not built from the canonical dataset")

    runtime = RetrievalRuntime.__new__(RetrievalRuntime)
    runtime.models = {}
    for language in ("English", "Twi"):
        summary = metadata["artifacts"][language]
        path = version_dir / summary["file"]
        if sha256_file(path) != summary["sha256"]:
            raise RuntimeError(f"{language} candidate checksum mismatch")
        runtime.models[language] = RetrievalRuntime.prepare_artifact(
            joblib.load(path), language
        )
    return runtime


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="1.3.1")
    args = parser.parse_args()
    runtime = load_candidate(args.version)

    failures = []
    print("Required maize-fertilizer paraphrases:")
    for question in REQUIRED_MAIZE_CASES:
        result = runtime.retrieve(question, "en")
        candidate = result["candidates"][0]
        record_id = f"qa-{candidate['id']:04d}"
        print(
            f"  {result['state']} {record_id} "
            f"raw={candidate['raw_tfidf_similarity']:.4f} "
            f"margin={result['raw_similarity_margin']:.4f} | {question}"
        )
        if result["state"] != "A" or record_id != "qa-0002":
            failures.append(question)

    with DATASET.open(encoding="utf-8") as handle:
        records = json.load(handle)
    exact_failures = []
    for language, field, code in (
        ("English", "question_en", "en"),
        ("Twi", "question_twi", "tw"),
    ):
        for record in records:
            result = runtime.retrieve(record[field], code)
            expected = f"qa-{record['id']:04d}"
            actual = f"qa-{result['candidates'][0]['id']:04d}"
            if result["state"] != "A" or actual != expected:
                exact_failures.append((language, expected, actual, result["state"]))
    print(f"Canonical exact questions: {1126 - len(exact_failures)}/1126 correct State-A")

    challenge = json.loads(CHALLENGE.read_text(encoding="utf-8"))
    challenge_summary = {"English": [0, 0], "Twi": [0, 0]}
    challenge_failures = []
    for case in challenge["positive_cases"]:
        code = "tw" if case["language"] == "Twi" else "en"
        result = runtime.retrieve(case["question"], code)
        actual = result["candidates"][0]["id"]
        challenge_summary[case["language"]][1] += 1
        if result["state"] == "A" and actual in case["acceptable_record_ids"]:
            challenge_summary[case["language"]][0] += 1
        elif result["state"] == "A":
            challenge_failures.append((case["id"], actual, "unsafe_answer"))
    ambiguous_failures = []
    for case in challenge["ambiguous_agriculture_cases"]:
        code = "tw" if case["language"] == "Twi" else "en"
        result = runtime.retrieve(case["question"], code)
        if result["state"] != "B":
            ambiguous_failures.append((case["id"], result["state"]))
    print(
        "Fresh challenge correct State-A: "
        + ", ".join(
            f"{language}={values[0]}/{values[1]}"
            for language, values in challenge_summary.items()
        )
    )
    if challenge_summary["English"][0] < 16 or challenge_summary["Twi"][0] < 10:
        challenge_failures.append(("minimum_coverage", challenge_summary))

    if failures or exact_failures or challenge_failures or ambiguous_failures:
        if exact_failures:
            print("First exact failures:", exact_failures[:10])
        raise SystemExit(
            f"Candidate validation failed: {len(failures)} paraphrase failures, "
            f"{len(exact_failures)} exact-question failures, "
            f"{len(challenge_failures)} challenge failures, "
            f"{len(ambiguous_failures)} ambiguity failures"
        )
    print(f"Candidate {args.version} passed without changing active_model.json")


if __name__ == "__main__":
    main()
