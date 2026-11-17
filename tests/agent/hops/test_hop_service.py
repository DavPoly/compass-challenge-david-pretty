import logging

import pytest

from archive.agent.hops import hop_service
from archive.agent.hops.hop_constants import (
    HOP_LOG_MISSING_MAX_CHARS,
    HOP_NEW_HITS_MAX,
    MIN_ORIGINAL_SLOTS,
    MISSING_QUERY_MAX_CHARS,
)
from archive.agent.hops.hop_model import HopPolicy
from archive.agent.hops.hop_service import run_hops
from archive.agent.prompt_constants import (
    MAX_PROMPT_CHUNKS,
    NO_DOCUMENTS_MISSING,
)
from archive.agent.recipes.recipe_model import RecipeResult
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


def _hit(doc_id: str, identifiers: list[str] | None = None) -> SearchHit:
    chunk = Chunk(
        doc_id=doc_id,
        chunk_id=f"{doc_id}#0",
        chunk_kind=ChunkKind.TEXT,
        doc_type="unknown",
        doc_date=None,
        identifiers=identifiers or [],
        lang="fr",
        text=doc_id,
    )
    return SearchHit(chunk, 1.0)


def _gap(missing: str | None = "email of Xavier") -> DraftAnswer:
    return ANSWER.model_copy(
        update={"evidence_sufficient": False, "missing": missing}
    )


def _doc_ids(result: RecipeResult) -> list[str]:
    return [hit.chunk.doc_id for hit in result.hits]


class FakeSearch:
    """Returns a fresh chunk per search when `growing`, else fixed hits."""

    def __init__(
        self, plain: list[SearchHit] | None = None, growing: bool = False
    ) -> None:
        self.plain = plain or []
        self.growing = growing
        self.queries: list[tuple[str, SearchFilters | None, int]] = []

    def hybrid_search(
        self, query: str, filters: SearchFilters | None, k: int
    ) -> list[SearchHit]:
        self.queries.append((query, filters, k))
        if self.growing:
            return [_hit(f"doc_new{len(self.queries)}")]
        return [] if filters else self.plain

    def list_by_filter(
        self, filters: SearchFilters, cap: int
    ) -> list[SearchHit]:
        return []


class FakeLlm:
    def __init__(self, *drafts: DraftAnswer) -> None:
        self.drafts = list(drafts) or [ANSWER]
        self.calls: list[Messages] = []

    def complete_json(
        self, messages: Messages, schema: type[DraftAnswer]
    ) -> DraftAnswer:
        self.calls.append(messages)
        index = min(len(self.calls), len(self.drafts)) - 1
        return self.drafts[index]

    def user_prompt(self, call_index: int) -> str:
        return str(self.calls[call_index][1]["content"])


class FakeClock:
    def __init__(self, *ticks: float) -> None:
        self.ticks = list(ticks)

    def __call__(self) -> float:
        return self.ticks.pop(0) if len(self.ticks) > 1 else self.ticks[0]


def _patch_expand(
    monkeypatch: pytest.MonkeyPatch, found: list[SearchHit]
) -> list[int]:
    calls: list[int] = []

    def fake_expand(
        question: Question, hits: list[SearchHit], search: object
    ) -> list[SearchHit]:
        calls.append(len(hits))
        return list(found)

    monkeypatch.setattr(hop_service, "expand_by_identifiers", fake_expand)
    return calls


@pytest.fixture(autouse=True)
def _no_expansion(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_expand(monkeypatch, [])


def _run(
    llm: FakeLlm,
    search: FakeSearch,
    policy: HopPolicy,
    hits: list[SearchHit] | None = None,
    first_draft: DraftAnswer | None = None,
) -> RecipeResult:
    gateway: LlmGateway = llm  # type: ignore[assignment]
    return run_hops(
        QUESTION,
        hits if hits is not None else [_hit("doc_a")],
        search,
        gateway,
        policy,
        first_draft=first_draft,
    )


def test_policies_differ_in_drafts_and_expansion() -> None:
    assert HopPolicy.multi_hop().max_drafts == 3
    assert HopPolicy.multi_hop().expand_upfront
    assert HopPolicy.safety_net().max_drafts == 2
    assert not HopPolicy.safety_net().expand_upfront


def test_seeded_sufficient_draft_makes_no_llm_call() -> None:
    llm = FakeLlm()
    hits = [_hit(f"doc_{n:02d}") for n in range(MAX_PROMPT_CHUNKS + 2)]

    result = _run(
        llm, FakeSearch(), HopPolicy.safety_net(), hits, first_draft=ANSWER
    )

    assert result.draft == ANSWER
    assert result.hits == hits[:MAX_PROMPT_CHUNKS]
    assert llm.calls == []


def test_sufficient_draft_stops_after_one_call() -> None:
    llm = FakeLlm(ANSWER)

    result = _run(llm, FakeSearch(), HopPolicy.multi_hop())

    assert len(llm.calls) == 1
    assert result.draft == ANSWER


def test_blank_missing_stops_the_loop() -> None:
    llm = FakeLlm(_gap("   "))
    search = FakeSearch(plain=[_hit("doc_b")])

    _run(llm, search, HopPolicy.multi_hop())

    assert len(llm.calls) == 1
    assert search.queries == []


def test_not_found_despite_sufficient_does_not_follow_up() -> None:
    lead = ANSWER.model_copy(
        update={
            "status": AnswerStatus.NOT_FOUND,
            "evidence_sufficient": True,
            "missing": "email of Lea Frechette",
        }
    )
    llm = FakeLlm(lead)
    search = FakeSearch(plain=[_hit("doc_b")])

    _run(llm, search, HopPolicy.multi_hop())

    assert len(llm.calls) == 1
    assert search.queries == []


def test_sentinel_missing_never_follows_up() -> None:
    llm = FakeLlm(_gap(f"  {NO_DOCUMENTS_MISSING} "))
    search = FakeSearch(plain=[_hit("doc_b")])

    _run(llm, search, HopPolicy.multi_hop())

    assert len(llm.calls) == 1
    assert search.queries == []


def test_no_original_hits_never_follows_up() -> None:
    llm = FakeLlm(_gap())
    search = FakeSearch(plain=[_hit("doc_b")])

    _run(llm, search, HopPolicy.multi_hop(), hits=[])

    assert search.queries == []


def test_note_reaches_every_draft() -> None:
    llm = FakeLlm(_gap(), ANSWER)
    gateway: LlmGateway = llm  # type: ignore[assignment]

    run_hops(
        QUESTION,
        [_hit("doc_a")],
        FakeSearch(plain=[_hit("doc_b")]),
        gateway,
        HopPolicy.multi_hop(),
        note="use the newest",
    )

    assert len(llm.calls) == 2
    assert all("use the newest" in llm.user_prompt(n) for n in range(2))


def test_answered_sufficient_with_missing_does_not_follow_up() -> None:
    done = ANSWER.model_copy(update={"missing": "something"})
    llm = FakeLlm(done)
    search = FakeSearch(plain=[_hit("doc_b")])

    _run(llm, search, HopPolicy.multi_hop())

    assert len(llm.calls) == 1
    assert search.queries == []


def test_not_found_with_blank_missing_stops_the_loop() -> None:
    lead = ANSWER.model_copy(
        update={
            "status": AnswerStatus.NOT_FOUND,
            "evidence_sufficient": True,
            "missing": " ",
        }
    )
    llm = FakeLlm(lead)

    _run(llm, FakeSearch(plain=[_hit("doc_b")]), HopPolicy.multi_hop())

    assert len(llm.calls) == 1


def test_none_missing_stops_the_loop() -> None:
    llm = FakeLlm(_gap(None))

    _run(llm, FakeSearch(plain=[_hit("doc_b")]), HopPolicy.multi_hop())

    assert len(llm.calls) == 1


def test_every_draft_logs_one_line_with_truncated_missing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    long_missing = "x" * (HOP_LOG_MISSING_MAX_CHARS + 50) + "\nforged"
    llm = FakeLlm(_gap(long_missing), ANSWER)
    search = FakeSearch(plain=[_hit("doc_b")])

    with caplog.at_level(logging.INFO, logger=hop_service.logger.name):
        _run(llm, search, HopPolicy.multi_hop())

    lines = [
        record.getMessage()
        for record in caplog.records
        if " draft " in record.getMessage()
    ]
    assert len(lines) == 2
    assert lines[0].startswith(f"question {QUESTION.id}: draft 1 ")
    assert repr("x" * HOP_LOG_MISSING_MAX_CHARS) in lines[0]
    assert "forged" not in lines[0]
    assert lines[1].startswith(f"question {QUESTION.id}: draft 2 ")


def test_no_new_chunk_stops_the_loop() -> None:
    llm = FakeLlm(_gap())
    search = FakeSearch(plain=[_hit("doc_a")])

    result = _run(llm, search, HopPolicy.multi_hop())

    assert len(llm.calls) == 1
    assert result.draft == _gap()


def test_follow_up_prompt_lists_targeted_hits_first() -> None:
    llm = FakeLlm(_gap(), ANSWER)
    search = FakeSearch(plain=[_hit("doc_new")])

    result = _run(llm, search, HopPolicy.multi_hop())

    second = llm.user_prompt(1)
    assert second.index("doc_new") < second.index("doc_a")
    assert result.draft == ANSWER


def test_result_hits_are_the_union_across_hops() -> None:
    llm = FakeLlm(_gap(), _gap("again"), ANSWER)

    result = _run(llm, FakeSearch(growing=True), HopPolicy.multi_hop())

    assert len(llm.calls) == 3
    assert _doc_ids(result)[0] == "doc_a"
    assert len(result.hits) == len({hit.chunk.chunk_id for hit in result.hits})
    assert len(result.hits) == 1 + 2 * 2


def test_draft_count_never_exceeds_max_drafts() -> None:
    llm = FakeLlm(_gap())

    _run(llm, FakeSearch(growing=True), HopPolicy.multi_hop())

    assert len(llm.calls) == HopPolicy.multi_hop().max_drafts


def test_seeded_draft_counts_toward_max_drafts() -> None:
    llm = FakeLlm(_gap())

    _run(
        llm,
        FakeSearch(growing=True),
        HopPolicy.safety_net(),
        first_draft=_gap(),
    )

    assert len(llm.calls) == HopPolicy.safety_net().max_drafts - 1


def test_time_budget_blocks_a_new_draft() -> None:
    llm = FakeLlm(_gap(), ANSWER)
    policy = HopPolicy(
        max_drafts=3,
        expand_upfront=False,
        time_budget_s=10.0,
        clock=FakeClock(0.0, 10.0),
    )

    result = _run(llm, FakeSearch(plain=[_hit("doc_b")]), policy)

    assert len(llm.calls) == 1
    assert result.draft == _gap()


def test_upfront_expansion_runs_once_before_first_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_expand(monkeypatch, [_hit("doc_sheet")])
    llm = FakeLlm(_gap(), ANSWER)

    _run(llm, FakeSearch(plain=[_hit("doc_b")]), HopPolicy.multi_hop())

    first = llm.user_prompt(0)
    assert first.index("doc_sheet") < first.index("doc_a")
    assert len(calls) == 1


def test_safety_net_expands_only_on_the_first_follow_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_expand(monkeypatch, [_hit("doc_sheet")])
    llm = FakeLlm(ANSWER)

    result = _run(
        llm, FakeSearch(), HopPolicy.safety_net(), first_draft=_gap()
    )

    assert calls == [1]
    assert "doc_sheet" in llm.user_prompt(0)
    assert _doc_ids(result) == ["doc_a", "doc_sheet"]


def test_follow_up_query_is_trimmed_and_typed() -> None:
    llm = FakeLlm(_gap("  " + "x" * 500), ANSWER)
    search = FakeSearch(plain=[_hit("doc_b")])

    _run(llm, search, HopPolicy.multi_hop())

    assert {len(query) for query, _, _ in search.queries} == {
        MISSING_QUERY_MAX_CHARS
    }
    typed = [f for _, f, _ in search.queries if f is not None]
    assert typed[0].doc_types == ["directory", "project_sheet", "contract"]


def _promotion_prompt_ids(
    monkeypatch: pytest.MonkeyPatch,
    targeted_codes: list[str],
    charter_codes: list[str],
) -> list[str]:
    originals = [_hit(f"doc_{n:02d}") for n in range(MAX_PROMPT_CHUNKS)]
    originals.append(_hit("doc_charter", charter_codes))
    _patch_expand(monkeypatch, [_hit("doc_target", targeted_codes)])

    result = _run(
        FakeLlm(), FakeSearch(), HopPolicy.multi_hop(), hits=originals
    )

    return _doc_ids(result)


def test_original_sharing_a_code_with_targeted_is_promoted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = _promotion_prompt_ids(monkeypatch, ["BRV-1"], ["BRV-1"])

    assert ids[:2] == ["doc_target", "doc_charter"]
    assert len(ids) == MAX_PROMPT_CHUNKS


def test_email_only_overlap_does_not_promote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = _promotion_prompt_ids(monkeypatch, ["a@b.fr"], ["a@b.fr"])

    assert "doc_charter" not in ids


def test_no_targeted_hits_keeps_original_order() -> None:
    originals = [_hit("doc_a"), _hit("doc_b", ["BRV-1"]), _hit("doc_c")]

    result = _run(
        FakeLlm(), FakeSearch(), HopPolicy.multi_hop(), hits=originals
    )

    assert _doc_ids(result) == ["doc_a", "doc_b", "doc_c"]


def test_many_targeted_hits_keep_originals_and_earlier_hops() -> None:
    first = [_hit(f"doc_t{n:02d}") for n in range(HOP_NEW_HITS_MAX + 4)]
    second = [_hit(f"doc_u{n:02d}") for n in range(HOP_NEW_HITS_MAX + 4)]

    class TwoHopSearch(FakeSearch):
        def hybrid_search(
            self, query: str, filters: SearchFilters | None, k: int
        ) -> list[SearchHit]:
            self.queries.append((query, filters, k))
            return (
                []
                if filters
                else (first, second)[(len(self.queries) - 1) // 2]
            )

    originals = [_hit(f"doc_o{n:02d}") for n in range(MAX_PROMPT_CHUNKS)]
    llm = FakeLlm(_gap(), _gap("again"), ANSWER)

    _run(llm, TwoHopSearch(), HopPolicy.multi_hop(), hits=originals)

    last = llm.user_prompt(2)
    assert last.count("<document ") == MAX_PROMPT_CHUNKS
    assert "doc_o00" in last
    assert last.count("doc_o") >= MIN_ORIGINAL_SLOTS
    assert "doc_u00" in last and "doc_t00" in last
    assert last.index("doc_u00") < last.index("doc_t00")
    assert f"doc_t{HOP_NEW_HITS_MAX:02d}" not in last


def test_targeted_but_unprompted_hit_is_not_new(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    targeted = [_hit(f"doc_t{n:02d}") for n in range(MAX_PROMPT_CHUNKS)]
    _patch_expand(monkeypatch, targeted)
    llm = FakeLlm(_gap())
    cut_off = targeted[-1]

    result = _run(llm, FakeSearch(plain=[cut_off]), HopPolicy.multi_hop())

    assert "doc_t15" not in llm.user_prompt(0)
    assert len(llm.calls) == 1
    assert cut_off not in result.hits


def _not_found(missing: str | None = None) -> DraftAnswer:
    return ANSWER.model_copy(
        update={
            "status": AnswerStatus.NOT_FOUND,
            "evidence_sufficient": False,
            "missing": missing,
        }
    )


def test_final_not_found_keeps_an_earlier_answered_draft() -> None:
    partial = _gap().model_copy(update={"answer": "partial"})
    llm = FakeLlm(partial, _not_found())

    result = _run(
        llm, FakeSearch(plain=[_hit("doc_b")]), HopPolicy.multi_hop()
    )

    assert len(llm.calls) == 2
    assert result.draft == partial
    assert _doc_ids(result) == ["doc_a", "doc_b"]


def test_final_not_found_keeps_the_seeded_answered_draft() -> None:
    seeded = _gap().model_copy(update={"answer": "seeded"})
    llm = FakeLlm(_not_found())

    result = _run(
        llm,
        FakeSearch(plain=[_hit("doc_b")]),
        HopPolicy.safety_net(),
        first_draft=seeded,
    )

    assert result.draft == seeded


def test_not_found_without_earlier_answer_is_returned() -> None:
    lead = _not_found("email of Xavier")
    llm = FakeLlm(lead, _not_found())

    result = _run(
        llm, FakeSearch(plain=[_hit("doc_b")]), HopPolicy.multi_hop()
    )

    assert result.draft == _not_found()
