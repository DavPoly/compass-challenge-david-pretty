from pathlib import Path

import pdfplumber
import pytest

from archive.validation.answer_model import Evidence
from archive.viewer.page_render_gateway import render_evidence

PDF_PATH = Path(__file__).resolve().parents[2] / "corpus" / "doc_0042.pdf"
MIN_QUOTE_WORDS = 6

pytestmark = pytest.mark.skipif(
    not PDF_PATH.exists(), reason="corpus/doc_0042.pdf is absent"
)


def _first_line_quote() -> str:
    with pdfplumber.open(PDF_PATH) as pdf:
        words = [w["text"] for w in pdf.pages[0].extract_words()]
    return " ".join(words[:MIN_QUOTE_WORDS])


def test_located_quote_writes_crop_and_full_page(tmp_path: Path) -> None:
    evidence = Evidence(doc_id="doc_0042", quote=_first_line_quote())
    result = render_evidence(PDF_PATH, evidence, True, tmp_path / "a" / "q1")
    assert result.is_located
    assert result.page is not None
    assert result.crop_path is not None and result.crop_path.exists()
    assert result.full_path is not None and result.full_path.exists()


def test_unlocated_quote_falls_back_to_first_page(tmp_path: Path) -> None:
    evidence = Evidence(doc_id="doc_0042", quote="zzqx not in this pdf at all")
    result = render_evidence(PDF_PATH, evidence, False, tmp_path / "q2")
    assert not result.is_located
    assert result.page == 1
    assert result.crop_path is None
    assert result.full_path is not None and result.full_path.exists()


def test_missing_pdf_propagates(tmp_path: Path) -> None:
    evidence = Evidence(doc_id="x", quote="anything long enough")
    with pytest.raises(FileNotFoundError):
        render_evidence(tmp_path / "nope.pdf", evidence, True, tmp_path / "q")
