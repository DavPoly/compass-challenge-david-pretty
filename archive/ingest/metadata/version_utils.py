"""Version, effective date and series of a versioned policy."""

import re
from dataclasses import dataclass

from archive.common.text.date_parsing_utils import (
    find_first_date,
    find_month_year,
)
from archive.common.text.text_normalize_utils import normalize_for_match
from archive.ingest.metadata.metadata_constants import (
    SERIES_NOISE_PATTERN,
    SERIES_SEPARATOR,
    VERSION_HEADER_LINES,
    VERSION_LINE_PATTERN,
)

_VERSION_LINE = re.compile(VERSION_LINE_PATTERN)
_SERIES_NOISE = re.compile(SERIES_NOISE_PATTERN)


@dataclass(frozen=True)
class VersionInfo:
    """Versioning facts of one policy document.

    Attributes:
        version: Version label, e.g. "3".
        effective_from: ISO date the version takes effect, or None.
        series: Normalized title shared by every version of a policy.
    """

    version: str
    effective_from: str | None
    series: str


def parse_version(text: str) -> VersionInfo | None:
    """Read the ``Version N - <effective date>`` line under the title.

    The title is the non-empty line just above the version line. The
    series key is that title without accents, case, punctuation or
    repeated spaces, so spelling variants of one title share a key.
    Letter typos in ``Version`` and in the month names are tolerated.

    Args:
        text: Normalized document text.

    Returns:
        The version facts, or None when the header has no version line
        or no title above it.
    """
    lines = [
        line for line in normalize_for_match(text).split("\n") if line.strip()
    ][:VERSION_HEADER_LINES]
    for index in range(1, len(lines)):
        match = _VERSION_LINE.match(lines[index])
        if match is None:
            continue
        rest = match.group("rest")
        return VersionInfo(
            version=match.group("number"),
            effective_from=find_first_date(rest) or find_month_year(rest),
            series=series_key(lines[index - 1]),
        )
    return None


def series_key(title: str) -> str:
    """Normalized key of a policy title.

    Args:
        title: Title line as written.

    Returns:
        Lowercase, accent-free words joined by single spaces.
    """
    words = _SERIES_NOISE.split(normalize_for_match(title))
    return SERIES_SEPARATOR.join(word for word in words if word)
