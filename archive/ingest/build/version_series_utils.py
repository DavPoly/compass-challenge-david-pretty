"""Derive `effective_to` for versioned policy chunks."""

from collections import defaultdict

from archive.common.chunk_model import Chunk


def with_effective_to(chunks: list[Chunk]) -> list[Chunk]:
    """Set `effective_to` on chunks that belong to a version series.

    Chunks with a `series` and an `effective_from` are grouped by
    series. Each gets the next later `effective_from` of its series, or
    None for the latest; versions sharing a date share the same end.
    Other chunks are returned unchanged. The input is not mutated; the
    output keeps the input order.

    Args:
        chunks: Chunks of any documents.

    Returns:
        New list with updated copies of the series chunks.
    """
    starts_by_series: dict[str, set[str]] = defaultdict(set)
    for chunk in chunks:
        if chunk.series is not None and chunk.effective_from is not None:
            starts_by_series[chunk.series].add(chunk.effective_from)
    return [_with_end(chunk, starts_by_series) for chunk in chunks]


def _with_end(chunk: Chunk, starts_by_series: dict[str, set[str]]) -> Chunk:
    if chunk.series is None or chunk.effective_from is None:
        return chunk
    later = [
        start
        for start in starts_by_series[chunk.series]
        if start > chunk.effective_from
    ]
    return chunk.model_copy(
        update={"effective_to": min(later) if later else None}
    )
