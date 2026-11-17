from pathlib import Path

import pytest

from archive.ingest.pdf_parse_gateway import PdfParseError, parse_pdf


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
