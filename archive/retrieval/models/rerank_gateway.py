"""Gateway to the cross-encoder reranking model."""

import logging
from collections.abc import Sequence
from typing import Any, Protocol

from fastembed.rerank.cross_encoder import TextCrossEncoder

from archive.retrieval.models.model_constants import (
    LOG_RERANK_DISABLED,
    MODEL_CACHE_DIR,
    MODEL_THREADS,
    RERANK_ENABLED,
    RERANK_MODEL_NAME,
)
from archive.retrieval.models.model_loading_utils import (
    load_with_timeout,
)

logger = logging.getLogger(__name__)


class RerankPort(Protocol):
    """Cross-encoder reranker."""

    def score(self, query: str, texts: Sequence[str]) -> list[float]:
        """Score each text against the query; higher is better."""
        ...


class FastEmbedReranker:
    """Reranker backed by a fastembed ``TextCrossEncoder``."""

    def __init__(self, model: Any) -> None:
        """Wrap a loaded model (Any: third-party boundary)."""
        self._model = model

    def score(self, query: str, texts: Sequence[str]) -> list[float]:
        """Score each text against the query, in input order."""
        scores = self._model.rerank(query, list(texts))
        return [float(value) for value in scores]


def _build_reranker() -> RerankPort:
    """Construct the cross-encoder."""
    model = TextCrossEncoder(
        model_name=RERANK_MODEL_NAME,
        cache_dir=str(MODEL_CACHE_DIR),
        threads=MODEL_THREADS,
    )
    return FastEmbedReranker(model)


def load_reranker(timeout_s: float) -> RerankPort | None:
    """Load the reranker.

    Args:
        timeout_s: Maximum seconds to wait for the model.

    Returns:
        The reranker, or None when RERANK_ENABLED is False or
        loading fails or times out (after one warning).
    """
    if not RERANK_ENABLED:
        logger.debug(LOG_RERANK_DISABLED)
        return None
    return load_with_timeout(_build_reranker, RERANK_MODEL_NAME, timeout_s)
