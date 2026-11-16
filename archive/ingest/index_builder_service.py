"""Build the committed index: parse PDFs, chunk, upsert, manifest."""

import hashlib
import json
import logging
import shutil
import time
from collections.abc import Iterator
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

from archive.common.chunk_model import Chunk
from archive.common.constants import (
    BUILD_FLUSH_CHUNKS,
    BUILD_MAP_CHUNKSIZE,
    FILE_HASH_BLOCK_BYTES,
    MANIFEST_FILE_NAME,
    MANIFEST_INDENT,
    PDF_GLOB,
)
from archive.ingest.chunking_service import chunk_document
from archive.ingest.metadata_service import extract_metadata
from archive.ingest.pdf_parse_gateway import PdfParseError, parse_pdf
from archive.retrieval.qdrant_constants import QDRANT_SUBDIR
from archive.retrieval.qdrant_gateway import QdrantGateway

logger = logging.getLogger(__name__)


class ManifestError(Exception):
    """Raised when the index manifest is missing or invalid."""


class ManifestEntry(TypedDict):
    """Size in bytes and SHA-1 of an indexed PDF."""

    size: int
    sha1: str


@dataclass(frozen=True)
class BuildReport:
    """Outcome of an index build."""

    docs: int
    chunks: int
    failed_docs: list[str]
    seconds: float


@dataclass(frozen=True)
class _ParsedFile:
    """Worker result: chunks and manifest entry, or the parse error."""

    doc_id: str
    entry: ManifestEntry | None
    chunks: list[Chunk]
    error: str | None


def build(
    corpus_dir: Path, index_dir: Path, workers: int | None = None
) -> BuildReport:
    """Rebuild the index of every PDF of `corpus_dir` from scratch.

    PDFs are parsed in worker processes; the main process upserts the
    chunks and writes `manifest.json` last. A PDF that cannot be parsed
    is logged, left out of the index and counted in the report. The
    previous `<index_dir>/qdrant` directory is deleted first.

    Args:
        corpus_dir: Directory of `*.pdf` files.
        index_dir: Output directory (`qdrant/` and `manifest.json`).
        workers: Worker processes; None lets the executor decide.

    Returns:
        Counts of documents, chunks and failures, and the duration.
    """
    started = time.monotonic()
    paths = sorted(corpus_dir.glob(PDF_GLOB))
    shutil.rmtree(index_dir / QDRANT_SUBDIR, ignore_errors=True)
    manifest: dict[str, ManifestEntry] = {}
    failed: list[str] = []
    chunk_count = 0
    gateway = QdrantGateway.open(index_dir)
    try:
        gateway.ensure_collection()
        buffer: list[Chunk] = []
        for parsed in _parse_all(paths, workers):
            if parsed.entry is None:
                failed.append(parsed.doc_id)
                logger.warning("skipped %s: %s", parsed.doc_id, parsed.error)
                continue
            manifest[parsed.doc_id] = parsed.entry
            buffer.extend(parsed.chunks)
            chunk_count += len(parsed.chunks)
            if len(buffer) >= BUILD_FLUSH_CHUNKS:
                gateway.upsert(buffer)
                buffer = []
        gateway.upsert(buffer)
    finally:
        gateway.close()
    _write_manifest(index_dir, manifest)
    return BuildReport(
        docs=len(manifest),
        chunks=chunk_count,
        failed_docs=failed,
        seconds=time.monotonic() - started,
    )


def load_manifest(index_dir: Path) -> dict[str, ManifestEntry]:
    """Read `<index_dir>/manifest.json`.

    Raises:
        ManifestError: if the file is missing or not valid JSON.
    """
    path = index_dir / MANIFEST_FILE_NAME
    try:
        content = path.read_text(encoding="utf-8")
        manifest: dict[str, ManifestEntry] = json.loads(content)
    except (OSError, ValueError) as error:
        raise ManifestError(
            f"Cannot read the index manifest {path}: {error}. Build the "
            "index with scripts/build_index.py."
        ) from error
    return manifest


def _write_manifest(
    index_dir: Path, manifest: dict[str, ManifestEntry]
) -> None:
    index_dir.mkdir(parents=True, exist_ok=True)
    (index_dir / MANIFEST_FILE_NAME).write_text(
        json.dumps(manifest, sort_keys=True, indent=MANIFEST_INDENT) + "\n",
        encoding="utf-8",
    )


def _parse_all(
    paths: list[Path], workers: int | None
) -> Iterator[_ParsedFile]:
    with ProcessPoolExecutor(max_workers=workers) as executor:
        yield from executor.map(
            _parse_file, paths, chunksize=BUILD_MAP_CHUNKSIZE
        )


def _parse_file(path: Path) -> _ParsedFile:
    """Worker: parse, extract metadata and chunk one PDF."""
    try:
        doc = parse_pdf(path)
    except PdfParseError as error:
        return _ParsedFile(path.stem, None, [], str(error))
    chunks = chunk_document(doc, extract_metadata(doc))
    return _ParsedFile(path.stem, _file_entry(path), chunks, None)


def _file_entry(path: Path) -> ManifestEntry:
    digest = hashlib.sha1(usedforsecurity=False)
    with path.open("rb") as handle:
        while block := handle.read(FILE_HASH_BLOCK_BYTES):
            digest.update(block)
    return ManifestEntry(size=path.stat().st_size, sha1=digest.hexdigest())
