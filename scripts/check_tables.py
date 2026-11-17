"""CLI: check table detection on a stable stratified corpus sample.

Picks the first docs (sorted by file name) of each family, prints their
table counts and rendered rows, and checks that invoice table amounts
sum to the printed subtotal.
"""

import argparse
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pdfplumber
from pdfminer.psexceptions import PSException

# Allow `python scripts/check_tables.py` from any directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from archive.common.chunk_model import DocType  # noqa: E402
from archive.ingest.metadata.doc_type_utils import (  # noqa: E402
    detect_doc_type,
)
from archive.ingest.parse.parse_constants import (  # noqa: E402
    TABLE_CELL_SEPARATOR,
)
from archive.ingest.parse.pdf_parse_gateway import (  # noqa: E402
    ParsedDoc,
    parse_pdf,
)
from scripts.check_tables_constants import (  # noqa: E402
    AMOUNT_CLEANUP,
    FAMILY_QUOTAS,
    FRENCH_DECIMAL,
    NON_ITEM_LABEL,
    SUBTOTAL_PATTERN,
)


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


def select_sample(corpus: Path) -> list[tuple[DocType, Path]]:
    """Pick the first docs per family, in file-name order."""
    quotas = dict(FAMILY_QUOTAS)
    sample: list[tuple[DocType, Path]] = []
    for path in sorted(corpus.glob("*.pdf")):
        if not any(quotas.values()):
            break
        try:
            family = detect_doc_type(_first_page_text(path))
        except (PSException, OSError) as error:
            print(f"skip {path.name}: {error}", file=sys.stderr)
            continue
        if quotas.get(family, 0) > 0:
            quotas[family] -= 1
            sample.append((family, path))
    return sample


def _report_doc(family: DocType, path: Path) -> tuple[int, bool | None]:
    doc = parse_pdf(path)
    print(f"== {path.stem} [{family.value}] tables={doc.table_count}")
    for cells in table_rows(doc):
        print("   " + TABLE_CELL_SEPARATOR.join(cells))
    if family is not DocType.INVOICE:
        return doc.table_count, None
    passed, detail = check_invoice(doc)
    print(f"   sum check: {'PASS' if passed else 'FAIL'} ({detail})")
    return doc.table_count, passed


def main(argv: list[str] | None = None) -> int:
    """Run the check and print the per-family summary."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    args = parser.parse_args(argv)
    seen: dict[DocType, list[int]] = {name: [] for name in FAMILY_QUOTAS}
    sum_checks: list[bool] = []
    for family, path in select_sample(args.corpus):
        count, passed = _report_doc(family, path)
        seen[family].append(count)
        if passed is not None:
            sum_checks.append(passed)
    print("\nSUMMARY")
    for family, counts in seen.items():
        hits = sum(1 for count in counts if count > 0)
        print(f"{family.value}: {hits}/{len(counts)} docs with tables")
    print(f"invoice sum check: {sum(sum_checks)}/{len(sum_checks)} pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
