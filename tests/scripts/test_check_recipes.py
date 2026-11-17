from pathlib import Path

from archive.agent.recipes.recipe_model import RecipeResult
from archive.validation.answer_model import AnswerStatus, DraftAnswer
from scripts.check_recipes import (
    GoldRow,
    aggregation_line,
    answers_match,
    compare_ids,
    fallback_line,
    load_gold_rows,
    superseded_line,
)

GOLD = GoldRow("q?", "103500.00", ["doc_1", "doc_2"])


def _result(answer: str, citations: list[str]) -> RecipeResult:
    draft = DraftAnswer(
        answer=answer,
        status=AnswerStatus.ANSWERED,
        citations=citations,
        evidence_sufficient=True,
    )
    return RecipeResult(hits=[], draft=draft)


def test_compare_ids_reports_missing_and_extra() -> None:
    assert compare_ids(["a", "c"], ["a", "b"]) == (["b"], ["c"])


def test_answers_match_compares_numbers() -> None:
    assert answers_match("103500.0", "103500.00")
    assert not answers_match("103500.01", "103500.00")


def test_exact_aggregation_passes() -> None:
    line, is_exact = aggregation_line(
        "s07", GOLD, _result("103500.00", ["doc_2", "doc_1"])
    )

    assert is_exact
    assert "OK" in line


def test_aggregation_with_extra_id_differs() -> None:
    line, is_exact = aggregation_line(
        "s07", GOLD, _result("103500.00", ["doc_1", "doc_2", "doc_9"])
    )

    assert not is_exact
    assert "extra=['doc_9']" in line


def test_aggregation_fallback_is_a_difference() -> None:
    _, is_exact = aggregation_line("s07", GOLD, None)

    assert not is_exact


def test_superseded_without_result_reports_fallback() -> None:
    assert "first_hit=fallback" in superseded_line("s01", GOLD, None)


def test_fallback_line_requires_none() -> None:
    assert fallback_line("s18", None)[1]
    assert not fallback_line("s18", _result("1", []))[1]


def test_load_gold_rows_reads_fields(tmp_path: Path) -> None:
    gold = tmp_path / "gold.jsonl"
    gold.write_text(
        '{"id": "a", "question": "q", "answer": 3, "citations": ["d"]}\n\n',
        encoding="utf-8",
    )

    assert load_gold_rows(gold) == {"a": GoldRow("q", "3", ["d"])}
