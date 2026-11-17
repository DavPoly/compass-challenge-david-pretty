"""Follow identifier links from hits to related documents."""

from collections import Counter

from archive.agent.hops.hop_constants import (
    EMAIL_MARKER,
    EXPAND_CAP,
    EXPAND_MAX_CODES,
    EXPAND_PER_CODE_CAP,
    EXPAND_SHARED_MIN_HITS,
    EXPAND_SOURCE_HITS,
)
from archive.agent.recipes.recipe_model import RecipeSearchPort
from archive.common.chunk_model import DocType
from archive.retrieval.search_service import (
    SearchFilters,
    SearchHit,
    find_identifiers,
)
from archive.validation.input_model import Question


def expand_by_identifiers(
    question: Question,
    hits: list[SearchHit],
    search: RecipeSearchPort,
) -> list[SearchHit]:
    """Return chunks linked to the question and hits by a shared code.

    Pivot codes, in priority order: codes in the question text; codes
    carried by at least `EXPAND_SHARED_MIN_HITS` distinct documents
    among all hits (most frequent first); codes of the top
    `EXPAND_SOURCE_HITS` hits. Emails are ignored and the list is capped
    at `EXPAND_MAX_CODES`. Each code is listed separately over project
    sheets and contracts, so a many-code query cannot crowd out the
    relevant code. Listing stops once `EXPAND_CAP` chunks are found.

    Args:
        question: The question being answered.
        hits: Retrieved hits whose identifiers seed the expansion.
        search: Search port used to list chunks by identifier.

    Returns:
        Only chunks not already in `hits` (by chunk id), in code order:
        question codes first, then shared codes, then top-hit codes.
    """
    seen = {hit.chunk.chunk_id for hit in hits}
    fresh: list[SearchHit] = []
    for code in _collect_codes(question, hits):
        filters = SearchFilters(
            identifiers=[code],
            doc_types=[
                DocType.PROJECT_SHEET.value,
                DocType.CONTRACT.value,
            ],
        )
        for hit in search.list_by_filter(filters, EXPAND_PER_CODE_CAP):
            if hit.chunk.chunk_id not in seen:
                seen.add(hit.chunk.chunk_id)
                fresh.append(hit)
        if len(fresh) >= EXPAND_CAP:
            break
    return fresh[:EXPAND_CAP]


def _collect_codes(question: Question, hits: list[SearchHit]) -> list[str]:
    """Deduped non-email codes by priority, capped at the max."""
    codes = find_identifiers(question.question)
    codes.extend(_shared_codes(hits))
    for hit in hits[:EXPAND_SOURCE_HITS]:
        codes.extend(hit.chunk.identifiers)
    unique = dict.fromkeys(codes)
    kept = [code for code in unique if EMAIL_MARKER not in code]
    return kept[:EXPAND_MAX_CODES]


def _shared_codes(hits: list[SearchHit]) -> list[str]:
    """Codes on several distinct docs, most frequent first."""
    docs_by_code: dict[str, set[str]] = {}
    for hit in hits:
        for code in hit.chunk.identifiers:
            docs_by_code.setdefault(code, set()).add(hit.chunk.doc_id)
    counts = Counter({c: len(d) for c, d in docs_by_code.items()})
    shared = [
        code
        for code, count in counts.items()
        if count >= EXPAND_SHARED_MIN_HITS
    ]
    # dict order is first-rank order; sort is stable so ties keep it.
    return sorted(shared, key=lambda code: -counts[code])
