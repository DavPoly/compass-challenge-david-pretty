"""Split a parsed document into overlapping text chunks."""

import re

from archive.common.chunk_model import Chunk, ChunkKind
from archive.common.constants import (
    CHUNK_ID_SEPARATOR,
    CHUNK_OVERLAP_TOKENS,
    CHUNK_PARAGRAPH_SNAP_TOKENS,
    CHUNK_SINGLE_MAX_TOKENS,
    CHUNK_TARGET_TOKENS,
    PARAGRAPH_BREAK,
    WORD_PATTERN,
)
from archive.common.text.text_normalize_utils import join_pages
from archive.ingest.metadata_service import DocMetadata
from archive.ingest.pdf_parse_gateway import ParsedDoc

_WORD = re.compile(WORD_PATTERN)


def chunk_document(doc: ParsedDoc, metadata: DocMetadata) -> list[Chunk]:
    """Split a document into text chunks carrying its metadata.

    Tokens are approximated by whitespace-separated words. A document of
    at most `CHUNK_SINGLE_MAX_TOKENS` tokens is one chunk. Longer ones
    are cut into windows of about `CHUNK_TARGET_TOKENS` tokens that
    overlap by `CHUNK_OVERLAP_TOKENS`; a window ends at a paragraph break
    when one lies in its last `CHUNK_PARAGRAPH_SNAP_TOKENS` tokens.

    Args:
        doc: Parsed document.
        metadata: Metadata copied onto every chunk.

    Returns:
        Chunks with ids `<doc_id>#<n>` (n from 0); empty when the
        document has no text.
    """
    text = join_pages(doc.pages)
    words = list(_WORD.finditer(text))
    if not words:
        return []
    bounds = _window_bounds(text, words)
    return [
        Chunk(
            doc_id=doc.doc_id,
            chunk_id=f"{doc.doc_id}{CHUNK_ID_SEPARATOR}{index}",
            chunk_kind=ChunkKind.TEXT,
            doc_type=metadata.doc_type,
            doc_date=metadata.doc_date,
            identifiers=list(metadata.identifiers),
            lang=metadata.lang,
            text=text[words[start].start() : words[end - 1].end()],
        )
        for index, (start, end) in enumerate(bounds)
    ]


def _window_bounds(
    text: str, words: list[re.Match[str]]
) -> list[tuple[int, int]]:
    """Return `(first_word, end_word)` index pairs of every chunk."""
    total = len(words)
    if total <= CHUNK_SINGLE_MAX_TOKENS:
        return [(0, total)]
    bounds: list[tuple[int, int]] = []
    start = 0
    while True:
        end = min(start + CHUNK_TARGET_TOKENS, total)
        if end < total:
            end = _snap_to_paragraph(text, words, start, end)
        bounds.append((start, end))
        if end == total:
            return bounds
        start = end - CHUNK_OVERLAP_TOKENS


def _snap_to_paragraph(
    text: str, words: list[re.Match[str]], start: int, end: int
) -> int:
    """Move `end` back to the last paragraph start in the snap zone."""
    lowest = max(start + 1, end - CHUNK_PARAGRAPH_SNAP_TOKENS)
    for index in range(end, lowest - 1, -1):
        gap = text[words[index - 1].end() : words[index].start()]
        if PARAGRAPH_BREAK in gap:
            return index
    return end
