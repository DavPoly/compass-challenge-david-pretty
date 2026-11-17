from decimal import Decimal

import pytest

from archive.agent.recipes.invoice_parsing_utils import (
    client_matches,
    parse_invoice,
)

FRENCH_INVOICE = (
    "FACTURE N° F-2021-1770\n"
    "Date : 22 novembre 2021\n"
    "Facturé à : Ville de Cap-Pervenche\n"
    "Projet : BRV-2021-03\n"
    "Description | Montant\n"
    "Rapport technique | 47 375 $\n"
    "Sous-total : 47 375 $\n"
    "TPS (5 %) : 2 368,75 $\n"
    "TOTAL : 54 469,41 $\n"
)
ENGLISH_INVOICE = (
    "INVOICE No. F-2024-1187\n"
    "Bill to: Wrenfield Properties Ltd.\n"
    "Project: BRV-2022-24\n"
    "Subtotal: $10,925.00\n"
    "GST (5%): $546.25\n"
    "TOTAL: $12,561.02\n"
)


def test_parses_french_invoice_with_nbsp_amounts() -> None:
    fields = parse_invoice(FRENCH_INVOICE)

    assert fields.client == "Ville de Cap-Pervenche"
    assert fields.project_code == "BRV-2021-03"
    assert fields.subtotal == Decimal("47375.00")
    assert fields.total == Decimal("54469.41")
    assert fields.subtotal_line == "Sous-total : 47 375 $"
    assert fields.total_line == "TOTAL : 54 469,41 $"


def test_parses_english_invoice() -> None:
    fields = parse_invoice(ENGLISH_INVOICE)

    assert fields.client == "Wrenfield Properties Ltd."
    assert fields.project_code == "BRV-2022-24"
    assert fields.subtotal == Decimal("10925.00")
    assert fields.total == Decimal("12561.02")


def test_parses_cad_prefix_and_suffix() -> None:
    suffix = parse_invoice("Sous-total : 48 975,00 $ CAD\nTOTAL : 1 $ CAD")
    prefix = parse_invoice("Subtotal: CAD 30,850.00\nTOTAL: CAD 35,469.79")

    assert suffix.subtotal == Decimal("48975.00")
    assert prefix.subtotal == Decimal("30850.00")
    assert prefix.total == Decimal("35469.79")


def test_tolerates_typos_in_the_subtotal_label() -> None:
    fields = parse_invoice("Sous-totaal : 23 550,00 $\nTOTAL : 27 076,61 $")

    assert fields.subtotal == Decimal("23550.00")
    assert fields.total == Decimal("27076.61")


def test_unreadable_amount_stays_none() -> None:
    fields = parse_invoice("Sous-total : n/a\nTOTAL : 10 $")

    assert fields.subtotal is None
    assert fields.subtotal_line == "Sous-total : n/a"
    assert fields.total == Decimal("10.00")


def test_text_without_invoice_lines_has_no_fields() -> None:
    fields = parse_invoice("Just a memo")

    assert fields.client is None
    assert fields.subtotal is None
    assert fields.total is None


@pytest.mark.parametrize(
    ("candidate", "wanted"),
    [
        ("Grayheron Logistics Ltd.", "grayheron logistics ltd"),
        ("Grayheron Logistics Ltd.", "Grayheron Logistics"),
        ("Société de transport", "Societe de transport"),
        ("Grayheron Logistcs Ltd.", "Grayheron Logistics Ltd."),
    ],
)
def test_client_matches_variants(candidate: str, wanted: str) -> None:
    assert client_matches(candidate, wanted)


@pytest.mark.parametrize(
    ("candidate", "wanted"),
    [
        ("Ville de Val-Mélusine", "Ville de Cap-Pervenche"),
        ("Wrenfield Properties Ltd.", "Marshvale Logistics Ltd."),
        ("", "Wrenfield"),
    ],
)
def test_client_matches_rejects_other_clients(
    candidate: str, wanted: str
) -> None:
    assert not client_matches(candidate, wanted)
