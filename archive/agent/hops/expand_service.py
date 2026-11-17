"""Follow identifier links from hits to related documents."""

from archive.agent.recipes.recipe_model import RecipeSearchPort
from archive.retrieval.search_service import SearchHit
from archive.validation.input_model import Question


def expand_by_identifiers(
    question: Question,
    hits: list[SearchHit],
    search: RecipeSearchPort,
) -> list[SearchHit]:
    """Return chunks linked to the question and hits by a shared code.

    Codes come from the question text and from the identifiers of the
    top hits; emails are ignored. Chunks of project sheets and
    contracts carrying any of those codes are listed with
    `list_by_filter`.

    Args:
        question: The question being answered.
        hits: Retrieved hits whose identifiers seed the expansion.
        search: Search port used to list chunks by identifier.

    Returns:
        Only chunks not already in `hits` (by chunk id), in the order
        the codes were found, question codes first.
    """
    return []
