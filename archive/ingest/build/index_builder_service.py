"""Build the committed index: parse PDFs, chunk, upsert, manifest."""

import logging
import shutil
import time
from collections.abc import Iterator, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from archive.common.chunk_model import Chunk
from archive.common.constants import PDF_GLOB
from archive.ingest.build.build_constants import (
    BUILD_FLUSH_CHUNKS,
    BUILD_MAP_CHUNKSIZE,
    DENSE_BATCH_SIZE,
    DENSE_LOG_EVERY_BATCHES,
    LOG_DENSE_PROGRESS,
    MANIFEST_FILE_NAME,
)
from archive.ingest.build.manifest_gateway import (
    ManifestEntry,
    file_entry,
    write_manifest,
)
from archive.ingest.build.version_series_utils import with_effective_to
from archive.ingest.chunking_service import chunk_document
from archive.ingest.metadata.metadata_service import extract_metadata
from archive.ingest.parse.pdf_parse_gateway import (
    PdfParseError,
    parse_pdf,
)
from archive.retrieval.models.embedding_gateway import EmbeddingPort
from archive.retrieval.qdrant.qdrant_constants import QDRANT_SUBDIR
from archive.retrieval.qdrant.qdrant_gateway import QdrantGateway

logger = logging.getLogger(__name__)


class IndexBuildError(Exception):
    """Raised when the previous index cannot be cleared for a rebuild."""


@dataclass(frozen=True)
class BuildReport:
    """Outcome of an index build."""

    docs: int
    chunks: int
    failed_docs: list[str]
    seconds: float
    dense_chunks: int = 0


@dataclass(frozen=True)
class ParsedFile:
    """Worker result: chunks and manifest entry, or the parse error."""

    doc_id: str
    entry: ManifestEntry | None
    chunks: list[Chunk]
    error: str | None


def build(
    corpus_dir: Path,
    index_dir: Path,
    workers: int | None = None,
    embedder: EmbeddingPort | None = None,
) -> BuildReport:
    """Rebuild the index of every PDF of `corpus_dir` from scratch.

    PDFs are parsed in worker processes; the main process upserts the
    chunks and writes `manifest.json` last. A PDF that cannot be parsed
    is logged, left out of the index and counted in the report. The
    previous manifest and `<index_dir>/qdrant` directory are deleted
    first, so an aborted build leaves no manifest. Any other exception
    in a worker is also logged and counted as a failure.

    Args:
        corpus_dir: Directory of `*.pdf` files.
        index_dir: Output directory (`qdrant/` and `manifest.json`).
        workers: Worker processes; None lets the executor decide.
        embedder: When set, every chunk also gets a dense vector (no
            time budget); otherwise the index is sparse-only.

    Returns:
        Counts of documents, chunks and failures, and the duration.

    Raises:
        IndexBuildError: if the previous index cannot be deleted.
    """
    started = time.monotonic()
    paths = sorted(corpus_dir.glob(PDF_GLOB))
    _clear_previous_index(index_dir)
    manifest: dict[str, ManifestEntry] = {}
    failed: list[str] = []
    chunk_count = 0
    dense_count = 0
    gateway = QdrantGateway.open(index_dir)
    try:
        gateway.ensure_collection(embedder.dim if embedder else None)
        buffer: list[Chunk] = []
        series_chunks: list[Chunk] = []
        for parsed in parse_all(paths, workers):
            if parsed.entry is None:
                failed.append(parsed.doc_id)
                logger.warning("skipped %s: %s", parsed.doc_id, parsed.error)
                continue
            manifest[parsed.doc_id] = parsed.entry
            for chunk in parsed.chunks:
                is_series = chunk.series is not None
                (series_chunks if is_series else buffer).append(chunk)
            chunk_count += len(parsed.chunks)
            if len(buffer) >= BUILD_FLUSH_CHUNKS:
                dense_count += _upsert(gateway, buffer, embedder)
                buffer = []
        dense_count += _upsert(gateway, buffer, embedder)
        series_chunks = with_effective_to(series_chunks)
        dense_count += _upsert(gateway, series_chunks, embedder)
    finally:
        gateway.close()
    write_manifest(index_dir, manifest)
    return BuildReport(
        docs=len(manifest),
        chunks=chunk_count,
        failed_docs=failed,
        seconds=time.monotonic() - started,
        dense_chunks=dense_count,
    )


def _upsert(
    gateway: QdrantGateway,
    chunks: list[Chunk],
    embedder: EmbeddingPort | None,
) -> int:
    """Upsert chunks, with dense vectors when embedding; return count."""
    if embedder is None:
        gateway.upsert(chunks)
        return 0
    vectors = [
        vector for batch in embed_batches(embedder, chunks) for vector in batch
    ]
    gateway.upsert(chunks, vectors)
    return len(vectors)


def embed_batches(
    embedder: EmbeddingPort, chunks: Sequence[Chunk]
) -> Iterator[list[list[float]]]:
    """Lazily embed chunk texts, yielding one list of vectors per batch.

    Progress is logged every DENSE_LOG_EVERY_BATCHES batches. An
    embedder error propagates to the caller.
    """
    for batch_index, start in enumerate(
        range(0, len(chunks), DENSE_BATCH_SIZE), start=1
    ):
        texts = [c.text for c in chunks[start : start + DENSE_BATCH_SIZE]]
        yield embedder.embed_passages(texts)
        if batch_index % DENSE_LOG_EVERY_BATCHES == 0:
            logger.info(LOG_DENSE_PROGRESS, start + len(texts))


def _clear_previous_index(index_dir: Path) -> None:
    storage = index_dir / QDRANT_SUBDIR
    try:
        (index_dir / MANIFEST_FILE_NAME).unlink(missing_ok=True)
        shutil.rmtree(storage, ignore_errors=False)
    except FileNotFoundError:
        return
    except OSError as error:
        raise IndexBuildError(
            f"Cannot delete the previous index at {storage}: {error}. "
            "Close any process using it and retry."
        ) from error


def parse_all(paths: list[Path], workers: int | None) -> Iterator[ParsedFile]:
    """Parse PDFs in worker processes, yielding results in path order."""
    if not paths:
        return
    with ProcessPoolExecutor(max_workers=workers) as executor:
        yield from executor.map(
            parse_file, paths, chunksize=BUILD_MAP_CHUNKSIZE
        )


def parse_file(path: Path) -> ParsedFile:
    """Worker: parse, extract metadata and chunk one PDF."""
    try:
        doc = parse_pdf(path)
        chunks = chunk_document(doc, extract_metadata(doc))
    except PdfParseError as error:
        return ParsedFile(path.stem, None, [], str(error))
    except Exception as error:  # any worker failure must not abort the build
        message = f"{type(error).__name__}: {error}"
        return ParsedFile(path.stem, None, [], message)
    return ParsedFile(path.stem, file_entry(path), chunks, None)
