"""Gateway to the dense embedding model."""

import logging
from collections.abc import Sequence
from typing import Any, Protocol

from fastembed import TextEmbedding

from archive.retrieval.models.model_constants import (
    DENSE_DIM,
    DENSE_EMBED_BATCH_SIZE,
    DENSE_MAX_TOKENS,
    DENSE_MODEL_NAME,
    DENSE_PASSAGE_PREFIX,
    DENSE_QUERY_PREFIX,
    LOG_DIM_MISMATCH,
    LOG_NO_TOKENIZER,
    MODEL_CACHE_DIR,
    MODEL_THREADS,
)
from archive.retrieval.models.model_loading_utils import (
    load_with_timeout,
)

logger = logging.getLogger(__name__)

_PROBE_TEXT = "probe"


class EmbeddingPort(Protocol):
    """Dense text embedder."""

    dim: int

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed passages; one vector of ``dim`` floats per text."""
        ...

    def embed_query(self, text: str) -> list[float]:
        """Embed a query; a vector of ``dim`` floats."""
        ...


class FastEmbedEmbedder:
    """Dense embedder backed by a fastembed ``TextEmbedding``."""

    def __init__(self, model: Any, dim: int) -> None:
        """Wrap a loaded model.

        Args:
            model: A fastembed ``TextEmbedding`` (Any: third-party
                boundary, kept out of the rest of the code).
            dim: Vector dimension produced by the model.
        """
        self._model = model
        self.dim = dim

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed passages with the passage prefix, in input order."""
        prefixed = [DENSE_PASSAGE_PREFIX + text for text in texts]
        vectors = self._model.embed(
            prefixed, batch_size=DENSE_EMBED_BATCH_SIZE
        )
        return [[float(value) for value in vec] for vec in vectors]

    def embed_query(self, text: str) -> list[float]:
        """Embed a query with the query prefix."""
        vectors = self._model.embed([DENSE_QUERY_PREFIX + text])
        return [float(value) for value in next(iter(vectors))]


def _apply_max_tokens(model: Any) -> None:
    """Cap tokenizer truncation at DENSE_MAX_TOKENS, if configured."""
    if DENSE_MAX_TOKENS is None:
        return
    tokenizer = getattr(getattr(model, "model", None), "tokenizer", None)
    if tokenizer is None:
        logger.warning(LOG_NO_TOKENIZER, DENSE_MODEL_NAME)
        return
    tokenizer.enable_truncation(max_length=DENSE_MAX_TOKENS)


def _build_embedder() -> EmbeddingPort | None:
    """Construct the model and check its dimension with a probe."""
    model = TextEmbedding(
        model_name=DENSE_MODEL_NAME,
        cache_dir=str(MODEL_CACHE_DIR),
        threads=MODEL_THREADS,
    )
    _apply_max_tokens(model)
    embedder = FastEmbedEmbedder(model, DENSE_DIM)
    probe_dim = len(embedder.embed_query(_PROBE_TEXT))
    if probe_dim != DENSE_DIM:
        logger.warning(
            LOG_DIM_MISMATCH, DENSE_MODEL_NAME, probe_dim, DENSE_DIM
        )
        return None
    return embedder


def load_embedder(timeout_s: float) -> EmbeddingPort | None:
    """Load the dense embedder.

    Downloads and loads the model in a daemon thread joined with
    ``timeout_s``, caching under MODEL_CACHE_DIR and using
    MODEL_THREADS threads. The vector dimension is checked against
    DENSE_DIM with one probe embedding.

    Args:
        timeout_s: Maximum seconds to wait for the model.

    Returns:
        The embedder, or None (after one warning) when loading
        fails, the dimension differs, or the wait times out.
    """
    return load_with_timeout(_build_embedder, DENSE_MODEL_NAME, timeout_s)
