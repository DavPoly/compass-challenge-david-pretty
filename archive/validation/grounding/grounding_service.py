"""Flag-only grounding checks on a model draft.

Quotes must appear in the retrieved text of their document and answer
values must come from a verified quote or the recipe note. Nothing is
changed: the result is a report with issues and a confidence.
"""

import re
from collections.abc import Iterable

from archive.common.text.date_parsing_constants import DAY_FIRST_DATE_RE
from archive.common.text.date_parsing_utils import build_iso_date
from archive.common.text.quote_match_utils import (
    fold_text,
    is_quote_in_text,
    quote_pieces,
)
from archive.validation.answer_model import (
    AnswerStatus,
    DraftAnswer,
    Evidence,
)
from archive.validation.answer_validator import (
    ValidationResult,
    normalize_amount,
    normalize_date,
    normalize_doc_id,
)
from archive.validation.grounding.grounding_constants import (
    BARE_AMOUNT_SUFFIX,
    BARE_INTEGER_RE,
    BARE_YEAR_RE,
    DATE_SCAN_PATTERNS,
    IDENTIFIER_RE,
    ISSUE_NO_EVIDENCE,
    ISSUE_QUOTE_UNVERIFIED,
    ISSUE_VALUE_UNGROUNDED,
    LABEL_BEFORE_RE,
    ORDINAL_AFTER_RE,
    TRAILING_PUNCTUATION,
)
from archive.validation.grounding.grounding_model import (
    Confidence,
    GroundingReport,
    GroundingSources,
)
from archive.validation.issue_model import IssueCode, ValidationIssue
from archive.validation.validation_constants import AMOUNT_RE

KeySpan = tuple[set[str], tuple[int, int]]


def _is_verified(evidence: Evidence, sources: GroundingSources) -> bool:
    pieces = quote_pieces(evidence.quote)
    if not pieces:
        return False
    texts = sources.texts_by_doc.get(normalize_doc_id(evidence.doc_id), ())
    return any(is_quote_in_text(pieces, text) for text in texts)


def _amount_key(text: str) -> str | None:
    """Plain decimal for a currency amount or a bare number."""
    return normalize_amount(text) or normalize_amount(
        text.strip() + BARE_AMOUNT_SUFFIX
    )


def _day_first_readings(match: re.Match[str]) -> set[str]:
    """Both ISO readings (DD/MM and MM/DD) of an ambiguous date."""
    first, second, year = (int(group) for group in match.groups())
    readings = {
        build_iso_date(year, second, first),
        build_iso_date(year, first, second),
    }
    return {reading for reading in readings if reading}


def _is_label_or_year(folded: str, match: re.Match[str]) -> bool:
    """True for a bare integer that is a year, label or ordinal."""
    if match["before"] or match["after"]:
        return False
    number = match["number"]
    if not BARE_INTEGER_RE.fullmatch(number):
        return False
    if BARE_YEAR_RE.fullmatch(number):
        return True
    if LABEL_BEFORE_RE.search(folded[: match.start("number")]):
        return True
    return bool(ORDINAL_AFTER_RE.match(folded[match.end("number") :]))


def _blank(folded: str, patterns: Iterable[re.Pattern[str]]) -> str:
    """Text with every match of ``patterns`` replaced by spaces."""
    for pattern in patterns:
        folded = pattern.sub(lambda m: " " * len(m.group(0)), folded)
    return folded


def _amount_spans(folded: str) -> list[KeySpan]:
    """Amounts in text whose dates and identifiers were blanked."""
    folded = _blank(folded, (IDENTIFIER_RE, *DATE_SCAN_PATTERNS))
    spans: list[KeySpan] = []
    for match in AMOUNT_RE.finditer(folded):
        if _is_label_or_year(folded, match):
            continue
        if amount := _amount_key(match["number"]):
            spans.append(({amount}, match.span()))
    return spans


def _date_spans(folded: str) -> list[KeySpan]:
    """Dates (both readings when ambiguous) in identifier-free text."""
    folded = _blank(folded, (IDENTIFIER_RE,))
    spans: list[KeySpan] = []
    for pattern in DATE_SCAN_PATTERNS:
        for match in pattern.finditer(folded):
            if date := normalize_date(match.group(0)):
                spans.append(({date}, match.span()))
    for match in DAY_FIRST_DATE_RE.finditer(folded):
        if readings := _day_first_readings(match):
            spans.append((readings, match.span()))
    return spans


def _key_spans(folded: str) -> list[KeySpan]:
    """Keys of the dates and amounts in folded text, with their spans."""
    return _date_spans(folded) + _amount_spans(folded)


def _scan_keys(folded: str) -> set[str]:
    """Normalized dates and amounts occurring in folded text."""
    return set().union(*(keys for keys, _ in _key_spans(folded)))


def _is_grounded(item: str, haystacks: list[str]) -> bool:
    trimmed = item.strip().rstrip(TRAILING_PUNCTUATION)
    folded = fold_text(trimmed)
    if any(folded in haystack for haystack in haystacks):
        return True
    item_keys = {
        key for key in (normalize_date(trimmed), _amount_key(trimmed)) if key
    }
    haystack_keys = [_scan_keys(haystack) for haystack in haystacks]
    if any(item_keys & keys for keys in haystack_keys):
        return True
    embedded_keys = _scan_keys(folded)
    known_keys = set().union(*haystack_keys)
    return bool(embedded_keys) and embedded_keys <= known_keys


def _missing_values(item: str, haystacks: list[str]) -> list[str]:
    """Embedded values of an ungrounded item found in no haystack.

    Each is the original text span; the whole item when it holds no
    embedded value or every one is known.
    """
    trimmed = item.strip().rstrip(TRAILING_PUNCTUATION)
    folded = fold_text(trimmed)
    known = set().union(*(_scan_keys(haystack) for haystack in haystacks))
    source = trimmed if len(trimmed) == len(folded) else folded
    missing = [
        source[start:end].strip()
        for keys, (start, end) in sorted(
            _key_spans(folded), key=lambda key_span: key_span[1]
        )
        if not keys <= known
    ]
    return missing or [item]


def _answer_items(draft: DraftAnswer) -> list[str]:
    raw = draft.answer
    items = raw if isinstance(raw, list) else [raw]
    return [item for item in items if fold_text(item)]


def _ungrounded_values(
    draft: DraftAnswer, verified: list[Evidence], sources: GroundingSources
) -> tuple[list[str], list[str]]:
    """Ungrounded answer items and the values missing inside them."""
    haystacks = [fold_text(evidence.quote) for evidence in verified]
    if sources.note:
        haystacks.append(fold_text(sources.note))
    ungrounded = [
        item
        for item in _answer_items(draft)
        if not _is_grounded(item, haystacks)
    ]
    missing = [
        value
        for item in ungrounded
        for value in _missing_values(item, haystacks)
    ]
    return ungrounded, missing


def _issues(code: IssueCode, details: Iterable[str]) -> list[ValidationIssue]:
    return [ValidationIssue(code=code, detail=detail) for detail in details]


def _confidence(
    draft: DraftAnswer,
    sources: GroundingSources,
    validation: ValidationResult,
    is_flagged: bool,
) -> Confidence:
    if draft.status is AnswerStatus.NOT_FOUND:
        return Confidence.MEDIUM if sources.texts_by_doc else Confidence.HIGH
    if is_flagged or validation.dropped_citations:
        return Confidence.LOW
    has_other_issue = any(
        issue.code is not IssueCode.NORMALIZED for issue in validation.issues
    )
    if has_other_issue or not draft.evidence_sufficient:
        return Confidence.MEDIUM
    return Confidence.HIGH


def check_grounding(
    draft: DraftAnswer,
    sources: GroundingSources,
    validation: ValidationResult,
) -> GroundingReport:
    """Check quotes and values of a draft against its sources.

    A quote is verified when its folded text is a substring of a
    retrieved text of the same document. For an answered draft, each
    answer item must sit in a verified quote or the note, or equal a
    date or amount found there. Pure; never raises on bad model output.

    Returns a report with one issue per flagged item and the confidence.
    """
    unverified = [
        evidence
        for evidence in draft.evidence
        if not _is_verified(evidence, sources)
    ]
    verified = [
        evidence for evidence in draft.evidence if evidence not in unverified
    ]
    ungrounded: list[str] = []
    missing: list[str] = []
    if draft.status is AnswerStatus.ANSWERED:
        ungrounded, missing = _ungrounded_values(draft, verified, sources)
    issues = _issues(
        IssueCode.QUOTE_UNVERIFIED,
        (
            ISSUE_QUOTE_UNVERIFIED.format(
                doc_id=evidence.doc_id, quote=evidence.quote
            )
            for evidence in unverified
        ),
    )
    issues += _issues(
        IssueCode.VALUE_UNGROUNDED,
        (ISSUE_VALUE_UNGROUNDED.format(value=value) for value in ungrounded),
    )
    has_no_evidence = (
        draft.status is not AnswerStatus.NOT_FOUND and not draft.evidence
    )
    if has_no_evidence:
        issues += _issues(
            IssueCode.NO_EVIDENCE,
            [ISSUE_NO_EVIDENCE.format(status=draft.status)],
        )
    is_flagged = bool(unverified or ungrounded or has_no_evidence)
    return GroundingReport(
        issues=issues,
        unverified_quotes=[evidence.quote for evidence in unverified],
        ungrounded_values=ungrounded,
        missing_values=missing,
        confidence=_confidence(draft, sources, validation, is_flagged),
    )
