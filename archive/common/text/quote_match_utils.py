"""Quote matching primitives shared by grounding and the run viewer.

Text is folded (case, accents, typographic punctuation, whitespace), a
quote is split on ellipsis markers and its pieces must appear in order,
with a whitespace-free fallback for sources that glue or split words
differently from the quote.
"""

from archive.common.text.text_normalize_constants import (
    ELLIPSIS_RE,
    MIN_QUOTE_PIECE_LENGTH,
    PUNCTUATION_FOLD,
    WHITESPACE_RE,
)
from archive.common.text.text_normalize_utils import normalize_for_match


def fold_text(text: str) -> str:
    """Case, accent, whitespace and typographic punctuation folded."""
    plain = normalize_for_match(text.translate(PUNCTUATION_FOLD))
    return WHITESPACE_RE.sub(" ", plain).strip()


def quote_pieces(quote: str) -> list[str]:
    """Folded pieces of a quote split on ellipsis markers.

    Tiny pieces are dropped only when a long enough piece remains;
    a quote of tiny pieces only yields no piece.
    """
    parts = ELLIPSIS_RE.split(quote)
    pieces = [piece for piece in map(fold_text, parts) if piece]
    if len(parts) == 1:
        return pieces
    return [piece for piece in pieces if len(piece) >= MIN_QUOTE_PIECE_LENGTH]


def has_pieces_in_order(pieces: list[str], text: str) -> bool:
    """True when every piece occurs in text, one after the other."""
    position = 0
    for piece in pieces:
        found = text.find(piece, position)
        if found < 0:
            return False
        position = found + len(piece)
    return True


def is_quote_in_text(pieces: list[str], text: str) -> bool:
    """True when the folded pieces occur in order in the folded text.

    Falls back to a whitespace-free comparison. Pieces come from
    quote_pieces; text is raw and folded here.
    """
    folded = fold_text(text)
    if has_pieces_in_order(pieces, folded):
        return True
    compact = WHITESPACE_RE.sub("", folded)
    return has_pieces_in_order(
        [WHITESPACE_RE.sub("", piece) for piece in pieces], compact
    )
