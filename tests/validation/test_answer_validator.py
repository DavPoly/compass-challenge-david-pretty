import pytest

from archive.validation.answer_model import AnswerStatus, DraftAnswer
from archive.validation.answer_validator import (
    normalize_amount,
    normalize_date,
    validate,
)
from archive.validation.issue_model import IssueCode
from archive.validation.validation_constants import INVISIBLE_SPACE_RE

KNOWN = {"doc_0001", "doc_0002", "doc_0003"}
INVISIBLE_SPACE_CHARS = " \u00a0\u202f'"
NON_INVISIBLE_CHARS = "a1$,\t.\u2009\u2003"


def _draft(
    answer: str | list[str] = "x",
    status: AnswerStatus = AnswerStatus.ANSWERED,
    citations: list[str] | None = None,
) -> DraftAnswer:
    return DraftAnswer(
        answer=answer,
        status=status,
        citations=citations if citations is not None else ["doc_0001"],
        evidence_sufficient=True,
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2025-03-04", "2025-03-04"),
        ("14/03/2025", "2025-03-14"),
        ("04/03/2025", None),
        ("03/04/2025", None),
        ("4 mars 2025", "2025-03-04"),
        ("1er février 2024", "2024-02-01"),
        ("March 4, 2025", "2025-03-04"),
        ("31 décembre 2023.", "2023-12-31"),
        ("31/02/2025", None),
        ("le 4 mars 2025 environ", None),
        ("hello", None),
    ],
)
def test_normalize_date(raw: str, expected: str | None) -> None:
    assert normalize_date(raw) == expected


def test_invisible_space_re_matches_exactly_four_characters() -> None:
    assert INVISIBLE_SPACE_RE.pattern == r"[\u00a0\u202f ']"
    assert all(
        INVISIBLE_SPACE_RE.fullmatch(char) for char in INVISIBLE_SPACE_CHARS
    )
    assert not any(
        INVISIBLE_SPACE_RE.fullmatch(char) for char in NON_INVISIBLE_CHARS
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("12 500,00 $", "12500.00"),
        ("$12,500.00", "12500.00"),
        ("1 234,5 $", "1234.50"),
        ("1,234 $", "1234.00"),
        ("1.234 $", "1234.00"),
        ("0.125 $", "0.13"),
        ("0,125 $", "0.13"),
        ("1,23 $", "1.23"),
        ("1.2345 $", "1.23"),
        ("49 $", "49.00"),
        ("1.234.567,89 CAD", "1234567.89"),
        ("1,234,567.89 $", "1234567.89"),
        ("12,5 k$", None),
        ("12500", None),
        ("3", None),
    ],
)
def test_normalize_amount(raw: str, expected: str | None) -> None:
    assert normalize_amount(raw) == expected


def test_unknown_and_unretrieved_citations_are_dropped() -> None:
    draft = _draft(citations=["doc_0001", "doc_0002", "doc_9999"])

    result = validate("q1", draft, {"doc_0001", "doc_9999"}, KNOWN)

    assert result.answer.citations == ["doc_0001"]
    assert result.dropped_citations == ["doc_0002", "doc_9999"]
    assert result.issues


def test_citations_are_deduplicated_in_order() -> None:
    draft = _draft(
        citations=["doc_0002", "doc_0001.pdf", "doc_0002", "doc_0001"]
    )

    result = validate("q1", draft, KNOWN, KNOWN)

    assert result.answer.citations == ["doc_0002", "doc_0001"]
    assert result.dropped_citations == []


def test_answered_with_all_citations_dropped_stays_answered() -> None:
    draft = _draft(answer="42", citations=["doc_0009"])

    result = validate("q1", draft, KNOWN, KNOWN)

    assert result.answer.status is AnswerStatus.ANSWERED
    assert result.answer.answer == "42"
    assert result.answer.citations == []
    assert any("no valid citation" in str(issue) for issue in result.issues)


def test_conflict_with_one_citation_records_issue_only() -> None:
    draft = _draft(
        answer="1 / 2",
        status=AnswerStatus.CONFLICT,
        citations=["doc_0001"],
    )

    result = validate("q1", draft, KNOWN, KNOWN)

    assert result.answer.status is AnswerStatus.CONFLICT
    assert any("conflict cites 1" in str(issue) for issue in result.issues)


def test_conflict_with_two_citations_has_no_issue() -> None:
    draft = _draft(
        status=AnswerStatus.CONFLICT, citations=["doc_0001", "doc_0002"]
    )

    assert validate("q1", draft, KNOWN, KNOWN).issues == []


def test_not_found_is_emptied() -> None:
    draft = _draft(
        answer="maybe 5",
        status=AnswerStatus.NOT_FOUND,
        citations=["doc_0001"],
    )

    result = validate("q1", draft, KNOWN, KNOWN)

    assert result.answer.answer == ""
    assert result.answer.citations == []
    assert result.answer.status is AnswerStatus.NOT_FOUND
    assert [issue.code for issue in result.issues] == [
        IssueCode.NOT_FOUND_CLEARED
    ]


def test_answer_is_normalized_and_trimmed() -> None:
    result = validate("q1", _draft(answer="  $12,500.00 "), KNOWN, KNOWN)

    assert result.answer.answer == "12500.00"
    assert result.issues


def test_clean_answer_has_no_issue() -> None:
    result = validate("q1", _draft(answer="2025-03-04"), KNOWN, KNOWN)

    assert result.issues == []


def test_long_answer_is_kept_and_flagged() -> None:
    long_text = "a" * 250

    result = validate("q1", _draft(answer=long_text), KNOWN, KNOWN)

    assert result.answer.answer == long_text
    assert any("250 chars" in str(issue) for issue in result.issues)


def test_list_answer_stays_list_with_items_normalized() -> None:
    draft = _draft(answer=[" BRV-1 ", "4 mars 2025"])

    result = validate("q1", draft, KNOWN, KNOWN)

    assert result.answer.answer == ["BRV-1", "2025-03-04"]


def test_empty_list_answer_is_kept() -> None:
    result = validate("q1", _draft(answer=[]), KNOWN, KNOWN)

    assert result.answer.answer == []
    assert result.answer.status is AnswerStatus.ANSWERED


def test_issue_has_code_and_readable_text() -> None:
    result = validate("q1", _draft(answer="$12,500.00"), KNOWN, KNOWN)

    issue = result.issues[0]

    assert issue.code is IssueCode.NORMALIZED
    assert str(issue).startswith("normalized: normalized answer")


def test_issues_are_typed_with_stable_codes() -> None:
    result = validate("q1", _draft(citations=["doc_9999"]), KNOWN, KNOWN)

    assert [issue.code for issue in result.issues] == [
        IssueCode.CITATIONS_DROPPED,
        IssueCode.NO_VALID_CITATION,
    ]
    assert str(result.issues[0]) == (
        "citations_dropped: dropped citations not retrieved: ['doc_9999']"
    )


def test_number_coercion_flows_through_validation() -> None:
    draft = DraftAnswer.model_validate(
        {
            "answer": 3,
            "status": "answered",
            "citations": "doc_0001",
            "evidence_sufficient": True,
        }
    )

    result = validate("q1", draft, KNOWN, KNOWN)

    assert result.answer.answer == "3"
    assert result.answer.citations == ["doc_0001"]
