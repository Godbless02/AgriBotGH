"""Conservative bilingual operation compatibility for retrieved questions."""

from __future__ import annotations

import re
from dataclasses import dataclass


PLANTING_ESTABLISHMENT = "PLANTING_ESTABLISHMENT"
HARVEST_MATURITY = "HARVEST_MATURITY"
SITE_LAND_SELECTION = "SITE_LAND_SELECTION"


ENGLISH_PATTERNS = {
    SITE_LAND_SELECTION: (
        re.compile(r"\b(?:where|which (?:site|place|land)|what (?:site|land))\b.{0,35}\b(?:grow|plant|suitable|best|choose)\b", re.I),
        re.compile(r"\b(?:select|choose)\s+(?:a\s+|the\s+)?(?:site|land|field|place)\b", re.I),
        re.compile(r"\b(?:site|land|field|place)\s+(?:is|would be)\s+(?:best|suitable)\b", re.I),
    ),
    PLANTING_ESTABLISHMENT: (
        re.compile(r"\b(?:how (?:do|should|can) i|how (?:should|can) (?:we|you))\s+(?:properly\s+)?(?:plant|sow|transplant|establish)\b", re.I),
        re.compile(r"\b(?:planting|sowing|transplanting)\s+(?!season\b|time\b)", re.I),
        re.compile(r"\b(?:plant|sow|transplant|establish)\s+(?:my\s+|the\s+|a\s+)?(?:seeds?\b|seedlings?\b|[a-z][\w'-]*\??$)", re.I),
    ),
    HARVEST_MATURITY: (
        re.compile(r"\b(?:how|when)\s+(?:do|should|can)\s+(?:i|we|you)\s+(?:harvest|pick)\b", re.I),
        re.compile(r"\b(?:harvest(?:ing)?|picking)\b", re.I),
        re.compile(r"\bready\s+to\s+harvest\b", re.I),
        re.compile(r"\b(?:know|tell)\b.{0,35}\b(?:mature|ready)\b", re.I),
    ),
}

# These expressions are taken from recurring canonical Twi question frames.
# Phase 1 deliberately leaves less certain Twi wording unknown.
TWI_PATTERNS = {
    SITE_LAND_SELECTION: (
        re.compile(r"\b(?:apaw|paw)\s+(?:asase|beae|afuo)\b", re.I),
        re.compile(r"\bbeae\s+bɛn\s+na\s+ɛfata\b", re.I),
    ),
    PLANTING_ESTABLISHMENT: (
        re.compile(r"\b(?:mɛdua|medua|wɔdua|dua)\b", re.I),
        re.compile(r"\b(?:aba|nnɔbae)\s+(?:to|gu)\s+(?:asase\s+)?mu\b", re.I),
    ),
    HARVEST_MATURITY: (
        re.compile(r"\b(?:metutu|wɔtutu|tutu)\b", re.I),
        re.compile(r"\b(?:megye|wɔgye)\b.{0,30}\b(?:aba|nnuaba|bankye|mako|bayerɛ)\b", re.I),
    ),
}


@dataclass(frozen=True)
class OperationCompatibilityDecision:
    compatible: bool
    reason: str
    query_operations: frozenset[str]
    candidate_operations: frozenset[str]


class OperationCompatibilityGuard:
    """Downgrade only clear, single-operation conflicts; otherwise fail open."""

    _INCOMPATIBLE = {
        (PLANTING_ESTABLISHMENT, HARVEST_MATURITY): "planting_vs_harvest",
        (PLANTING_ESTABLISHMENT, SITE_LAND_SELECTION): "planting_vs_site_selection",
        (HARVEST_MATURITY, PLANTING_ESTABLISHMENT): "harvest_vs_planting",
    }

    def detect(self, text: str, language_code: str) -> frozenset[str]:
        patterns = TWI_PATTERNS if language_code == "tw" else ENGLISH_PATTERNS
        value = str(text or "")
        operations = {
            operation
            for operation, expressions in patterns.items()
            if any(expression.search(value) for expression in expressions)
        }
        # In "where should I plant" frames, planting names the future activity;
        # the explicit question is choosing its location.
        if SITE_LAND_SELECTION in operations:
            operations.discard(PLANTING_ESTABLISHMENT)
        return frozenset(operations)

    def preserves_operation(
        self, original: str, interpreted: str, language_code: str
    ) -> bool:
        original_operations = self.detect(original, language_code)
        interpreted_operations = self.detect(interpreted, language_code)
        if len(original_operations) != 1 or len(interpreted_operations) != 1:
            return True
        original_operation = next(iter(original_operations))
        interpreted_operation = next(iter(interpreted_operations))
        return original_operation == interpreted_operation

    def evaluate(
        self, query: str, candidate_question: str, language_code: str
    ) -> OperationCompatibilityDecision:
        query_operations = self.detect(query, language_code)
        candidate_operations = self.detect(candidate_question, language_code)
        if not query_operations or not candidate_operations:
            return OperationCompatibilityDecision(
                True, "unknown_operation", query_operations, candidate_operations
            )
        if len(query_operations) != 1 or len(candidate_operations) != 1:
            return OperationCompatibilityDecision(
                True, "multi_intent", query_operations, candidate_operations
            )
        pair = (next(iter(query_operations)), next(iter(candidate_operations)))
        reason = self._INCOMPATIBLE.get(pair)
        return OperationCompatibilityDecision(
            reason is None,
            reason or "compatible",
            query_operations,
            candidate_operations,
        )
