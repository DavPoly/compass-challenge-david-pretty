"""Tests for metadata extraction."""

import pytest

from archive.ingest.metadata.metadata_service import (
    DocMetadata,
    extract_identifiers,
    extract_metadata,
)
from archive.ingest.parse.pdf_parse_gateway import ParsedDoc


def _meta(*pages: str) -> DocMetadata:
    return extract_metadata(ParsedDoc(doc_id="d", pages=list(pages)))


def test_empty_doc_has_no_metadata() -> None:
    metadata = _meta()

    assert metadata.identifiers == []
    assert metadata.doc_date is None
    assert metadata.lang == "fr"
    assert metadata.doc_type == "unknown"


def test_identifiers_of_a_bare_text_are_extracted_without_a_document() -> None:
    assert extract_identifiers("Ref : f-2023-0042, cc A@B.co") == [
        "F-2023-0042",
        "a@b.co",
    ]


def test_canonical_codes_are_extracted_sorted_unique() -> None:
    text = (
        "Facture F-2023-0042 projet BRV-2023-06 contrat C-2023-15 F-2023-0042"
    )

    assert _meta(text).identifiers == [
        "BRV-2023-06",
        "C-2023-15",
        "F-2023-0042",
    ]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("F\u20132023\u20130042", "F-2023-0042"),
        ("F 2023 0042", "F-2023-0042"),
        ("F20230042", "F-2023-0042"),
        ("f-2023-0042", "F-2023-0042"),
        ("F-2O23-OO42", "F-2023-0042"),
        ("brv-2023-O6", "BRV-2023-06"),
        ("BRV 2023-06", "BRV-2023-06"),
        ("C\u20142023\u201415", "C-2023-15"),
        ("c-2019-03", "C-2019-03"),
    ],
)
def test_typo_variants_are_canonicalized(raw: str, expected: str) -> None:
    assert _meta(f"Ref : {raw}.").identifiers == [expected]


@pytest.mark.parametrize(
    "text",
    [
        "en 2023 15 personnes",
        "Annee 2023",
        "le c 2023 15 est",
        "F-2023-42",
        "F-2023-00421",
        "C-2023-155",
        "BRV-2023",
        "XF-2023-0042",
        "Total : 2023-12",
    ],
)
def test_plain_numbers_and_malformed_codes_are_ignored(text: str) -> None:
    assert _meta(text).identifiers == []


def test_emails_are_lowercased() -> None:
    text = "De : Xavier <Xavier.Ricard@Brumeval.example>, cc a@b.co."

    assert _meta(text).identifiers == [
        "a@b.co",
        "xavier.ricard@brumeval.example",
    ]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Date : 2024-05-29", "2024-05-29"),
        ("Date : 2024-06-23 11 h 47", "2024-06-23"),
        ("Date : 25/03/2024", "2024-03-25"),
        ("Date : 25.03.2024", "2024-03-25"),
        ("Date : 22/06/21", "2021-06-22"),
        ("Date : 13 février 2023", "2023-02-13"),
        ("Date : 13 fevrier 2023", "2023-02-13"),
        ("Date : 1er juin 2026", "2026-06-01"),
        ("Date : 16 novvembre 2024 8 h 47", "2024-11-16"),
        ("Date: December 20, 2021", "2021-12-20"),
        ("Date: May 11th, 2022", "2022-05-11"),
        ("Date: Dccember 8, 2025", "2025-12-08"),
        ("Date: 12 March 2024", "2024-03-12"),
    ],
)
def test_date_formats(text: str, expected: str) -> None:
    assert _meta(text).doc_date == expected


def test_first_date_in_text_wins() -> None:
    text = "Emis le 12 mars 2024. Echeance 2025-01-01."

    assert _meta(text).doc_date == "2024-03-12"


def test_invalid_date_is_skipped() -> None:
    assert _meta("31/02/2024 puis 2024-13-01").doc_date is None
    assert _meta("version 1.2.24 du 5 mai 2020").doc_date == "2020-05-05"


def test_non_month_word_is_not_a_date() -> None:
    assert _meta("12 jours 2024 pieces").doc_date is None


def test_lang_french() -> None:
    assert (
        _meta("Les travaux de la route sont termines pour le client").lang
        == "fr"
    )


def test_lang_english() -> None:
    assert (
        _meta("The works of the road are finished for the client").lang == "en"
    )


def test_lang_tie_defaults_to_french() -> None:
    assert _meta("Brumeval 2023").lang == "fr"


def test_metadata_reads_all_pages() -> None:
    metadata = _meta("page one", "ref BRV-2023-06\u00a0date 2023-01-02")

    assert metadata.identifiers == ["BRV-2023-06"]
    assert metadata.doc_date == "2023-01-02"
