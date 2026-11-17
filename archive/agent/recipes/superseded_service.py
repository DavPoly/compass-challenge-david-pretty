"""Superseded recipe: pick the policy version in force."""

import datetime
import logging
import re

from pydantic import BaseModel

from archive.agent.recipes.recipe_constants import (
    LOG_SUPERSEDED_EXACT_RULE,
    LOG_SUPERSEDED_LIST_CAPPED,
    LOG_SUPERSEDED_LLM_DOWN,
    LOG_SUPERSEDED_NO_SERIES,
    LOG_SUPERSEDED_NO_VERSION,
    LOG_SUPERSEDED_PERIOD_RULE,
    SUPERSEDED_CHOICE_SYSTEM_PROMPT,
    SUPERSEDED_CHOICE_USER_PROMPT,
    SUPERSEDED_LIST_CAP,
    SUPERSEDED_MONTH_PERIOD_FORMAT,
    SUPERSEDED_NOTE_TEMPLATE,
    SUPERSEDED_PERIOD_CLOSED,
    SUPERSEDED_PERIOD_NOTE_TEMPLATE,
    SUPERSEDED_PERIOD_OPEN,
    SUPERSEDED_SEARCH_K,
    SUPERSEDED_SERIES_LINE,
    SUPERSEDED_TODAY_LABEL,
    SUPERSEDED_TOPIC_LINE,
    SUPERSEDED_TOPIC_TAG,
    SUPERSEDED_UNKNOWN_LANG,
    SUPERSEDED_YEAR_RE,
)
from archive.agent.recipes.recipe_model import RecipeResult, RecipeSearchPort
from archive.agent.route.route_model import QuestionPlan
from archive.common.chunk_model import Chunk, DocType
from archive.common.constants import QUESTION_TAG
from archive.common.text.date_parsing_utils import (
    find_first_date,
    find_month_year,
)
from archive.common.text.prompt_delimit_utils import wrap_untrusted
from archive.llm.llm_gateway import LlmGateway, LlmUnavailableError, Messages
from archive.retrieval.search_service import SearchFilters, SearchHit
from archive.validation.input_model import Question

logger = logging.getLogger(__name__)

_YEAR_RE = re.compile(SUPERSEDED_YEAR_RE)


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


def _question_period(
    question_text: str, as_of_date: str | None
) -> tuple[str, datetime.date, datetime.date] | None:
    """The calendar year or month the question names, if only that.

    Returns None when the question holds an exact date, names no year,
    or when `as_of_date` falls outside the named period.

    Returns:
        (label, first day, first day after the period) or None.
    """
    if find_first_date(question_text) is not None:
        return None
    month_start = find_month_year(question_text)
    if month_start is not None:
        start = datetime.date.fromisoformat(month_start)
        label = SUPERSEDED_MONTH_PERIOD_FORMAT.format(
            year=start.year, month=start.month
        )
        end = (start + datetime.timedelta(days=31)).replace(day=1)
    else:
        found = _YEAR_RE.search(question_text)
        if found is None:
            return None
        start = datetime.date(int(found.group(1)), 1, 1)
        label = found.group(1)
        end = datetime.date(start.year + 1, 1, 1)
    if as_of_date and not start.isoformat() <= as_of_date < end.isoformat():
        return None
    return label, start, end


def _pick_latest_in_period(
    versions: list[SearchHit], start: datetime.date, end: datetime.date
) -> SearchHit | None:
    """Pick the latest-starting version in force during [start, end)."""
    start_text, end_text = start.isoformat(), end.isoformat()
    overlapping = [
        hit
        for hit in versions
        if hit.chunk.effective_from
        and hit.chunk.effective_from < end_text
        and (
            hit.chunk.effective_to is None
            or hit.chunk.effective_to > start_text
        )
    ]
    return max(
        overlapping,
        key=lambda hit: hit.chunk.effective_from or "",
        default=None,
    )


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


def _format_period(chunk: Chunk) -> str:
    """Effective interval of a version as text."""
    if chunk.effective_to:
        return SUPERSEDED_PERIOD_CLOSED.format(
            effective_from=chunk.effective_from,
            effective_to=chunk.effective_to,
        )
    return SUPERSEDED_PERIOD_OPEN.format(effective_from=chunk.effective_from)


def _build_period_note(picked: SearchHit, period_label: str) -> str:
    """Describe the latest version in force during a year or month."""
    chunk = picked.chunk
    return SUPERSEDED_PERIOD_NOTE_TEMPLATE.format(
        period=period_label,
        doc_id=chunk.doc_id,
        version=chunk.version,
        effective=_format_period(chunk),
    )


def _build_note(picked: SearchHit, as_of_date: str | None) -> str:
    """Describe the version in force for the draft prompt."""
    chunk = picked.chunk
    return SUPERSEDED_NOTE_TEMPLATE.format(
        as_of=as_of_date or SUPERSEDED_TODAY_LABEL,
        doc_id=chunk.doc_id,
        version=chunk.version,
        period=_format_period(chunk),
    )


def _select_version(
    question: Question, plan: QuestionPlan, versions: list[SearchHit]
) -> tuple[SearchHit, str] | None:
    """Pick the version and build its note, or None when none applies.

    A question naming only a year (or month) gets the latest version in
    force at any point of that period; otherwise the version in force
    on the day.
    """
    period = _question_period(question.question, plan.as_of_date)
    if period is not None:
        label, start, end = period
        latest = _pick_latest_in_period(versions, start, end)
        if latest is not None:
            logger.info(LOG_SUPERSEDED_PERIOD_RULE, question.id, label)
            return latest, _build_period_note(latest, label)
    as_of = plan.as_of_date or _today()
    picked = _pick_version(versions, as_of)
    if picked is None:
        logger.info(LOG_SUPERSEDED_NO_VERSION, question.id, as_of)
        return None
    logger.info(LOG_SUPERSEDED_EXACT_RULE, question.id, as_of)
    return picked, _build_note(picked, plan.as_of_date)


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
    when there is no date) goes first. A question naming only a year
    or month gets the latest version in force during that period.

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
    selected = _select_version(question, plan, versions)
    if selected is None:
        return None
    picked, note = selected
    top_hits = search.hybrid_search(
        question.question,
        SearchFilters(doc_types=[DocType.POLICY.value]),
        SUPERSEDED_SEARCH_K,
    )
    return RecipeResult(
        hits=_order_hits(picked, versions, top_hits),
        note=note,
    )
