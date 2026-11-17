"""Flag-only grounding checks on a model draft.

Quotes must appear in the retrieved text of their document and answer
values must come from a verified quote or the recipe note. Nothing is
changed: the result is a report with issues and a confidence.
"""

from collections.abc import Iterable

from archive.common.text.text_normalize_utils import normalize_for_match
from archive.validation.answer_model import (
    AnswerStatus,
    DraftAnswer,
    Evidence,
)
from archive.validation.answer_validator import (
    ValidationResult,
    normalize_amount,
    normalize_date,
)
from archive.validation.grounding.grounding_constants import (
    BARE_AMOUNT_SUFFIX,
    DATE_SCAN_PATTERNS,
    ISSUE_NO_EVIDENCE,
    ISSUE_QUOTE_UNVERIFIED,
    ISSUE_VALUE_UNGROUNDED,
    WHITESPACE_RE,
)
from archive.validation.grounding.grounding_model import (
    Confidence,
    GroundingReport,
    GroundingSources,
)
from archive.validation.issue_model import IssueCode, ValidationIssue
from archive.validation.validation_constants import AMOUNT_RE, PDF_SUFFIX


def _fold(text: str) -> str:
    """Case, accent and whitespace-insensitive form for matching."""
    return WHITESPACE_RE.sub(" ", normalize_for_match(text)).strip()


def _is_verified(evidence: Evidence, sources: GroundingSources) -> bool:
    quote = _fold(evidence.quote)
    if not quote:
        return False
    doc_id = evidence.doc_id.strip().removesuffix(PDF_SUFFIX)
    texts = sources.texts_by_doc.get(doc_id, ())
    return any(quote in _fold(text) for text in texts)


def _amount_key(text: str) -> str | None:
    """Plain decimal for a currency amount or a bare number."""
    return normalize_amount(text) or normalize_amount(
        text.strip() + BARE_AMOUNT_SUFFIX
    )


def _scan_keys(folded: str) -> set[str]:
    """Normalized dates and amounts occurring in folded text."""
    keys: set[str] = set()
    for pattern in DATE_SCAN_PATTERNS:
        for match in pattern.finditer(folded):
            if date := normalize_date(match.group(0)):
                keys.add(date)
    for match in AMOUNT_RE.finditer(folded):
        if amount := _amount_key(match["number"]):
            keys.add(amount)
    return keys


def _is_grounded(item: str, haystacks: list[str]) -> bool:
    folded = _fold(item)
    if any(folded in haystack for haystack in haystacks):
        return True
    item_keys = {
        key for key in (normalize_date(item), _amount_key(item)) if key
    }
    return any(item_keys & _scan_keys(haystack) for haystack in haystacks)


def _answer_items(draft: DraftAnswer) -> list[str]:
    raw = draft.answer
    items = raw if isinstance(raw, list) else [raw]
    return [item for item in items if _fold(item)]


def _ungrounded_values(
    draft: DraftAnswer, verified: list[Evidence], sources: GroundingSources
) -> list[str]:
    haystacks = [_fold(evidence.quote) for evidence in verified]
    if sources.note:
        haystacks.append(_fold(sources.note))
    return [
        item
        for item in _answer_items(draft)
        if not _is_grounded(item, haystacks)
    ]


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
    verified = [e for e in draft.evidence if e not in unverified]
    ungrounded: list[str] = []
    if draft.status is AnswerStatus.ANSWERED:
        ungrounded = _ungrounded_values(draft, verified, sources)
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
        confidence=_confidence(draft, sources, validation, is_flagged),
    )
