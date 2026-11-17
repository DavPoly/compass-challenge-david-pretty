"""Tests for text normalization."""

from archive.common.text.text_normalize_utils import (
    join_pages,
    normalize_for_match,
    normalize_text,
    strip_accents,
)


def test_normalize_text_replaces_special_spaces() -> None:
    raw = "24\u00a0475,00\u202f$ et 12\u2009h"

    assert normalize_text(raw) == "24 475,00 $ et 12 h"


def test_normalize_text_collapses_spaces_and_tabs() -> None:
    assert normalize_text("a  \t b   c") == "a b c"


def test_normalize_text_keeps_one_blank_line_at_most() -> None:
    assert normalize_text("a\n\n\n\n\nb\nc") == "a\n\nb\nc"


def test_normalize_text_unifies_line_endings_and_strips() -> None:
    assert normalize_text("  \r\na \r\n b\r\n\r\n") == "a\nb"


def test_normalize_text_keeps_accents_and_case() -> None:
    assert normalize_text("Élève  Brumeval") == "Élève Brumeval"


def test_normalize_text_empty() -> None:
    assert normalize_text("") == ""
    assert normalize_text(" \n\t \n") == ""


def test_normalize_text_applies_nfkc() -> None:
    assert normalize_text("\ufb01n \u2460") == "fin 1"


def test_normalize_for_match_folds_accents_and_case() -> None:
    assert normalize_for_match("Rosalie LAFRENIÈRE-Marcoux") == (
        "rosalie lafreniere-marcoux"
    )


def test_normalize_for_match_handles_decomposed_input() -> None:
    assert normalize_for_match("e\u0301te\u0301") == "ete"


def test_normalize_for_match_normalizes_spaces() -> None:
    assert normalize_for_match("Facturé\u00a0à") == "facture a"


def test_strip_accents_folds_precomposed_and_decomposed_marks() -> None:
    assert strip_accents("\u00e9") == "e"
    assert strip_accents("e\u0301") == "e"
    assert strip_accents("\u00e7a") == "ca"


def test_strip_accents_keeps_case_and_other_characters() -> None:
    assert strip_accents("\u00c9l\u00e8ve 12") == "Eleve 12"


def test_strip_accents_empty() -> None:
    assert strip_accents("") == ""


def test_normalize_for_match_is_strip_accents_of_lowercased_text() -> None:
    raw = "Factur\u00e9\u00a0\u00e0 LAFRENI\u00c8RE"

    assert normalize_for_match(raw) == strip_accents(
        normalize_text(raw).lower()
    )


def test_normalize_for_match_folds_mixed_accent_forms() -> None:
    assert normalize_for_match("\u00c9t\u00e9 e\u0301te\u0301") == "ete ete"


def test_join_pages_separates_pages_with_blank_line() -> None:
    assert join_pages([" p1 ", "", "p3"]) == "p1\n\np3"


def test_join_pages_without_text_is_empty() -> None:
    assert join_pages([]) == ""
    assert join_pages(["", " "]) == ""
