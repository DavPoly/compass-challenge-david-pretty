"""Embedded Qdrant access: sparse (BM25-style) indexing and search."""

import threading
import warnings
from collections.abc import Sequence
from pathlib import Path

from qdrant_client import QdrantClient, models

from archive.common.chunk_model import Chunk
from archive.retrieval.qdrant_constants import (
    BUILD_HINT,
    COLLECTION_NAME,
    KEYWORD_PAYLOAD_FIELDS,
    OPEN_FAILURE_HINT,
    QDRANT_SUBDIR,
    SCROLL_PAGE_SIZE,
    SPARSE_VECTOR_NAME,
    UPSERT_BATCH_SIZE,
)
from archive.retrieval.sparse_encoding_utils import point_id, sparse_vector


class IndexOpenError(Exception):
    """Raised when the Qdrant index cannot be opened."""


class QdrantGateway:
    """One shared embedded Qdrant client with a write lock."""

    def __init__(self, client: QdrantClient) -> None:
        self._client = client
        self._write_lock = threading.Lock()

    @classmethod
    def open(cls, index_dir: Path) -> "QdrantGateway":
        """Open (or create) the embedded index under `index_dir`.

        Raises:
            IndexOpenError: if the storage is locked or unusable.
        """
        path = index_dir / QDRANT_SUBDIR
        try:
            return cls(QdrantClient(path=str(path)))
        except (RuntimeError, OSError) as error:
            raise IndexOpenError(
                f"Cannot open the Qdrant index at {path}: {error}. "
                f"{OPEN_FAILURE_HINT}"
            ) from error

    @classmethod
    def open_existing(cls, index_dir: Path) -> "QdrantGateway":
        """Open a built index; never creates storage.

        Raises:
            IndexOpenError: if the storage is missing, empty, locked,
                or holds no chunk collection.
        """
        path = index_dir / QDRANT_SUBDIR
        if not path.is_dir() or not any(path.iterdir()):
            raise IndexOpenError(
                f"No Qdrant index found at {path}. {BUILD_HINT}"
            )
        gateway = cls.open(index_dir)
        if not gateway.has_collection():
            gateway.close()
            raise IndexOpenError(
                f"The Qdrant index at {path} has no "
                f"'{COLLECTION_NAME}' collection. {BUILD_HINT}"
            )
        return gateway

    def has_collection(self) -> bool:
        """Whether the chunk collection exists."""
        return self._client.collection_exists(COLLECTION_NAME)

    def ensure_collection(self) -> None:
        """Create the sparse collection and payload indexes if absent."""
        with self._write_lock:
            if self._client.collection_exists(COLLECTION_NAME):
                return
            self._client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config={},
                sparse_vectors_config={
                    SPARSE_VECTOR_NAME: models.SparseVectorParams(
                        modifier=models.Modifier.IDF
                    )
                },
            )
            with warnings.catch_warnings():
                # Local mode ignores payload indexes (it warns); they
                # take effect if the index moves to a Qdrant server.
                warnings.simplefilter("ignore", UserWarning)
                for field in KEYWORD_PAYLOAD_FIELDS:
                    self._client.create_payload_index(
                        COLLECTION_NAME,
                        field,
                        models.PayloadSchemaType.KEYWORD,
                    )

    def upsert(self, chunks: Sequence[Chunk]) -> None:
        """Insert or replace chunks, in batches."""
        with self._write_lock:
            for start in range(0, len(chunks), UPSERT_BATCH_SIZE):
                batch = chunks[start : start + UPSERT_BATCH_SIZE]
                self._client.upsert(
                    COLLECTION_NAME,
                    points=[self._to_point(chunk) for chunk in batch],
                )

    def query_sparse(
        self,
        vector: models.SparseVector,
        query_filter: models.Filter | None,
        k: int,
    ) -> list[tuple[Chunk, float]]:
        """Return the top `k` chunks by sparse score, best first."""
        response = self._client.query_points(
            COLLECTION_NAME,
            query=vector,
            using=SPARSE_VECTOR_NAME,
            query_filter=query_filter,
            limit=k,
            with_payload=True,
        )
        return [
            (Chunk.model_validate(point.payload), point.score)
            for point in response.points
        ]

    def scroll(
        self, query_filter: models.Filter | None, cap: int
    ) -> list[Chunk]:
        """Return up to `cap` chunks matching the filter, unranked."""
        chunks: list[Chunk] = []
        offset: models.ExtendedPointId | None = None
        while len(chunks) < cap:
            points, offset = self._client.scroll(
                COLLECTION_NAME,
                scroll_filter=query_filter,
                limit=min(SCROLL_PAGE_SIZE, cap - len(chunks)),
                offset=offset,
                with_payload=True,
            )
            chunks.extend(Chunk.model_validate(p.payload) for p in points)
            if not points or offset is None:
                break
        return chunks

    def close(self) -> None:
        """Release the storage lock."""
        self._client.close()

    @staticmethod
    def _to_point(chunk: Chunk) -> models.PointStruct:
        return models.PointStruct(
            id=point_id(chunk.chunk_id),
            vector={SPARSE_VECTOR_NAME: sparse_vector(chunk.text)},
            payload=chunk.model_dump(mode="json"),
        )
