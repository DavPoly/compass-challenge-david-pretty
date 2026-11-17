from typing import Any, cast

import pytest

from archive.agent.recipes import superseded_service
from archive.agent.recipes.superseded_service import (
    PolicyChoice,
    run_superseded,
)
from archive.agent.route.route_model import QuestionFamily, QuestionPlan
from archive.common.chunk_model import Chunk, ChunkKind
from archive.llm.llm_gateway import LlmGateway, LlmUnavailableError
from archive.retrieval.search_service import SearchFilters, SearchHit
from archive.validation.input_model import Question

QUESTION = Question(id="q1", question="Taux de la politique ?")
SERIES = "politique de frais"


def _hit(
    doc_id: str,
    version: str | None = None,
    start: str | None = None,
    end: str | None = None,
    series: str | None = SERIES,
) -> SearchHit:
    chunk = Chunk(
        doc_id=doc_id,
        chunk_id=f"{doc_id}#0",
        chunk_kind=ChunkKind.TEXT,
        doc_type="policy",
        doc_date=None,
        identifiers=[],
        lang="fr",
        text=doc_id,
        version=version,
        effective_from=start,
        effective_to=end,
        series=series,
    )
    return SearchHit(chunk, 1.0)


V1 = _hit("doc_v1", "1", "2020-01-01", "2022-01-01")
V2 = _hit("doc_v2", "2", "2022-01-01", "2024-01-01")
V3 = _hit("doc_v3", "3", "2024-01-01", "2027-01-01")
V4 = _hit("doc_v4", "4", "2027-01-01")
OTHER = _hit("doc_other", "1", "2021-01-01", series="autre politique")
TODAY = "2026-11-17"


class FakeSearch:
    def __init__(self, listed: list[SearchHit]) -> None:
        self.listed = listed
        self.queries: list[str] = []

    def hybrid_search(
        self, query: str, filters: SearchFilters | None, k: int
    ) -> list[SearchHit]:
        self.queries.append(query)
        return [V3, OTHER]

    def list_by_filter(
        self, filters: SearchFilters, cap: int
    ) -> list[SearchHit]:
        return self.listed


class FakeLlm:
    def __init__(self, number: int | None = 1, fails: bool = False) -> None:
        self.number = number
        self.fails = fails
        self.prompt = ""

    def complete_json(self, messages: Any, schema: Any) -> PolicyChoice:
        self.prompt = "\n".join(message["content"] for message in messages)
        if self.fails:
            raise LlmUnavailableError("down")
        return PolicyChoice(series_number=self.number)


@pytest.fixture(autouse=True)
def _fixed_today(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(superseded_service, "_today", lambda: TODAY)


def _run(
    as_of: str | None,
    llm: FakeLlm | None = None,
    listed: list[SearchHit] | None = None,
    topic: str | None = None,
) -> tuple[list[str], str | None] | None:
    plan = QuestionPlan(
        family=QuestionFamily.SUPERSEDED, as_of_date=as_of, policy_topic=topic
    )
    search = FakeSearch([V1, V2, V3, V4, OTHER] if listed is None else listed)
    result = run_superseded(
        QUESTION, plan, search, cast(LlmGateway, llm or FakeLlm())
    )
    if result is None:
        return None
    return [hit.chunk.doc_id for hit in result.hits], result.note


def test_date_inside_a_version_picks_it() -> None:
    outcome = _run("2023-05-01")

    assert outcome is not None
    assert outcome[0][0] == "doc_v2"


def test_date_on_the_boundary_picks_the_next_version() -> None:
    outcome = _run("2022-01-01")

    assert outcome is not None
    assert outcome[0][0] == "doc_v2"


def test_date_before_every_version_returns_none() -> None:
    assert _run("2019-12-31") is None


def test_no_date_picks_the_version_in_force_today() -> None:
    outcome = _run(None)

    assert outcome is not None
    assert outcome[0][0] == "doc_v3"
    assert outcome[1] is not None and "today" in outcome[1]


def test_future_version_is_not_current_today() -> None:
    outcome = _run(None, listed=[V3, V4])

    assert outcome is not None
    assert outcome[0] == ["doc_v3", "doc_v4", "doc_other"]


def test_no_version_started_yet_returns_none() -> None:
    assert _run(None, listed=[V4]) is None


def test_llm_choice_selects_the_series() -> None:
    other_v1 = _hit("doc_o1", "1", "2020-01-01", series="autre politique")
    # series are numbered in first-seen order: 1 = SERIES, 2 = autre
    outcome = _run(None, FakeLlm(2), [V1, V2, other_v1])

    assert outcome is not None
    assert outcome[0][0] == "doc_o1"


def test_null_choice_returns_none() -> None:
    assert _run(None, FakeLlm(None)) is None


@pytest.mark.parametrize("number", [0, 3, -1])
def test_out_of_range_choice_returns_none(number: int) -> None:
    assert _run(None, FakeLlm(number)) is None


def test_llm_error_returns_none() -> None:
    assert _run(None, FakeLlm(fails=True)) is None


def test_prompt_lists_titles_and_delimited_question() -> None:
    llm = FakeLlm()

    _run(None, llm, topic="frais")

    assert f"1. {SERIES} (language: fr)" in llm.prompt
    assert "2. autre politique" in llm.prompt
    delimited = f"<question>\n{QUESTION.question}\n</question>"
    assert delimited in llm.prompt
    assert "frais" in llm.prompt


def test_hits_list_picked_then_newest_first_then_other_top_hits() -> None:
    outcome = _run("2021-06-01")

    assert outcome is not None
    assert outcome[0] == [
        "doc_v1",
        "doc_v4",
        "doc_v3",
        "doc_v2",
        "doc_other",
    ]


def test_other_series_policies_are_not_listed_as_versions() -> None:
    outcome = _run("2021-06-01", listed=[V1, V2, OTHER])

    assert outcome is not None
    assert outcome[0] == ["doc_v1", "doc_v2", "doc_v3", "doc_other"]


def test_note_names_the_picked_version() -> None:
    outcome = _run("2023-05-01")

    assert outcome is not None
    note = outcome[1] or ""
    for expected in ("doc_v2", "2022-01-01", "2024-01-01", "2023-05-01"):
        assert expected in note
    assert "superseded" in note


def test_version_without_effective_from_is_listed_not_picked() -> None:
    undated = _hit("doc_undated", "9")

    outcome = _run(None, listed=[V3, undated])

    assert outcome is not None
    assert outcome[0] == ["doc_v3", "doc_undated", "doc_other"]
