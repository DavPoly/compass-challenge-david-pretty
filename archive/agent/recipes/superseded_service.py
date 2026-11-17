"""Superseded recipe: pick the policy version in force."""

import datetime
import logging

from pydantic import BaseModel

from archive.agent.recipes.recipe_constants import (
    LOG_SUPERSEDED_LIST_CAPPED,
    LOG_SUPERSEDED_LLM_DOWN,
    LOG_SUPERSEDED_NO_SERIES,
    LOG_SUPERSEDED_NO_VERSION,
    SUPERSEDED_CHOICE_SYSTEM_PROMPT,
    SUPERSEDED_CHOICE_USER_PROMPT,
    SUPERSEDED_LIST_CAP,
    SUPERSEDED_NOTE_TEMPLATE,
    SUPERSEDED_PERIOD_CLOSED,
    SUPERSEDED_PERIOD_OPEN,
    SUPERSEDED_SEARCH_K,
    SUPERSEDED_SERIES_LINE,
    SUPERSEDED_TODAY_LABEL,
    SUPERSEDED_TOPIC_LINE,
    SUPERSEDED_TOPIC_TAG,
    SUPERSEDED_UNKNOWN_LANG,
)
from archive.agent.recipes.recipe_model import RecipeResult, RecipeSearchPort
from archive.agent.route.route_model import QuestionPlan
from archive.common.chunk_model import DocType
from archive.common.constants import QUESTION_TAG
from archive.common.text.prompt_delimit_utils import wrap_untrusted
from archive.llm.llm_gateway import LlmGateway, LlmUnavailableError, Messages
from archive.retrieval.search_service import SearchFilters, SearchHit
from archive.validation.input_model import Question

logger = logging.getLogger(__name__)


class PolicyChoice(BaseModel):
    """LLM reply: the 1-based number of the chosen series, or None."""

    series_number: int | None = None


def _today() -> str:
    """Today's date as ISO text (patched in tests)."""
    return datetime.date.today().isoformat()


def _series_keys(policies: list[SearchHit]) -> list[str]:
    """Distinct series keys, in first-seen order."""
    keys = {hit.chunk.series: None for hit in policies if hit.chunk.series}
    return list(keys)


def _build_choice_messages(
    question: Question,
    plan: QuestionPlan,
    series_list: list[str],
    policies: list[SearchHit],
) -> Messages:
    """Build the prompt asking which series the question is about.

    The question and the router's topic hint are untrusted and sit in
    delimited blocks.
    """
    langs = {
        hit.chunk.series: hit.chunk.lang
        for hit in policies
        if hit.chunk.series
    }
    lines = [
        SUPERSEDED_SERIES_LINE.format(
            number=number,
            series=series,
            lang=langs.get(series) or SUPERSEDED_UNKNOWN_LANG,
        )
        for number, series in enumerate(series_list, start=1)
    ]
    topic_line = (
        SUPERSEDED_TOPIC_LINE.format(
            topic=wrap_untrusted(SUPERSEDED_TOPIC_TAG, plan.policy_topic)
        )
        if plan.policy_topic
        else ""
    )
    user = SUPERSEDED_CHOICE_USER_PROMPT.format(
        policies="\n".join(lines),
        question=wrap_untrusted(QUESTION_TAG, question.question),
        topic_line=topic_line,
    )
    return [
        {"role": "system", "content": SUPERSEDED_CHOICE_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def _choose_series(
    question: Question,
    messages: Messages,
    series_list: list[str],
    llm: LlmGateway,
) -> str | None:
    """Ask the LLM which series the question is about."""
    try:
        choice = llm.complete_json(messages, PolicyChoice)
    except LlmUnavailableError:
        logger.warning(LOG_SUPERSEDED_LLM_DOWN, question.id)
        return None
    number = choice.series_number
    if number is None or not 1 <= number <= len(series_list):
        logger.info(LOG_SUPERSEDED_NO_SERIES, question.id, number)
        return None
    return series_list[number - 1]


def _series_versions(hits: list[SearchHit], series: str) -> list[SearchHit]:
    """Keep one hit per document of the series, first seen wins."""
    by_doc: dict[str, SearchHit] = {}
    for hit in hits:
        if hit.chunk.series == series:
            by_doc.setdefault(hit.chunk.doc_id, hit)
    return list(by_doc.values())


def _pick_version(versions: list[SearchHit], as_of: str) -> SearchHit | None:
    """Pick the version in force on the ISO date, if any."""
    for hit in versions:
        chunk = hit.chunk
        if not chunk.effective_from or chunk.effective_from > as_of:
            continue
        if chunk.effective_to is None or as_of < chunk.effective_to:
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
    seen = {hit.chunk.chunk_id for hit in ordered}
    for hit in top_hits:
        if hit.chunk.chunk_id not in seen:
            ordered.append(hit)
            seen.add(hit.chunk.chunk_id)
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


def run_superseded(
    question: Question,
    plan: QuestionPlan,
    search: RecipeSearchPort,
    llm: LlmGateway,
) -> RecipeResult | None:
    """Gather the policy versions and name the one in force.

    The LLM picks the policy series from the list of all policies
    (it can match across French and English). All versions of that
    series are listed; the one in force on `plan.as_of_date` (or today
    when there is no date) goes first.

    Args:
        question: The question being answered.
        plan: Routing plan; `as_of_date` and `policy_topic` are used.
        search: Search port.
        llm: Gateway used to choose the series.

    Returns:
        The hits and a note for the draft prompt, or None when no
        series or version in force is found (use the direct path).
    """
    policies = search.list_by_filter(
        SearchFilters(doc_types=[DocType.POLICY.value]), SUPERSEDED_LIST_CAP
    )
    if len(policies) == SUPERSEDED_LIST_CAP:
        logger.warning(LOG_SUPERSEDED_LIST_CAPPED, question.id, len(policies))
    series_list = _series_keys(policies)
    messages = _build_choice_messages(question, plan, series_list, policies)
    series = _choose_series(question, messages, series_list, llm)
    if series is None:
        return None
    versions = _series_versions(policies, series)
    as_of = plan.as_of_date or _today()
    picked = _pick_version(versions, as_of)
    if picked is None:
        logger.info(LOG_SUPERSEDED_NO_VERSION, question.id, as_of)
        return None
    top_hits = search.hybrid_search(
        question.question,
        SearchFilters(doc_types=[DocType.POLICY.value]),
        SUPERSEDED_SEARCH_K,
    )
    return RecipeResult(
        hits=_order_hits(picked, versions, top_hits),
        note=_build_note(picked, plan.as_of_date),
    )
