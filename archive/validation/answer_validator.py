"""Deterministic checks and format fixes on a model draft.

Validation never abstains: a draft that fails a check keeps its status
and an issue is recorded instead.
"""

from collections.abc import Collection
from decimal import Decimal, InvalidOperation, localcontext

from pydantic import BaseModel

from archive.common.constants import PDF_SUFFIX
from archive.common.text.date_parsing_constants import (
    AMBIGUOUS_DAY_MONTH_LIMIT,
    DAY_FIRST_DATE_RE,
    DAY_MONTH_NAME_RE,
    ISO_DATE_RE,
    MONTH_NAME_DAY_RE,
    MONTHS,
)
from archive.common.text.date_parsing_utils import build_iso_date
from archive.common.text.text_normalize_utils import strip_accents
from archive.validation.answer_model import (
    AnswerStatus,
    DraftAnswer,
    FinalAnswer,
)
from archive.validation.issue_model import IssueCode, ValidationIssue
from archive.validation.validation_constants import (
    AMOUNT_RE,
    AMOUNT_ROUNDING,
    DECIMAL_PLACES,
    INVISIBLE_SPACE_RE,
    ISSUE_CONFLICT_CITATIONS,
    ISSUE_DROPPED,
    ISSUE_NO_CITATION,
    ISSUE_NORMALIZED,
    ISSUE_NOT_FOUND_CLEARED,
    ISSUE_TOO_LONG,
    MAX_ANSWER_CHARS,
    MAX_DECIMAL_DIGITS,
    MIN_CONFLICT_CITATIONS,
    NOT_FOUND_ANSWER,
    SEPARATOR_RE,
    THOUSANDS_GROUP_DIGITS,
)


class ValidationResult(BaseModel):
    """Final answer plus what validation changed or flagged."""

    answer: FinalAnswer
    issues: list[ValidationIssue]
    dropped_citations: list[str]


def normalize_doc_id(citation: str) -> str:
    """Doc id of a citation: trimmed, without a ``.pdf`` suffix."""
    return citation.strip().removesuffix(PDF_SUFFIX)


def normalize_date(text: str) -> str | None:
    """Return ISO form when the whole text is one date, else None.

    Accepts YYYY-MM-DD, ``4 mars 2025`` and ``March 4, 2025``. A
    DD/MM/YYYY date is converted only when the day is above 12, as it
    is otherwise ambiguous with MM/DD/YYYY; the scorer tries both
    orders, so an ambiguous date is left as written.
    """
    plain = strip_accents(text.strip().rstrip(".")).lower()
    if match := ISO_DATE_RE.fullmatch(plain):
        year, month, day = match.groups()
    elif match := DAY_FIRST_DATE_RE.fullmatch(plain):
        day, month, year = match.groups()
        if int(day) <= AMBIGUOUS_DAY_MONTH_LIMIT:
            return None
    elif match := DAY_MONTH_NAME_RE.fullmatch(plain):
        day, name, year = match.groups()
        month = str(MONTHS[name])
    elif match := MONTH_NAME_DAY_RE.fullmatch(plain):
        name, day, year = match.groups()
        month = str(MONTHS[name])
    else:
        return None
    return build_iso_date(int(year), int(month), int(day))


def _is_decimal_mark(digits: str, separators: list[int]) -> bool:
    """Whether the last separator is a decimal mark, not a thousands one."""
    last = separators[-1]
    tail = digits[last + 1 :]
    if len(separators) == 1:
        if len(tail) == THOUSANDS_GROUP_DIGITS:
            return digits[:last] in ("", "0")
        return len(tail) <= MAX_DECIMAL_DIGITS or digits[last] == "."
    return (
        digits[last] != digits[separators[0]]
        and len(tail) <= MAX_DECIMAL_DIGITS
    )


def _to_decimal(raw: str) -> Decimal | None:
    digits = INVISIBLE_SPACE_RE.sub("", raw)
    negative = digits.startswith("-")
    digits = digits.lstrip("-")
    separators = [i for i, char in enumerate(digits) if char in ",."]
    if separators:
        last = separators[-1]
        if _is_decimal_mark(digits, separators):
            head = SEPARATOR_RE.sub("", digits[:last])
            digits = f"{head}.{digits[last + 1 :]}"
        else:
            digits = SEPARATOR_RE.sub("", digits)
    try:
        value = Decimal(digits)
    except InvalidOperation:
        return None
    return -value if negative else value


def _format_amount(value: Decimal) -> str:
    """Render an amount with half-up rounding to the decimal places kept."""
    with localcontext() as context:
        context.rounding = AMOUNT_ROUNDING
        return f"{value:.{DECIMAL_PLACES}f}"


def normalize_amount(text: str) -> str | None:
    """Return a plain decimal like ``12500.00`` for a currency amount.

    Only a text made of one number with a currency marker ($, CAD,
    dollars) is converted; anything else returns None.

    Separator heuristic (mirrors the scorer): spaces, apostrophes and
    non-breaking spaces are grouping marks and dropped. With several
    separators, the last one is the decimal mark only when it differs
    from the first and has at most two digits after it. A single ``.``
    or ``,`` followed by exactly three digits is a thousands separator
    (``1,234`` is 1234) unless the head is empty or ``0`` (``0.125``
    stays 0.125). Otherwise a single separator followed by up to two
    digits is decimal, and so is a single ``.`` followed by more than
    three digits. The amount is finally rounded half up to two places
    (``0.125`` becomes 0.13).
    """
    match = AMOUNT_RE.fullmatch(text.strip())
    if not match or not (match["before"] or match["after"]):
        return None
    value = _to_decimal(match["number"])
    if value is None:
        return None
    return _format_amount(value)


def _normalize_item(item: str) -> tuple[str, list[ValidationIssue]]:
    stripped = item.strip()
    fixed = normalize_date(stripped) or normalize_amount(stripped)
    result = fixed or stripped
    if result == item:
        return result, []
    detail = ISSUE_NORMALIZED.format(original=item, fixed=result)
    return result, [ValidationIssue(code=IssueCode.NORMALIZED, detail=detail)]


def _normalize_answer(
    answer: str | list[str],
) -> tuple[str | list[str], list[ValidationIssue]]:
    if isinstance(answer, list):
        pairs = [_normalize_item(item) for item in answer]
        return (
            [value for value, _ in pairs],
            [issue for _, found in pairs for issue in found],
        )
    fixed, issues = _normalize_item(answer)
    if len(fixed) >= MAX_ANSWER_CHARS:
        detail = ISSUE_TOO_LONG.format(
            length=len(fixed), limit=MAX_ANSWER_CHARS
        )
        issues.append(
            ValidationIssue(code=IssueCode.ANSWER_TOO_LONG, detail=detail)
        )
    return fixed, issues


def _filter_citations(
    citations: list[str], allowed: set[str]
) -> tuple[list[str], list[str]]:
    """Split citations into kept doc ids and dropped raw citations."""
    kept: list[str] = []
    dropped: list[str] = []
    for citation in citations:
        doc_id = normalize_doc_id(citation)
        if doc_id not in allowed:
            if citation not in dropped:
                dropped.append(citation)
        elif doc_id not in kept:
            kept.append(doc_id)
    return kept, dropped


def _check_status(
    status: AnswerStatus, citations: list[str]
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not citations:
        issues.append(
            ValidationIssue(
                code=IssueCode.NO_VALID_CITATION,
                detail=ISSUE_NO_CITATION.format(status=status),
            )
        )
    if status is AnswerStatus.CONFLICT and (
        len(citations) < MIN_CONFLICT_CITATIONS
    ):
        detail = ISSUE_CONFLICT_CITATIONS.format(
            count=len(citations), minimum=MIN_CONFLICT_CITATIONS
        )
        issues.append(
            ValidationIssue(code=IssueCode.CONFLICT_CITATIONS, detail=detail)
        )
    return issues


def _abstain(question_id: str, draft: DraftAnswer) -> ValidationResult:
    issues: list[ValidationIssue] = []
    if draft.answer != NOT_FOUND_ANSWER or draft.citations:
        issues.append(
            ValidationIssue(
                code=IssueCode.NOT_FOUND_CLEARED,
                detail=ISSUE_NOT_FOUND_CLEARED,
            )
        )
    return ValidationResult(
        answer=FinalAnswer.not_found(question_id),
        issues=issues,
        dropped_citations=[],
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

    Returns the final answer, typed issues and the dropped citations.
    No I/O.
    """
    if draft.status is AnswerStatus.NOT_FOUND:
        return _abstain(question_id, draft)
    allowed = set(retrieved_doc_ids) & set(known_doc_ids)
    citations, dropped = _filter_citations(draft.citations, allowed)
    issues: list[ValidationIssue] = []
    if dropped:
        issues.append(
            ValidationIssue(
                code=IssueCode.CITATIONS_DROPPED,
                detail=ISSUE_DROPPED.format(dropped=dropped),
            )
        )
    issues.extend(_check_status(draft.status, citations))
    answer, answer_issues = _normalize_answer(draft.answer)
    final = FinalAnswer(
        id=question_id,
        answer=answer,
        citations=citations,
        status=draft.status,
    )
    return ValidationResult(
        answer=final,
        issues=issues + answer_issues,
        dropped_citations=dropped,
    )
