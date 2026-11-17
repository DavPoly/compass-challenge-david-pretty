import pytest

from archive.validation.answer_model import (
    AnswerStatus,
    DraftAnswer,
    Evidence,
    FinalAnswer,
)
from archive.validation.answer_validator import ValidationResult
from archive.validation.grounding.grounding_model import (
    Confidence,
    GroundingReport,
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


def _grounded_report(
    answer: str, doc_text: str, quote: str
) -> GroundingReport:
    sources = GroundingSources(
        texts_by_doc={"doc_0001": [doc_text]}, note=None
    )
    evidence = [Evidence(doc_id="doc_0001", quote=quote)]
    return check_grounding(
        _draft(answer, evidence=evidence), sources, _validation()
    )


@pytest.mark.parametrize("answer", ["2024-03-05", "2024-05-03"])
def test_ambiguous_day_month_date_grounds_both_readings(answer: str) -> None:
    report = _grounded_report(answer, "Signé le 05/03/2024.", "le 05/03/2024")

    assert report.ungrounded_values == []


def test_day_month_date_with_other_day_is_ungrounded() -> None:
    report = _grounded_report(
        "2024-03-06", "Signé le 05/03/2024.", "le 05/03/2024"
    )

    assert report.ungrounded_values == ["2024-03-06"]


@pytest.mark.parametrize(
    ("doc_text", "quote"),
    [
        ("l’équipe d'Anne", "l'équipe d’Anne"),
        ("l'équipe d'Anne", "l’équipe d’Anne"),
        ("dit «oui» – non", 'dit "oui" - non'),
    ],
)
def test_typographic_punctuation_is_folded(doc_text: str, quote: str) -> None:
    report = _grounded_report("equipe", doc_text, quote)

    assert report.unverified_quotes == []


def test_trailing_punctuation_of_an_answer_is_ignored() -> None:
    report = _grounded_report(
        "Montréal.", "Ville : Montréal", "Ville : Montréal"
    )

    assert report.ungrounded_values == []


ELIDED_DOC = (
    "Project number | BRV-2023-14 | Date | 2023-05-01 | "
    "Subcontractor | Pavage Brightwater ltée"
)


@pytest.mark.parametrize("marker", ["...", "…", "[...]"])
def test_elided_quote_with_ordered_pieces_is_verified(marker: str) -> None:
    quote = f"Project number | BRV-2023-14 {marker} Subcontractor | Pavage"
    report = _grounded_report("BRV-2023-14", ELIDED_DOC, quote)

    assert report.unverified_quotes == []


def test_elided_quote_tolerates_spacing_differences() -> None:
    quote = "Project number | BRV-2023-14 ... PavageBrightwater ltée"
    report = _grounded_report("BRV-2023-14", ELIDED_DOC, quote)

    assert report.unverified_quotes == []


def test_elided_quote_with_absent_piece_is_unverified() -> None:
    quote = "Project number | BRV-2023-14 ... Subcontractor | Autre ltée"
    report = _grounded_report("BRV-2023-14", ELIDED_DOC, quote)

    assert report.unverified_quotes == [quote]
    assert report.confidence is Confidence.LOW


def test_elided_quote_with_pieces_in_wrong_order_is_unverified() -> None:
    quote = "Subcontractor | Pavage ... Project number | BRV-2023-14"
    report = _grounded_report("BRV-2023-14", ELIDED_DOC, quote)

    assert report.unverified_quotes == [quote]


def test_quote_of_only_ellipsis_and_tiny_pieces_is_unverified() -> None:
    report = _grounded_report("BRV-2023-14", ELIDED_DOC, "Date ... ltée")

    assert report.unverified_quotes == ["Date ... ltée"]


@pytest.mark.parametrize(
    ("answer", "doc_text", "quote"),
    [
        ("0.57 $ par kilomètre", "Taux : 0,57 $ / km", "0,57 $ / km"),
        (
            "730000.00 CAD (taxes en sus)",
            "Montant : 730 000,00 $ avant taxes",
            "730 000,00 $",
        ),
    ],
)
def test_amount_embedded_in_answer_text_is_grounded(
    answer: str, doc_text: str, quote: str
) -> None:
    report = _grounded_report(answer, doc_text, quote)

    assert report.ungrounded_values == []


def test_embedded_amount_differing_from_quote_is_ungrounded() -> None:
    report = _grounded_report(
        "0.58 $ par kilomètre", "Taux : 0,57 $ / km", "0,57 $ / km"
    )

    assert report.ungrounded_values == ["0.58 $ par kilomètre"]


KM_DOC = (
    "Le taux de remboursement kilométrique est fixé à $0.57 par kilomètre."
)
KM_QUOTE = "est fixé à $0.57 par kilomètre."
KM_NOTE = (
    "Policy version in force on 2025-01-01: document doc_2692, "
    "version 2, effective from 2022-01-11 to 2025-01-17."
)


def _km_report(answer: str) -> GroundingReport:
    sources = GroundingSources(
        texts_by_doc={"doc_0001": [KM_DOC]}, note=KM_NOTE
    )
    evidence = [Evidence(doc_id="doc_0001", quote=KM_QUOTE)]
    return check_grounding(
        _draft(answer, evidence=evidence), sources, _validation()
    )


def test_date_parts_and_version_label_do_not_ungrounded_amount() -> None:
    report = _km_report(
        "0,57 $ par kilomètre (version 3, en vigueur le 2025-01-17)"
    )

    assert report.ungrounded_values == []
    assert report.confidence is not Confidence.LOW


def test_unsupported_amount_next_to_version_label_is_flagged() -> None:
    answer = "0,62 $ (version 3)"

    report = _km_report(answer)

    assert report.ungrounded_values == [answer]


@pytest.mark.parametrize(
    "answer", ["0,57 $ en vigueur le 2025-01-17", "0,57 $ depuis 2025"]
)
def test_date_or_year_extra_does_not_create_amount_keys(answer: str) -> None:
    report = _km_report(answer)

    assert report.ungrounded_values == []
