"""Bring the index up to date with the corpus, touching only changes."""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from archive.common.chunk_model import Chunk
from archive.common.constants import PDF_GLOB
from archive.ingest.build.build_constants import (
    LOG_DENSE_BUDGET_SPENT,
    LOG_DENSE_FAILED,
    LOG_DENSE_INDEX_SPARSE,
    LOG_SYNC_DONE,
    LOG_SYNC_FULL_BUILD,
    LOG_SYNC_SKIPPED,
    REASON_NO_COLLECTION,
    REASON_NO_STORAGE,
    SYNC_DENSE_BUDGET_S,
)
from archive.ingest.build.index_builder_service import (
    build,
    embed_batches,
    parse_all,
)
from archive.ingest.build.manifest_gateway import (
    ManifestEntry,
    ManifestError,
    file_entry,
    load_manifest,
    write_manifest,
)
from archive.ingest.build.version_series_utils import with_effective_to
from archive.retrieval.models.embedding_gateway import EmbeddingPort
from archive.retrieval.qdrant.qdrant_constants import QDRANT_SUBDIR
from archive.retrieval.qdrant.qdrant_gateway import QdrantGateway

logger = logging.getLogger(__name__)
_monotonic: Callable[[], float] = time.monotonic


@dataclass(frozen=True)
class SyncReport:
    """Doc ids touched by a sync, and its duration.

    A changed PDF that fails to parse is listed in both `changed` and
    `failed`: its old points are removed and it stays out of the index
    until it parses.
    """

    added: list[str]
    changed: list[str]
    removed: list[str]
    failed: list[str]
    seconds: float
    sparse_only: int = 0


class _DenseSession:
    """Embeds chunks within the sync budget; counts the overflow."""

    def __init__(self, embedder: EmbeddingPort) -> None:
        self._embedder = embedder
        self._started = _monotonic()
        self._stop: tuple[str, object] | None = None
        self.sparse_only = 0

    def vectors(self, chunks: list[Chunk]) -> list[list[float] | None]:
        """One vector per chunk; None once the budget or embedder fails."""
        vectors: list[list[float] | None] = []
        batches = embed_batches(self._embedder, chunks)
        while self._stop is None and len(vectors) < len(chunks):
            if _monotonic() - self._started >= SYNC_DENSE_BUDGET_S:
                self._stop = (LOG_DENSE_BUDGET_SPENT, SYNC_DENSE_BUDGET_S)
                break
            try:
                vectors.extend(next(batches))
            except Exception as error:  # never fail a sync on embedding
                self._stop = (LOG_DENSE_FAILED, error)
        missing = len(chunks) - len(vectors)
        if missing and self._stop is not None:
            logger.warning(self._stop[0], self._stop[1], missing)
        vectors.extend([None] * missing)
        self.sparse_only += missing
        return vectors


@dataclass(frozen=True)
class _Diff:
    added: list[str]
    changed: list[str]
    removed: list[str]

    @property
    def is_empty(self) -> bool:
        """Whether the index already matches the corpus."""
        return not (self.added or self.changed or self.removed)


def sync_index(
    corpus_dir: Path,
    index_dir: Path,
    workers: int | None = None,
    embedder: EmbeddingPort | None = None,
) -> SyncReport:
    """Update the index so it matches the PDFs of `corpus_dir`.

    The corpus is compared with `manifest.json` by size, then SHA-1.
    Changed and removed documents lose their points; new and changed
    ones are parsed in worker processes and upserted; the
    `effective_to` of every version series is recomputed; the manifest
    is written last. Nothing changed means no Qdrant access. A PDF that
    fails to parse is logged and left out of the manifest, so the next
    sync retries it. Without a usable manifest or collection, a full
    `build` runs instead.

    New and changed chunks get a dense vector only when `embedder` is
    set and the collection has the dense vector, until
    SYNC_DENSE_BUDGET_S is spent; the rest are upserted sparse-only
    and counted. An embedder error never fails the sync.

    Args:
        corpus_dir: Directory of `*.pdf` files.
        index_dir: Index directory (`qdrant/` and `manifest.json`).
        workers: Worker processes; None lets the executor decide.
        embedder: Dense embedder, or None for a sparse-only sync.

    Returns:
        Doc ids per outcome, the sparse-only chunk count and the
        duration.

    Raises:
        IndexBuildError: if a full build cannot clear the old index.
        IndexOpenError: if the Qdrant storage cannot be opened.
        OSError: if the manifest or a PDF cannot be read or written.
    """
    started = time.monotonic()
    paths = {path.stem: path for path in corpus_dir.glob(PDF_GLOB)}
    manifest = _usable_manifest(index_dir)
    if manifest is None:
        return _full_build(corpus_dir, index_dir, (workers, embedder), started)
    diff = _diff(manifest, paths)
    if diff.is_empty:
        return SyncReport([], [], [], [], time.monotonic() - started)
    gateway = _open_collection(index_dir)
    if gateway is None:
        return _full_build(corpus_dir, index_dir, (workers, embedder), started)
    try:
        dense = _dense_session(gateway, embedder)
        stale = [*diff.added, *diff.changed, *diff.removed]
        _drop_stale(gateway, index_dir, stale, manifest, dense)
        todo = [paths[doc_id] for doc_id in [*diff.added, *diff.changed]]
        failed = _ingest(gateway, todo, manifest, (workers, dense))
    finally:
        gateway.close()
    write_manifest(index_dir, manifest)
    sparse_only = dense.sparse_only if dense else 0
    logger.info(
        LOG_SYNC_DONE,
        len(diff.added),
        len(diff.changed),
        len(diff.removed),
        len(failed),
        sparse_only,
    )
    return SyncReport(
        diff.added,
        diff.changed,
        diff.removed,
        failed,
        time.monotonic() - started,
        sparse_only,
    )


def _usable_manifest(index_dir: Path) -> dict[str, ManifestEntry] | None:
    storage = index_dir / QDRANT_SUBDIR
    try:
        manifest = load_manifest(index_dir)
    except ManifestError as error:
        logger.warning(LOG_SYNC_FULL_BUILD, index_dir, error)
        return None
    if not storage.is_dir() or not any(storage.iterdir()):
        logger.warning(LOG_SYNC_FULL_BUILD, index_dir, REASON_NO_STORAGE)
        return None
    return manifest


def _open_collection(index_dir: Path) -> QdrantGateway | None:
    gateway = QdrantGateway.open(index_dir)
    if gateway.has_collection():
        return gateway
    gateway.close()
    logger.warning(LOG_SYNC_FULL_BUILD, index_dir, REASON_NO_COLLECTION)
    return None


def _dense_session(
    gateway: QdrantGateway, embedder: EmbeddingPort | None
) -> _DenseSession | None:
    if embedder is None:
        return None
    if not gateway.has_dense():
        logger.info(LOG_DENSE_INDEX_SPARSE)
        return None
    return _DenseSession(embedder)


def _full_build(
    corpus_dir: Path,
    index_dir: Path,
    options: tuple[int | None, EmbeddingPort | None],
    started: float,
) -> SyncReport:
    workers, embedder = options
    report = build(corpus_dir, index_dir, workers, embedder)
    added = sorted(load_manifest(index_dir))
    return SyncReport(
        added, [], [], report.failed_docs, time.monotonic() - started
    )


def _diff(manifest: dict[str, ManifestEntry], paths: dict[str, Path]) -> _Diff:
    added = sorted(doc_id for doc_id in paths if doc_id not in manifest)
    changed = sorted(
        doc_id
        for doc_id, path in paths.items()
        if doc_id in manifest and _is_modified(path, manifest[doc_id])
    )
    removed = sorted(doc_id for doc_id in manifest if doc_id not in paths)
    return _Diff(added, changed, removed)


def _is_modified(path: Path, entry: ManifestEntry) -> bool:
    if path.stat().st_size != entry["size"]:
        return True
    return file_entry(path)["sha1"] != entry["sha1"]


def _drop_stale(
    gateway: QdrantGateway,
    index_dir: Path,
    stale: list[str],
    manifest: dict[str, ManifestEntry],
    dense: _DenseSession | None = None,
) -> None:
    """Delete docs from the collection and `manifest`, then save it.

    Added docs are included: a crash between an upsert and the
    manifest write leaves points the manifest does not know. The
    series are refreshed before the manifest is saved, so a failure
    leaves the stale docs listed and the next sync redoes the work. The
    manifest is saved before the upserts, so a crash after this point
    leaves those docs to be re-added by the next sync.
    """
    gateway.delete_docs(stale)
    for doc_id in stale:
        manifest.pop(doc_id, None)
    _refresh_series(gateway, dense)
    write_manifest(index_dir, manifest)


def _ingest(
    gateway: QdrantGateway,
    todo: list[Path],
    manifest: dict[str, ManifestEntry],
    options: tuple[int | None, _DenseSession | None],
) -> list[str]:
    """Parse and upsert PDFs, add them to `manifest`; return failures.

    `options` is the worker count and the dense session, if any.
    """
    workers, dense = options
    failed: list[str] = []
    new_chunks: list[Chunk] = []
    for parsed in parse_all(todo, workers):
        if parsed.entry is None:
            failed.append(parsed.doc_id)
            logger.warning(LOG_SYNC_SKIPPED, parsed.doc_id, parsed.error)
            continue
        manifest[parsed.doc_id] = parsed.entry
        new_chunks.extend(parsed.chunks)
    _upsert(gateway, new_chunks, dense)
    _refresh_series(gateway, dense)
    return failed


def _upsert(
    gateway: QdrantGateway,
    chunks: list[Chunk],
    dense: _DenseSession | None,
) -> None:
    gateway.upsert(chunks, dense.vectors(chunks) if dense else None)


def _refresh_series(
    gateway: QdrantGateway, dense: _DenseSession | None = None
) -> None:
    """Recompute `effective_to` over the whole collection's series.

    The upsert replaces whole points, so the changed chunks are
    re-embedded when a dense session is active; otherwise they
    become sparse-only.
    """
    stored = gateway.scroll_series()
    updated = with_effective_to(stored)
    changed = [
        new
        for old, new in zip(stored, updated, strict=True)
        if old.effective_to != new.effective_to
    ]
    _upsert(gateway, changed, dense)
