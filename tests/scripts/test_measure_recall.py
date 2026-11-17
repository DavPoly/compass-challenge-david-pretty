from pathlib import Path

import pytest

from archive.common.chunk_model import Chunk, ChunkKind
from archive.pipeline.pipeline_constants import EXIT_OK
from archive.retrieval.models import rerank_gateway
from archive.retrieval.search_service import SearchFilters, SearchHit
from scripts import measure_recall
from scripts.measure_recall import (
    GoldQuestion,
    _load_gold,
    _recall_rows,
)


def _hit(doc_id: str) -> SearchHit:
    chunk = Chunk(
        doc_id=doc_id,
        chunk_id=f"{doc_id}#0",
        chunk_kind=ChunkKind.TEXT,
        doc_type="unknown",
        doc_date=None,
        identifiers=[],
        lang="fr",
        text=doc_id,
    )
    return SearchHit(chunk, 1.0)


class FakeSearch:
    def __init__(self, doc_ids: list[str]) -> None:
        self.doc_ids = doc_ids

    def hybrid_search(
        self, query: str, filters: SearchFilters | None, k: int
    ) -> list[SearchHit]:
        return [_hit(doc_id) for doc_id in self.doc_ids[:k]]


def test_recall_is_share_of_gold_docs_retrieved() -> None:
    question = GoldQuestion("q1", "?", frozenset({"a", "b", "c", "d"}))
    search = FakeSearch(["a", "b", "x", "y"])

    rows = _recall_rows([question], search, [1, 4])

    assert rows == [[0.25, 0.5]]


def test_recall_is_zero_when_no_gold_doc_found() -> None:
    question = GoldQuestion("q1", "?", frozenset({"a"}))

    assert _recall_rows([question], FakeSearch(["x"]), [4]) == [[0.0]]


def test_load_gold_skips_rows_without_citations(tmp_path: Path) -> None:
    gold = tmp_path / "gold.jsonl"
    gold.write_text(
        '{"id": "q1", "question": "a?", "citations": ["d1"]}\n'
        "\n"
        '{"id": "q2", "question": "b?", "citations": []}\n'
        '{"id": "q3", "question": "c?"}\n',
        encoding="utf-8",
    )

    questions = _load_gold(gold)

    assert questions == [GoldQuestion("q1", "a?", frozenset({"d1"}))]


def test_load_gold_names_line_of_malformed_row(tmp_path: Path) -> None:
    gold = tmp_path / "gold.jsonl"
    gold.write_text(
        '{"id": "q1", "question": "a?", "citations": ["d1"]}\nnot json\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"gold\.jsonl:2"):
        _load_gold(gold)


def test_load_gold_names_line_of_row_missing_fields(
    tmp_path: Path,
) -> None:
    gold = tmp_path / "gold.jsonl"
    gold.write_text('{"citations": ["d1"]}\n', encoding="utf-8")

    with pytest.raises(ValueError, match=r"gold\.jsonl:1"):
        _load_gold(gold)


def test_load_gold_names_line_of_non_list_citations(
    tmp_path: Path,
) -> None:
    gold = tmp_path / "gold.jsonl"
    gold.write_text(
        '{"id": "q1", "question": "a?", "citations": 5}\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"gold\.jsonl:1"):
        _load_gold(gold)


class FakeSearchContext:
    """A SearchService stand-in: opens, finds nothing."""

    def __enter__(self) -> "FakeSearchContext":
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def hybrid_search(
        self, query: str, filters: SearchFilters | None, k: int
    ) -> list[SearchHit]:
        return []


@pytest.fixture
def opened_models(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[object, object]]:
    """Record the (embedder, reranker) pair given to SearchService.open."""
    opened: list[tuple[object, object]] = []

    def fake_open(
        index_dir: Path,
        embedder: object = None,
        reranker: object = None,
    ) -> FakeSearchContext:
        opened.append((embedder, reranker))
        return FakeSearchContext()

    monkeypatch.setattr(measure_recall.SearchService, "open", fake_open)
    return opened


@pytest.fixture
def gold_file(tmp_path: Path) -> Path:
    path = tmp_path / "gold.jsonl"
    path.write_text(
        '{"id": "q1", "question": "a?", "citations": ["d1"]}\n',
        encoding="utf-8",
    )
    return path


def _forbidden_load(timeout_s: float) -> None:
    raise AssertionError("the model must not be loaded")


def run_measure(gold: Path, tmp_path: Path, *extra: str) -> int:
    return measure_recall.main(
        ["--gold", str(gold), "--index", str(tmp_path / "index"), *extra]
    )


def test_default_run_loads_no_model(
    gold_file: Path,
    tmp_path: Path,
    opened_models: list[tuple[object, object]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(measure_recall, "load_embedder", _forbidden_load)
    monkeypatch.setattr(measure_recall, "load_reranker", _forbidden_load)

    assert run_measure(gold_file, tmp_path) == EXIT_OK
    assert opened_models == [(None, None)]


def test_no_dense_and_no_rerank_flags_load_no_model(
    gold_file: Path,
    tmp_path: Path,
    opened_models: list[tuple[object, object]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(measure_recall, "load_embedder", _forbidden_load)
    monkeypatch.setattr(measure_recall, "load_reranker", _forbidden_load)

    code = run_measure(gold_file, tmp_path, "--no-dense", "--no-rerank")

    assert code == EXIT_OK
    assert opened_models == [(None, None)]


def test_dense_flag_passes_the_loaded_embedder(
    gold_file: Path,
    tmp_path: Path,
    opened_models: list[tuple[object, object]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    embedder = object()
    monkeypatch.setattr(measure_recall, "load_embedder", lambda _: embedder)

    assert run_measure(gold_file, tmp_path, "--dense") == EXIT_OK
    assert opened_models == [(embedder, None)]


def test_missing_dense_model_measures_sparse_only(
    gold_file: Path,
    tmp_path: Path,
    opened_models: list[tuple[object, object]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(measure_recall, "load_embedder", lambda _: None)

    assert run_measure(gold_file, tmp_path, "--dense") == EXIT_OK
    assert opened_models == [(None, None)]
    assert measure_recall.MSG_DENSE_UNAVAILABLE in capsys.readouterr().err


def test_rerank_flag_overrides_the_production_gate(
    gold_file: Path,
    tmp_path: Path,
    opened_models: list[tuple[object, object]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reranker = object()
    gates: list[bool] = []

    def fake_load(timeout_s: float) -> object:
        gates.append(rerank_gateway.RERANK_ENABLED)
        return reranker

    monkeypatch.setattr(rerank_gateway, "RERANK_ENABLED", False)
    monkeypatch.setattr(measure_recall, "load_reranker", fake_load)

    assert run_measure(gold_file, tmp_path, "--rerank") == EXIT_OK
    assert gates == [True]
    assert opened_models == [(None, reranker)]
    assert rerank_gateway.RERANK_ENABLED is False


def test_missing_reranker_measures_without_reranking(
    gold_file: Path,
    tmp_path: Path,
    opened_models: list[tuple[object, object]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(measure_recall, "load_reranker", lambda _: None)

    assert run_measure(gold_file, tmp_path, "--rerank") == EXIT_OK
    assert opened_models == [(None, None)]
    assert measure_recall.MSG_RERANK_UNAVAILABLE in capsys.readouterr().err
