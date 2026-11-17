import pytest

from archive.agent import answer_service
from archive.agent.answer_service import answer_question
from archive.agent.hops.hop_model import HopPolicy
from archive.agent.prompt_constants import MAX_PROMPT_CHUNKS
from archive.agent.recipes.recipe_model import RecipeResult
from archive.agent.route.route_model import QuestionFamily, QuestionPlan
from archive.common.chunk_model import Chunk, ChunkKind
from archive.llm.llm_gateway import LlmGateway, Messages
from archive.retrieval.search_service import SearchFilters, SearchHit
from archive.validation.answer_model import AnswerStatus, DraftAnswer
from archive.validation.input_model import Question

QUESTION = Question(id="q1", question="Quel est le total ?")
LLM_ANSWER = DraftAnswer(
    answer="llm",
    status=AnswerStatus.ANSWERED,
    citations=["doc_a"],
    evidence_sufficient=True,
)
RECIPE_ANSWER = LLM_ANSWER.model_copy(update={"answer": "recipe"})


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
        return [_hit("doc_a")]

    def list_by_filter(
        self, filters: SearchFilters, cap: int
    ) -> list[SearchHit]:
        return []


class FakeLlm:
    def __init__(self, answer: DraftAnswer = LLM_ANSWER) -> None:
        self.calls: list[Messages] = []
        self.answer = answer

    def complete_json(
        self, messages: Messages, schema: type[DraftAnswer]
    ) -> DraftAnswer:
        self.calls.append(messages)
        return self.answer


def _plan_as(monkeypatch: pytest.MonkeyPatch, family: QuestionFamily) -> None:
    monkeypatch.setattr(
        answer_service,
        "plan_question",
        lambda question, llm: QuestionPlan(family=family),
    )


def _run(llm: FakeLlm) -> tuple[DraftAnswer, set[str]]:
    gateway: LlmGateway = llm  # type: ignore[assignment]
    return answer_question(QUESTION, FakeSearch(), gateway)


def test_direct_path_retrieves_then_drafts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _plan_as(monkeypatch, QuestionFamily.DIRECT)
    llm = FakeLlm()

    answer, retrieved_ids = _run(llm)

    assert answer == LLM_ANSWER
    assert retrieved_ids == {"doc_a"}
    assert len(llm.calls) == 1


def test_recipe_returning_none_falls_back_to_direct(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _plan_as(monkeypatch, QuestionFamily.SUPERSEDED)
    monkeypatch.setattr(answer_service, "run_superseded", lambda *args: None)
    llm = FakeLlm()

    answer, retrieved_ids = _run(llm)

    assert answer == LLM_ANSWER
    assert retrieved_ids == {"doc_a"}


def test_recipe_draft_skips_the_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _plan_as(monkeypatch, QuestionFamily.AGGREGATION)
    result = RecipeResult(hits=[_hit("doc_b")], draft=RECIPE_ANSWER)
    monkeypatch.setattr(
        answer_service, "run_aggregation", lambda *args: result
    )
    llm = FakeLlm()

    answer, retrieved_ids = _run(llm)

    assert answer == RECIPE_ANSWER
    assert retrieved_ids == {"doc_b"}
    assert llm.calls == []


def test_recipe_note_reaches_the_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _plan_as(monkeypatch, QuestionFamily.SUPERSEDED)
    result = RecipeResult(hits=[_hit("doc_c")], note="v2 is in force")
    monkeypatch.setattr(answer_service, "run_superseded", lambda *args: result)
    llm = FakeLlm()

    _, retrieved_ids = _run(llm)

    assert retrieved_ids == {"doc_c"}
    assert "Note: v2 is in force" in llm.calls[0][1]["content"]


def test_draft_path_ids_are_only_the_hits_in_the_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _plan_as(monkeypatch, QuestionFamily.DIRECT)
    hits = [_hit(f"doc_{n:02d}") for n in range(MAX_PROMPT_CHUNKS + 3)]
    monkeypatch.setattr(answer_service, "retrieve", lambda *args: hits)

    _, retrieved_ids = _run(FakeLlm())

    assert retrieved_ids == {f"doc_{n:02d}" for n in range(MAX_PROMPT_CHUNKS)}


def test_recipe_with_its_own_draft_keeps_all_its_hits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _plan_as(monkeypatch, QuestionFamily.AGGREGATION)
    hits = [_hit(f"inv_{n:02d}") for n in range(MAX_PROMPT_CHUNKS + 3)]
    result = RecipeResult(hits=hits, draft=RECIPE_ANSWER)
    monkeypatch.setattr(
        answer_service, "run_aggregation", lambda *args: result
    )

    _, retrieved_ids = _run(FakeLlm())

    assert len(retrieved_ids) == MAX_PROMPT_CHUNKS + 3


notes: list[str | None] = []


def _spy_run_hops(
    monkeypatch: pytest.MonkeyPatch, result: RecipeResult
) -> list[tuple[HopPolicy, DraftAnswer | None]]:
    seen: list[tuple[HopPolicy, DraftAnswer | None]] = []
    notes.clear()

    def fake_run_hops(
        question: Question,
        hits: list[SearchHit],
        search: object,
        llm: object,
        policy: HopPolicy,
        *,
        first_draft: DraftAnswer | None = None,
        note: str | None = None,
    ) -> RecipeResult:
        seen.append((policy, first_draft))
        notes.append(note)
        return result

    monkeypatch.setattr(answer_service, "run_hops", fake_run_hops)
    return seen


def test_multi_hop_dispatches_to_run_hops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _plan_as(monkeypatch, QuestionFamily.MULTI_HOP)
    result = RecipeResult(hits=[_hit("doc_m")], draft=RECIPE_ANSWER)
    seen = _spy_run_hops(monkeypatch, result)
    llm = FakeLlm()

    answer, retrieved_ids = _run(llm)

    assert answer == RECIPE_ANSWER
    assert retrieved_ids == {"doc_m"}
    assert [policy for policy, _ in seen] == [HopPolicy.multi_hop()]
    assert llm.calls == []


def test_sufficient_direct_draft_skips_the_safety_net(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _plan_as(monkeypatch, QuestionFamily.DIRECT)
    seen = _spy_run_hops(monkeypatch, RecipeResult(hits=[]))
    llm = FakeLlm()

    answer, retrieved_ids = _run(llm)

    assert answer == LLM_ANSWER
    assert retrieved_ids == {"doc_a"}
    assert len(llm.calls) == 1
    assert seen == []


def test_insufficient_direct_draft_runs_the_safety_net(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _plan_as(monkeypatch, QuestionFamily.DIRECT)
    first = LLM_ANSWER.model_copy(
        update={"evidence_sufficient": False, "missing": "email of Lea"}
    )
    hopped = RecipeResult(hits=[_hit("doc_n")], draft=RECIPE_ANSWER)
    seen = _spy_run_hops(monkeypatch, hopped)
    llm = FakeLlm(first)

    answer, retrieved_ids = _run(llm)

    assert answer == RECIPE_ANSWER
    assert retrieved_ids == {"doc_a", "doc_n"}
    assert len(llm.calls) == 1
    assert seen == [(HopPolicy.safety_net(), first)]


@pytest.mark.parametrize("missing", [None, "", "   "])
def test_insufficient_draft_without_missing_skips_the_safety_net(
    monkeypatch: pytest.MonkeyPatch, missing: str | None
) -> None:
    _plan_as(monkeypatch, QuestionFamily.DIRECT)
    first = LLM_ANSWER.model_copy(
        update={"evidence_sufficient": False, "missing": missing}
    )
    seen = _spy_run_hops(monkeypatch, RecipeResult(hits=[]))

    answer, _ = _run(FakeLlm(first))

    assert answer == first
    assert seen == []


def test_safety_net_receives_the_recipe_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _plan_as(monkeypatch, QuestionFamily.SUPERSEDED)
    monkeypatch.setattr(
        answer_service,
        "run_superseded",
        lambda *args: RecipeResult(hits=[_hit("doc_a")], note="newest"),
    )
    first = LLM_ANSWER.model_copy(
        update={"evidence_sufficient": False, "missing": "email of Lea"}
    )
    _spy_run_hops(monkeypatch, RecipeResult(hits=[], draft=RECIPE_ANSWER))

    _run(FakeLlm(first))

    assert notes == ["newest"]
