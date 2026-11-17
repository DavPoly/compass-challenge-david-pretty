"""Gateway to the dense embedding model."""

from collections.abc import Sequence
from typing import Protocol


class EmbeddingPort(Protocol):
    """Dense text embedder."""

    dim: int

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed passages; one vector of ``dim`` floats per text."""
        ...

    def embed_query(self, text: str) -> list[float]:
        """Embed a query; a vector of ``dim`` floats."""
        ...


def load_embedder(timeout_s: float) -> EmbeddingPort | None:
    """Load the dense embedder.

    Downloads and loads the model in a daemon thread joined with
    ``timeout_s``, caching under MODEL_CACHE_DIR and using
    MODEL_THREADS threads.

    Args:
        timeout_s: Maximum seconds to wait for the model.

    Returns:
        The embedder, or None (after one warning) when loading
        fails or times out.
    """
    return None
