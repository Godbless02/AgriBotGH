"""Dataset-grounded safeguards for crop and livestock entity substitution."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Mapping

from retrieval_semantics import extract_entities


WORD_PATTERN = re.compile(r"[^\W\d_]+(?:[-'][^\W\d_]+)?", re.UNICODE)

# These are language/function words and generic farming concepts, not a list of
# unsupported entities. Dataset-specific support is derived at runtime below.
GENERIC_TERMS = {
    "a", "about", "adequate", "after", "animal", "animals", "appropriate",
    "are", "around", "as", "at", "be", "before", "begin", "best", "business",
    "commercial", "commercially", "conditions", "crop", "crops", "do", "does",
    "enterprise", "farm", "farmer", "farmers", "farming", "feed", "feeding",
    "first", "food", "for", "from", "ghana", "good", "how", "i", "in", "is",
    "it", "keep", "keeping", "kind", "large", "livestock", "manage", "needed",
    "needs", "new", "of", "on", "organic", "plan", "production", "raise",
    "raising", "rear", "rearing", "record", "records", "required", "requires",
    "shelter", "should", "small", "soil", "start", "suitable", "the", "their",
    "them", "they", "to", "type", "what", "when", "where", "which", "who",
    "why", "with", "year", "your", "my", "our", "his", "her", "this", "that",
    "m", "s", "support",
    # Common Twi function and generic agriculture words.
    "adeɛn", "anaa", "ase", "bɛn", "de", "dɛn", "ɛdeɛn", "ɛfata", "ɛhia",
    "ɛsɛ", "fi", "ho", "kuayɛ", "ma", "me", "mu", "na", "nea", "nti", "no",
    "nso", "ofuo", "okuafo", "pa", "sɛ", "wɔ", "yɛ", "yɛn",
}

ENGLISH_FRAME_PATTERNS = (
    re.compile(
        r"\b(?:raise|raising|rear|rearing|breed|breeding|house|housing|feed|feeding|"
        r"grow|growing|cultivate|cultivating|plant|planting|harvest|harvesting|"
        r"produce|producing|manage|managing)\s+(?:an?\s+|some\s+|my\s+|the\s+)?"
        r"(?P<entity>[^\W\d_]+)", re.IGNORECASE | re.UNICODE
    ),
    re.compile(
        r"\b(?P<entity>[^\W\d_]+)\s+(?:farm|farming|rearing|husbandry|"
        r"cultivation|enterprise|ranch)\b", re.IGNORECASE | re.UNICODE
    ),
    re.compile(
        r"\b(?P<entity>[^\W\d_]+)\s+(?:need|needs|require|requires|eat|eats)\b",
        re.IGNORECASE | re.UNICODE,
    ),
    re.compile(
        r"\b(?:housing|house|shelter|feed|food|fence|fencing|diet)\b.{0,35}?"
        r"\bfor\s+(?:an?\s+|some\s+|the\s+)?(?P<entity>[^\W\d_]+)",
        re.IGNORECASE | re.UNICODE,
    ),
)

TWI_FRAME_PATTERNS = (
    re.compile(r"\b(?P<entity>[^\W\d_]+)\s+kuayɛ\b", re.IGNORECASE | re.UNICODE),
    re.compile(
        r"\b(?:yɛn|dua|dɔ)\s+(?:me\s+|no\s+)?(?P<entity>[^\W\d_]+)",
        re.IGNORECASE | re.UNICODE,
    ),
)

IRREGULAR_SINGULARS = {
    "geese": "goose",
    "mice": "mouse",
    "oxen": "ox",
    "turkeys": "turkey",
}


def normalize_term(value: str) -> str:
    """Normalize a single lexical entity without language-specific stemming."""
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold().strip("-' ")
    if normalized in IRREGULAR_SINGULARS:
        return IRREGULAR_SINGULARS[normalized]
    if len(normalized) > 4 and normalized.endswith("ies"):
        return normalized[:-3] + "y"
    if len(normalized) > 4 and normalized.endswith("es") and not normalized.endswith("ses"):
        return normalized[:-2]
    if len(normalized) > 3 and normalized.endswith("s") and not normalized.endswith("ss"):
        return normalized[:-1]
    return normalized


def normalized_words(text: str) -> set[str]:
    words = set()
    for match in WORD_PATTERN.finditer(str(text or "")):
        token = match.group(0)
        words.add(normalize_term(token))
        words.update(normalize_term(part) for part in re.split(r"[-']", token) if part)
    return words


def salient_agricultural_terms(text: str, language_code: str) -> set[str]:
    """Extract nouns occupying general crop/livestock slots in a query."""
    patterns = TWI_FRAME_PATTERNS if language_code == "tw" else ENGLISH_FRAME_PATTERNS
    terms = set()
    for pattern in patterns:
        for match in pattern.finditer(str(text or "")):
            term = normalize_term(match.group("entity"))
            if term and term not in GENERIC_TERMS:
                terms.add(term)
    return terms


@dataclass(frozen=True)
class CompatibilityDecision:
    compatible: bool
    reason: str
    salient_terms: frozenset[str]
    unsupported_terms: frozenset[str]


class DatasetEntityGuard:
    """Build supported vocabulary from the active canonical dataset."""

    def __init__(self, records: Iterable[Mapping[str, object]]) -> None:
        records = tuple(records)
        corpus_parts = []
        for record in records:
            corpus_parts.extend(str(value or "") for value in record.values())
        self.supported_vocabulary = frozenset(normalized_words(" ".join(corpus_parts)))

    @staticmethod
    def _language_name(language_code: str) -> str:
        return "Twi" if language_code == "tw" else "English"

    def profile(self, text: str, language_code: str) -> dict[str, frozenset[str]]:
        salient = salient_agricultural_terms(text, language_code)
        known = extract_entities(text, self._language_name(language_code))
        unsupported = {
            term for term in salient if term not in self.supported_vocabulary
        }
        return {
            "salient": frozenset(salient),
            "known": frozenset(known),
            "unsupported": frozenset(unsupported),
        }

    def preserves_salient_entities(
        self, original: str, interpreted: str, language_code: str
    ) -> bool:
        original_profile = self.profile(original, language_code)
        interpreted_profile = self.profile(interpreted, language_code)
        if not original_profile["salient"].issubset(interpreted_profile["salient"]):
            return False
        return original_profile["known"] == interpreted_profile["known"]

    def evaluate(
        self,
        query: str,
        candidate_question: str,
        candidate_category: str,
        language_code: str,
    ) -> CompatibilityDecision:
        query_profile = self.profile(query, language_code)
        salient = query_profile["salient"]
        unsupported = query_profile["unsupported"]
        if unsupported:
            return CompatibilityDecision(
                False, "unsupported_dataset_entity", salient, unsupported
            )

        language = self._language_name(language_code)
        query_known = set(query_profile["known"])
        candidate_text = f"{candidate_category} {candidate_question}"
        candidate_known = extract_entities(candidate_text, language)
        if query_known and candidate_known and not query_known & candidate_known:
            return CompatibilityDecision(
                False, "known_entity_conflict", salient, frozenset()
            )

        # Dataset-supported salient terms must occur in, or normalize to a known
        # alias shared with, the selected record. This catches entity swapping
        # while allowing corn/maize, cow/cattle, and chicken/poultry aliases.
        candidate_words = normalized_words(candidate_text)
        unmatched = {term for term in salient if term not in candidate_words}
        if unmatched and not (query_known and query_known & candidate_known):
            return CompatibilityDecision(
                False, "candidate_entity_mismatch", salient, frozenset()
            )
        return CompatibilityDecision(True, "compatible", salient, frozenset())
