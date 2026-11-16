"""Embedded Qdrant access: sparse (BM25-style) indexing and search."""

import re
import threading
import unicodedata
import uuid
import warnings
import zlib
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from qdrant_client import QdrantClient, models

from archive.common.chunk_model import Chunk
from archive.common.constants import STOPWORDS
from archive.retrieval.qdrant_constants import (
    CODE_PATTERN,
    COLLECTION_NAME,
    HASH_INDEX_MASK,
    KEYWORD_PAYLOAD_FIELDS,
    POINT_ID_NAMESPACE_NAME,
    QDRANT_SUBDIR,
    SCROLL_PAGE_SIZE,
    SPARSE_VECTOR_NAME,
    TF_SATURATION_K1,
    TOKEN_SPLIT_PATTERN,
    UPSERT_BATCH_SIZE,
)

_POINT_ID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, POINT_ID_NAMESPACE_NAME)
_SPLIT = re.compile(TOKEN_SPLIT_PATTERN)
_CODE = re.compile(CODE_PATTERN)


class IndexOpenError(Exception):
    """Raised when the Qdrant index cannot be opened."""


def _fold(text: str) -> str:
    """Lowercase and strip accents."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def tokenize(text: str) -> list[str]:
    """Split text into match tokens.

    Hyphenated codes containing a digit (e.g. `F-2023-0042`) are
    indexed both as one whole token (`f-2023-0042`) and as parts, so
    exact-code queries match strongly and partial ones still match.
    Stopwords and empty tokens are dropped.
    """
    folded = _fold(text)
    tokens = [
        code
        for code in _CODE.findall(folded)
        if any(char.isdigit() for char in code)
    ]
    tokens.extend(_SPLIT.split(folded))
    return [token for token in tokens if token and token not in STOPWORDS]


def _saturate(term_count: int) -> float:
    return (
        term_count * (TF_SATURATION_K1 + 1) / (term_count + TF_SATURATION_K1)
    )


def sparse_vector(text: str) -> models.SparseVector:
    """Hash tokens to sparse indices with saturated term frequencies.

    The hash is `crc32` masked to 31 bits, stable across processes.
    Colliding tokens have their counts summed; indices are sorted.
    Values are `tf * (k1 + 1) / (tf + k1)` (BM25 saturation, no length
    normalization) so a frequent common part cannot outweigh a rare
    whole code.
    """
    counts: Counter[int] = Counter()
    for token in tokenize(text):
        index = zlib.crc32(token.encode("utf-8")) & HASH_INDEX_MASK
        counts[index] += 1
    indices = sorted(counts)
    return models.SparseVector(
        indices=indices, values=[_saturate(counts[i]) for i in indices]
    )


def point_id(chunk_id: str) -> str:
    """Deterministic UUID for a chunk id."""
    return str(uuid.uuid5(_POINT_ID_NAMESPACE, chunk_id))


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
                "Close any other process using it, or rebuild it "
                "with scripts/build_index.py."
            ) from error

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
            if offset is None:
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
