"""CLI: measure gold-doc recall@k of `retrieve()` (no LLM).

Usage:
    python scripts/measure_recall.py [--gold samples/gold.jsonl]
        [--index index] [--k 8,12,16,24,32] [--dense|--no-dense]
        [--rerank|--no-rerank]

``--gold`` is a JSONL file whose rows hold ``id``, ``question`` and
``citations`` (gold doc ids). Rows with no citations are skipped.
For each k, recall@k = |gold & retrieved doc ids| / |gold|. Prints a
per-question table, the mean recall per k and how many questions
have at least one gold doc in the top k. Retrieval runs once per k,
because typed slots depend on k.

``--dense`` and ``--rerank`` load the models through the same loaders
the run uses; without them the measurement is the BM25-only baseline.
A model that cannot be loaded is noted and the measurement goes on
without it.
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
from archive.retrieval.models import rerank_gateway  # noqa: E402
from archive.retrieval.models.embedding_gateway import (  # noqa: E402
    EmbeddingPort,
    load_embedder,
)
from archive.retrieval.models.model_constants import (  # noqa: E402
    MODEL_LOAD_TIMEOUT_S,
)
from archive.retrieval.models.rerank_gateway import (  # noqa: E402
    RerankPort,
    load_reranker,
)
from archive.retrieval.search_service import SearchService  # noqa: E402
from scripts.measure_recall_constants import (  # noqa: E402
    CELL_WIDTH,
    DEFAULT_GOLD_PARTS,
    DEFAULT_KS,
    ID_WIDTH,
    MSG_DENSE_UNAVAILABLE,
    MSG_RERANK_UNAVAILABLE,
    RERANK_GATE_ATTR,
)

DEFAULT_GOLD = REPO_ROOT.joinpath(*DEFAULT_GOLD_PARTS)


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
    parser.add_argument(
        "--dense",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="fuse dense vectors into the search (needs the model)",
    )
    parser.add_argument(
        "--rerank",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="re-score the fused hits with the cross-encoder",
    )
    return parser.parse_args(argv)


def _load_gold(path: Path) -> list[GoldQuestion]:
    questions: list[GoldQuestion] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            citations = frozenset(row.get("citations") or [])
            if citations:
                questions.append(
                    GoldQuestion(row["id"], row["question"], citations)
                )
        except (
            json.JSONDecodeError,
            KeyError,
            AttributeError,
            TypeError,
        ) as error:
            raise ValueError(
                f"{path}:{line_number}: malformed gold row ({error!r});"
                " expected a JSON object with id, question, citations"
            ) from error
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


def _format_row(label: str, cells: list[str]) -> str:
    """One report line: label column then right-aligned cells."""
    return label.ljust(ID_WIDTH) + "".join(
        cell.rjust(CELL_WIDTH) for cell in cells
    )


def _print_report(
    questions: list[GoldQuestion],
    rows: list[list[float]],
    ks: list[int],
) -> None:
    print(_format_row("id", [f"@{k}" for k in ks]))
    for item, row in zip(questions, rows, strict=True):
        print(_format_row(item.question_id, [f"{v:.2f}" for v in row]))
    total = len(rows)
    columns = list(range(len(ks)))
    means = [sum(row[column] for row in rows) / total for column in columns]
    hits_any = [sum(row[column] > 0 for row in rows) for column in columns]
    print(_format_row("mean", [f"{mean:.2f}" for mean in means]))
    print(_format_row("any", [f"{hits}/{total}" for hits in hits_any]))


def _load_dense(is_dense: bool) -> EmbeddingPort | None:
    """Load the embedder when asked; a failed load stays sparse-only."""
    if not is_dense:
        return None
    embedder = load_embedder(MODEL_LOAD_TIMEOUT_S)
    if embedder is None:
        print(MSG_DENSE_UNAVAILABLE, file=sys.stderr)
    return embedder


def _load_rerank(is_rerank: bool) -> RerankPort | None:
    """Load the reranker when asked, over the production gate.

    `load_reranker` reads the `RERANK_ENABLED` flag of its own module
    (imported by value from the model constants), so the measurement
    flips that attribute for the load and restores it right after; the
    loader keeps its frozen signature.
    """
    if not is_rerank:
        return None
    enabled = bool(getattr(rerank_gateway, RERANK_GATE_ATTR))
    setattr(rerank_gateway, RERANK_GATE_ATTR, True)
    try:
        reranker = load_reranker(MODEL_LOAD_TIMEOUT_S)
    finally:
        setattr(rerank_gateway, RERANK_GATE_ATTR, enabled)
    if reranker is None:
        print(MSG_RERANK_UNAVAILABLE, file=sys.stderr)
    return reranker


def main(argv: list[str] | None = None) -> int:
    """Print the recall report; return the process exit code."""
    args = _parse_args(argv)
    ks = [int(value) for value in args.k.split(",")]
    questions = _load_gold(args.gold)
    if not questions:
        print(f"No gold question with citations in {args.gold}.")
        return EXIT_ERROR
    embedder = _load_dense(args.dense)
    reranker = _load_rerank(args.rerank)
    with SearchService.open(args.index, embedder, reranker) as search:
        rows = _recall_rows(questions, search, ks)
    _print_report(questions, rows, ks)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
