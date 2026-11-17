"""Document type detection from the title lines of a document."""

import re
from difflib import SequenceMatcher

from archive.common.chunk_model import DocType
from archive.common.text.text_normalize_utils import normalize_for_match
from archive.ingest.metadata.metadata_constants import (
    DOC_TYPE_HEADER_LINES,
    DOC_TYPE_PHRASES,
    EMAIL_HEADER_PATTERN,
    HEADER_WORD_PATTERN,
    PHRASE_FUZZY_CUTOFF,
    PHRASE_FUZZY_MIN_LENGTH,
)

_HEADER_WORD = re.compile(HEADER_WORD_PATTERN)
_EMAIL_HEADER = re.compile(EMAIL_HEADER_PATTERN)


def detect_doc_type(text: str) -> DocType:
    """Classify a document from the first lines of its header.

    Lines are scanned in order, so the document's own title wins over a
    family only mentioned later (a policy cited in minutes). Matching
    ignores accents and case and tolerates letter typos (``Rapport
    mcnsuel``). A line starting with ``De :`` or ``From:`` is an email.

    Args:
        text: Normalized document text.

    Returns:
        The detected family, `DocType.UNKNOWN` when no title matches.
    """
    lines = normalize_for_match(text).split("\n")
    for line in [line for line in lines if line][:DOC_TYPE_HEADER_LINES]:
        if _EMAIL_HEADER.match(line):
            return DocType.EMAIL
        if (doc_type := _type_of_line(line)) is not None:
            return doc_type
    return DocType.UNKNOWN


def _type_of_line(line: str) -> DocType | None:
    """Family whose title phrase appears in `line`, or None."""
    words = _HEADER_WORD.findall(line)
    for doc_type, phrases in DOC_TYPE_PHRASES.items():
        if any(_contains_phrase(words, phrase) for phrase in phrases):
            return doc_type
    return None


def _contains_phrase(words: list[str], phrase: str) -> bool:
    """Whether `words` hold `phrase`, up to a typo for long phrases."""
    size = len(phrase.split())
    is_fuzzy = len(phrase) >= PHRASE_FUZZY_MIN_LENGTH
    for start in range(len(words) - size + 1):
        window = " ".join(words[start : start + size])
        if window == phrase:
            return True
        if is_fuzzy and _is_close(window, phrase):
            return True
    return False


def _is_close(window: str, phrase: str) -> bool:
    """Whether two strings are similar enough to be the same phrase."""
    matcher = SequenceMatcher(None, window, phrase)
    return matcher.ratio() >= PHRASE_FUZZY_CUTOFF
