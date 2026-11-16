"""Text normalization shared by chunking, metadata and tokenizing."""

import re
import unicodedata

from archive.common.text.text_normalize_constants import (
    BLANK_LINES_PATTERN,
    HORIZONTAL_SPACE_PATTERN,
    PAGE_SEPARATOR,
    UNICODE_COMPAT_FORM,
    UNICODE_DECOMPOSED_FORM,
)

_HORIZONTAL_SPACE = re.compile(HORIZONTAL_SPACE_PATTERN)
_BLANK_LINES = re.compile(BLANK_LINES_PATTERN)


def normalize_text(text: str) -> str:
    """Clean raw PDF text while keeping accents, case and line layout.

    Applies NFKC (which turns no-break, narrow no-break and thin spaces
    into plain spaces), unifies line endings, collapses runs of spaces
    and tabs, trims every line, reduces 3+ consecutive newlines to one
    blank line and strips the result.

    Args:
        text: Raw text.

    Returns:
        The normalized text.
    """
    folded = unicodedata.normalize(UNICODE_COMPAT_FORM, text)
    folded = folded.replace("\r\n", "\n").replace("\r", "\n")
    folded = _HORIZONTAL_SPACE.sub(" ", folded)
    lines = [line.strip() for line in folded.split("\n")]
    return _BLANK_LINES.sub(PAGE_SEPARATOR, "\n".join(lines)).strip()


def strip_accents(text: str) -> str:
    """Remove diacritics from text, keeping every other character.

    The text is decomposed (NFKD) and the combining marks are dropped, so
    precomposed (``é``) and decomposed (``e`` + U+0301) accents fold the
    same way. Case is left untouched.

    Args:
        text: Any text.

    Returns:
        The text without diacritics.
    """
    decomposed = unicodedata.normalize(UNICODE_DECOMPOSED_FORM, text)
    return "".join(
        char for char in decomposed if not unicodedata.combining(char)
    )


def normalize_for_match(text: str) -> str:
    """Normalize text for token and identifier matching.

    Same as `normalize_text`, then lowercased with accents removed by
    `strip_accents`.

    Args:
        text: Raw text.

    Returns:
        Lowercase, accent-free normalized text.
    """
    return strip_accents(normalize_text(text).lower())


def join_pages(pages: list[str]) -> str:
    """Normalize pages and join them with blank lines.

    Args:
        pages: One raw string per page.

    Returns:
        The normalized document text; empty when no page has text.
    """
    return normalize_text(PAGE_SEPARATOR.join(pages))
