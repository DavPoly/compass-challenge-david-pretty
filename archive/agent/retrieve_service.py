"""Retrieval step: hybrid search with document-type hints.

Questions that name a document family ("facture", "policy") reserve a
share of the k slots for chunks of that family, so a large unfiltered
neighbourhood cannot crowd them out.
"""

import math
import re
from typing import Protocol

from archive.agent.retrieve_constants import (
    DOC_TYPE_KEYWORDS,
    RETRIEVE_TYPED_SHARE,
)
from archive.common.chunk_model import DocType
from archive.common.text.text_normalize_utils import normalize_for_match
from archive.retrieval.search_service import SearchFilters, SearchHit

_HINT_PATTERNS: dict[DocType, re.Pattern[str]] = {
    doc_type: re.compile("|".join(patterns))
    for doc_type, patterns in DOC_TYPE_KEYWORDS.items()
}


class SearchPort(Protocol):
    """The part of `SearchService` that `retrieve` needs."""

    def hybrid_search(
        self, query: str, filters: SearchFilters | None, k: int
    ) -> list[SearchHit]:
        """Return the top `k` hits for a query, best first."""
        ...


def detect_doc_type_hints(question: str) -> list[DocType]:
    """Document types a question names, via a FR/EN keyword table.

    Matching is case- and accent-insensitive.

    Args:
        question: The user question.

    Returns:
        Hinted types in table order; empty when none is named.
    """
    text = normalize_for_match(question)
    return [
        doc_type
        for doc_type, pattern in _HINT_PATTERNS.items()
        if pattern.search(text)
    ]


def retrieve(question: str, search: SearchPort, k: int) -> list[SearchHit]:
    """Return at most `k` hits for a question, typed hits first.

    With type hints, `ceil(k * RETRIEVE_TYPED_SHARE)` slots are filled
    from a `doc_types`-filtered search, then an unfiltered search fills
    the rest (deduped by `chunk_id`). When the typed search finds
    nothing, the result is the plain unfiltered top-k.

    Args:
        question: The user question.
        search: Search service.
        k: Maximum number of hits.

    Returns:
        Hits, typed ones first, then by search order; never more than `k`.
    """
    if k <= 0:
        return []
    hints = detect_doc_type_hints(question)
    typed: list[SearchHit] = []
    if hints:
        typed_slots = math.ceil(k * RETRIEVE_TYPED_SHARE)
        filters = SearchFilters(doc_types=[hint.value for hint in hints])
        typed = search.hybrid_search(question, filters, typed_slots)
    merged = dedupe_hits(typed[:k])
    if len(merged) >= k:
        return merged
    rest = search.hybrid_search(question, None, k)
    return dedupe_hits([*merged, *rest])[:k]


def dedupe_hits(hits: list[SearchHit]) -> list[SearchHit]:
    """Drop repeated chunk ids, keeping the first hit of each."""
    seen: set[str] = set()
    unique: list[SearchHit] = []
    for hit in hits:
        if hit.chunk.chunk_id not in seen:
            seen.add(hit.chunk.chunk_id)
            unique.append(hit)
    return unique
