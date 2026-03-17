"""Outreach deduplication: text normalization and similarity checking."""

from __future__ import annotations

import math
import re
import unicodedata


def normalize_outreach_text(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace. Works for CJK and Latin."""
    lowered = text.lower()
    # Remove punctuation (both ASCII and CJK punctuation)
    cleaned = re.sub(
        r"[^\w\s\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]",
        "",
        lowered,
    )
    # Collapse whitespace
    collapsed = re.sub(r"\s+", " ", cleaned).strip()
    return collapsed


def _char_ngrams(text: str, n: int = 3) -> dict[str, int]:
    """Build character n-gram frequency dict."""
    grams: dict[str, int] = {}
    for i in range(max(0, len(text) - n + 1)):
        gram = text[i : i + n]
        grams[gram] = grams.get(gram, 0) + 1
    return grams


def char_ngram_tfidf_similarity(a: str, b: str, *, n: int = 3) -> float:
    """Compute cosine similarity of character n-gram TF-IDF vectors.

    Uses stdlib only. Language-agnostic (works for CJK and Latin).
    """
    norm_a = normalize_outreach_text(a)
    norm_b = normalize_outreach_text(b)
    if not norm_a and not norm_b:
        return 1.0
    if not norm_a or not norm_b:
        return 0.0

    grams_a = _char_ngrams(norm_a, n)
    grams_b = _char_ngrams(norm_b, n)

    # Collect all grams across both documents for IDF
    all_grams = set(grams_a) | set(grams_b)
    if not all_grams:
        return 0.0

    # With only 2 documents, IDF is simple: log(2/df) where df is 1 or 2
    # df=2 → idf=0 (common to both, no discriminating power)
    # df=1 → idf=log(2)≈0.693 (unique to one document)
    # This is too aggressive — use smoothed IDF: log(1 + 2/(1+df))
    doc_count = 2
    idf: dict[str, float] = {}
    for gram in all_grams:
        df = (1 if gram in grams_a else 0) + (1 if gram in grams_b else 0)
        idf[gram] = math.log(1 + doc_count / (1 + df))

    # TF-IDF vectors
    dot = 0.0
    norm_a_sq = 0.0
    norm_b_sq = 0.0
    for gram in all_grams:
        tf_a = grams_a.get(gram, 0)
        tf_b = grams_b.get(gram, 0)
        w = idf[gram]
        va = tf_a * w
        vb = tf_b * w
        dot += va * vb
        norm_a_sq += va * va
        norm_b_sq += vb * vb

    denom = math.sqrt(norm_a_sq) * math.sqrt(norm_b_sq)
    if denom == 0:
        return 0.0
    return dot / denom


def is_duplicate_outreach(
    candidate: str,
    recent_texts: list[str],
    *,
    similarity_threshold: float = 0.75,
) -> bool:
    """Check if candidate is a duplicate of any recent outreach text.

    Returns True if exact normalized match or cosine similarity > threshold.
    """
    if not recent_texts:
        return False
    norm_candidate = normalize_outreach_text(candidate)
    if not norm_candidate:
        return False
    for recent in recent_texts:
        norm_recent = normalize_outreach_text(recent)
        if norm_candidate == norm_recent:
            return True
        if char_ngram_tfidf_similarity(candidate, recent) > similarity_threshold:
            return True
    return False
