"""CLI: check the aggregation and superseded recipes (no LLM).

Usage:
    python -m scripts.check_recipes [--index index]
        [--gold samples/gold.jsonl] [--dense|--no-dense]

Runs the recipes on hand-made plans of the gold questions, with an
LLM stub that is always unavailable, so only the regex path runs.
Aggregation answers are compared with the gold answer and citations;
superseded questions report their first hit against the gold
citation; the unanswerable one must fall back to the direct path.
Exit 0 when every aggregation matches exactly and the fallback holds.
"""

import argparse
import json
import sys
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, cast

# Allow `python scripts/check_recipes.py` from any directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from archive.agent.recipes.aggregation_service import (  # noqa: E402
    run_aggregation,
)
from archive.agent.recipes.recipe_model import (  # noqa: E402
    RecipeResult,
    RecipeSearchPort,
)
from archive.agent.recipes.superseded_service import (  # noqa: E402
    run_superseded,
)
from archive.common.constants import INDEX_DIR_NAME, REPO_ROOT  # noqa: E402
from archive.llm.llm_gateway import (  # noqa: E402
    LlmGateway,
    LlmUnavailableError,
)
from archive.pipeline.pipeline_constants import (  # noqa: E402
    EXIT_ERROR,
    EXIT_OK,
)
from archive.retrieval.models.embedding_gateway import (  # noqa: E402
    EmbeddingPort,
    load_embedder,
)
from archive.retrieval.models.model_constants import (  # noqa: E402
    MODEL_LOAD_TIMEOUT_S,
)
from archive.retrieval.search_service import SearchService  # noqa: E402
from archive.validation.input_model import Question  # noqa: E402
from scripts.check_recipes_constants import (  # noqa: E402
    AGGREGATION_IDS,
    DEFAULT_GOLD_PARTS,
    FALLBACK_IDS,
    FALLBACK_LABEL,
    LLM_OFFLINE_MESSAGE,
    MSG_AGGREGATION,
    MSG_DENSE_UNAVAILABLE,
    MSG_FALLBACK,
    MSG_MISSING_GOLD,
    MSG_SUMMARY,
    MSG_SUPERSEDED,
    PLANS,
    SUPERSEDED_IDS,
    VERDICT_DIFF,
    VERDICT_FAIL,
    VERDICT_OK,
    VERDICT_PASS,
)

DEFAULT_GOLD = REPO_ROOT.joinpath(*DEFAULT_GOLD_PARTS)


@dataclass(frozen=True)
class GoldRow:
    """The gold fields a recipe check compares against."""

    question: str
    answer: str
    citations: list[str]


class _OfflineLlm:
    """LLM stand-in that is always unavailable."""

    def complete_json(self, *args: Any, **kwargs: Any) -> Any:
        raise LlmUnavailableError(LLM_OFFLINE_MESSAGE)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument(
        "--index", type=Path, default=REPO_ROOT / INDEX_DIR_NAME
    )
    parser.add_argument(
        "--dense",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="fuse dense vectors into the search (needs the model)",
    )
    return parser.parse_args(argv)


def load_gold_rows(path: Path) -> dict[str, GoldRow]:
    """Map each question id of a gold JSONL file to its gold fields."""
    rows: dict[str, GoldRow] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            rows[str(row["id"])] = GoldRow(
                row["question"],
                str(row["answer"]),
                list(row.get("citations") or []),
            )
    return rows


def compare_ids(
    got: list[str], gold: list[str]
) -> tuple[list[str], list[str]]:
    """Return the (missing, extra) doc ids of `got` against `gold`."""
    return sorted(set(gold) - set(got)), sorted(set(got) - set(gold))


def answers_match(answer: str, gold_answer: str) -> bool:
    """Whether two answers are equal, as text or as numbers."""
    if answer.strip() == gold_answer.strip():
        return True
    try:
        return Decimal(answer.strip()) == Decimal(gold_answer.strip())
    except InvalidOperation:
        return False


def _answer_text(result: RecipeResult) -> str:
    draft = result.draft
    if draft is None:
        return ""
    answer = draft.answer
    return answer if isinstance(answer, str) else "; ".join(answer)


def aggregation_line(
    question_id: str, gold: GoldRow, result: RecipeResult | None
) -> tuple[str, bool]:
    """Report line of an aggregation and whether it matches exactly."""
    if result is None or result.draft is None:
        line = MSG_FALLBACK.format(id=question_id, verdict=VERDICT_DIFF)
        return line, False
    answer = _answer_text(result)
    citations = result.draft.citations
    missing, extra = compare_ids(citations, gold.citations)
    is_exact = answers_match(answer, gold.answer) and not (missing or extra)
    line = MSG_AGGREGATION.format(
        id=question_id,
        verdict=VERDICT_OK if is_exact else VERDICT_DIFF,
        answer=answer,
        gold=gold.answer,
        count=len(citations),
        missing=missing,
        extra=extra,
    )
    return line, is_exact


def superseded_line(
    question_id: str, gold: GoldRow, result: RecipeResult | None
) -> str:
    """Report line of a superseded question (informational)."""
    first = result.hits[0].chunk.doc_id if result and result.hits else None
    return MSG_SUPERSEDED.format(
        id=question_id,
        first=first or FALLBACK_LABEL,
        gold=gold.citations,
    )


def fallback_line(
    question_id: str, result: RecipeResult | None
) -> tuple[str, bool]:
    """Report line of an expected fallback and whether it held."""
    is_fallback = result is None
    verdict = VERDICT_OK if is_fallback else VERDICT_DIFF
    return MSG_FALLBACK.format(id=question_id, verdict=verdict), is_fallback


def _question(question_id: str, gold: GoldRow) -> Question:
    return Question(id=question_id, question=gold.question)


def check_recipes(
    golds: dict[str, GoldRow], search: RecipeSearchPort
) -> tuple[list[str], bool]:
    """Run every check; return the report lines and the overall pass."""
    llm = cast(LlmGateway, _OfflineLlm())
    lines: list[str] = []
    is_pass = True
    for question_id in AGGREGATION_IDS:
        gold = golds[question_id]
        result = run_aggregation(
            _question(question_id, gold), PLANS[question_id], search, llm
        )
        line, is_exact = aggregation_line(question_id, gold, result)
        lines.append(line)
        is_pass = is_pass and is_exact
    for question_id in SUPERSEDED_IDS:
        gold = golds[question_id]
        superseded = run_superseded(
            _question(question_id, gold), PLANS[question_id], search
        )
        lines.append(superseded_line(question_id, gold, superseded))
    for question_id in FALLBACK_IDS:
        gold = golds[question_id]
        result = run_aggregation(
            _question(question_id, gold), PLANS[question_id], search, llm
        )
        line, is_fallback = fallback_line(question_id, result)
        lines.append(line)
        is_pass = is_pass and is_fallback
    return lines, is_pass


def _load_dense(is_dense: bool) -> EmbeddingPort | None:
    """Load the embedder when asked; a failed load stays sparse-only."""
    if not is_dense:
        return None
    embedder = load_embedder(MODEL_LOAD_TIMEOUT_S)
    if embedder is None:
        print(MSG_DENSE_UNAVAILABLE, file=sys.stderr)
    return embedder


def main(argv: list[str] | None = None) -> int:
    """Print the recipe report; return the process exit code."""
    args = _parse_args(argv)
    golds = load_gold_rows(args.gold)
    wanted = [*AGGREGATION_IDS, *SUPERSEDED_IDS, *FALLBACK_IDS]
    absent = [name for name in wanted if name not in golds]
    if absent:
        print(MSG_MISSING_GOLD.format(ids=absent, path=args.gold))
        return EXIT_ERROR
    embedder = _load_dense(args.dense)
    with SearchService.open(args.index, embedder, None) as search:
        lines, is_pass = check_recipes(golds, search)
    print("\n".join(lines))
    verdict = VERDICT_PASS if is_pass else VERDICT_FAIL
    print(MSG_SUMMARY.format(verdict=verdict))
    return EXIT_OK if is_pass else EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
