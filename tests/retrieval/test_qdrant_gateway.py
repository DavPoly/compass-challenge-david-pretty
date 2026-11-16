from collections.abc import Iterator
from pathlib import Path

import pytest
from qdrant_client import models

from archive.common.chunk_model import Chunk, ChunkKind
from archive.retrieval.qdrant_constants import SPARSE_VECTOR_NAME
from archive.retrieval.qdrant_gateway import (
    IndexOpenError,
    QdrantGateway,
)
from archive.retrieval.sparse_encoding_utils import (
    point_id,
    sparse_vector,
    tokenize,
)


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


def test_to_point_uses_shared_sparse_encoding() -> None:
    chunk = make_chunk("a#0", "budget approuvé BRV-2023-06")
    point = QdrantGateway._to_point(chunk)
    assert point.id == point_id("a#0")
    assert point.vector == {
        SPARSE_VECTOR_NAME: sparse_vector("budget approuvé BRV-2023-06")
    }
    assert point.payload is not None
    assert point.payload["doc_id"] == "a"
