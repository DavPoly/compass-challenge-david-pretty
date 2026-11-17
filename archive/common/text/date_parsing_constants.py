"""Month tables and date patterns shared by ingest and validation.

`MONTHS` is the merge of `MONTH_FULL_NAMES` (what ingest matches, fuzzy
tolerant) and `MONTH_ABBREVIATIONS` (accepted by the validation date
patterns only).
"""

import re

MONTH_FULL_NAMES: dict[str, int] = {
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5,
    "juin": 6, "juillet": 7, "aout": 8, "septembre": 9,
    "octobre": 10, "novembre": 11, "decembre": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5,
    "june": 6, "july": 7, "august": 8, "september": 9,
    "october": 10, "november": 11, "december": 12,
}  # fmt: skip

MONTH_ABBREVIATIONS: dict[str, int] = {
    "janv": 1, "jan": 1,
    "fevr": 2, "fev": 2, "feb": 2,
    "mar": 3,
    "avr": 4, "apr": 4,
    "jun": 6,
    "juil": 7, "jul": 7,
    "aug": 8,
    "sept": 9, "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}  # fmt: skip

MONTHS: dict[str, int] = {**MONTH_FULL_NAMES, **MONTH_ABBREVIATIONS}
_MONTH_NAMES = "|".join(sorted(MONTHS, key=len, reverse=True))

# Compiled patterns: strict `fullmatch` validation of a whole answer
# (validation package).
ISO_DATE_RE = re.compile(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})")
DAY_FIRST_DATE_RE = re.compile(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})")
DAY_MONTH_NAME_RE = re.compile(
    rf"(\d{{1,2}})(?:er|st|nd|rd|th)?[\s-]*(?:of\s+|de\s+)?"
    rf"({_MONTH_NAMES})\.?,?[\s-]+(\d{{4}})"
)
MONTH_NAME_DAY_RE = re.compile(
    rf"({_MONTH_NAMES})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})"
)

# Pattern strings: tolerant `finditer` scanning of document text
# (ingest package).
DATE_ISO_PATTERN = r"(?<![\d-])(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})(?!\d)"
DATE_NUMERIC_PATTERN = (
    r"(?<![\d/.])(?P<d>\d{1,2})[/.](?P<m>\d{1,2})[/.]"
    r"(?P<y>\d{4})(?![\d/.])"
)
DATE_SHORT_YEAR_PATTERN = (
    r"(?<![\d/.])(?P<d>\d{2})/(?P<m>\d{2})/(?P<y>\d{2})(?![\d/.])"
)
DATE_DAY_MONTH_WORD_PATTERN = (
    r"(?<!\d)(?P<d>\d{1,2})(?:er|st|nd|rd|th)?\s+"
    r"(?P<m>[^\W\d_]{3,12})\.?,?\s+(?P<y>\d{4})(?!\d)"
)
DATE_MONTH_WORD_DAY_PATTERN = (
    r"(?<![^\W\d_])(?P<m>[^\W\d_]{3,12})\.?\s+(?P<d>\d{1,2})"
    r"(?:st|nd|rd|th)?,?\s+(?P<y>\d{4})(?!\d)"
)
DATE_MONTH_YEAR_PATTERN = (
    r"(?<![^\W\d_])(?P<m>[^\W\d_]{3,12})\.?\s+(?P<y>\d{4})(?!\d)"
)

MONTH_FIRST_DAY = 1
SHORT_YEAR_CENTURY = 2000
SHORT_YEAR_DIGITS = 2
MONTH_FUZZY_MIN_LENGTH = 4
MONTH_FUZZY_CUTOFF = 0.8
# A day of 12 or less could be the month, so DD/MM and MM/DD are
# ambiguous and such a date is left as written.
AMBIGUOUS_DAY_MONTH_LIMIT = 12
