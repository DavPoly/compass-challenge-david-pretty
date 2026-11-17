"""PDF reading through pdfplumber."""

import logging
from dataclasses import dataclass
from pathlib import Path

import pdfplumber
from pdfplumber.page import Page

from archive.ingest.parse.table_render_utils import (
    merge_by_position,
    render_table,
)

logger = logging.getLogger(__name__)


class PdfParseError(Exception):
    """Raised when a PDF cannot be opened or read."""


@dataclass(frozen=True)
class ParsedDoc:
    """Text of a PDF, one string per page, and its table count."""

    doc_id: str
    pages: list[str]
    table_count: int = 0


def _extract_page(page: Page) -> tuple[str, int]:
    """Return a page's text with tables rendered as rows, and the table
    count. Falls back to plain text if table extraction fails."""
    try:
        tables = page.find_tables()
        if not tables:
            return page.extract_text() or "", 0
        rendered = [(t.bbox[1], render_table(t.extract())) for t in tables]
        remaining = page
        for table in tables:
            remaining = remaining.outside_bbox(table.bbox)
        lines = [
            (line["top"], line["text"])
            for line in remaining.extract_text_lines()
        ]
        return merge_by_position(lines, rendered), len(tables)
    except Exception as error:  # pdfminer/pdfplumber raise many types
        logger.debug("table extraction failed, using plain text: %s", error)
        return page.extract_text() or "", 0


def parse_pdf(path: Path) -> ParsedDoc:
    """Extract the text of every page of a PDF.

    Args:
        path: PDF file; its stem becomes `doc_id`.

    Returns:
        The parsed document; pages without text are empty strings.
        Each detected table is rendered in place as one line per row
        (cells joined by " | ") and counted in `table_count`.

    Raises:
        PdfParseError: if the file is missing or not a readable PDF.
    """
    try:
        with pdfplumber.open(path) as pdf:
            extracted = [_extract_page(page) for page in pdf.pages]
    except Exception as error:  # pdfminer raises many exception types
        raise PdfParseError(
            f"Cannot read PDF {path}: {error}. Check that the file "
            "exists and is not corrupted."
        ) from error
    return ParsedDoc(
        doc_id=path.stem,
        pages=[text for text, _ in extracted],
        table_count=sum(count for _, count in extracted),
    )
