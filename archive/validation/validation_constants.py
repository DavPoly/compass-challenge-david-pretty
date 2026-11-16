"""Constants shared by the validation package."""

import re
from decimal import ROUND_HALF_UP

LINE_ID_PREFIX = "line-"
MAX_ANSWER_CHARS = 200
MIN_CONFLICT_CITATIONS = 2
NOT_FOUND_ANSWER = ""

ANSWER_FIELD_DESCRIPTION = (
    "The value alone, short. Dates as YYYY-MM-DD, amounts as plain "
    "decimals like 1234.50. A JSON list for multi-item answers. "
    "Empty string when status is not_found."
)
STATUS_FIELD_DESCRIPTION = (
    "answered, not_found (absent from the documents) or conflict "
    "(documents contradict each other and nothing settles it)."
)
CITATIONS_FIELD_DESCRIPTION = (
    "Document ids (like doc_0042) that justify the answer. Every "
    "document of a conflict."
)
EVIDENCE_FIELD_DESCRIPTION = (
    "Verbatim quotes supporting the answer, one per document used."
)
SUFFICIENT_FIELD_DESCRIPTION = (
    "True when the supplied excerpts are enough to answer or to "
    "conclude not_found or conflict."
)
MISSING_FIELD_DESCRIPTION = (
    "What information is still needed when the evidence is not sufficient."
)

MONTHS: dict[str, int] = {
    "janvier": 1, "janv": 1, "january": 1, "jan": 1,
    "fevrier": 2, "fevr": 2, "fev": 2, "february": 2, "feb": 2,
    "mars": 3, "march": 3, "mar": 3,
    "avril": 4, "avr": 4, "april": 4, "apr": 4,
    "mai": 5, "may": 5,
    "juin": 6, "june": 6, "jun": 6,
    "juillet": 7, "juil": 7, "july": 7, "jul": 7,
    "aout": 8, "august": 8, "aug": 8,
    "septembre": 9, "sept": 9, "september": 9, "sep": 9,
    "octobre": 10, "oct": 10, "october": 10,
    "novembre": 11, "nov": 11, "november": 11,
    "decembre": 12, "dec": 12, "december": 12,
}  # fmt: skip
_MONTH_NAMES = "|".join(sorted(MONTHS, key=len, reverse=True))

ISO_DATE_RE = re.compile(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})")
DAY_FIRST_DATE_RE = re.compile(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})")
DAY_MONTH_NAME_RE = re.compile(
    rf"(\d{{1,2}})(?:er|st|nd|rd|th)?[\s-]*(?:of\s+|de\s+)?"
    rf"({_MONTH_NAMES})\.?,?[\s-]+(\d{{4}})"
)
MONTH_NAME_DAY_RE = re.compile(
    rf"({_MONTH_NAMES})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})"
)

AMOUNT_RE = re.compile(
    r"(?P<before>(?:\$|cad)\s?)?"
    r"(?P<number>-?\d[\d\u00a0\u202f '.,]*\d|-?\d)"
    r"(?P<after>\s?(?:\$|cad\b|dollars?))?",
    re.IGNORECASE,
)
DECIMAL_PLACES = 2
AMOUNT_ROUNDING = ROUND_HALF_UP
MAX_DECIMAL_DIGITS = 2
THOUSANDS_GROUP_DIGITS = 3
MAX_UNAMBIGUOUS_MONTH = 12
PDF_SUFFIX = ".pdf"

INVISIBLE_SPACE_RE = re.compile(r"[   ']")
SEPARATOR_RE = re.compile(r"[,.]")

ISSUE_NORMALIZED = "normalized answer {original!r} to {fixed!r}"
ISSUE_TOO_LONG = "answer has {length} chars, expected under {limit}"
ISSUE_DROPPED = "dropped citations not retrieved: {dropped}"
ISSUE_NO_CITATION = "status {status} has no valid citation"
ISSUE_CONFLICT_CITATIONS = (
    "conflict cites {count} document(s), expected at least {minimum}"
)
ISSUE_NOT_FOUND_CLEARED = "not_found cleared answer and citations"
