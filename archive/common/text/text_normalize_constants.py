"""Unicode forms, patterns and separators used to normalize text."""

from typing import Final

UNICODE_COMPAT_FORM: Final = "NFKC"
UNICODE_DECOMPOSED_FORM: Final = "NFKD"
HORIZONTAL_SPACE_PATTERN = r"[ \t\f\v]+"
BLANK_LINES_PATTERN = r"\n{3,}"
PAGE_SEPARATOR = "\n\n"
