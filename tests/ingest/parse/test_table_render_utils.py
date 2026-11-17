from archive.ingest.parse.table_render_utils import (
    clean_cell,
    merge_by_position,
    render_row,
    render_table,
)


def test_none_cell_is_empty() -> None:
    assert clean_cell(None) == ""


def test_multiline_cell_becomes_one_line() -> None:
    assert clean_cell(" Line one\nline two \r\n three ") == (
        "Line one line two  three"
    )


def test_row_joins_cells_and_keeps_empty_ones() -> None:
    assert render_row(["Item", None, "$5.00"]) == "Item |  | $5.00"


def test_table_has_one_line_per_row() -> None:
    assert render_table([["a", "b"], ["c", "d"]]) == "a | b\nc | d"


def test_empty_table_renders_empty() -> None:
    assert render_table([]) == ""


def test_merge_orders_by_position() -> None:
    merged = merge_by_position(
        [(10.0, "before"), (90.0, "after")], [(50.0, "a | b")]
    )
    assert merged == "before\na | b\nafter"


def test_merge_without_tables_keeps_text() -> None:
    assert merge_by_position([(1.0, "x"), (2.0, "y")], []) == "x\ny"
