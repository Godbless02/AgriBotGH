"""One-pass Gemini interpretation followed by the existing retrieval runtime."""

from __future__ import annotations

import logging
from typing import Any


LOGGER = logging.getLogger(__name__)


def candidate_raw_score(retrieval: dict[str, Any]) -> float:
    candidates = retrieval.get("candidates") or []
    if not candidates:
        return 0.0
    return float(candidates[0].get("raw_tfidf_similarity") or 0.0)


def attempt_retrieval_assistance(
    original_query: str,
    language_code: str,
    original_retrieval: dict[str, Any],
    retrieval_runtime: Any,
    gemini_service: Any,
    entity_guard: Any = None,
) -> dict[str, Any]:
    """Make at most one interpretation call and conservatively compare results."""
    original_score = candidate_raw_score(original_retrieval)
    result = {
        "eligible": original_retrieval.get("state") == "B",
        "called": False,
        "accepted": False,
        "reason": "not_low_confidence",
        "original_query": original_query,
        "interpreted_query": None,
        "original_score": original_score,
        "interpreted_score": None,
        "original_retrieval": original_retrieval,
        "interpreted_retrieval": None,
        "selected_retrieval": original_retrieval,
    }
    if not result["eligible"]:
        return result
    if not gemini_service.available:
        result["reason"] = gemini_service.availability()["reason"]
        return result

    result["called"] = True
    interpretation = gemini_service.interpret_query(original_query, language_code)
    if not interpretation.get("success"):
        result["reason"] = interpretation.get("code", "interpretation_failed")
        return result

    interpreted_query = interpretation["interpreted_query"]
    result["interpreted_query"] = interpreted_query
    if interpreted_query.casefold() == original_query.strip().casefold():
        result["reason"] = "unchanged_interpretation"
        return result
    if entity_guard is not None and not entity_guard.preserves_salient_entities(
        original_query, interpreted_query, language_code
    ):
        result["reason"] = "salient_entity_not_preserved"
        return result

    interpreted_retrieval = retrieval_runtime.retrieve(
        interpreted_query, language_code
    )
    interpreted_score = candidate_raw_score(interpreted_retrieval)
    result["interpreted_retrieval"] = interpreted_retrieval
    result["interpreted_score"] = interpreted_score

    second_is_strong = interpreted_retrieval.get("state") == "A"
    non_regressing_score = interpreted_score >= original_score
    candidate_compatible = True
    if second_is_strong and entity_guard is not None:
        candidate = interpreted_retrieval["candidates"][0]
        original_decision = entity_guard.evaluate(
            original_query,
            candidate["question"],
            candidate["category"],
            language_code,
        )
        interpreted_decision = entity_guard.evaluate(
            interpreted_query,
            candidate["question"],
            candidate["category"],
            language_code,
        )
        candidate_compatible = (
            original_decision.compatible and interpreted_decision.compatible
        )
    if second_is_strong and non_regressing_score and candidate_compatible:
        result["accepted"] = True
        result["reason"] = "stronger_dataset_match"
        result["selected_retrieval"] = interpreted_retrieval
    elif not candidate_compatible:
        result["reason"] = "entity_incompatible_second_pass"
    elif not second_is_strong:
        result["reason"] = "second_pass_still_uncertain"
    else:
        result["reason"] = "second_pass_score_regressed"

    LOGGER.info(
        "Retrieval assistance: language=%s accepted=%s reason=%s first=%.4f second=%s",
        language_code,
        result["accepted"],
        result["reason"],
        original_score,
        "none" if interpreted_score is None else f"{interpreted_score:.4f}",
    )
    return result
