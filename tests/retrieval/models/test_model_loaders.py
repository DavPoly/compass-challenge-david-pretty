"""Tests for the dense embedder and reranker loaders."""

import logging
import threading
import time
from collections.abc import Iterator, Sequence
from typing import Any

import pytest

from archive.retrieval.models import embedding_gateway, rerank_gateway

LOAD_TIMEOUT_S = 5.0
TINY_TIMEOUT_S = 0.05
MAX_FAST_RETURN_S = 2.0
FAKE_DIM = 3
QUERY_PREFIX = "query: "
PASSAGE_PREFIX = "passage: "
TRUNCATION_LIMIT = 128


class FakeTokenizer:
    def __init__(self) -> None:
        self.max_length: int | None = None

    def enable_truncation(self, max_length: int) -> None:
        self.max_length = max_length


class FakeInnerModel:
    def __init__(self) -> None:
        self.tokenizer = FakeTokenizer()


def make_fake_embedding(
    dim: int, seen: list[str], with_inner: bool = True
) -> type:
    class FakeTextEmbedding:
        def __init__(self, **_kwargs: Any) -> None:
            if with_inner:
                self.model = FakeInnerModel()

        def embed(
            self, texts: Sequence[str], **_kwargs: Any
        ) -> Iterator[list[float]]:
            for text in texts:
                seen.append(text)
                yield [0.5] * dim

    return FakeTextEmbedding


@pytest.fixture
def seen_texts() -> list[str]:
    return []


def test_embedder_applies_prefixes(
    monkeypatch: pytest.MonkeyPatch, seen_texts: list[str]
) -> None:
    monkeypatch.setattr(embedding_gateway, "DENSE_DIM", FAKE_DIM)
    monkeypatch.setattr(embedding_gateway, "DENSE_QUERY_PREFIX", QUERY_PREFIX)
    monkeypatch.setattr(
        embedding_gateway, "DENSE_PASSAGE_PREFIX", PASSAGE_PREFIX
    )
    monkeypatch.setattr(
        embedding_gateway,
        "TextEmbedding",
        make_fake_embedding(FAKE_DIM, seen_texts),
    )

    embedder = embedding_gateway.load_embedder(LOAD_TIMEOUT_S)
    assert embedder is not None
    seen_texts.clear()
    query_vector = embedder.embed_query("hello")
    passage_vectors = embedder.embed_passages(["a", "b"])

    assert embedder.dim == FAKE_DIM
    assert query_vector == [0.5] * FAKE_DIM
    assert passage_vectors == [[0.5] * FAKE_DIM] * 2
    assert seen_texts == ["query: hello", "passage: a", "passage: b"]


def test_embedder_dim_mismatch_returns_none(
    monkeypatch: pytest.MonkeyPatch,
    seen_texts: list[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(embedding_gateway, "DENSE_DIM", FAKE_DIM)
    monkeypatch.setattr(
        embedding_gateway,
        "TextEmbedding",
        make_fake_embedding(FAKE_DIM + 1, seen_texts),
    )

    with caplog.at_level(logging.WARNING):
        embedder = embedding_gateway.load_embedder(LOAD_TIMEOUT_S)

    assert embedder is None
    assert len(caplog.records) == 1


def test_embedder_constructor_error_warns_once(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def failing(**_kwargs: Any) -> None:
        raise OSError("offline and not cached")

    monkeypatch.setattr(embedding_gateway, "TextEmbedding", failing)

    with caplog.at_level(logging.WARNING):
        embedder = embedding_gateway.load_embedder(LOAD_TIMEOUT_S)

    assert embedder is None
    assert len(caplog.records) == 1
    assert "offline and not cached" in caplog.records[0].getMessage()


def test_embedder_timeout_returns_none_quickly(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    release = threading.Event()

    def blocking(**_kwargs: Any) -> None:
        release.wait()

    monkeypatch.setattr(embedding_gateway, "TextEmbedding", blocking)

    try:
        started = time.monotonic()
        with caplog.at_level(logging.WARNING):
            embedder = embedding_gateway.load_embedder(TINY_TIMEOUT_S)
        elapsed = time.monotonic() - started
    finally:
        release.set()

    assert embedder is None
    assert elapsed < MAX_FAST_RETURN_S
    assert len(caplog.records) == 1
    assert embedding_gateway.DENSE_MODEL_NAME in caplog.text


def test_max_tokens_applied_to_tokenizer(
    monkeypatch: pytest.MonkeyPatch, seen_texts: list[str]
) -> None:
    monkeypatch.setattr(embedding_gateway, "DENSE_DIM", FAKE_DIM)
    monkeypatch.setattr(
        embedding_gateway, "DENSE_MAX_TOKENS", TRUNCATION_LIMIT
    )
    fake_class = make_fake_embedding(FAKE_DIM, seen_texts)
    created: list[Any] = []

    def factory(**kwargs: Any) -> Any:
        created.append(fake_class(**kwargs))
        return created[-1]

    monkeypatch.setattr(embedding_gateway, "TextEmbedding", factory)

    assert embedding_gateway.load_embedder(LOAD_TIMEOUT_S) is not None
    assert created[0].model.tokenizer.max_length == TRUNCATION_LIMIT


def test_missing_tokenizer_warns_and_keeps_embedder(
    monkeypatch: pytest.MonkeyPatch,
    seen_texts: list[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(embedding_gateway, "DENSE_DIM", FAKE_DIM)
    monkeypatch.setattr(
        embedding_gateway, "DENSE_MAX_TOKENS", TRUNCATION_LIMIT
    )
    monkeypatch.setattr(
        embedding_gateway,
        "TextEmbedding",
        make_fake_embedding(FAKE_DIM, seen_texts, with_inner=False),
    )

    with caplog.at_level(logging.WARNING):
        embedder = embedding_gateway.load_embedder(LOAD_TIMEOUT_S)

    assert embedder is not None
    assert len(caplog.records) == 1


def test_reranker_disabled_does_not_construct(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(**_kwargs: Any) -> None:
        raise AssertionError("must not construct")

    monkeypatch.setattr(rerank_gateway, "RERANK_ENABLED", False)
    monkeypatch.setattr(rerank_gateway, "TextCrossEncoder", forbidden)

    assert rerank_gateway.load_reranker(LOAD_TIMEOUT_S) is None


def test_reranker_scores_in_input_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeCrossEncoder:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def rerank(self, _query: str, documents: list[str]) -> Iterator[float]:
            for document in documents:
                yield float(len(document))

    monkeypatch.setattr(rerank_gateway, "RERANK_ENABLED", True)
    monkeypatch.setattr(rerank_gateway, "TextCrossEncoder", FakeCrossEncoder)

    reranker = rerank_gateway.load_reranker(LOAD_TIMEOUT_S)

    assert reranker is not None
    assert reranker.score("q", ["a", "abc", "ab"]) == [1.0, 3.0, 2.0]


def test_reranker_constructor_error_returns_none(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def failing(**_kwargs: Any) -> None:
        raise OSError("no model")

    monkeypatch.setattr(rerank_gateway, "RERANK_ENABLED", True)
    monkeypatch.setattr(rerank_gateway, "TextCrossEncoder", failing)

    with caplog.at_level(logging.WARNING):
        reranker = rerank_gateway.load_reranker(LOAD_TIMEOUT_S)

    assert reranker is None
    assert len(caplog.records) == 1
