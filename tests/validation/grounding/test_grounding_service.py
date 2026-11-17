from archive.validation.answer_model import (
    AnswerStatus,
    DraftAnswer,
    Evidence,
    FinalAnswer,
)
from archive.validation.answer_validator import ValidationResult
from archive.validation.grounding.grounding_model import (
    Confidence,
    GroundingSources,
)
from archive.validation.grounding.grounding_service import check_grounding
from archive.validation.issue_model import IssueCode, ValidationIssue

DOC_TEXT = (
    "Le contrat prévoit un montant de 12 500,00 $ payable le 4 mars 2025."
)
SOURCES = GroundingSources(
    texts_by_doc={"doc_0001": [DOC_TEXT], "doc_0002": ["Autre texte."]},
    note=None,
)


def _draft(
    answer: str | list[str] = "12500.00",
    status: AnswerStatus = AnswerStatus.ANSWERED,
    evidence: list[Evidence] | None = None,
    is_sufficient: bool = True,
) -> DraftAnswer:
    if evidence is None:
        evidence = [
            Evidence(doc_id="doc_0001", quote="montant de 12 500,00 $")
        ]
    return DraftAnswer(
        answer=answer,
        status=status,
        citations=["doc_0001"],
        evidence=evidence,
        evidence_sufficient=is_sufficient,
    )


def _validation(
    issues: list[ValidationIssue] | None = None,
    dropped: list[str] | None = None,
) -> ValidationResult:
    final = FinalAnswer(
        id="q1",
        answer="x",
        citations=["doc_0001"],
        status=AnswerStatus.ANSWERED,
    )
    return ValidationResult(
        answer=final,
        issues=issues or [],
        dropped_citations=dropped or [],
    )


def test_grounded_answer_has_high_confidence() -> None:
    report = check_grounding(_draft(), SOURCES, _validation())

    assert report.issues == []
    assert report.confidence is Confidence.HIGH


def test_quote_match_ignores_case_accents_and_whitespace() -> None:
    evidence = [Evidence(doc_id="doc_0001", quote="LE  CONTRAT\nPREVOIT")]

    report = check_grounding(
        _draft(answer="", evidence=evidence), SOURCES, _validation()
    )

    assert report.unverified_quotes == []


def test_doc_id_pdf_suffix_is_stripped() -> None:
    evidence = [Evidence(doc_id="doc_0001.pdf", quote="un montant")]

    report = check_grounding(
        _draft(answer="", evidence=evidence), SOURCES, _validation()
    )

    assert report.unverified_quotes == []


def test_quote_not_in_text_is_unverified_and_low() -> None:
    evidence = [Evidence(doc_id="doc_0001", quote="montant de 99 $")]

    report = check_grounding(_draft(evidence=evidence), SOURCES, _validation())

    assert report.unverified_quotes == ["montant de 99 $"]
    assert report.issues[0].code is IssueCode.QUOTE_UNVERIFIED
    assert report.confidence is Confidence.LOW


def test_quote_attributed_to_another_doc_is_unverified() -> None:
    evidence = [Evidence(doc_id="doc_0002", quote="un montant")]

    report = check_grounding(
        _draft(answer="", evidence=evidence), SOURCES, _validation()
    )

    assert report.unverified_quotes == ["un montant"]


def test_quote_of_doc_not_in_sources_is_unverified() -> None:
    evidence = [Evidence(doc_id="doc_0099", quote="un montant")]

    report = check_grounding(
        _draft(answer="", evidence=evidence), SOURCES, _validation()
    )

    assert report.unverified_quotes == ["un montant"]


def test_empty_quote_is_unverified() -> None:
    evidence = [Evidence(doc_id="doc_0001", quote="  ")]

    report = check_grounding(
        _draft(answer="", evidence=evidence), SOURCES, _validation()
    )

    assert report.unverified_quotes == ["  "]


def test_empty_evidence_is_flagged_and_low() -> None:
    draft = _draft(evidence=[])

    report = check_grounding(draft, SOURCES, _validation())

    assert IssueCode.NO_EVIDENCE in [i.code for i in report.issues]
    assert report.confidence is Confidence.LOW


def test_amount_written_differently_is_grounded() -> None:
    report = check_grounding(_draft("12500.00"), SOURCES, _validation())

    assert report.ungrounded_values == []


def test_date_in_other_format_is_grounded() -> None:
    evidence = [Evidence(doc_id="doc_0001", quote="le 4 mars 2025")]

    report = check_grounding(
        _draft("2025-03-04", evidence=evidence), SOURCES, _validation()
    )

    assert report.ungrounded_values == []


def test_value_absent_from_quotes_is_ungrounded() -> None:
    report = check_grounding(_draft("13000.00"), SOURCES, _validation())

    assert report.ungrounded_values == ["13000.00"]
    assert IssueCode.VALUE_UNGROUNDED in [i.code for i in report.issues]
    assert report.confidence is Confidence.LOW


def test_value_only_in_unverified_quote_is_ungrounded() -> None:
    evidence = [Evidence(doc_id="doc_0001", quote="total de 777,00 $")]

    report = check_grounding(
        _draft("777.00", evidence=evidence), SOURCES, _validation()
    )

    assert report.ungrounded_values == ["777.00"]


def test_text_answer_contained_in_quote_is_grounded() -> None:
    evidence = [Evidence(doc_id="doc_0001", quote="Le contrat prévoit")]

    report = check_grounding(
        _draft("Contrat", evidence=evidence), SOURCES, _validation()
    )

    assert report.ungrounded_values == []


def test_list_answer_flags_only_the_ungrounded_item() -> None:
    evidence = [
        Evidence(doc_id="doc_0001", quote="12 500,00 $ payable le 4 mars 2025")
    ]

    report = check_grounding(
        _draft(["12500.00", "2025-03-04", "9999.00"], evidence=evidence),
        SOURCES,
        _validation(),
    )

    assert report.ungrounded_values == ["9999.00"]


def test_empty_answer_items_are_skipped() -> None:
    report = check_grounding(_draft(["12500.00", ""]), SOURCES, _validation())

    assert report.ungrounded_values == []


def test_note_grounds_an_aggregation_total() -> None:
    sources = GroundingSources(
        texts_by_doc={"doc_0001": [DOC_TEXT]},
        note="Total calculé : 31 000,00 $",
    )

    report = check_grounding(_draft("31000.00"), sources, _validation())

    assert report.ungrounded_values == []
    assert report.confidence is Confidence.HIGH


def test_conflict_status_skips_value_check() -> None:
    draft = _draft("whatever", status=AnswerStatus.CONFLICT)

    report = check_grounding(draft, SOURCES, _validation())

    assert report.ungrounded_values == []
    assert report.confidence is Confidence.HIGH


def test_conflict_without_evidence_is_low() -> None:
    draft = _draft(status=AnswerStatus.CONFLICT, evidence=[])

    report = check_grounding(draft, SOURCES, _validation())

    assert report.confidence is Confidence.LOW


def test_not_found_with_retrieved_texts_is_medium() -> None:
    draft = _draft("", status=AnswerStatus.NOT_FOUND, evidence=[])

    report = check_grounding(draft, SOURCES, _validation())

    assert report.issues == []
    assert report.confidence is Confidence.MEDIUM


def test_not_found_with_nothing_retrieved_is_high() -> None:
    draft = _draft("", status=AnswerStatus.NOT_FOUND, evidence=[])
    empty = GroundingSources(texts_by_doc={}, note=None)

    report = check_grounding(draft, empty, _validation())

    assert report.confidence is Confidence.HIGH


def test_dropped_citations_make_confidence_low() -> None:
    validation = _validation(dropped=["doc_0500"])

    report = check_grounding(_draft(), SOURCES, validation)

    assert report.confidence is Confidence.LOW


def test_other_validation_issue_makes_confidence_medium() -> None:
    issue = ValidationIssue(code=IssueCode.ANSWER_TOO_LONG, detail="long")

    report = check_grounding(_draft(), SOURCES, _validation([issue]))

    assert report.confidence is Confidence.MEDIUM


def test_normalized_issue_alone_keeps_confidence_high() -> None:
    issue = ValidationIssue(code=IssueCode.NORMALIZED, detail="fixed")

    report = check_grounding(_draft(), SOURCES, _validation([issue]))

    assert report.confidence is Confidence.HIGH


def test_insufficient_evidence_makes_confidence_medium() -> None:
    report = check_grounding(
        _draft(is_sufficient=False), SOURCES, _validation()
    )

    assert report.confidence is Confidence.MEDIUM
