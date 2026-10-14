"""Explainable confidence score in [0, 1].

A name match alone never proves identity, so without any context
(country / organisation / field) the score is capped at NAME_ONLY_CAP.
"""
from rapidfuzz import fuzz

from .utils import normalize_text

NAME_ONLY_CAP = 0.6


def score_result(query, result):
    target = normalize_text(query.full_name)
    name_sim = max(
        (fuzz.token_sort_ratio(target, normalize_text(n)) / 100 for n in result.names),
        default=0.0,
    )

    terms = query.context_terms
    haystack = normalize_text(f"{result.title} {result.snippet}")
    hits = [t for t in terms if normalize_text(t) in haystack]
    context_ratio = len(hits) / len(terms) if terms else None

    # Name similarity is a gate (multiplier): context and source reliability
    # can strengthen a good name match but never rescue a wrong name.
    if terms:
        confidence = name_sim * (0.5 + 0.3 * context_ratio + 0.2 * result.reliability)
    else:
        confidence = min(name_sim * (0.7 + 0.3 * result.reliability), NAME_ONLY_CAP)

    signals = {
        "name_similarity": round(name_sim, 3),
        "context_terms": terms,
        "context_hits": hits,
        "source_reliability": result.reliability,
        "capped_name_only": not terms,
        **result.extra,
    }
    return round(confidence, 3), signals
