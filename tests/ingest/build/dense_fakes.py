"""Deterministic fake embedder and dense-point counter for build tests."""

import math
import zlib
from collections.abc import Callable, Sequence
from pathlib import Path

from qdrant_client import models

from archive.retrieval.qdrant.qdrant_gateway import QdrantGateway

FAKE_DIM = 8
POINT_CAP = 10_000


class FakeEmbedder:
    """Hashes tokens into a small normalised bag-of-words vector.

    `on_batch` runs before each batch (to advance a fake clock);
    `fail_after_batches` makes the next batch raise.
    """

    dim = FAKE_DIM

    def __init__(
        self,
        fail_after_batches: int | None = None,
        on_batch: Callable[[], None] | None = None,
    ) -> None:
        self.fail_after_batches = fail_after_batches
        self.on_batch = on_batch
        self.batch_count = 0

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        if self.on_batch:
            self.on_batch()
        if self.fail_after_batches == self.batch_count:
            raise RuntimeError("embedder down")
        self.batch_count += 1
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        vector = [0.0] * FAKE_DIM
        for token in text.lower().split():
            vector[zlib.crc32(token.encode()) % FAKE_DIM] += 1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]


def dense_point_count(index_dir: Path) -> int:
    """Number of points that carry a dense vector."""
    gateway = QdrantGateway.open_existing(index_dir)
    try:
        hits = gateway.query_hybrid(
            models.SparseVector(indices=[], values=[]),
            FakeEmbedder().embed_query("probe"),
            None,
            POINT_CAP,
            POINT_CAP,
        )
        return len(hits)
    finally:
        gateway.close()


def has_dense(index_dir: Path) -> bool:
    """Whether the collection declares the dense vector."""
    gateway = QdrantGateway.open_existing(index_dir)
    try:
        return gateway.has_dense()
    finally:
        gateway.close()
