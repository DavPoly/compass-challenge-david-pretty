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
    HOP_NEW_HITS_MAX,
    LOG_DRAFT,
    LOG_FOLLOW_UP,
    LOG_NO_NEW_CHUNKS,
    MIN_ORIGINAL_SLOTS,
    MISSING_QUERY_MAX_CHARS,
)
from archive.agent.hops.hop_model import HopPolicy
from archive.agent.prompt_constants import (
    MAX_PROMPT_CHUNKS,
    NO_DOCUMENTS_MISSING,
)
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
        answered: The latest draft whose status was `answered`.
    """

    original: list[SearchHit]
    targeted: list[SearchHit] = field(default_factory=list)
    used: dict[str, SearchHit] = field(default_factory=dict)
    expanded: bool = False
    answered: DraftAnswer | None = None

    def prompt_hits(self) -> list[SearchHit]:
        """Return targeted hits, then linked originals, then the rest.

        Originals sharing a non-email identifier with a targeted hit
        come before unlinked ones. At least `MIN_ORIGINAL_SLOTS`
        prompt slots (or all originals, if fewer) stay reserved for
        originals, so a long targeted list cannot push out the start
        of the chain; older targeted hits are cut first.
        """
        targeted = dedupe_hits(self.targeted)
        targeted_ids = {hit.chunk.chunk_id for hit in targeted}
        linked_codes = _codes(targeted)
        linked = [hit for hit in self.original if _codes([hit]) & linked_codes]
        originals = [
            hit
            for hit in dedupe_hits(linked + self.original)
            if hit.chunk.chunk_id not in targeted_ids
        ]
        reserved = min(MIN_ORIGINAL_SLOTS, len(originals))
        kept = targeted[: MAX_PROMPT_CHUNKS - reserved]
        return kept + originals[: MAX_PROMPT_CHUNKS - len(kept)]

    def final_draft(self, current: DraftAnswer) -> DraftAnswer:
        """Return `current`, or an earlier answer if it regressed.

        A final `not_found` draft never replaces an answered one.
        """
        if current.status is AnswerStatus.NOT_FOUND and self.answered:
            return self.answered
        return current

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
    """Search for the missing evidence; keep chunks not yet seen."""
    query = missing.strip()[:MISSING_QUERY_MAX_CHARS]
    found: list[SearchHit] = []
    if not state.expanded:
        state.expanded = True
        found += expand_by_identifiers(question, state.prompt_hits(), search)
    typed = SearchFilters(doc_types=list(FOLLOW_UP_DOC_TYPES))
    found += search.hybrid_search(query, typed, FOLLOW_UP_TYPED_K)
    found += search.hybrid_search(query, None, FOLLOW_UP_K)
    seen = state.used.keys() | {hit.chunk.chunk_id for hit in state.targeted}
    return [
        hit for hit in dedupe_hits(found) if hit.chunk.chunk_id not in seen
    ]


def needs_follow_up(current: DraftAnswer) -> bool:
    """Return whether a draft names missing evidence worth searching.

    True only when the draft is not `evidence_sufficient` and its
    `missing` is non-blank and not the no-documents sentinel.
    """
    missing = (current.missing or "").strip()
    if not missing or missing == NO_DOCUMENTS_MISSING:
        return False
    return not current.evidence_sufficient


def _should_follow_up(
    current: DraftAnswer,
    state: _LoopState,
    drafts_made: int,
    elapsed_s: float,
    policy: HopPolicy,
) -> bool:
    """Return whether another hop is allowed and worthwhile."""
    if not state.original or not needs_follow_up(current):
        return False
    return drafts_made < policy.max_drafts and elapsed_s < policy.time_budget_s


def _draft_next(
    question: Question,
    state: _LoopState,
    llm: LlmGateway,
    note: str | None,
) -> DraftAnswer:
    """Draft from the current prompt hits and record them as used."""
    prompt_hits = state.prompt_hits()
    state.mark_used(prompt_hits)
    return draft(question, prompt_hits, llm, note=note)


def _record_draft(
    question: Question,
    draft_number: int,
    current: DraftAnswer,
    state: _LoopState,
) -> None:
    """Log one line describing a draft and remember answered ones."""
    if current.status is AnswerStatus.ANSWERED:
        state.answered = current
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
    note: str | None = None,
) -> RecipeResult:
    """Draft an answer, adding hits while the draft lacks evidence.

    The loop stops at the first of: the draft does not need a follow-up
    (see `needs_follow_up`), there are no original hits, the follow-up
    search adds no new chunk,
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
        note: Extra context rendered into every draft prompt.

    Returns:
        A result with every hit that reached a prompt and the last
        draft; a final `not_found` is replaced by the latest earlier
        `answered` draft. Prompt hits: targeted ones (newest first), originals
        sharing an identifier with them, then the other originals,
        capped at `MAX_PROMPT_CHUNKS`.

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
        current = _draft_next(question, state, llm, note)
    drafts_made = 1
    _record_draft(question, drafts_made, current, state)
    while _should_follow_up(
        current, state, drafts_made, policy.clock() - start, policy
    ):
        new_hits = _follow_up_hits(
            question, current.missing or "", state, search
        )
        if not new_hits:
            logger.info(LOG_NO_NEW_CHUNKS, question.id, drafts_made)
            break
        logger.info(LOG_FOLLOW_UP, question.id, drafts_made, len(new_hits))
        state.targeted = new_hits[:HOP_NEW_HITS_MAX] + state.targeted
        current = _draft_next(question, state, llm, note)
        drafts_made += 1
        _record_draft(question, drafts_made, current, state)
    final = state.final_draft(current)
    return RecipeResult(hits=list(state.used.values()), draft=final)
