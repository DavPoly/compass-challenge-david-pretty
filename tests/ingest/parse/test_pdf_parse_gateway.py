from pathlib import Path

import pytest

from archive.ingest.parse.pdf_parse_gateway import (
    PdfParseError,
    _extract_page,
    parse_pdf,
)


def test_parse_real_pdf(kit_corpus_dir: Path) -> None:
    doc = parse_pdf(kit_corpus_dir / "doc_0001.pdf")
    assert doc.doc_id == "doc_0001"
    assert any(page.strip() for page in doc.pages)


def test_unreadable_pdf_raises(tmp_path: Path) -> None:
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"not a pdf")
    with pytest.raises(PdfParseError, match=r"broken\.pdf"):
        parse_pdf(broken)


def test_missing_pdf_raises(tmp_path: Path) -> None:
    with pytest.raises(PdfParseError):
        parse_pdf(tmp_path / "absent.pdf")


class _FakeTable:
    def __init__(self, top: float, rows: list[list[str | None]]) -> None:
        self.bbox = (0.0, top, 100.0, top + 10)
        self._rows = rows

    def extract(self) -> list[list[str | None]]:
        return self._rows


class _FakePage:
    def __init__(
        self,
        tables: list[_FakeTable],
        lines: list[tuple[float, str]],
        fail: bool = False,
    ) -> None:
        self._tables = tables
        self._lines = lines
        self._fail = fail

    def find_tables(self) -> list[_FakeTable]:
        if self._fail:
            raise ValueError("boom")
        return self._tables

    def outside_bbox(self, bbox: tuple[float, ...]) -> "_FakePage":
        kept = [
            (top, text)
            for top, text in self._lines
            if not bbox[1] <= top <= bbox[3]
        ]
        return _FakePage(self._tables, kept)

    def extract_text_lines(self) -> list[dict[str, object]]:
        return [{"top": top, "text": text} for top, text in self._lines]

    def extract_text(self) -> str:
        return "\n".join(text for _, text in self._lines)


def test_page_without_tables_uses_plain_text() -> None:
    page = _FakePage([], [(1.0, "alpha"), (2.0, "beta")])
    assert _extract_page(page) == ("alpha\nbeta", 0)  # type: ignore[arg-type]


def test_table_replaces_its_lines_in_place() -> None:
    table = _FakeTable(20.0, [["Item", "Amt"], ["Fee", None]])
    page = _FakePage(
        [table],
        [(1.0, "head"), (20.0, "Item Amt"), (25.0, "Fee"), (50.0, "foot")],
    )
    text, count = _extract_page(page)  # type: ignore[arg-type]
    assert (text, count) == ("head\nItem | Amt\nFee | \nfoot", 1)


def test_detection_failure_falls_back_to_plain_text() -> None:
    page = _FakePage([], [(1.0, "alpha")], fail=True)
    assert _extract_page(page) == ("alpha", 0)  # type: ignore[arg-type]
