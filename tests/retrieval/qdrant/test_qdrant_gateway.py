import logging
from collections.abc import Iterator
from pathlib import Path

import pytest
from qdrant_client import models

from archive.common.chunk_model import Chunk, ChunkKind
from archive.retrieval.qdrant import qdrant_gateway
from archive.retrieval.qdrant.qdrant_constants import SPARSE_VECTOR_NAME
from archive.retrieval.qdrant.qdrant_gateway import (
    IndexOpenError,
    QdrantGateway,
)
from archive.retrieval.qdrant.sparse_encoding_utils import (
    point_id,
    sparse_vector,
    tokenize,
)

CAP = 10
MAX_SCROLL_CALLS = 3


def make_chunk(chunk_id: str, text: str, doc_type: str = "invoice") -> Chunk:
    return Chunk(
        doc_id=chunk_id.split("#", maxsplit=1)[0],
        chunk_id=chunk_id,
        chunk_kind=ChunkKind.TEXT,
        doc_type=doc_type,
        doc_date=None,
        identifiers=[],
        lang="fr",
        text=text,
    )


@pytest.fixture
def gateway(tmp_path: Path) -> Iterator[QdrantGateway]:
    opened = QdrantGateway.open(tmp_path)
    opened.ensure_collection()
    yield opened
    opened.close()


def test_sparse_vector_is_deterministic_and_sorted() -> None:
    text = "Facture F-2023-0042 émise pour Brumeval, facture payée"
    first, second = sparse_vector(text), sparse_vector(text)
    assert first == second
    assert first.indices == sorted(set(first.indices))
    assert len(first.indices) == len(first.values)


def test_tokenize_drops_stopwords_and_folds_accents() -> None:
    assert tokenize("Le prix de la Facture") == ["prix", "facture"]
    assert tokenize("Éléphant") == ["elephant"]


def test_tokenize_keeps_code_whole_and_in_parts() -> None:
    tokens = tokenize("See F-2023-0042.")
    assert "f-2023-0042" in tokens
    assert "0042" in tokens


def test_sparse_vector_counts_term_frequency() -> None:
    vector = sparse_vector("alpha alpha beta")
    assert vector.values[0] != vector.values[1]
    assert max(vector.values) < 2.2


def test_empty_text_gives_empty_vector() -> None:
    vector = sparse_vector("")
    assert vector.indices == []
    assert vector.values == []


def test_upsert_query_and_scroll(gateway: QdrantGateway) -> None:
    gateway.upsert(
        [
            make_chunk("a#0", "budget approuvé BRV-2023-06"),
            make_chunk("b#0", "contrat C-2023-15 signé", "contract"),
            make_chunk("c#0", "réunion de démarrage"),
        ]
    )
    hits = gateway.query_sparse(sparse_vector("BRV-2023-06"), None, 3)
    assert hits[0][0].doc_id == "a"
    contract_filter = models.Filter(
        must=[
            models.FieldCondition(
                key="doc_type", match=models.MatchValue(value="contract")
            )
        ]
    )
    contracts = gateway.scroll(contract_filter, 10)
    assert [chunk.doc_id for chunk in contracts] == ["b"]
    assert len(gateway.scroll(None, 2)) == 2


def test_upsert_same_chunk_id_replaces(gateway: QdrantGateway) -> None:
    gateway.upsert([make_chunk("a#0", "old")])
    gateway.upsert([make_chunk("a#0", "new")])
    chunks = gateway.scroll(None, 10)
    assert [chunk.text for chunk in chunks] == ["new"]


def test_delete_docs_removes_all_chunks_of_those_docs(
    gateway: QdrantGateway,
) -> None:
    gateway.upsert(
        [
            make_chunk("a#0", "one"),
            make_chunk("a#1", "two"),
            make_chunk("b#0", "three"),
            make_chunk("c#0", "four"),
        ]
    )
    gateway.delete_docs({"a", "c", "missing"})
    assert [c.chunk_id for c in gateway.scroll(None, 10)] == ["b#0"]


def test_delete_docs_with_no_ids_is_a_noop(gateway: QdrantGateway) -> None:
    gateway.upsert([make_chunk("a#0", "one")])
    gateway.delete_docs([])
    assert len(gateway.scroll(None, 10)) == 1


def test_scroll_series_returns_only_series_chunks(
    gateway: QdrantGateway,
) -> None:
    versioned = make_chunk("a#0", "policy", "policy")
    versioned.series = "leave"
    gateway.upsert([versioned, make_chunk("b#0", "invoice")])
    assert [c.chunk_id for c in gateway.scroll_series()] == ["a#0"]


def test_scroll_series_warns_when_the_cap_is_reached(
    gateway: QdrantGateway,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    versioned = make_chunk("a#0", "policy", "policy")
    versioned.series = "leave"
    gateway.upsert([versioned])
    monkeypatch.setattr(qdrant_gateway, "SERIES_SCROLL_CAP", 1)
    with caplog.at_level(logging.WARNING):
        gateway.scroll_series()
    assert "chunk cap" in caplog.text


def test_open_locked_index_raises(tmp_path: Path) -> None:
    first = QdrantGateway.open(tmp_path)
    try:
        with pytest.raises(IndexOpenError, match="Close any other process"):
            QdrantGateway.open(tmp_path)
    finally:
        first.close()


def test_open_existing_without_storage_raises_and_creates_nothing(
    tmp_path: Path,
) -> None:
    with pytest.raises(IndexOpenError, match="build_index"):
        QdrantGateway.open_existing(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_open_existing_with_empty_storage_creates_nothing(
    tmp_path: Path,
) -> None:
    storage = tmp_path / "qdrant"
    storage.mkdir()
    with pytest.raises(IndexOpenError, match="build_index"):
        QdrantGateway.open_existing(tmp_path)
    assert list(storage.iterdir()) == []


def test_open_existing_without_collection_raises(tmp_path: Path) -> None:
    QdrantGateway.open(tmp_path).close()
    with pytest.raises(IndexOpenError, match="archive_chunks"):
        QdrantGateway.open_existing(tmp_path)
    QdrantGateway.open(tmp_path).close()


class EmptyPageClient:
    """Scroll always answers an empty page with a non-None offset."""

    def __init__(self) -> None:
        self.calls = 0

    def scroll(self, *_args: object, **_kwargs: object) -> tuple[list, str]:
        self.calls += 1
        assert self.calls <= MAX_SCROLL_CALLS, "scroll did not terminate"
        return [], "next-page"


def test_scroll_stops_on_an_empty_page_with_an_offset() -> None:
    client = EmptyPageClient()
    gateway = QdrantGateway(client)  # type: ignore[arg-type]

    assert gateway.scroll(None, CAP) == []
    assert client.calls == 1


def test_to_point_uses_shared_sparse_encoding() -> None:
    chunk = make_chunk("a#0", "budget approuvé BRV-2023-06")
    point = QdrantGateway._to_point(chunk)
    assert point.id == point_id("a#0")
    assert point.vector == {
        SPARSE_VECTOR_NAME: sparse_vector("budget approuvé BRV-2023-06")
    }
    assert point.payload is not None
    assert point.payload["doc_id"] == "a"


DENSE_DIM = 3
HYBRID_K = 5
PREFETCH_K = 10
ALIGNED = [1.0, 0.0, 0.0]
ORTHOGONAL = [0.0, 1.0, 0.0]
NEARBY = [0.9, 0.1, 0.0]


@pytest.fixture
def dense_gateway(tmp_path: Path) -> Iterator[QdrantGateway]:
    opened = QdrantGateway.open(tmp_path)
    opened.ensure_collection(DENSE_DIM)
    yield opened
    opened.close()


def hybrid_ids(
    gateway: QdrantGateway,
    dense: list[float] | None,
    query_filter: models.Filter | None = None,
) -> list[str]:
    hits = gateway.query_hybrid(
        sparse_vector("alpha beta"),
        dense,
        query_filter,
        HYBRID_K,
        PREFETCH_K,
    )
    return [chunk.doc_id for chunk, _ in hits]


def test_has_dense_reflects_collection_config(
    dense_gateway: QdrantGateway, tmp_path: Path
) -> None:
    assert dense_gateway.has_dense()
    sparse_dir = tmp_path / "sparse"
    sparse_only = QdrantGateway.open(sparse_dir)
    try:
        sparse_only.ensure_collection()
        assert not sparse_only.has_dense()
    finally:
        sparse_only.close()


def test_upsert_dense_length_mismatch_raises(
    dense_gateway: QdrantGateway,
) -> None:
    with pytest.raises(ValueError, match="lengths must match"):
        dense_gateway.upsert([make_chunk("a#0", "alpha")], [])


def test_sparse_only_point_is_found_by_query_hybrid(
    dense_gateway: QdrantGateway,
) -> None:
    dense_gateway.upsert(
        [make_chunk("a#0", "alpha beta"), make_chunk("b#0", "alpha beta")],
        [ALIGNED, None],
    )
    assert set(hybrid_ids(dense_gateway, ALIGNED)) == {"a", "b"}


def test_rrf_ranks_doc_top_on_both_sides_first(
    dense_gateway: QdrantGateway,
) -> None:
    dense_gateway.upsert(
        [
            make_chunk("lexical#0", "alpha"),
            make_chunk("both#0", "alpha beta"),
            make_chunk("semantic#0", "gamma"),
        ],
        [ORTHOGONAL, ALIGNED, NEARBY],
    )
    assert hybrid_ids(dense_gateway, ALIGNED)[0] == "both"


def test_dense_none_matches_sparse_ranking(
    dense_gateway: QdrantGateway,
) -> None:
    dense_gateway.upsert(
        [make_chunk("a#0", "alpha"), make_chunk("b#0", "alpha beta")],
        [ALIGNED, ORTHOGONAL],
    )
    sparse = dense_gateway.query_sparse(
        sparse_vector("alpha beta"), None, HYBRID_K
    )
    assert hybrid_ids(dense_gateway, None) == [c.doc_id for c, _ in sparse]


def test_query_hybrid_applies_filter_to_both_sides(
    dense_gateway: QdrantGateway,
) -> None:
    dense_gateway.upsert(
        [
            make_chunk("a#0", "alpha beta", "invoice"),
            make_chunk("b#0", "alpha beta", "contract"),
        ],
        [ALIGNED, ALIGNED],
    )
    contract_filter = models.Filter(
        must=[
            models.FieldCondition(
                key="doc_type", match=models.MatchValue(value="contract")
            )
        ]
    )
    assert hybrid_ids(dense_gateway, ALIGNED, contract_filter) == ["b"]
