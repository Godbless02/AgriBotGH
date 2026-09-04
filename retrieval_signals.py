"""General, explainable auxiliary signals for AgriBotGH retrieval."""

from __future__ import annotations

import re

import numpy as np

from query_normalization import normalize_query


STOPWORDS = {
    "English": {
        "a", "an", "and", "are", "be", "can", "could", "do", "does", "for",
        "from", "have", "how", "i", "in", "is", "it", "me", "my", "of", "on",
        "please", "should", "tell", "the", "this", "to", "use", "what", "when",
        "where", "which", "why", "with", "would", "you",
    },
    "Twi": {
        "anaa", "b\u025bn", "de", "d\u025bn", "ma", "me", "mede", "meny\u025b", "m\u025by\u025b",
        "na", "ne", "no", "nti", "s\u025b", "wo", "w\u0254", "\u025bde\u025bn", "\u025by\u025b",
    },
}


def normalize_question_identity(value, language="English"):
    """Normalize harmless formatting for dataset-question identity checks."""
    text = normalize_query(value, language)
    return " ".join(re.sub(r"[^\w]+", " ", text, flags=re.UNICODE).split())


def word_vectorizer(vectorizer):
    """Return the word component from a vectorizer or FeatureUnion."""
    components = getattr(vectorizer, "transformer_list", None)
    if components is None:
        return vectorizer
    for name, component in components:
        if name == "word":
            return component
    raise ValueError("Retrieval vectorizer does not contain a word component")


def build_term_coverage_context(vectorizer, normalized_questions, language):
    """Precompute candidate tokens and learned IDF weights."""
    word = word_vectorizer(vectorizer)
    tokenizer = word.build_tokenizer()
    terms = word.get_feature_names_out()
    idf = np.asarray(word.idf_, dtype=float)
    weights = {term: float(idf[index]) for index, term in enumerate(terms)}
    unknown_weight = float(idf.max()) if idf.size else 1.0
    stopwords = STOPWORDS[language]
    candidate_tokens = [
        set(tokenizer(question)) - stopwords for question in normalized_questions
    ]
    return {
        "tokenizer": tokenizer,
        "idf_weights": weights,
        "unknown_weight": unknown_weight,
        "candidate_tokens": candidate_tokens,
        "stopwords": stopwords,
    }


def weighted_query_term_coverage(normalized_query, context):
    """Measure how much learned query vocabulary each candidate covers.

    The score is asymmetric: a detailed candidate may safely contain more
    words, while missing a rare or out-of-vocabulary user term is penalized.
    """
    query_tokens = (
        set(context["tokenizer"](normalized_query)) - context["stopwords"]
    )
    if not query_tokens:
        return np.zeros(len(context["candidate_tokens"]), dtype=float)
    weights = context["idf_weights"]
    default = context["unknown_weight"]
    denominator = sum(weights.get(token, default) for token in query_tokens)
    if denominator <= 0:
        return np.zeros(len(context["candidate_tokens"]), dtype=float)
    return np.asarray([
        sum(weights.get(token, default) for token in query_tokens & candidate)
        / denominator
        for candidate in context["candidate_tokens"]
    ])


def substantive_query_term_count(normalized_query, context):
    """Return the number of non-generic query terms used by coverage."""
    return len(
        set(context["tokenizer"](normalized_query)) - context["stopwords"]
    )
