from decimal import Decimal

import pytest

from archive.ingest.parse.pdf_parse_gateway import ParsedDoc
from scripts.check_tables import check_invoice, parse_amount


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("31 750,00 $", Decimal("31750.00")),
        ("$17,575.00", Decimal("17575.00")),
        ("1.234,5 $", Decimal("1234.5")),
        ("-$12.50", Decimal("-12.50")),
    ],
)
def test_parse_amount_handles_fr_and_en(text: str, expected: Decimal) -> None:
    assert parse_amount(text) == expected


@pytest.mark.parametrize("text", ["", "n/a", "$"])
def test_parse_amount_without_digits_is_none(text: str) -> None:
    assert parse_amount(text) is None


def _invoice(subtotal: str) -> ParsedDoc:
    page = (
        "Facture no 1\n"
        "Item A | $100.00\n"
        "Item B | $50.50\n"
        "TPS | $7.50\n"
        f"Sous-total : {subtotal}\n"
    )
    return ParsedDoc(doc_id="inv", pages=[page], table_count=1)


def test_invoice_items_summing_to_subtotal_pass() -> None:
    passed, _ = check_invoice(_invoice("$150.50"))
    assert passed


def test_invoice_items_not_matching_subtotal_fail() -> None:
    passed, detail = check_invoice(_invoice("$999.00"))
    assert not passed
    assert "150.50" in detail


def test_invoice_without_subtotal_fails() -> None:
    doc = ParsedDoc(doc_id="x", pages=["Item | $1.00"], table_count=1)
    assert check_invoice(doc) == (False, "no subtotal found")
