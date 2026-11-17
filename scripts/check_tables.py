"""CLI: check table detection on a stable stratified corpus sample.

Picks the first docs (sorted by file name) of each family, prints their
table counts and rendered rows, and checks that invoice table amounts
sum to the printed subtotal.
"""

import argparse
import difflib
import re
import sys
import unicodedata
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pdfplumber

# Allow `python scripts/check_tables.py` from any directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from archive.ingest.parse.parse_constants import (  # noqa: E402
    TABLE_CELL_SEPARATOR,
)
from archive.ingest.parse.pdf_parse_gateway import (  # noqa: E402
    ParsedDoc,
    parse_pdf,
)

# Family name -> (sample size, header keywords).
FAMILIES: dict[str, tuple[int, tuple[str, ...]]] = {
    "invoice": (10, ("invoice", "facture")),
    "monthly_report": (
        10,
        ("rapport mensuel", "monthly progress report"),
    ),
    "project_sheet": (5, ("fiche de projet", "project charter")),
    "staff_directory": (3, ("bottin du personnel", "staff directory")),
    "technical_note": (2, ("note technique", "technical note")),
}
HEADER_LINES = 6
FUZZY_RATIO = 0.86
SUBTOTAL_PATTERN = re.compile(
    r"(?:sub|sous)[-\s]?total\s*:?\s*([^\n]+)", re.IGNORECASE
)
EMAIL_START = re.compile(r"^(from|de)\s*:", re.IGNORECASE)
NON_ITEM_LABEL = re.compile(r"total|tps|tvq|gst|qst|tax", re.IGNORECASE)
AMOUNT_CLEANUP = re.compile(r"[^\d,.\-]")
FRENCH_DECIMAL = re.compile(r",\d{1,2}$")


def _normalize(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in folded if not unicodedata.combining(ch))


def _has_keyword(header: str, keyword: str) -> bool:
    """True if `keyword` appears in `header`, tolerating typos."""
    size = len(keyword)
    for start in range(max(1, len(header) - size + 1)):
        window = header[start : start + size]
        ratio = difflib.SequenceMatcher(None, window, keyword).ratio()
        if ratio >= FUZZY_RATIO:
            return True
    return False


def detect_family(first_page_text: str) -> str | None:
    """Return the family whose keyword is in the page header."""
    if EMAIL_START.match(first_page_text):
        return None
    lines = first_page_text.splitlines()[:HEADER_LINES]
    header = _normalize("\n".join(lines))
    for family, (_, keywords) in FAMILIES.items():
        if any(_has_keyword(header, kw) for kw in keywords):
            return family
    return None


def parse_amount(text: str) -> Decimal | None:
    """Parse "$17,575.00" or "17 575,00 $" into a Decimal."""
    cleaned = AMOUNT_CLEANUP.sub("", text)
    if not any(ch.isdigit() for ch in cleaned):
        return None
    if FRENCH_DECIMAL.search(cleaned):
        cleaned = cleaned.replace(".", "").replace(",", ".")
    else:
        cleaned = cleaned.replace(",", "")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def table_rows(doc: ParsedDoc) -> list[list[str]]:
    """Rendered table rows of a doc, split back into cells."""
    return [
        line.split(TABLE_CELL_SEPARATOR)
        for page in doc.pages
        for line in page.splitlines()
        if TABLE_CELL_SEPARATOR in line
    ]


def check_invoice(doc: ParsedDoc) -> tuple[bool, str]:
    """Check item amounts in table rows sum to the subtotal."""
    match = SUBTOTAL_PATTERN.search("\n".join(doc.pages))
    subtotal = parse_amount(match.group(1)) if match else None
    if subtotal is None:
        return False, "no subtotal found"
    amounts = [
        amount
        for cells in table_rows(doc)
        if not NON_ITEM_LABEL.search(cells[0])
        for amount in [parse_amount(cells[-1])]
        if amount is not None
    ]
    total = sum(amounts, Decimal(0))
    return total == subtotal, f"sum {total} vs subtotal {subtotal}"


def _first_page_text(path: Path) -> str:
    with pdfplumber.open(path) as pdf:
        return (pdf.pages[0].extract_text() or "") if pdf.pages else ""


def select_sample(corpus: Path) -> list[tuple[str, Path]]:
    """Pick the first docs per family, in file-name order."""
    quotas = {name: size for name, (size, _) in FAMILIES.items()}
    sample: list[tuple[str, Path]] = []
    for path in sorted(corpus.glob("*.pdf")):
        if not any(quotas.values()):
            break
        try:
            family = detect_family(_first_page_text(path))
        except Exception as error:  # pdfminer raises many types
            print(f"skip {path.name}: {error}", file=sys.stderr)
            continue
        if family and quotas[family] > 0:
            quotas[family] -= 1
            sample.append((family, path))
    return sample


def _report_doc(family: str, path: Path) -> tuple[int, bool | None]:
    doc = parse_pdf(path)
    print(f"== {path.stem} [{family}] tables={doc.table_count}")
    for cells in table_rows(doc):
        print("   " + TABLE_CELL_SEPARATOR.join(cells))
    if family != "invoice":
        return doc.table_count, None
    passed, detail = check_invoice(doc)
    print(f"   sum check: {'PASS' if passed else 'FAIL'} ({detail})")
    return doc.table_count, passed


def main(argv: list[str] | None = None) -> int:
    """Run the check and print the per-family summary."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    args = parser.parse_args(argv)
    seen: dict[str, list[int]] = {name: [] for name in FAMILIES}
    sum_checks: list[bool] = []
    for family, path in select_sample(args.corpus):
        count, passed = _report_doc(family, path)
        seen[family].append(count)
        if passed is not None:
            sum_checks.append(passed)
    print("\nSUMMARY")
    for family, counts in seen.items():
        hits = sum(1 for count in counts if count > 0)
        print(f"{family}: {hits}/{len(counts)} docs with tables")
    print(f"invoice sum check: {sum(sum_checks)}/{len(sum_checks)} pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
