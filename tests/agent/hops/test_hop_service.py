from archive.agent.hops.hop_model import HopPolicy
from archive.agent.hops.hop_service import run_hops
from archive.agent.prompt_constants import MAX_PROMPT_CHUNKS
from archive.common.chunk_model import Chunk, ChunkKind
from archive.llm.llm_gateway import LlmGateway, Messages
from archive.retrieval.search_service import SearchFilters, SearchHit
from archive.validation.answer_model import AnswerStatus, DraftAnswer
from archive.validation.input_model import Question

QUESTION = Question(id="q1", question="Quel est le total ?")
ANSWER = DraftAnswer(
    answer="x",
    status=AnswerStatus.ANSWERED,
    citations=["doc_a"],
    evidence_sufficient=True,
)


def _hit(doc_id: str) -> SearchHit:
    chunk = Chunk(
        doc_id=doc_id,
        chunk_id=f"{doc_id}#0",
        chunk_kind=ChunkKind.TEXT,
        doc_type="unknown",
        doc_date=None,
        identifiers=[],
        lang="fr",
        text=doc_id,
    )
    return SearchHit(chunk, 1.0)


class FakeSearch:
    def hybrid_search(
        self, query: str, filters: SearchFilters | None, k: int
    ) -> list[SearchHit]:
        return []

    def list_by_filter(
        self, filters: SearchFilters, cap: int
    ) -> list[SearchHit]:
        return []


class FakeLlm:
    def __init__(self) -> None:
        self.calls: list[Messages] = []

    def complete_json(
        self, messages: Messages, schema: type[DraftAnswer]
    ) -> DraftAnswer:
        self.calls.append(messages)
        return ANSWER


def test_policies_differ_in_drafts_and_expansion() -> None:
    assert HopPolicy.multi_hop().max_drafts == 3
    assert HopPolicy.multi_hop().expand_upfront
    assert HopPolicy.safety_net().max_drafts == 2
    assert not HopPolicy.safety_net().expand_upfront


def test_seeded_first_draft_is_returned_without_an_llm_call() -> None:
    llm = FakeLlm()
    gateway: LlmGateway = llm  # type: ignore[assignment]
    hits = [_hit(f"doc_{n:02d}") for n in range(MAX_PROMPT_CHUNKS + 2)]

    result = run_hops(
        QUESTION,
        hits,
        FakeSearch(),
        gateway,
        HopPolicy.safety_net(),
        first_draft=ANSWER,
    )

    assert result.draft == ANSWER
    assert result.hits == hits[:MAX_PROMPT_CHUNKS]
    assert llm.calls == []


def test_without_a_seed_one_draft_is_made() -> None:
    llm = FakeLlm()
    gateway: LlmGateway = llm  # type: ignore[assignment]

    result = run_hops(
        QUESTION,
        [_hit("doc_a")],
        FakeSearch(),
        gateway,
        HopPolicy.multi_hop(),
    )

    assert result.draft == ANSWER
    assert len(llm.calls) == 1
