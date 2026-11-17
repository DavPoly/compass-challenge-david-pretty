"""CLI: measure gold-doc recall@k of `retrieve()` (no LLM).

Usage:
    python scripts/measure_recall.py [--gold samples/gold.jsonl]
        [--index index] [--k 8,12,16,24,32]

``--gold`` is a JSONL file whose rows hold ``id``, ``question`` and
``citations`` (gold doc ids). Rows with no citations are skipped.
For each k, recall@k = |gold & retrieved doc ids| / |gold|. Prints a
per-question table, the mean recall per k and how many questions
have at least one gold doc in the top k. Retrieval runs once per k,
because typed slots depend on k.
"""

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

# Allow `python scripts/measure_recall.py` from any directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from archive.agent.retrieve_service import retrieve  # noqa: E402
from archive.common.constants import INDEX_DIR_NAME, REPO_ROOT  # noqa: E402
from archive.pipeline.pipeline_constants import (  # noqa: E402
    EXIT_ERROR,
    EXIT_OK,
)
from archive.retrieval.search_service import SearchService  # noqa: E402

DEFAULT_GOLD = REPO_ROOT / "samples" / "gold.jsonl"
DEFAULT_KS = "8,12,16,24,32"
ID_WIDTH = 6
CELL_WIDTH = 9


@dataclass(frozen=True)
class GoldQuestion:
    """A gold row with at least one citation."""

    question_id: str
    question: str
    gold_docs: frozenset[str]


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument(
        "--index", type=Path, default=REPO_ROOT / INDEX_DIR_NAME
    )
    parser.add_argument("--k", default=DEFAULT_KS)
    return parser.parse_args(argv)


def _load_gold(path: Path) -> list[GoldQuestion]:
    questions: list[GoldQuestion] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        citations = frozenset(row.get("citations") or [])
        if citations:
            questions.append(
                GoldQuestion(row["id"], row["question"], citations)
            )
    return questions


def _recall_rows(
    questions: list[GoldQuestion], search: SearchService, ks: list[int]
) -> list[list[float]]:
    rows: list[list[float]] = []
    for item in questions:
        row: list[float] = []
        for k in ks:
            hits = retrieve(item.question, search, k)
            found = {hit.chunk.doc_id for hit in hits} & item.gold_docs
            row.append(len(found) / len(item.gold_docs))
        rows.append(row)
    return rows


def _print_report(
    questions: list[GoldQuestion],
    rows: list[list[float]],
    ks: list[int],
) -> None:
    print(
        "id".ljust(ID_WIDTH) + "".join(f"@{k}".rjust(CELL_WIDTH) for k in ks)
    )
    for item, row in zip(questions, rows, strict=True):
        cells = "".join(f"{value:.2f}".rjust(CELL_WIDTH) for value in row)
        print(item.question_id.ljust(ID_WIDTH) + cells)
    total = len(rows)
    means = [sum(row[i] for row in rows) / total for i in range(len(ks))]
    hits_any = [sum(row[i] > 0 for row in rows) for i in range(len(ks))]
    print(
        "mean".ljust(ID_WIDTH)
        + "".join(f"{m:.2f}".rjust(CELL_WIDTH) for m in means)
    )
    print(
        "any".ljust(ID_WIDTH)
        + "".join(f"{h}/{total}".rjust(CELL_WIDTH) for h in hits_any)
    )


def main(argv: list[str] | None = None) -> int:
    """Print the recall report; return the process exit code."""
    args = _parse_args(argv)
    ks = [int(value) for value in args.k.split(",")]
    questions = _load_gold(args.gold)
    if not questions:
        print(f"No gold question with citations in {args.gold}.")
        return EXIT_ERROR
    with SearchService.open(args.index) as search:
        rows = _recall_rows(questions, search, ks)
    _print_report(questions, rows, ks)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
