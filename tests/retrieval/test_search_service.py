import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from archive.common.chunk_model import Chunk, ChunkKind
from archive.ingest.index_builder_service import ManifestError
from archive.retrieval import search_service
from archive.retrieval.qdrant_gateway import IndexOpenError, QdrantGateway
from archive.retrieval.search_service import (
    SearchFilters,
    SearchHit,
    SearchService,
    find_identifiers,
    to_qdrant_filter,
)

DEFAULT_SAMPLES = "C:/Users/david/Dev/compass-challenge-kit/samples"
SAMPLES_DIR = Path(os.environ.get("ARCHIVE_TEST_SAMPLES", DEFAULT_SAMPLES))
INDEX_DIR = Path(__file__).resolve().parents[2] / "index"
TOP_K = 8
CODE_QUESTION_COUNT = 5


def make_chunk(
    doc_id: str,
    identifiers: list[str],
    doc_type: str,
    doc_date: str | None,
) -> Chunk:
    return Chunk(
        doc_id=doc_id,
        chunk_id=f"{doc_id}#0",
        chunk_kind=ChunkKind.TEXT,
        doc_type=doc_type,
        doc_date=doc_date,
        identifiers=identifiers,
        lang="fr",
        text="facture totale",
    )


CHUNKS = [
    make_chunk("a", ["F-2021-1393"], "invoice", "2021-03-01"),
    make_chunk("b", [], "invoice", "2023-06-01"),
    make_chunk("c", [], "contract", None),
]


@pytest.fixture
def service(tmp_path: Path) -> Iterator[SearchService]:
    gateway = QdrantGateway.open(tmp_path)
    gateway.ensure_collection()
    gateway.upsert(CHUNKS)
    manifest = {chunk.doc_id: {"size": 1, "sha1": "x"} for chunk in CHUNKS}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    opened = SearchService(gateway, tmp_path)
    yield opened
    opened.close()


def doc_ids(hits: list[SearchHit]) -> list[str]:
    return [hit.chunk.doc_id for hit in hits]


def test_no_filters_gives_no_qdrant_filter() -> None:
    assert to_qdrant_filter(None) is None
    assert to_qdrant_filter(SearchFilters()) is None


def test_filters_convert_to_one_condition_each() -> None:
    converted = to_qdrant_filter(
        SearchFilters(["F-1"], ["invoice"], "2023-01-01", "2023-12-31")
    )
    assert converted is not None
    assert converted.must is not None
    assert [c.key for c in converted.must] == [  # type: ignore[union-attr]
        "identifiers",
        "doc_type",
        "doc_date",
    ]


def test_find_identifiers_canonicalizes_query_codes() -> None:
    assert find_identifiers("facture f-2021-1393 ?") == ["F-2021-1393"]


def test_identifier_in_query_restricts_results(
    service: SearchService,
) -> None:
    hits = service.hybrid_search("facture F-2021-1393", None, TOP_K)
    assert doc_ids(hits) == ["a"]


def test_unmatched_identifier_falls_back_to_unfiltered(
    service: SearchService,
) -> None:
    hits = service.hybrid_search("facture F-2099-0001", None, TOP_K)
    assert set(doc_ids(hits)) == {"a", "b", "c"}


def test_fallback_keeps_other_filters(service: SearchService) -> None:
    filters = SearchFilters(doc_types=["contract"])
    hits = service.hybrid_search("totale F-2099-0001", filters, TOP_K)
    assert doc_ids(hits) == ["c"]


def test_date_range_filters_hits(service: SearchService) -> None:
    filters = SearchFilters(date_from="2023-01-01", date_to="2023-12-31")
    hits = service.hybrid_search("facture totale", filters, TOP_K)
    assert doc_ids(hits) == ["b"]


def test_stopword_only_query_returns_nothing(
    service: SearchService,
) -> None:
    assert service.hybrid_search("le de la", None, TOP_K) == []


def test_list_by_filter_respects_cap_and_is_unranked(
    service: SearchService,
) -> None:
    hits = service.list_by_filter(SearchFilters(doc_types=["invoice"]), 1)
    assert len(hits) == 1
    assert hits[0].score == 0.0


def test_known_doc_ids_come_from_manifest(service: SearchService) -> None:
    assert service.known_doc_ids() == {"a", "b", "c"}


def test_open_missing_index_raises_build_hint_and_creates_nothing(
    tmp_path: Path,
) -> None:
    with pytest.raises(IndexOpenError, match="build_index"):
        SearchService.open(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_open_without_manifest_raises_and_releases_lock(
    tmp_path: Path,
) -> None:
    built = QdrantGateway.open(tmp_path)
    built.ensure_collection()
    built.close()
    with pytest.raises(ManifestError):
        SearchService.open(tmp_path)
    QdrantGateway.open(tmp_path).close()


def test_open_closes_gateway_on_keyboard_interrupt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    built = QdrantGateway.open(tmp_path)
    built.ensure_collection()
    built.close()
    closed: list[str] = []
    real_close = QdrantGateway.close

    def spy(gateway: QdrantGateway) -> None:
        closed.append("close")
        real_close(gateway)

    def interrupt(_index_dir: Path) -> frozenset[str]:
        raise KeyboardInterrupt

    monkeypatch.setattr(QdrantGateway, "close", spy)
    monkeypatch.setattr(search_service, "load_manifest", interrupt)
    with pytest.raises(KeyboardInterrupt):
        SearchService.open(tmp_path)
    assert closed == ["close"]


def _code_questions() -> list[tuple[str, set[str]]]:
    questions = SAMPLES_DIR / "questions.jsonl"
    gold = SAMPLES_DIR / "gold.jsonl"
    if not (questions.is_file() and gold.is_file()):
        pytest.skip(f"samples not found at {SAMPLES_DIR}")
    golds = {
        row["id"]: set(row["citations"])
        for row in map(json.loads, gold.read_text("utf-8").splitlines())
    }
    found = []
    for line in questions.read_text("utf-8").splitlines():
        row = json.loads(line)
        if find_identifiers(row["question"]) and golds[row["id"]]:
            found.append((row["question"], golds[row["id"]]))
    return found[:CODE_QUESTION_COUNT]


def test_sample_code_questions_hit_gold_doc_in_top_8() -> None:
    cases = _code_questions()
    if not (INDEX_DIR / "manifest.json").is_file():
        pytest.skip("committed index not built")
    with SearchService.open(INDEX_DIR) as committed:
        for question, gold_docs in cases:
            hits = committed.hybrid_search(question, None, TOP_K)
            assert gold_docs & set(doc_ids(hits)), question
