"""Schema checks for the paraphrase / cross-lingual gold set.

The set has to stay loadable by `measure_recall`, which reads ``id``,
``question`` and ``citations``; a row without citations is skipped.
"""

import json
from pathlib import Path

import pytest

from scripts.measure_recall import _load_gold

GOLD_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "data"
    / "paraphrase_gold.jsonl"
)
REQUIRED_FIELDS = frozenset({"id", "question", "citations"})
MIN_ENTRIES = 15


def _rows() -> list[dict[str, object]]:
    lines = GOLD_PATH.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


@pytest.fixture(scope="module")
def rows() -> list[dict[str, object]]:
    return _rows()


def test_file_is_lf_jsonl_without_bom() -> None:
    raw = GOLD_PATH.read_bytes()

    assert not raw.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" not in raw


def test_set_holds_the_expected_number_of_entries(
    rows: list[dict[str, object]],
) -> None:
    assert len(rows) >= MIN_ENTRIES


def test_every_row_holds_the_required_fields(
    rows: list[dict[str, object]],
) -> None:
    for row in rows:
        assert set(row) >= REQUIRED_FIELDS
        for field in ("id", "question"):
            assert isinstance(row[field], str)
            assert row[field]
        assert isinstance(row["citations"], list)


def test_every_citation_is_a_non_empty_doc_id(
    rows: list[dict[str, object]],
) -> None:
    for row in rows:
        citations = row["citations"]
        assert isinstance(citations, list)
        assert citations
        assert all(
            isinstance(citation, str) and citation for citation in citations
        )


def test_ids_are_unique(rows: list[dict[str, object]]) -> None:
    ids = [row["id"] for row in rows]

    assert len(ids) == len(set(ids))


def test_measure_recall_reads_every_row() -> None:
    questions = _load_gold(GOLD_PATH)

    assert len(questions) == len(_rows())
