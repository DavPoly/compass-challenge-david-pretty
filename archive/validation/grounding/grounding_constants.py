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
BARE_AMOUNT_SUFFIX = " $"
WHITESPACE_RE = re.compile(r"\s+")

ISSUE_QUOTE_UNVERIFIED = (
    "quote for {doc_id} not found in its retrieved text: {quote!r}"
)
ISSUE_VALUE_UNGROUNDED = (
    "answer value {value!r} not found in any verified quote or note"
)
ISSUE_NO_EVIDENCE = "status {status} has no evidence quote"
