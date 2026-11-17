"""CLI: measure how well the router finds the family of a question.

Usage:
    python -m scripts.measure_route
        [--questions samples/questions.jsonl] [--gold samples/gold.jsonl]

Plans every question with the LLM router and prints, per question, the
gold type, the predicted family and the extracted fields. The accuracy
is computed over answerable questions only, with the gold types mapped
to families (conflict counts as direct). Needs the `LLM_*` variables.
"""

import argparse
import json
import sys
from pathlib import Path

# Allow `python scripts/measure_route.py` from any directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from archive.agent.route.route_model import QuestionPlan  # noqa: E402
from archive.agent.route.route_service import plan_question  # noqa: E402
from archive.common.config import AppConfig, ConfigError  # noqa: E402
from archive.common.constants import REPO_ROOT  # noqa: E402
from archive.llm.llm_gateway import LlmGateway  # noqa: E402
from archive.pipeline.pipeline_constants import (  # noqa: E402
    EXIT_ERROR,
    EXIT_OK,
)
from archive.validation.input_model import (  # noqa: E402
    Question,
    load_questions,
)
from scripts.measure_route_constants import (  # noqa: E402
    DEFAULT_GOLD_PARTS,
    DEFAULT_QUESTIONS_PARTS,
    FAMILY_WIDTH,
    GOLD_TYPE_TO_FAMILY,
    ID_WIDTH,
    MSG_ACCURACY,
    MSG_MISSING_CONFIG,
    MSG_NO_ANSWERABLE,
    PLAN_FIELDS,
    TYPE_WIDTH,
)

DEFAULT_QUESTIONS = REPO_ROOT.joinpath(*DEFAULT_QUESTIONS_PARTS)
DEFAULT_GOLD = REPO_ROOT.joinpath(*DEFAULT_GOLD_PARTS)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    return parser.parse_args(argv)


def load_gold_types(path: Path) -> dict[str, str]:
    """Map each question id of a gold JSONL file to its gold type."""
    types: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            types[str(row["id"])] = str(row["type"])
    return types


def expected_family(gold_type: str) -> str | None:
    """Family a gold type should route to; None if unanswerable."""
    return GOLD_TYPE_TO_FAMILY.get(gold_type)


def family_accuracy(pairs: list[tuple[str, str]]) -> tuple[int, int]:
    """Return (correct, scored) over `(gold_type, predicted)` pairs.

    Gold types with no expected family (unanswerable) are not scored.
    """
    scored = [
        (expected_family(gold_type), predicted)
        for gold_type, predicted in pairs
        if expected_family(gold_type) is not None
    ]
    correct = sum(expected == predicted for expected, predicted in scored)
    return correct, len(scored)


def _format_fields(plan: QuestionPlan) -> str:
    values = plan.model_dump(mode="json")
    return " ".join(
        f"{name}={values[name]}"
        for name in PLAN_FIELDS
        if values[name] not in (None, [])
    )


def _format_row(question: Question, gold_type: str, plan: QuestionPlan) -> str:
    return (
        f"{question.id.ljust(ID_WIDTH)}{gold_type.ljust(TYPE_WIDTH)}"
        f"{plan.family.value.ljust(FAMILY_WIDTH)}{_format_fields(plan)}"
    )


def main(argv: list[str] | None = None) -> int:
    """Print the routing report; return the process exit code."""
    args = _parse_args(argv)
    try:
        llm = LlmGateway(AppConfig.from_env())
    except ConfigError as error:
        print(MSG_MISSING_CONFIG.format(error=error), file=sys.stderr)
        return EXIT_ERROR
    gold_types = load_gold_types(args.gold)
    pairs: list[tuple[str, str]] = []
    for question in load_questions(args.questions):
        plan = plan_question(question, llm)
        gold_type = gold_types.get(question.id, "")
        pairs.append((gold_type, plan.family.value))
        print(_format_row(question, gold_type, plan))
    correct, total = family_accuracy(pairs)
    if total == 0:
        print(MSG_NO_ANSWERABLE.format(path=args.gold))
        return EXIT_ERROR
    ratio = correct / total
    print(MSG_ACCURACY.format(correct=correct, total=total, ratio=ratio))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
