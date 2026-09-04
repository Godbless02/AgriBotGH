"""Conservative, language-aware normalization for AgriBotGH retrieval."""

import re
import unicodedata


ENGLISH_SAFE_REPLACEMENTS = (
    (re.compile(r"\bfertilisers?\b"), "fertilizer"),
    (re.compile(r"\bcorn\b"), "maize"),
    (re.compile(r"\bpest management\b"), "pest control"),
)


def normalize_query(value, language="English"):
    """Normalize formatting and a small set of meaning-preserving variants.

    This intentionally does not remove general stop words, stem arbitrary
    words, reorder tokens, or rewrite farmer questions into canned intents.
    """

    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = text.replace("’", "'").replace("‘", "'")
    text = re.sub(r"\s+", " ", text).strip()
    if language == "English":
        for pattern, replacement in ENGLISH_SAFE_REPLACEMENTS:
            text = pattern.sub(replacement, text)
    return text
