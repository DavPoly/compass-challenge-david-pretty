"""Month-number lookup and ISO date building shared by date consumers."""

from collections.abc import Mapping
from datetime import date
from difflib import get_close_matches

from archive.common.text.date_parsing_constants import (
    MONTH_FUZZY_CUTOFF,
    MONTH_FUZZY_MIN_LENGTH,
)
from archive.common.text.text_normalize_utils import normalize_for_match


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
