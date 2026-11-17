"""Follow identifier links from hits to related documents."""

from archive.agent.hops.hop_constants import (
    EMAIL_MARKER,
    EXPAND_CAP,
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

    Codes come from the question text and from the identifiers of the
    top hits; emails are ignored. Chunks of project sheets and
    contracts carrying any of those codes are listed with
    `list_by_filter`.

    Args:
        question: The question being answered.
        hits: Retrieved hits whose identifiers seed the expansion.
        search: Search port used to list chunks by identifier.

    Returns:
        Only chunks not already in `hits` (by chunk id), in the order
        the codes were found, question codes first.
    """
    codes = _collect_codes(question, hits)
    if not codes:
        return []
    filters = SearchFilters(
        identifiers=codes,
        doc_types=[DocType.PROJECT_SHEET.value, DocType.CONTRACT.value],
    )
    listed = search.list_by_filter(filters, EXPAND_CAP)
    return _rank_new_chunks(listed, hits, codes)[:EXPAND_CAP]


def _collect_codes(question: Question, hits: list[SearchHit]) -> list[str]:
    """Deduped non-email codes: question first, then top hits."""
    codes = find_identifiers(question.question)
    for hit in hits[:EXPAND_SOURCE_HITS]:
        codes.extend(hit.chunk.identifiers)
    unique = dict.fromkeys(codes)
    return [code for code in unique if EMAIL_MARKER not in code]


def _rank_new_chunks(
    listed: list[SearchHit], hits: list[SearchHit], codes: list[str]
) -> list[SearchHit]:
    """Unseen, deduped chunks ordered by their first matching code."""
    seen = {hit.chunk.chunk_id for hit in hits}
    fresh: list[SearchHit] = []
    for hit in listed:
        if hit.chunk.chunk_id not in seen:
            seen.add(hit.chunk.chunk_id)
            fresh.append(hit)
    return sorted(fresh, key=lambda hit: _code_rank(hit, codes))


def _code_rank(hit: SearchHit, codes: list[str]) -> int:
    """Index of the first code the chunk carries (len if none)."""
    for position, code in enumerate(codes):
        if code in hit.chunk.identifiers:
            return position
    return len(codes)
