"""Tests for the model loader stubs."""

from archive.retrieval.models.embedding_gateway import load_embedder
from archive.retrieval.models.rerank_gateway import load_reranker

LOAD_TIMEOUT_S = 1.0


def test_load_embedder_returns_none() -> None:
    assert load_embedder(LOAD_TIMEOUT_S) is None


def test_load_reranker_returns_none() -> None:
    assert load_reranker(LOAD_TIMEOUT_S) is None
