"""Month-number lookup and ISO date building shared by date consumers."""

import re
from collections.abc import Mapping
from datetime import date
from difflib import get_close_matches

from archive.common.text.date_parsing_constants import (
    DATE_DAY_MONTH_WORD_PATTERN,
    DATE_ISO_PATTERN,
    DATE_MONTH_WORD_DAY_PATTERN,
    DATE_MONTH_YEAR_PATTERN,
    DATE_NUMERIC_PATTERN,
    DATE_SHORT_YEAR_PATTERN,
    MONTH_FIRST_DAY,
    MONTH_FULL_NAMES,
    MONTH_FUZZY_CUTOFF,
    MONTH_FUZZY_MIN_LENGTH,
    SHORT_YEAR_CENTURY_1900,
    SHORT_YEAR_CENTURY_2000,
    SHORT_YEAR_DIGITS,
    SHORT_YEAR_PIVOT,
)
from archive.common.text.text_normalize_utils import normalize_for_match

_FULL_DATE_PATTERNS = [
    re.compile(pattern)
    for pattern in (
        DATE_ISO_PATTERN,
        DATE_NUMERIC_PATTERN,
        DATE_SHORT_YEAR_PATTERN,
        DATE_DAY_MONTH_WORD_PATTERN,
        DATE_MONTH_WORD_DAY_PATTERN,
    )
]
_MONTH_YEAR = re.compile(DATE_MONTH_YEAR_PATTERN)


def fuzzy_month_number(token: str, months: Mapping[str, int]) -> int | None:
    """Month number of a table entry, tolerating OCR-like typos.

    The token is accent-folded and lowercased first. An exact entry wins;
    otherwise the closest name of `months` is used once the folded token
    has at least `MONTH_FUZZY_MIN_LENGTH` characters and is at least
    `MONTH_FUZZY_CUTOFF` similar.

    Args:
        token: Month name as written, e.g. ``Février`` or ``Septembr``.
        months: Month names to look the token up in.

    Returns:
        The month number, or None when no name is close enough.
    """
    name = normalize_for_match(token)
    if (number := months.get(name)) is not None:
        return number
    if len(name) < MONTH_FUZZY_MIN_LENGTH:
        return None
    close = get_close_matches(name, months, n=1, cutoff=MONTH_FUZZY_CUTOFF)
    return months[close[0]] if close else None


def build_iso_date(year: int, month: int, day: int) -> str | None:
    """ISO `YYYY-MM-DD` form of a calendar date, or None if it is invalid.

    Args:
        year: Four-digit year.
        month: Month number, 1 to 12.
        day: Day of month.

    Returns:
        The ISO date, or None when the day does not exist in that month.
    """
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def find_first_date(text: str) -> str | None:
    """Earliest valid full date of `text` as ISO, or None.

    Accepts ISO, `DD/MM/YYYY`, `DD.MM.YYYY`, `DD/MM/YY`, `12 mars 2024`,
    `1er mars 2024`, `March 12, 2024` and `12 March 2024`; month names
    tolerate typos.

    Args:
        text: Text to scan.

    Returns:
        The ISO date that starts first in the text, or None.
    """
    candidates: list[tuple[int, str]] = []
    for pattern in _FULL_DATE_PATTERNS:
        for match in pattern.finditer(text):
            iso = _match_to_iso(match)
            if iso is not None:
                candidates.append((match.start(), iso))
                break
    return min(candidates)[1] if candidates else None


def find_month_year(text: str) -> str | None:
    """First `Month YYYY` of `text` as the ISO first day of that month.

    Args:
        text: Text to scan, e.g. ``Période : août 2023``.

    Returns:
        The ISO date ``YYYY-MM-01``, or None when no month-year exists.
    """
    for match in _MONTH_YEAR.finditer(text):
        month = fuzzy_month_number(match.group("m"), MONTH_FULL_NAMES)
        if month is not None:
            return build_iso_date(
                int(match.group("y")), month, MONTH_FIRST_DAY
            )
    return None


def _match_to_iso(match: re.Match[str]) -> str | None:
    """Convert a date match to ISO, or None if it is not a real date."""
    groups = match.groupdict()
    token = groups["m"]
    if token.isdigit():
        month: int | None = int(token)
    else:
        month = fuzzy_month_number(token, MONTH_FULL_NAMES)
    if month is None:
        return None
    year = int(groups["y"])
    if len(groups["y"]) == SHORT_YEAR_DIGITS:
        is_recent = year <= SHORT_YEAR_PIVOT
        year += (
            SHORT_YEAR_CENTURY_2000 if is_recent else SHORT_YEAR_CENTURY_1900
        )
    return build_iso_date(year, month, int(groups["d"]))
