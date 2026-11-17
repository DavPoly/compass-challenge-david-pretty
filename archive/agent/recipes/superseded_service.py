"""Superseded recipe: pick the policy version in force."""

from archive.agent.recipes.recipe_model import RecipeResult, RecipeSearchPort
from archive.agent.route.route_model import QuestionPlan
from archive.validation.input_model import Question


def run_superseded(
    question: Question, plan: QuestionPlan, search: RecipeSearchPort
) -> RecipeResult | None:
    """Gather the policy versions, or None to use the direct path."""
    return None
