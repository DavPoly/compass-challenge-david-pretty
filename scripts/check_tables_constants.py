"""Constants of the table check script."""

import re

from archive.common.chunk_model import DocType

# Docs sampled per family, in file-name order.
FAMILY_QUOTAS: dict[DocType, int] = {
    DocType.INVOICE: 10,
    DocType.MONTHLY_REPORT: 10,
    DocType.PROJECT_SHEET: 5,
    DocType.DIRECTORY: 3,
    DocType.TECHNICAL_NOTE: 2,
}
SUBTOTAL_PATTERN = re.compile(
    r"(?:sub|sous)[-\s]?total\s*:?\s*([^\n]+)", re.IGNORECASE
)
NON_ITEM_LABEL = re.compile(r"total|tps|tvq|gst|qst|tax", re.IGNORECASE)
AMOUNT_CLEANUP = re.compile(r"[^\d,.\-]")
FRENCH_DECIMAL = re.compile(r",\d{1,2}$")
