"""Deterministic checks and format fixes on a model draft.

Validation never abstains: a draft that fails a check keeps its status
and an issue is recorded instead.
"""

import re
import unicodedata
from collections.abc import Collection
from datetime import date
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel

from archive.validation.answer_model import (
    AnswerStatus,
    DraftAnswer,
    FinalAnswer,
)
from archive.validation.validation_constants import (
    AMOUNT_RE,
    DAY_FIRST_DATE_RE,
    DAY_MONTH_NAME_RE,
    DECIMAL_PLACES,
    ISO_DATE_RE,
    MAX_ANSWER_CHARS,
    MAX_DECIMAL_DIGITS,
    MIN_CONFLICT_CITATIONS,
    MONTH_NAME_DAY_RE,
    MONTHS,
    NOT_FOUND_ANSWER,
    THOUSANDS_GROUP_DIGITS,
)


class ValidationResult(BaseModel):
    """Final answer plus what validation changed or flagged."""

    answer: FinalAnswer
    issues: list[str]
    dropped_citations: list[str]


def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _make_date(year: int, month: int, day: int) -> str | None:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def normalize_date(text: str) -> str | None:
    """Return ISO form when the whole text is one date, else None.

    Accepts YYYY-MM-DD, DD/MM/YYYY (day first), ``4 mars 2025`` and
    ``March 4, 2025``.
    """
    plain = _strip_accents(text.strip().rstrip(".")).lower()
    if match := ISO_DATE_RE.fullmatch(plain):
        year, month, day = match.groups()
    elif match := DAY_FIRST_DATE_RE.fullmatch(plain):
        day, month, year = match.groups()
    elif match := DAY_MONTH_NAME_RE.fullmatch(plain):
        day, name, year = match.groups()
        month = str(MONTHS[name])
    elif match := MONTH_NAME_DAY_RE.fullmatch(plain):
        name, day, year = match.groups()
        month = str(MONTHS[name])
    else:
        return None
    return _make_date(int(year), int(month), int(day))


def _is_decimal_mark(digits: str, separators: list[int]) -> bool:
    """Whether the last separator is a decimal mark, not a thousands one."""
    last = separators[-1]
    tail = digits[last + 1 :]
    if len(separators) == 1:
        return len(tail) <= MAX_DECIMAL_DIGITS or (
            digits[last] == "." and len(tail) != THOUSANDS_GROUP_DIGITS
        )
    return (
        digits[last] != digits[separators[0]]
        and len(tail) <= MAX_DECIMAL_DIGITS
    )


def _to_decimal(raw: str) -> Decimal | None:
    digits = re.sub(r"[   ']", "", raw)
    negative = digits.startswith("-")
    digits = digits.lstrip("-")
    separators = [i for i, char in enumerate(digits) if char in ",."]
    if separators:
        last = separators[-1]
        if _is_decimal_mark(digits, separators):
            head = re.sub(r"[,.]", "", digits[:last])
            digits = f"{head}.{digits[last + 1 :]}"
        else:
            digits = re.sub(r"[,.]", "", digits)
    try:
        value = Decimal(digits)
    except InvalidOperation:
        return None
    return -value if negative else value


def normalize_amount(text: str) -> str | None:
    """Return a plain decimal like ``12500.00`` for a currency amount.

    Only a text made of one number with a currency marker ($, CAD,
    dollars) is converted; anything else returns None.
    """
    match = AMOUNT_RE.fullmatch(text.strip())
    if not match or not (match["before"] or match["after"]):
        return None
    value = _to_decimal(match["number"])
    if value is None:
        return None
    return f"{value:.{DECIMAL_PLACES}f}"


def _normalize_item(item: str, issues: list[str]) -> str:
    stripped = item.strip()
    fixed = normalize_date(stripped) or normalize_amount(stripped)
    result = fixed or stripped
    if result != item:
        issues.append(f"normalized answer {item!r} to {result!r}")
    return result


def _normalize_answer(
    answer: str | list[str], issues: list[str]
) -> str | list[str]:
    if isinstance(answer, list):
        return [_normalize_item(item, issues) for item in answer]
    fixed = _normalize_item(answer, issues)
    if len(fixed) >= MAX_ANSWER_CHARS:
        issues.append(
            f"answer has {len(fixed)} chars, expected under {MAX_ANSWER_CHARS}"
        )
    return fixed


def _filter_citations(
    citations: list[str], allowed: set[str], dropped: list[str]
) -> list[str]:
    kept: list[str] = []
    for citation in citations:
        doc_id = citation.strip().removesuffix(".pdf")
        if doc_id not in allowed:
            if citation not in dropped:
                dropped.append(citation)
        elif doc_id not in kept:
            kept.append(doc_id)
    return kept


def _check_status(
    status: AnswerStatus, citations: list[str], issues: list[str]
) -> None:
    if not citations:
        issues.append(f"status {status} has no valid citation")
    if status is AnswerStatus.CONFLICT and (
        len(citations) < MIN_CONFLICT_CITATIONS
    ):
        issues.append(
            f"conflict cites {len(citations)} document(s), expected "
            f"at least {MIN_CONFLICT_CITATIONS}"
        )


def validate(
    question_id: str,
    draft: DraftAnswer,
    retrieved_doc_ids: Collection[str],
    known_doc_ids: Collection[str],
) -> ValidationResult:
    """Turn a draft into a FinalAnswer, fixing format where safe.

    ``question_id`` is needed to build the FinalAnswer. Citations are
    kept only when retrieved for this question and known in the corpus
    (deduplicated, order kept). Dates become ISO, currency amounts plain
    decimals. A not_found draft becomes the empty abstention line. The
    status is never turned into an abstention by a failed check.

    Returns the final answer, human-readable issues and the dropped
    citations. No I/O.
    """
    issues: list[str] = []
    dropped: list[str] = []
    if draft.status is AnswerStatus.NOT_FOUND:
        if draft.answer != NOT_FOUND_ANSWER or draft.citations:
            issues.append("not_found cleared answer and citations")
        return ValidationResult(
            answer=FinalAnswer.not_found(question_id),
            issues=issues,
            dropped_citations=dropped,
        )
    allowed = set(retrieved_doc_ids) & set(known_doc_ids)
    citations = _filter_citations(draft.citations, allowed, dropped)
    if dropped:
        issues.append(f"dropped citations not retrieved: {dropped}")
    _check_status(draft.status, citations, issues)
    answer = _normalize_answer(draft.answer, issues)
    final = FinalAnswer(
        id=question_id,
        answer=answer,
        citations=citations,
        status=draft.status,
    )
    return ValidationResult(
        answer=final, issues=issues, dropped_citations=dropped
    )
