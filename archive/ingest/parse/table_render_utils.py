"""Pure helpers that render extracted tables as text rows."""

from collections.abc import Sequence

from archive.ingest.parse.parse_constants import (
    EMPTY_CELL,
    EOL_CHARS,
    EOL_REPLACEMENT,
    LINE_SEPARATOR,
    TABLE_CELL_SEPARATOR,
)

PositionedText = tuple[float, str]


def clean_cell(cell: str | None) -> str:
    """Return a cell as one stripped line; None becomes empty."""
    if cell is None:
        return EMPTY_CELL
    for eol in EOL_CHARS:
        cell = cell.replace(eol, EOL_REPLACEMENT)
    return cell.strip()


def render_row(cells: Sequence[str | None]) -> str:
    """Join the cells of one table row with the cell separator."""
    return TABLE_CELL_SEPARATOR.join(clean_cell(cell) for cell in cells)


def render_table(rows: Sequence[Sequence[str | None]]) -> str:
    """Render a table as one line per row."""
    return LINE_SEPARATOR.join(render_row(row) for row in rows)


def merge_by_position(
    text_lines: Sequence[PositionedText],
    tables: Sequence[PositionedText],
) -> str:
    """Interleave text lines and rendered tables by vertical position.

    Args:
        text_lines: (top, text) pairs for non-table lines.
        tables: (top, rendered table) pairs.

    Returns:
        All entries joined by newlines, ordered by top (stable: text
        before a table at the same position).
    """
    entries = [(top, 0, text) for top, text in text_lines]
    entries += [(top, 1, text) for top, text in tables]
    entries.sort(key=lambda entry: entry[:2])
    return LINE_SEPARATOR.join(text for _, _, text in entries)
