"""Answer one question: plan, run a recipe or retrieve, then draft."""

import time
from dataclasses import dataclass, replace

from archive.agent.draft_service import draft
from archive.agent.hops.hop_model import HopPolicy
from archive.agent.hops.hop_service import needs_follow_up, run_hops
from archive.agent.prompt_constants import MAX_PROMPT_CHUNKS
from archive.agent.recipes.aggregation_service import run_aggregation
from archive.agent.recipes.recipe_model import RecipeResult, RecipeSearchPort
from archive.agent.recipes.superseded_service import run_superseded
from archive.agent.retrieve_constants import SEARCH_TOP_K
from archive.agent.retrieve_service import retrieve
from archive.agent.route.route_model import QuestionFamily, QuestionPlan
from archive.agent.route.route_service import plan_question
from archive.common.step_constants import (
    DETAIL_LABELS,
    DRAFT_DETAIL,
    EXTRACTS_DETAIL,
    FIRST_DRAFT_NUMBER,
    RECIPE_DETAIL,
)
from archive.common.step_model import PipelineStep, StepCallback, emit_step
from archive.llm.llm_gateway import LlmGateway
from archive.retrieval.search_service import SearchHit
from archive.validation.answer_model import DraftAnswer
from archive.validation.input_model import Question


@dataclass(frozen=True)
class DraftOutcome:
    """A draft with its hits, the recipe note and the question plan."""

    draft: DraftAnswer
    hits: list[SearchHit]
    note: str | None
    plan: QuestionPlan | None = None

    @property
    def doc_ids(self) -> set[str]:
        """Doc ids of the hits the draft relied on."""
        return _doc_ids(self.hits)


def answer_question(
    question: Question,
    search: RecipeSearchPort,
    llm: LlmGateway,
    on_step: StepCallback | None = None,
) -> DraftOutcome:
    """Return the draft answer, its hits and the recipe note.

    On the draft path the hits are those that reached the prompt (plus
    any safety-net hop hits); a recipe that drafts itself keeps all
    its hits. The note is the recipe note, None otherwise. An insufficient
    draft that names what is missing gets one safety-net hop.
    ``on_step`` is told when each stage starts or ends; its failures
    are ignored.

    Raises:
        LlmUnavailableError: the LLM could not give a valid draft.
    """
    started_s = time.monotonic()
    plan = plan_question(question, llm)
    emit_step(on_step, PipelineStep.ROUTE, _detail_label(plan.family.value))
    result = _run_recipe(question, plan, search, llm)
    if result is None:
        hits = retrieve(question.question, search, SEARCH_TOP_K)
        emit_step(
            on_step,
            PipelineStep.RETRIEVE,
            EXTRACTS_DETAIL.format(count=len(hits)),
        )
        if plan.family is QuestionFamily.MULTI_HOP:
            policy = replace(HopPolicy.multi_hop(), started_s=started_s)
            result = run_hops(question, hits, search, llm, policy)
        else:
            result = RecipeResult(hits=hits)
    else:
        emit_step(
            on_step,
            PipelineStep.RETRIEVE,
            RECIPE_DETAIL.format(
                count=len(result.hits),
                recipe=_detail_label(plan.family.value),
            ),
        )
    if result.draft is not None:
        return DraftOutcome(result.draft, result.hits, result.note, plan)
    return _draft_with_safety_net(
        question, result, plan, search, llm, started_s, on_step
    )


def _detail_label(code: str) -> str:
    return DETAIL_LABELS.get(code, code)


def _draft_with_safety_net(  # noqa: PLR0913, PLR0917 - one value per input
    question: Question,
    result: RecipeResult,
    plan: QuestionPlan,
    search: RecipeSearchPort,
    llm: LlmGateway,
    started_s: float,
    on_step: StepCallback | None,
) -> DraftOutcome:
    """Draft from a recipe result; hop once more on a named gap.

    The first draft uses the top `MAX_PROMPT_CHUNKS` hits and the
    recipe note. When `needs_follow_up` holds, a safety-net hop loop
    continues from it, carrying the same note; its time budget runs
    from `started_s`, the clock reading when the question began.

    Returns:
        The final draft, every hit that was used and the recipe note.

    Raises:
        LlmUnavailableError: the LLM could not give a valid draft.
    """
    prompt_hits = result.hits[:MAX_PROMPT_CHUNKS]
    emit_step(
        on_step,
        PipelineStep.DRAFT,
        DRAFT_DETAIL.format(number=FIRST_DRAFT_NUMBER),
    )
    drafted = draft(question, prompt_hits, llm, note=result.note)
    if not needs_follow_up(drafted):
        return DraftOutcome(drafted, prompt_hits, result.note, plan)
    emit_step(on_step, PipelineStep.HOP, drafted.missing)
    policy = replace(HopPolicy.safety_net(), started_s=started_s)
    hopped = run_hops(
        question,
        result.hits,
        search,
        llm,
        policy,
        first_draft=drafted,
        note=result.note,
    )
    final = hopped.draft if hopped.draft is not None else drafted
    return DraftOutcome(final, prompt_hits + hopped.hits, result.note, plan)


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
