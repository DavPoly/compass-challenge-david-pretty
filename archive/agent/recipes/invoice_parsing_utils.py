"""Read the fields of an invoice text and match client names."""

import re
from dataclasses import dataclass
from decimal import Decimal
from difflib import SequenceMatcher

from archive.agent.recipes.recipe_constants import (
    CAD_SUFFIX_RE,
    CLIENT_LINE_RE,
    CLIENT_MATCH_RATIO,
    PROJECT_LINE_RE,
    SUBTOTAL_LINE_RE,
    TOTAL_LINE_RE,
)
from archive.common.text.text_normalize_utils import normalize_for_match
from archive.validation.answer_validator import normalize_amount

_CAD_SUFFIX = re.compile(CAD_SUFFIX_RE, re.IGNORECASE)
_CLIENT_LINE = re.compile(CLIENT_LINE_RE, re.IGNORECASE | re.MULTILINE)
_PROJECT_LINE = re.compile(PROJECT_LINE_RE, re.IGNORECASE | re.MULTILINE)
_SUBTOTAL_LINE = re.compile(SUBTOTAL_LINE_RE, re.IGNORECASE | re.MULTILINE)
_TOTAL_LINE = re.compile(TOTAL_LINE_RE, re.IGNORECASE | re.MULTILINE)


@dataclass(frozen=True)
class InvoiceFields:
    """Fields read from an invoice; None when a line is unreadable.

    Attributes:
        client: The billed client.
        project_code: The project the invoice belongs to.
        subtotal: Amount before taxes.
        total: Amount with taxes included.
        subtotal_line: The source line of the subtotal, verbatim.
        total_line: The source line of the total, verbatim.
    """

    client: str | None
    project_code: str | None
    subtotal: Decimal | None
    total: Decimal | None
    subtotal_line: str | None
    total_line: str | None


def _read_amount(
    pattern: re.Pattern[str], text: str
) -> tuple[Decimal | None, str | None]:
    """Return the amount and its source line for the first match."""
    match = pattern.search(text)
    if match is None:
        return None, None
    normalized = normalize_amount(_CAD_SUFFIX.sub("", match["value"]))
    amount = Decimal(normalized) if normalized is not None else None
    return amount, match.group(0).strip()


def _read_value(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    return match["value"] if match else None


def parse_invoice(text: str) -> InvoiceFields:
    """Parse an invoice with French or English labels.

    Amounts go through `normalize_amount`, so "47 375 $" and
    "$10,925.00" both give an exact `Decimal`.
    """
    subtotal, subtotal_line = _read_amount(_SUBTOTAL_LINE, text)
    total, total_line = _read_amount(_TOTAL_LINE, text)
    return InvoiceFields(
        client=_read_value(_CLIENT_LINE, text),
        project_code=_read_value(_PROJECT_LINE, text),
        subtotal=subtotal,
        total=total,
        subtotal_line=subtotal_line,
        total_line=total_line,
    )


def client_matches(candidate: str, wanted: str) -> bool:
    """Whether two client names denote the same client.

    Names are normalized (case, accents, spacing), then compared by
    containment either way or by a `difflib` ratio, since the
    documents carry typos even in their headers.
    """
    left = normalize_for_match(candidate)
    right = normalize_for_match(wanted)
    if not left or not right:
        return False
    if left in right or right in left:
        return True
    return SequenceMatcher(None, left, right).ratio() >= CLIENT_MATCH_RATIO
