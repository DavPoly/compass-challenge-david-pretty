"""Document metadata extraction: identifiers, date and language."""

import re
from dataclasses import dataclass
from datetime import date
from difflib import get_close_matches

from archive.common.constants import (
    DATE_DAY_MONTH_WORD_PATTERN,
    DATE_ISO_PATTERN,
    DATE_MONTH_WORD_DAY_PATTERN,
    DATE_NUMERIC_PATTERN,
    DATE_SHORT_YEAR_PATTERN,
    DOC_TYPE_UNKNOWN,
    EMAIL_PATTERN,
    IDENTIFIER_DASH_CHARS,
    IDENTIFIER_PATTERN,
    IDENTIFIER_SERIAL_DIGITS,
    LANG_EN,
    LANG_FR,
    LANG_HINTS_EN,
    LANG_HINTS_FR,
    LANG_WORD_PATTERN,
    MONTH_FUZZY_CUTOFF,
    MONTH_FUZZY_MIN_LENGTH,
    MONTH_NUMBERS,
    SHORT_YEAR_CENTURY,
    SHORT_YEAR_DIGITS,
)
from archive.ingest.pdf_parse_gateway import ParsedDoc
from archive.ingest.text_normalize_utils import (
    join_pages,
    normalize_for_match,
)

_IDENTIFIER = re.compile(IDENTIFIER_PATTERN)
_EMAIL = re.compile(EMAIL_PATTERN)
_LANG_WORD = re.compile(LANG_WORD_PATTERN)
_DATE_PATTERNS = [
    re.compile(pattern)
    for pattern in (
        DATE_ISO_PATTERN,
        DATE_NUMERIC_PATTERN,
        DATE_SHORT_YEAR_PATTERN,
        DATE_DAY_MONTH_WORD_PATTERN,
        DATE_MONTH_WORD_DAY_PATTERN,
    )
]


@dataclass(frozen=True)
class DocMetadata:
    """Metadata shared by every chunk of a document.

    Attributes:
        doc_type: Document type; "unknown" until classification exists.
        doc_date: First date found, ISO `YYYY-MM-DD`, or None.
        identifiers: Canonical codes and emails, sorted and unique.
        lang: "fr" or "en".
    """

    doc_type: str
    doc_date: str | None
    identifiers: list[str]
    lang: str


def extract_metadata(doc: ParsedDoc) -> DocMetadata:
    """Extract identifiers, first date and language from a document.

    Identifiers are `F-YYYY-NNNN`, `C-YYYY-NN`, `BRV-YYYY-NN` (typo
    variants are canonicalized) and lowercased emails. Dates accepted:
    ISO, `DD/MM/YYYY`, `DD.MM.YYYY`, `DD/MM/YY`, `12 mars 2024`,
    `March 12, 2024`, `12 March 2024`; the earliest in the text wins.

    Args:
        doc: Parsed document.

    Returns:
        The metadata; an empty document gives no identifiers, no date
        and language "fr".
    """
    text = join_pages(doc.pages)
    return DocMetadata(
        doc_type=DOC_TYPE_UNKNOWN,
        doc_date=_find_first_date(text),
        identifiers=_find_identifiers(text),
        lang=_detect_lang(text),
    )


def _find_identifiers(text: str) -> list[str]:
    """Return sorted unique canonical codes and emails of `text`."""
    found = {
        code
        for code in map(_canonical_code, _IDENTIFIER.finditer(text))
        if code
    }
    found.update(match.group().lower() for match in _EMAIL.finditer(text))
    return sorted(found)


def _canonical_code(match: re.Match[str]) -> str | None:
    """Canonical `PREFIX-YYYY-N..` form of a match, or None if invalid."""
    prefix = match.group("prefix")
    is_dash = match.group("sep") in IDENTIFIER_DASH_CHARS
    if prefix != prefix.upper() and not is_dash:
        return None
    prefix = prefix.upper()
    serial = match.group("serial").replace("O", "0")
    if len(serial) != IDENTIFIER_SERIAL_DIGITS[prefix]:
        return None
    year = match.group("year").replace("O", "0")
    return f"{prefix}-{year}-{serial}"


def _find_first_date(text: str) -> str | None:
    """Return the earliest valid date of `text` as ISO, or None."""
    candidates: list[tuple[int, str]] = []
    for pattern in _DATE_PATTERNS:
        for match in pattern.finditer(text):
            iso = _to_iso(match)
            if iso is not None:
                candidates.append((match.start(), iso))
                break
    return min(candidates)[1] if candidates else None


def _to_iso(match: re.Match[str]) -> str | None:
    """Convert a date match to ISO, or None if it is not a real date."""
    groups = match.groupdict()
    month = _month_number(groups["m"])
    if month is None:
        return None
    year = int(groups["y"])
    if len(groups["y"]) == SHORT_YEAR_DIGITS:
        year += SHORT_YEAR_CENTURY
    try:
        return date(year, month, int(groups["d"])).isoformat()
    except ValueError:
        return None


def _month_number(token: str) -> int | None:
    """Month number of a numeric or FR/EN month token (typo tolerant)."""
    if token.isdigit():
        return int(token)
    name = normalize_for_match(token)
    if name in MONTH_NUMBERS:
        return MONTH_NUMBERS[name]
    if len(name) < MONTH_FUZZY_MIN_LENGTH:
        return None
    close = get_close_matches(
        name, MONTH_NUMBERS, n=1, cutoff=MONTH_FUZZY_CUTOFF
    )
    return MONTH_NUMBERS[close[0]] if close else None


def _detect_lang(text: str) -> str:
    """Return "en" if English stopwords outnumber French ones, else "fr"."""
    words = _LANG_WORD.findall(normalize_for_match(text))
    french_hits = sum(word in LANG_HINTS_FR for word in words)
    english_hits = sum(word in LANG_HINTS_EN for word in words)
    return LANG_EN if english_hits > french_hits else LANG_FR
