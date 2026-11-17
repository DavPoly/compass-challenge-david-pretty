"""Locate a quote and its value among the words of a PDF page.

Matching mirrors the grounding check: words are folded (case, accents,
typographic punctuation), the quote is split on ellipsis markers and its
pieces are found in order, with a whitespace-free fallback for PDFs that
glue or split words differently from the quote.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from archive.common.text.text_normalize_utils import normalize_for_match
from archive.validation.grounding.grounding_constants import (
    ELLIPSIS_RE,
    MIN_QUOTE_PIECE_LENGTH,
    PUNCTUATION_FOLD,
    WHITESPACE_RE,
)
from archive.viewer.viewer_constants import LINE_TOP_TOLERANCE_PT


@dataclass(frozen=True)
class Word:
    """A PDF word with its box in points (pdfplumber convention)."""

    text: str
    x0: float
    top: float
    x1: float
    bottom: float


@dataclass(frozen=True)
class Box:
    """A rectangle in PDF points, origin at the top-left of the page."""

    x0: float
    top: float
    x1: float
    bottom: float


@dataclass(frozen=True)
class QuoteMatch:
    """Where a quote (and its value) sit on a page.

    Attributes:
        boxes: One box per line of the matched quote words.
        value_boxes: One box per line of the matched value words;
            empty when the value was not found.
    """

    boxes: list[Box]
    value_boxes: list[Box]


@dataclass(frozen=True)
class _Index:
    """Folded text of some words and the word owning each character."""

    text: str
    owners: list[int]


def _fold(text: str) -> str:
    plain = normalize_for_match(text.translate(PUNCTUATION_FOLD))
    return WHITESPACE_RE.sub(" ", plain).strip()


def _pieces(quote: str) -> list[str]:
    parts = ELLIPSIS_RE.split(quote)
    pieces = [piece for piece in map(_fold, parts) if piece]
    if len(parts) == 1:
        return pieces
    return [p for p in pieces if len(p) >= MIN_QUOTE_PIECE_LENGTH]


def _build_index(
    folded_words: Sequence[tuple[int, str]], separator: str
) -> _Index:
    chars: list[str] = []
    owners: list[int] = []
    for word_index, folded in folded_words:
        if chars and separator:
            chars.append(separator)
            owners.append(owners[-1])
        chars.append(folded)
        owners.extend([word_index] * len(folded))
    return _Index("".join(chars), owners)


def _find_in_order(index: _Index, pieces: list[str]) -> list[int] | None:
    """Word indices covered by the pieces found in order, else None."""
    position = 0
    covered: set[int] = set()
    for piece in pieces:
        start = index.text.find(piece, position)
        if start < 0:
            return None
        position = start + len(piece)
        covered.update(index.owners[start:position])
    return sorted(covered)


def _find_words(
    folded_words: Sequence[tuple[int, str]], pieces: list[str]
) -> list[int] | None:
    spaced = _find_in_order(_build_index(folded_words, " "), pieces)
    if spaced is not None:
        return spaced
    compact_words = [
        (index, WHITESPACE_RE.sub("", folded))
        for index, folded in folded_words
    ]
    compact_words = [item for item in compact_words if item[1]]
    compact_pieces = [WHITESPACE_RE.sub("", piece) for piece in pieces]
    return _find_in_order(_build_index(compact_words, ""), compact_pieces)


def _union(words: Sequence[Word]) -> Box:
    return Box(
        min(word.x0 for word in words),
        min(word.top for word in words),
        max(word.x1 for word in words),
        max(word.bottom for word in words),
    )


def _line_boxes(words: Sequence[Word], indices: list[int]) -> list[Box]:
    lines: list[list[Word]] = []
    for word_index in indices:
        word = words[word_index]
        same_line = (
            lines and abs(lines[-1][0].top - word.top) <= LINE_TOP_TOLERANCE_PT
        )
        if same_line:
            lines[-1].append(word)
        else:
            lines.append([word])
    return [_union(line) for line in lines]


def _locate_value(
    folded_words: Sequence[tuple[int, str]],
    quote_indices: list[int],
    value: str,
) -> list[int]:
    pieces = [_fold(value)]
    if not pieces[0]:
        return []
    first, last = quote_indices[0], quote_indices[-1]
    inside = [item for item in folded_words if first <= item[0] <= last]
    found = _find_words(inside, pieces)
    if found is None:
        found = _find_words(folded_words, pieces)
    return found or []


def locate_quote(
    words: Sequence[Word], quote: str, value: str | None
) -> QuoteMatch | None:
    """Find a quote, and optionally its value, among page words.

    Args:
        words: The words of one page in reading order.
        quote: The quote; may contain ellipsis markers between pieces.
        value: The answer value to highlight, preferably inside the
            quote's span; None to skip.

    Returns:
        The line boxes of the quote and of the value, or None when the
        quote is empty or not found on this page. Never raises.
    """
    pieces = _pieces(quote)
    if not pieces:
        return None
    folded_words = [
        (index, folded)
        for index, word in enumerate(words)
        if (folded := _fold(word.text))
    ]
    quote_indices = _find_words(folded_words, pieces)
    if not quote_indices:
        return None
    value_indices = (
        _locate_value(folded_words, quote_indices, value) if value else []
    )
    return QuoteMatch(
        _line_boxes(words, quote_indices),
        _line_boxes(words, value_indices),
    )
