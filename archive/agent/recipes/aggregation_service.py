"""Aggregation recipe: sum invoice amounts over a filtered set."""

from archive.agent.recipes.recipe_model import RecipeResult, RecipeSearchPort
from archive.agent.route.route_model import QuestionPlan
from archive.llm.llm_gateway import LlmGateway
from archive.validation.input_model import Question


def run_aggregation(
    question: Question,
    plan: QuestionPlan,
    search: RecipeSearchPort,
    llm: LlmGateway,
) -> RecipeResult | None:
    """Answer an aggregation question, or None to use the direct path."""
    return None
