"""PDF reading through pdfplumber."""

from dataclasses import dataclass
from pathlib import Path

import pdfplumber


class PdfParseError(Exception):
    """Raised when a PDF cannot be opened or read."""


@dataclass(frozen=True)
class ParsedDoc:
    """Text of a PDF, one string per page."""

    doc_id: str
    pages: list[str]


def parse_pdf(path: Path) -> ParsedDoc:
    """Extract the text of every page of a PDF.

    Args:
        path: PDF file; its stem becomes `doc_id`.

    Returns:
        The parsed document; pages without text are empty strings.

    Raises:
        PdfParseError: if the file is missing or not a readable PDF.
    """
    try:
        with pdfplumber.open(path) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
    except Exception as error:  # pdfminer raises many exception types
        raise PdfParseError(
            f"Cannot read PDF {path}: {error}. Check that the file "
            "exists and is not corrupted."
        ) from error
    return ParsedDoc(doc_id=path.stem, pages=pages)
