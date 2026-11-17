"""Draft an answer, following missing evidence with more hops."""

from archive.agent.draft_service import draft
from archive.agent.hops.expand_service import expand_by_identifiers
from archive.agent.hops.hop_model import HopPolicy
from archive.agent.prompt_constants import MAX_PROMPT_CHUNKS
from archive.agent.recipes.recipe_model import (
    RecipeResult,
    RecipeSearchPort,
)
from archive.llm.llm_gateway import LlmGateway
from archive.retrieval.search_service import SearchHit
from archive.validation.answer_model import DraftAnswer
from archive.validation.input_model import Question


def run_hops(  # noqa: PLR0913 - frozen signature
    question: Question,
    hits: list[SearchHit],
    search: RecipeSearchPort,
    llm: LlmGateway,
    policy: HopPolicy,
    *,
    first_draft: DraftAnswer | None = None,
) -> RecipeResult:
    """Draft an answer, adding hits while the draft lacks evidence.

    The loop stops at the first of: the draft is sufficient,
    `missing` is empty, the follow-up search adds no new chunk,
    `policy.max_drafts` is reached, or the time budget is spent. The
    follow-up search merges `hybrid_search(missing)` with a typed
    search over directory, project sheet and contract documents.

    Args:
        question: The question being answered.
        hits: Retrieved hits, best first.
        search: Search port for expansion and follow-up searches.
        llm: Gateway used for the draft calls.
        policy: Draft limit, upfront expansion and time budget.
        first_draft: A draft already made from `hits`; when given it
            is not repeated.

    Returns:
        A result whose hits are every hit that reached a prompt and
        whose draft is the last draft. Prompt hits are the targeted
        ones (expansion and follow-up, newest first), then the
        original hits, capped at `MAX_PROMPT_CHUNKS`.

    Raises:
        LlmUnavailableError: the LLM could not give a valid draft.
    """
    if first_draft is not None:
        prompt_hits = hits[:MAX_PROMPT_CHUNKS]
        return RecipeResult(hits=prompt_hits, draft=first_draft)
    if policy.expand_upfront:
        hits = expand_by_identifiers(question, hits, search) + hits
    prompt_hits = hits[:MAX_PROMPT_CHUNKS]
    drafted = draft(question, prompt_hits, llm)
    return RecipeResult(hits=prompt_hits, draft=drafted)
