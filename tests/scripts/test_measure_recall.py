from pathlib import Path

import pytest

from archive.common.chunk_model import Chunk, ChunkKind
from archive.retrieval.search_service import SearchFilters, SearchHit
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
