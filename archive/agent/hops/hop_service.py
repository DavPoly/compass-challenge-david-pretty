"""Draft an answer, following missing evidence with more hops."""

import logging
from dataclasses import dataclass, field

from archive.agent.draft_service import draft
from archive.agent.hops.code_utils import non_email_codes
from archive.agent.hops.expand_service import expand_by_identifiers
from archive.agent.hops.hop_constants import (
    FOLLOW_UP_DOC_TYPES,
    FOLLOW_UP_K,
    FOLLOW_UP_TYPED_K,
    HOP_LOG_MISSING_MAX_CHARS,
    LOG_DRAFT,
    LOG_FOLLOW_UP,
    LOG_NO_NEW_CHUNKS,
    MISSING_QUERY_MAX_CHARS,
)
from archive.agent.hops.hop_model import HopPolicy
from archive.agent.prompt_constants import MAX_PROMPT_CHUNKS
from archive.agent.recipes.recipe_model import (
    RecipeResult,
    RecipeSearchPort,
)
from archive.agent.retrieve_service import dedupe_hits
from archive.llm.llm_gateway import LlmGateway
from archive.retrieval.search_service import SearchFilters, SearchHit
from archive.validation.answer_model import AnswerStatus, DraftAnswer
from archive.validation.input_model import Question

logger = logging.getLogger(__name__)


@dataclass
class _LoopState:
    """Mutable state of one hop loop.

    Attributes:
        original: Retrieved hits, best first.
        targeted: Expansion and follow-up hits, newest first.
        used: Every hit that reached a prompt, by first appearance.
        expanded: Whether identifier expansion already ran.
    """

    original: list[SearchHit]
    targeted: list[SearchHit] = field(default_factory=list)
    used: dict[str, SearchHit] = field(default_factory=dict)
    expanded: bool = False

    def prompt_hits(self) -> list[SearchHit]:
        """Return targeted hits, linked originals, then the rest.

        Originals sharing a non-email identifier with a targeted hit
        come before unlinked ones. The result is deduped and capped.
        """
        linked_codes = _codes(self.targeted)
        linked = [hit for hit in self.original if _codes([hit]) & linked_codes]
        merged = dedupe_hits(self.targeted + linked + self.original)
        return merged[:MAX_PROMPT_CHUNKS]

    def mark_used(self, prompt_hits: list[SearchHit]) -> None:
        """Record hits that reached a prompt."""
        for hit in prompt_hits:
            self.used.setdefault(hit.chunk.chunk_id, hit)


def _codes(hits: list[SearchHit]) -> set[str]:
    """Return the non-email identifiers carried by the hits."""
    return set(
        non_email_codes(code for hit in hits for code in hit.chunk.identifiers)
    )


def _follow_up_hits(
    question: Question,
    missing: str,
    state: _LoopState,
    search: RecipeSearchPort,
) -> list[SearchHit]:
    """Search for the missing evidence; keep chunks not yet used."""
    query = missing.strip()[:MISSING_QUERY_MAX_CHARS]
    found: list[SearchHit] = []
    if not state.expanded:
        state.expanded = True
        found += expand_by_identifiers(question, state.prompt_hits(), search)
    typed = SearchFilters(doc_types=list(FOLLOW_UP_DOC_TYPES))
    found += search.hybrid_search(query, typed, FOLLOW_UP_TYPED_K)
    found += search.hybrid_search(query, None, FOLLOW_UP_K)
    return [
        hit
        for hit in dedupe_hits(found)
        if hit.chunk.chunk_id not in state.used
    ]


def _should_follow_up(
    current: DraftAnswer,
    drafts_made: int,
    elapsed_s: float,
    policy: HopPolicy,
) -> bool:
    """Return whether another hop is allowed and worthwhile."""
    if not (current.missing or "").strip():
        return False
    is_gap = (
        not current.evidence_sufficient
        or current.status is AnswerStatus.NOT_FOUND
    )
    if not is_gap:
        return False
    return drafts_made < policy.max_drafts and elapsed_s < policy.time_budget_s


def _log_draft(
    question: Question, draft_number: int, current: DraftAnswer
) -> None:
    """Log one line describing a draft, with `missing` truncated."""
    missing = (current.missing or "").strip()[:HOP_LOG_MISSING_MAX_CHARS]
    logger.info(
        LOG_DRAFT,
        question.id,
        draft_number,
        current.status.value,
        current.evidence_sufficient,
        missing,
    )


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

    The loop stops at the first of: `missing` is empty, the draft is
    sufficient and not `not_found`, the follow-up search adds no new chunk,
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
        ones (expansion and follow-up, newest first), then original
        hits sharing an identifier with a targeted one, then the
        other original hits, capped at `MAX_PROMPT_CHUNKS`.

    Raises:
        LlmUnavailableError: the LLM could not give a valid draft.
    """
    start = policy.clock()
    state = _LoopState(original=hits)
    if first_draft is not None:
        current = first_draft
        state.mark_used(hits[:MAX_PROMPT_CHUNKS])
    else:
        if policy.expand_upfront:
            state.expanded = True
            state.targeted = expand_by_identifiers(question, hits, search)
        prompt_hits = state.prompt_hits()
        state.mark_used(prompt_hits)
        current = draft(question, prompt_hits, llm)
    drafts_made = 1
    _log_draft(question, drafts_made, current)
    while _should_follow_up(
        current, drafts_made, policy.clock() - start, policy
    ):
        new_hits = _follow_up_hits(
            question, current.missing or "", state, search
        )
        if not new_hits:
            logger.info(LOG_NO_NEW_CHUNKS, question.id, drafts_made)
            break
        logger.info(LOG_FOLLOW_UP, question.id, drafts_made, len(new_hits))
        state.targeted = new_hits + state.targeted
        prompt_hits = state.prompt_hits()
        state.mark_used(prompt_hits)
        current = draft(question, prompt_hits, llm)
        drafts_made += 1
        _log_draft(question, drafts_made, current)
    return RecipeResult(hits=list(state.used.values()), draft=current)
