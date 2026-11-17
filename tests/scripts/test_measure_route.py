from pathlib import Path

from scripts.measure_route import (
    expected_family,
    family_accuracy,
    load_gold_types,
)


def test_conflict_maps_to_direct() -> None:
    assert expected_family("conflict") == "direct"
    assert expected_family("multi_hop") == "multi_hop"


def test_unanswerable_has_no_family() -> None:
    assert expected_family("unanswerable") is None


def test_accuracy_skips_unanswerable() -> None:
    pairs = [
        ("direct", "direct"),
        ("conflict", "direct"),
        ("aggregation", "direct"),
        ("unanswerable", "direct"),
    ]

    assert family_accuracy(pairs) == (2, 3)


def test_accuracy_of_nothing_is_zero_of_zero() -> None:
    assert family_accuracy([("unanswerable", "direct")]) == (0, 0)


def test_load_gold_types_reads_id_and_type(tmp_path: Path) -> None:
    gold = tmp_path / "gold.jsonl"
    gold.write_text(
        '{"id": "a1", "type": "direct"}\n\n{"id": "a2", "type": "conflict"}\n',
        encoding="utf-8",
    )

    assert load_gold_types(gold) == {"a1": "direct", "a2": "conflict"}
