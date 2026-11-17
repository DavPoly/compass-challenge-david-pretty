"""Plan a question: pick its family and extract filters."""

import calendar
import logging
import re

from archive.agent.route.route_constants import (
    ISO_DATE_PATTERN,
    MAX_DAY_OF_MONTH,
    MSG_INVALID_DATE,
    MSG_PLAN_FALLBACK,
    SYSTEM_PROMPT,
    USER_PROMPT,
)
from archive.agent.route.route_model import QuestionFamily, QuestionPlan
from archive.common.constants import QUESTION_TAG
from archive.common.text.date_parsing_utils import build_iso_date
from archive.common.text.prompt_delimit_utils import wrap_untrusted
from archive.llm.llm_gateway import LlmGateway, LlmUnavailableError, Messages
from archive.retrieval.search_service import find_identifiers
from archive.validation.input_model import Question

logger = logging.getLogger(__name__)

_ISO_DATE = re.compile(ISO_DATE_PATTERN)


def build_messages(question: Question) -> Messages:
    """Return the system and user messages of the plan call.

    The question text is delimited as untrusted data.
    """
    user = USER_PROMPT.format(
        question=wrap_untrusted(QUESTION_TAG, question.question)
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def _normalize_date(value: str | None) -> str | None:
    """`value` as a real ISO date; a day past the month end is clamped.

    Raises:
        ValueError: `value` is not an ISO date, or its year, month or
            day is out of range (day 0, month 13, day 32...).
    """
    if value is None:
        return None
    match = _ISO_DATE.fullmatch(value.strip())
    if match is None:
        raise ValueError(value)
    year, month, day = (int(part) for part in match.groups())
    if 1 <= day <= MAX_DAY_OF_MONTH:
        day = min(day, calendar.monthrange(year, month)[1])
    iso_date = build_iso_date(year, month, day)
    if iso_date is None:
        raise ValueError(value)
    return iso_date


def plan_question(question: Question, llm: LlmGateway) -> QuestionPlan:
    """Return the plan of a question.

    One LLM call picks the family and extracts the filters. Identifiers
    found by regex replace the LLM's project codes. A day past the
    month end is clamped to the last day; an unparseable date
    downgrades the plan to `direct`. If the LLM is unavailable the
    plan is `direct` with the regex codes only.
    """
    codes = find_identifiers(question.question)
    try:
        plan = llm.complete_json(build_messages(question), QuestionPlan)
    except LlmUnavailableError as error:
        logger.warning(MSG_PLAN_FALLBACK, question.id, error)
        return QuestionPlan(family=QuestionFamily.DIRECT, project_codes=codes)
    return _with_valid_dates(question, plan, codes)


def _with_valid_dates(
    question: Question, plan: QuestionPlan, codes: list[str]
) -> QuestionPlan:
    """Plan with normalised dates, or a direct plan if one is garbage."""
    try:
        dates = {
            "date_from": _normalize_date(plan.date_from),
            "date_to": _normalize_date(plan.date_to),
            "as_of_date": _normalize_date(plan.as_of_date),
        }
    except ValueError as error:
        logger.warning(MSG_INVALID_DATE, question.id, str(error))
        return QuestionPlan(family=QuestionFamily.DIRECT, project_codes=codes)
    return plan.model_copy(update={"project_codes": codes, **dates})
