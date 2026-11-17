"""Superseded recipe: pick the policy version in force."""

import logging
from itertools import zip_longest

from archive.agent.recipes.recipe_constants import (
    POLICY_DOC_TYPE,
    SUPERSEDED_LIST_CAP,
    SUPERSEDED_NOTE_TEMPLATE,
    SUPERSEDED_PERIOD_CLOSED,
    SUPERSEDED_PERIOD_OPEN,
    SUPERSEDED_RRF_OFFSET,
    SUPERSEDED_SEARCH_K,
    SUPERSEDED_SERIES_MARGIN,
    SUPERSEDED_TODAY_LABEL,
)
from archive.agent.recipes.recipe_model import RecipeResult, RecipeSearchPort
from archive.agent.route.route_model import QuestionPlan
from archive.retrieval.search_service import SearchFilters, SearchHit
from archive.validation.input_model import Question

logger = logging.getLogger(__name__)


def run_superseded(
    question: Question, plan: QuestionPlan, search: RecipeSearchPort
) -> RecipeResult | None:
    """Gather the policy versions and name the one in force.

    The series comes from the best policy search hit that has one,
    searching on the policy topic (or the question text). All versions
    of that series are listed; the one in force on `plan.as_of_date`
    (or the latest one when there is no date) goes first.

    Args:
        question: The question being answered.
        plan: Routing plan; `as_of_date` and `policy_topic` are used.
        search: Search port.

    Returns:
        The hits and a note for the draft prompt, or None when no
        series or version in force is found (use the direct path).
    """
    filters = SearchFilters(doc_types=[POLICY_DOC_TYPE])
    queries = [question.question]
    if plan.policy_topic:
        queries.append(plan.policy_topic)
    rankings = [
        search.hybrid_search(query, filters, SUPERSEDED_SEARCH_K)
        for query in queries
    ]
    top_hits = _merge_rankings(rankings)
    series = _winning_series(rankings)
    if series is None:
        logger.info("question %s: no clear policy series", question.id)
        return None
    versions = _series_versions(
        [*top_hits, *search.list_by_filter(filters, SUPERSEDED_LIST_CAP)],
        series,
    )
    picked = _pick_version(versions, plan.as_of_date)
    if picked is None:
        logger.info(
            "question %s: no version in force on %s",
            question.id,
            plan.as_of_date,
        )
        return None
    return RecipeResult(
        hits=_order_hits(picked, versions, top_hits),
        note=_build_note(picked, plan.as_of_date),
    )


def _merge_rankings(rankings: list[list[SearchHit]]) -> list[SearchHit]:
    """Interleave rankings by rank, dropping repeated documents."""
    merged: list[SearchHit] = []
    seen: set[str] = set()
    for rank_hits in zip_longest(*rankings):
        for hit in rank_hits:
            if hit is not None and hit.chunk.doc_id not in seen:
                seen.add(hit.chunk.doc_id)
                merged.append(hit)
    return merged


def _winning_series(rankings: list[list[SearchHit]]) -> str | None:
    """Vote for a series by summed reciprocal rank over all rankings.

    Returns None unless the top series beats the runner-up by
    `SUPERSEDED_SERIES_MARGIN` (a ratio), so ambiguous questions fall
    back to the direct path.
    """
    scores: dict[str, float] = {}
    for hits in rankings:
        for rank, hit in enumerate(hits, start=1):
            if hit.chunk.series:
                scores[hit.chunk.series] = scores.get(
                    hit.chunk.series, 0.0
                ) + 1 / (SUPERSEDED_RRF_OFFSET + rank)
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    if not ranked:
        return None
    if (
        len(ranked) > 1
        and ranked[0][1] < SUPERSEDED_SERIES_MARGIN * ranked[1][1]
    ):
        return None
    return ranked[0][0]


def _series_versions(hits: list[SearchHit], series: str) -> list[SearchHit]:
    """Keep one hit per document of the series, first seen wins."""
    by_doc: dict[str, SearchHit] = {}
    for hit in hits:
        if hit.chunk.series == series:
            by_doc.setdefault(hit.chunk.doc_id, hit)
    return list(by_doc.values())


def _pick_version(
    versions: list[SearchHit], as_of_date: str | None
) -> SearchHit | None:
    """Pick the version in force on the date (latest when None)."""
    dated = [hit for hit in versions if hit.chunk.effective_from]
    if as_of_date is None:
        return max(
            dated, key=lambda hit: hit.chunk.effective_from or "", default=None
        )
    for hit in dated:
        chunk = hit.chunk
        starts = chunk.effective_from or ""
        if starts <= as_of_date and (
            chunk.effective_to is None or as_of_date < chunk.effective_to
        ):
            return hit
    return None


def _order_hits(
    picked: SearchHit, versions: list[SearchHit], top_hits: list[SearchHit]
) -> list[SearchHit]:
    """Put the picked version first, then the rest, newest first."""
    others = sorted(
        (hit for hit in versions if hit is not picked),
        key=lambda hit: hit.chunk.effective_from or "",
        reverse=True,
    )
    ordered = [picked, *others]
    seen = {hit.chunk.doc_id for hit in ordered}
    for hit in top_hits:
        if hit.chunk.doc_id not in seen:
            ordered.append(hit)
            seen.add(hit.chunk.doc_id)
    return ordered


def _build_note(picked: SearchHit, as_of_date: str | None) -> str:
    """Describe the version in force for the draft prompt."""
    chunk = picked.chunk
    if chunk.effective_to:
        period = SUPERSEDED_PERIOD_CLOSED.format(
            effective_from=chunk.effective_from,
            effective_to=chunk.effective_to,
        )
    else:
        period = SUPERSEDED_PERIOD_OPEN.format(
            effective_from=chunk.effective_from
        )
    return SUPERSEDED_NOTE_TEMPLATE.format(
        as_of=as_of_date or SUPERSEDED_TODAY_LABEL,
        doc_id=chunk.doc_id,
        version=chunk.version,
        period=period,
    )
