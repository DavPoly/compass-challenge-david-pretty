"""Document metadata extraction: identifiers, date and language."""

import re
from dataclasses import dataclass

from archive.common.chunk_model import DocType
from archive.common.text.date_parsing_utils import (
    find_first_date,
    find_month_year,
)
from archive.common.text.text_normalize_utils import (
    join_pages,
    normalize_for_match,
)
from archive.ingest.metadata.doc_type_utils import detect_doc_type
from archive.ingest.metadata.metadata_constants import (
    DATE_HEADER_LINES,
    DATE_LABEL_PATTERN,
    EMAIL_PATTERN,
    IDENTIFIER_DASH_CHARS,
    IDENTIFIER_PATTERN,
    IDENTIFIER_SERIAL_DIGITS,
    LANG_EN,
    LANG_FR,
    LANG_HINTS_EN,
    LANG_HINTS_FR,
    LANG_WORD_PATTERN,
)
from archive.ingest.metadata.version_utils import parse_version
from archive.ingest.parse.pdf_parse_gateway import ParsedDoc

_IDENTIFIER = re.compile(IDENTIFIER_PATTERN)
_EMAIL = re.compile(EMAIL_PATTERN)
_LANG_WORD = re.compile(LANG_WORD_PATTERN)
_DATE_LABEL = re.compile(DATE_LABEL_PATTERN)


@dataclass(frozen=True)
class DocMetadata:
    """Metadata shared by every chunk of a document.

    Attributes:
        doc_type: `DocType` value of the document family.
        doc_date: Document date, ISO `YYYY-MM-DD`, or None.
        identifiers: Canonical codes and emails, sorted and unique.
        lang: "fr" or "en".
        version: Document version label, or None.
        effective_from: ISO date the version takes effect, or None.
        series: Key shared by the versions of one document, or None.
    """

    doc_type: str
    doc_date: str | None
    identifiers: list[str]
    lang: str
    version: str | None = None
    effective_from: str | None = None
    series: str | None = None


def extract_metadata(doc: ParsedDoc) -> DocMetadata:
    """Extract identifiers, first date and language from a document.

    Identifiers are `F-YYYY-NNNN`, `C-YYYY-NN`, `BRV-YYYY-NN` (typo
    variants are canonicalized) and lowercased emails. `doc_date` is the
    date of a labelled header line ("Date :", "Report date:", "En
    vigueur le", "Effective", "Mise à jour :", "Période :"), else the
    earliest full date of the text (see `find_first_date`), else the
    first day of a month-year ("août 2023" gives `2023-08-01`). Policies
    also get version, effective date and series.

    Args:
        doc: Parsed document.

    Returns:
        The metadata; an empty document gives no identifiers, no date
        and language "fr".
    """
    text = join_pages(doc.pages)
    doc_type = detect_doc_type(text)
    info = parse_version(text) if doc_type is DocType.POLICY else None
    return DocMetadata(
        doc_type=doc_type,
        doc_date=_find_doc_date(text),
        identifiers=extract_identifiers(text),
        lang=_detect_lang(text),
        version=info.version if info else None,
        effective_from=info.effective_from if info else None,
        series=info.series if info else None,
    )


def extract_identifiers(text: str) -> list[str]:
    """Return the sorted unique canonical codes and emails of `text`."""
    found = {
        code
        for code in map(_canonical_code, _IDENTIFIER.finditer(text))
        if code
    }
    found.update(match.group().lower() for match in _EMAIL.finditer(text))
    return sorted(found)


def _canonical_code(match: re.Match[str]) -> str | None:
    """Canonical `PREFIX-YYYY-N..` form of a match, or None if invalid."""
    prefix = match.group("prefix")
    is_dash = match.group("sep") in IDENTIFIER_DASH_CHARS
    if prefix != prefix.upper() and not is_dash:
        return None
    prefix = prefix.upper()
    serial = match.group("serial").replace("O", "0")
    if len(serial) != IDENTIFIER_SERIAL_DIGITS[prefix]:
        return None
    year = match.group("year").replace("O", "0")
    return f"{prefix}-{year}-{serial}"


def _find_doc_date(text: str) -> str | None:
    """Labelled header date, else earliest full date, else period."""
    labelled = _find_labelled_date(text)
    if labelled is not None:
        return labelled
    return find_first_date(text) or find_month_year(text)


def _find_labelled_date(text: str) -> str | None:
    """Date after a label ("Date :", "Period:") in the header lines.

    A line gives its full date, or the first day of its month-year.
    """
    lines = normalize_for_match(text).split("\n")
    header = [line for line in lines if line.strip()][:DATE_HEADER_LINES]
    for line in header:
        label = _DATE_LABEL.search(line)
        if label is None:
            continue
        rest = label.group("rest")
        found = find_first_date(rest) or find_month_year(rest)
        if found is not None:
            return found
    return None


def _detect_lang(text: str) -> str:
    """Return "en" if English stopwords outnumber French ones, else "fr"."""
    words = _LANG_WORD.findall(normalize_for_match(text))
    french_hits = sum(word in LANG_HINTS_FR for word in words)
    english_hits = sum(word in LANG_HINTS_EN for word in words)
    return LANG_EN if english_hits > french_hits else LANG_FR
