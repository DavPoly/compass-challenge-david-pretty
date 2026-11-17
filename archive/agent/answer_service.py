"""Answer one question: plan, run a recipe or retrieve, then draft."""

from archive.agent.draft_service import draft
from archive.agent.prompt_constants import MAX_PROMPT_CHUNKS
from archive.agent.recipes.aggregation_service import run_aggregation
from archive.agent.recipes.recipe_model import RecipeResult, RecipeSearchPort
from archive.agent.recipes.superseded_service import run_superseded
from archive.agent.retrieve_constants import SEARCH_TOP_K
from archive.agent.retrieve_service import retrieve
from archive.agent.route.route_model import QuestionFamily, QuestionPlan
from archive.agent.route.route_service import plan_question
from archive.llm.llm_gateway import LlmGateway
from archive.retrieval.search_service import SearchHit
from archive.validation.answer_model import DraftAnswer
from archive.validation.input_model import Question


def answer_question(
    question: Question, search: RecipeSearchPort, llm: LlmGateway
) -> tuple[DraftAnswer, set[str]]:
    """Return the draft answer and the doc ids it was drafted from.

    On the draft path these are the hits that reached the prompt; a
    recipe that drafts itself keeps all its hits.

    Raises:
        LlmUnavailableError: the LLM could not give a valid draft.
    """
    plan = plan_question(question, llm)
    result = _run_recipe(question, plan, search, llm)
    if result is None:
        hits = retrieve(question.question, search, SEARCH_TOP_K)
        result = RecipeResult(hits=hits)
    if result.draft is not None:
        return result.draft, _doc_ids(result.hits)
    prompt_hits = result.hits[:MAX_PROMPT_CHUNKS]
    drafted = draft(question, prompt_hits, llm, note=result.note)
    return drafted, _doc_ids(prompt_hits)


def _doc_ids(hits: list[SearchHit]) -> set[str]:
    return {hit.chunk.doc_id for hit in hits}


def _run_recipe(
    question: Question,
    plan: QuestionPlan,
    search: RecipeSearchPort,
    llm: LlmGateway,
) -> RecipeResult | None:
    if plan.family is QuestionFamily.AGGREGATION:
        return run_aggregation(question, plan, search, llm)
    if plan.family is QuestionFamily.SUPERSEDED:
        return run_superseded(question, plan, search, llm)
    return None
