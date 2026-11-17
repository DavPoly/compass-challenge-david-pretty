"""Unicode forms, patterns and separators used to normalize text."""

import re
from typing import Final

UNICODE_COMPAT_FORM: Final = "NFKC"
UNICODE_DECOMPOSED_FORM: Final = "NFKD"
HORIZONTAL_SPACE_PATTERN = r"[ \t\f\v]+"
BLANK_LINES_PATTERN = r"\n{3,}"
PAGE_SEPARATOR = "\n\n"

PUNCTUATION_FOLD = str.maketrans(
    {
        "’": "'",
        "‘": "'",
        "ʼ": "'",
        "«": '"',
        "»": '"',
        "“": '"',
        "”": '"',
        "„": '"',
        "–": "-",
        "—": "-",
    }
)
WHITESPACE_RE = re.compile(r"\s+")
# Marks where a quote elides text: "...", the ellipsis character, "[...]".
ELLIPSIS_RE = re.compile(r"\[\s*(?:\.{3}|…)\s*\]|\.{3,}|…")
# Quote pieces shorter than this are ignored beside a longer piece.
MIN_QUOTE_PIECE_LENGTH = 8
