"""Gateway to the cross-encoder reranking model."""

from collections.abc import Sequence
from typing import Protocol


class RerankPort(Protocol):
    """Cross-encoder reranker."""

    def score(self, query: str, texts: Sequence[str]) -> list[float]:
        """Score each text against the query; higher is better."""
        ...


def load_reranker(timeout_s: float) -> RerankPort | None:
    """Load the reranker.

    Args:
        timeout_s: Maximum seconds to wait for the model.

    Returns:
        The reranker, or None when RERANK_ENABLED is False or
        loading fails or times out.
    """
    return None
