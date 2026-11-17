"""Tests for document type detection."""

import pytest

from archive.common.chunk_model import DocType
from archive.ingest.metadata.doc_type_utils import detect_doc_type

BOILERPLATE = (
    "Brumeval Ingénierie inc. — Document interne\n"
    "CONFIDENTIEL — usage interne seulement\n"
)


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("FACTURE N° F-2023-0042\nDate : 2023-05-01", DocType.INVOICE),
        ("INVOICE No. F-2023-0042", DocType.INVOICE),
        ("CONTRAT DE SOUS-TRAITANCE N° C-2019-26", DocType.CONTRACT),
        ("SUBCONTRACT AGREEMENT No. C-2023-11", DocType.CONTRACT),
        ("Rapport mensuel d'avancement n° 4 — Pont", DocType.MONTHLY_REPORT),
        ("Monthly progress report No. 4 — Bridge", DocType.MONTHLY_REPORT),
        ("Réunion de chantier n° 3", DocType.MINUTES),
        ("Procès-verbal — Réunion de démarrage", DocType.MINUTES),
        ("Site meeting no. 3", DocType.MINUTES),
        ("Minutes — Kick-off meeting", DocType.MINUTES),
        ("Comité de direction — procès-verbal", DocType.MINUTES),
        ("De : Xavier Ricard <x@brumeval.example>", DocType.EMAIL),
        ("From: Lea Frechette <l@brumeval.example>", DocType.EMAIL),
        ("Brumeval Monthly — issue 12", DocType.NEWSLETTER),
        ("NOTE DE SERVICE — Bienvenue", DocType.MEMO),
        ("Memo — Welcome", DocType.MEMO),
        ("Politique de télétravail\nVersion 2", DocType.POLICY),
        ("Mobile Device Policy\nVersion 1", DocType.POLICY),
        ("Bottin du personnel — Brumeval", DocType.DIRECTORY),
        ("Staff directory", DocType.DIRECTORY),
        ("Note technique — Étude géotechnique", DocType.TECHNICAL_NOTE),
        ("Technical note — Geotechnical", DocType.TECHNICAL_NOTE),
        ("Fiche de projet — Bassin", DocType.PROJECT_SHEET),
        ("Project charter — Basin", DocType.PROJECT_SHEET),
    ],
)
def test_each_family_is_recognized(header: str, expected: DocType) -> None:
    assert detect_doc_type(header) is expected


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("Monthy progress report No. 4", DocType.MONTHLY_REPORT),
        ("Rapport mcnsuel d'avancement n° 4", DocType.MONTHLY_REPORT),
        ("Rapport mensuel d'avanccment n° 4", DocType.MONTHLY_REPORT),
        ("Tcchnical note — Geotechnical", DocType.TECHNICAL_NOTE),
        ("Reunion de chantier n° 3", DocType.MINUTES),
        ("BRUEVAL Monthly — issue 3", DocType.NEWSLETTER),
        ("Politiquc de télétravail", DocType.POLICY),
    ],
)
def test_header_typos_and_accents_are_tolerated(
    header: str, expected: DocType
) -> None:
    assert detect_doc_type(header) is expected


def test_boilerplate_lines_before_the_title_are_skipped() -> None:
    text = BOILERPLATE + "Fiche de projet — Bassin de rétention"

    assert detect_doc_type(text) is DocType.PROJECT_SHEET


def test_own_title_wins_over_a_policy_mentioned_later() -> None:
    text = "Réunion de chantier n° 3\nOrdre du jour : politique de sécurité"

    assert detect_doc_type(text) is DocType.MINUTES


def test_email_header_wins_over_an_invoice_in_the_subject() -> None:
    text = "De : A <a@b.example>\nObjet : Re : Facture F-2023-0042"

    assert detect_doc_type(text) is DocType.EMAIL


def test_title_below_the_header_window_is_ignored() -> None:
    filler = "\n".join(f"ligne {number}" for number in range(30))

    assert detect_doc_type(filler + "\nFACTURE N° F-1") is DocType.UNKNOWN


@pytest.mark.parametrize("text", ["", "   \n\n", "Bonjour tout le monde"])
def test_untitled_text_is_unknown(text: str) -> None:
    assert detect_doc_type(text) is DocType.UNKNOWN
