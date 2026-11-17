"""Embedded Qdrant access: sparse and dense indexing and search."""

import logging
import threading
import warnings
from collections.abc import Collection, Sequence
from pathlib import Path

from qdrant_client import QdrantClient, models

from archive.common.chunk_model import Chunk
from archive.retrieval.qdrant.qdrant_constants import (
    BUILD_HINT,
    COLLECTION_NAME,
    DENSE_LENGTH_ERROR,
    DENSE_VECTOR_NAME,
    FIELD_DOC_ID,
    FIELD_SERIES,
    KEYWORD_PAYLOAD_FIELDS,
    LOG_SERIES_CAP_REACHED,
    OPEN_FAILURE_HINT,
    QDRANT_SUBDIR,
    SCROLL_PAGE_SIZE,
    SERIES_SCROLL_CAP,
    SPARSE_VECTOR_NAME,
    UPSERT_BATCH_SIZE,
)
from archive.retrieval.qdrant.sparse_encoding_utils import (
    point_id,
    sparse_vector,
)

logger = logging.getLogger(__name__)


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

    def has_dense(self) -> bool:
        """Whether the collection config has the dense vector."""
        vectors = self._client.get_collection(
            COLLECTION_NAME
        ).config.params.vectors
        return isinstance(vectors, dict) and DENSE_VECTOR_NAME in vectors

    def ensure_collection(self, dense_dim: int | None = None) -> None:
        """Create the collection and payload indexes if absent.

        Args:
            dense_dim: When set, the collection also gets the named
                cosine dense vector of this size.
        """
        with self._write_lock:
            if self._client.collection_exists(COLLECTION_NAME):
                return
            dense_config: dict[str, models.VectorParams] = {}
            if dense_dim is not None:
                dense_config[DENSE_VECTOR_NAME] = models.VectorParams(
                    size=dense_dim, distance=models.Distance.COSINE
                )
            self._client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=dense_config,
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

    def upsert(
        self,
        chunks: Sequence[Chunk],
        dense: Sequence[list[float] | None] | None = None,
    ) -> None:
        """Insert or replace chunks, in batches.

        Args:
            chunks: Chunks to index.
            dense: Optional dense vector per chunk, aligned with
                `chunks`; a None entry indexes that chunk sparse-only.

        Raises:
            ValueError: if `dense` and `chunks` differ in length.
        """
        if dense is not None and len(dense) != len(chunks):
            raise ValueError(DENSE_LENGTH_ERROR % (len(dense), len(chunks)))
        vectors = dense or [None] * len(chunks)
        with self._write_lock:
            for start in range(0, len(chunks), UPSERT_BATCH_SIZE):
                end = start + UPSERT_BATCH_SIZE
                self._client.upsert(
                    COLLECTION_NAME,
                    points=[
                        self._to_point(chunk, vector)
                        for chunk, vector in zip(
                            chunks[start:end],
                            vectors[start:end],
                            strict=True,
                        )
                    ],
                )

    def delete_docs(self, doc_ids: Collection[str]) -> None:
        """Delete every chunk of the given documents; no-op if empty."""
        if not doc_ids:
            return
        with self._write_lock:
            self._client.delete(
                COLLECTION_NAME,
                points_selector=models.FilterSelector(
                    filter=models.Filter(
                        must=[
                            models.FieldCondition(
                                key=FIELD_DOC_ID,
                                match=models.MatchAny(any=list(doc_ids)),
                            )
                        ]
                    )
                ),
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

    def query_hybrid(  # noqa: PLR0913 - frozen interface
        self,
        sparse: models.SparseVector,
        dense: list[float] | None,
        query_filter: models.Filter | None,
        k: int,
        prefetch_k: int,
    ) -> list[tuple[Chunk, float]]:
        """Fuse sparse and dense rankings with RRF, best first.

        Each side prefetches `prefetch_k` filtered candidates. With
        `dense=None` this is `query_sparse`.
        """
        if dense is None:
            return self.query_sparse(sparse, query_filter, k)
        response = self._client.query_points(
            COLLECTION_NAME,
            prefetch=[
                models.Prefetch(
                    query=sparse,
                    using=SPARSE_VECTOR_NAME,
                    filter=query_filter,
                    limit=prefetch_k,
                ),
                models.Prefetch(
                    query=dense,
                    using=DENSE_VECTOR_NAME,
                    filter=query_filter,
                    limit=prefetch_k,
                ),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
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

    def scroll_series(self) -> list[Chunk]:
        """Return every chunk that belongs to a version series."""
        has_series = models.Filter(
            must_not=[
                models.IsNullCondition(
                    is_null=models.PayloadField(key=FIELD_SERIES)
                )
            ]
        )
        chunks = self.scroll(has_series, SERIES_SCROLL_CAP)
        if len(chunks) >= SERIES_SCROLL_CAP:
            logger.warning(LOG_SERIES_CAP_REACHED, SERIES_SCROLL_CAP)
        return chunks

    def close(self) -> None:
        """Release the storage lock."""
        self._client.close()

    @staticmethod
    def _to_point(
        chunk: Chunk, dense: list[float] | None = None
    ) -> models.PointStruct:
        vector: dict[str, models.SparseVector | list[float]] = {
            SPARSE_VECTOR_NAME: sparse_vector(chunk.text)
        }
        if dense is not None:
            vector[DENSE_VECTOR_NAME] = dense
        return models.PointStruct(
            id=point_id(chunk.chunk_id),
            vector=vector,
            payload=chunk.model_dump(mode="json"),
        )
