import pytest

from archive.common.text.quote_match_utils import (
    fold_text,
    has_pieces_in_order,
    is_quote_in_text,
    quote_pieces,
)


def test_fold_text_folds_case_accents_quotes_and_whitespace() -> None:
    assert fold_text("  L’Été \n  “Chaud” ") == 'l\'ete "chaud"'


def test_quote_pieces_splits_on_ellipsis_and_drops_tiny_pieces() -> None:
    pieces = quote_pieces("début de phrase [...] ok … fin de phrase")

    assert pieces == ["debut de phrase", "fin de phrase"]


def test_quote_pieces_keeps_a_short_quote_without_ellipsis() -> None:
    assert quote_pieces("oui") == ["oui"]


def test_quote_pieces_of_tiny_pieces_only_is_empty() -> None:
    assert quote_pieces("a ... b") == []


@pytest.mark.parametrize(
    ("pieces", "expected"),
    [(["abc", "def"], True), (["def", "abc"], False), ([], True)],
)
def test_has_pieces_in_order(pieces: list[str], expected: bool) -> None:
    assert has_pieces_in_order(pieces, "abc xx def") is expected


def test_is_quote_in_text_uses_whitespace_free_fallback() -> None:
    pieces = quote_pieces("total payé")

    assert is_quote_in_text(pieces, "Le total  pa yé est élevé")
    assert not is_quote_in_text(pieces, "autre texte")
