"""Inspect AgriBotGH retrieval decisions locally without exposing an HTTP route."""

from __future__ import annotations

import argparse
from pathlib import Path

from retrieval_runtime import RetrievalRuntime


BASE_DIR = Path(__file__).resolve().parent
DATASET = BASE_DIR / "data" / "agribotgh_dataset_bilingual_563.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", nargs="+", help="Question to inspect")
    parser.add_argument("--language", choices=("en", "tw"), default="en")
    args = parser.parse_args()

    query = " ".join(args.query)
    details = RetrievalRuntime(BASE_DIR, DATASET).debug_retrieve(
        query, args.language
    )
    print(f"Original:   {details['original_query']}")
    print(f"Normalized: {details['normalized_query']}")
    print(
        f"Decision:   {details['decision']} (State {details['state']}); "
        f"domain={details['domain_score']:.4f}; "
        f"raw margin={details['raw_similarity_margin']:.4f}"
    )
    print(
        f"Gate:       similarity >= {details['similarity_threshold']}; "
        f"raw margin >= {details['minimum_raw_margin']}"
    )
    print("Top candidates:")
    for candidate in details["candidates"]:
        print(
            f"  {candidate['rank']}. qa-{candidate['id']:04d} "
            f"raw={candidate['raw_tfidf_similarity']:.4f} "
            f"final={candidate['final_score']:.4f} | {candidate['question']}"
        )
        print(f"     Answer: {candidate['answer']}")


if __name__ == "__main__":
    main()
