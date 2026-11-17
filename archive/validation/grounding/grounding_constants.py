"""Constants of the grounding check."""

import re

from archive.common.text.date_parsing_constants import (
    DAY_FIRST_DATE_RE,
    DAY_MONTH_NAME_RE,
    ISO_DATE_RE,
    MONTH_NAME_DAY_RE,
)

DATE_SCAN_PATTERNS: tuple[re.Pattern[str], ...] = (
    ISO_DATE_RE,
    DAY_FIRST_DATE_RE,
    DAY_MONTH_NAME_RE,
    MONTH_NAME_DAY_RE,
)
# Lets a bare number such as "12500" parse as a currency amount.
BARE_AMOUNT_SUFFIX = " $"
TRAILING_PUNCTUATION = ".,;:"

# Words that make a following bare integer a label, not an amount.
LABEL_WORDS = (
    "version",
    "v",
    "n°",
    "no",
    "article",
    "section",
    "page",
    "étape",
    "etape",
)
LABEL_BEFORE_RE = re.compile(
    rf"(?:\b|(?<=n°))(?:{'|'.join(re.escape(w) for w in LABEL_WORDS)})"
    r"\.?\s*$",
    re.IGNORECASE,
)
ORDINAL_AFTER_RE = re.compile(r"(?:er|ère|e|ème|st|nd|rd|th)\b", re.IGNORECASE)
BARE_YEAR_RE = re.compile(r"(?:19|20)\d{2}")
BARE_INTEGER_RE = re.compile(r"\d+")
# Document and invoice identifiers such as "doc_2692" or "F-2023-1084".
IDENTIFIER_RE = re.compile(r"\b[a-z]+[_-]\d+(?:[_-]\d+)*\b", re.IGNORECASE)

ISSUE_QUOTE_UNVERIFIED = (
    "quote for {doc_id} not found in its retrieved text: {quote!r}"
)
ISSUE_VALUE_UNGROUNDED = (
    "answer value {value!r} not found in any verified quote or note"
)
ISSUE_NO_EVIDENCE = "status {status} has no evidence quote"
