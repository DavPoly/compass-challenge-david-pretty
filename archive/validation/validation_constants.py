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
    "True when the excerpts are enough to answer or to conclude "
    "conflict, or not_found with no lead. False when they only give "
    "part of the chain (an intermediate fact, not the one asked)."
)
MISSING_FIELD_DESCRIPTION = (
    "The single next fact to look up, naming the entity, e.g. "
    "'email address of Xavier Ricard in the staff directory'."
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
PDF_SUFFIX = ".pdf"

INVISIBLE_SPACE_RE = re.compile(r"[\u00a0\u202f ']")
SEPARATOR_RE = re.compile(r"[,.]")

ISSUE_NORMALIZED = "normalized answer {original!r} to {fixed!r}"
ISSUE_TOO_LONG = "answer has {length} chars, expected under {limit}"
ISSUE_DROPPED = "dropped citations not retrieved: {dropped}"
ISSUE_NO_CITATION = "status {status} has no valid citation"
ISSUE_CONFLICT_CITATIONS = (
    "conflict cites {count} document(s), expected at least {minimum}"
)
ISSUE_NOT_FOUND_CLEARED = "not_found cleared answer and citations"
