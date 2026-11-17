from archive.agent.recipes.superseded_service import run_superseded
from archive.agent.route.route_model import QuestionFamily, QuestionPlan
from archive.common.chunk_model import Chunk, ChunkKind
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
V3 = _hit("doc_v3", "3", "2024-01-01")
OTHER = _hit("doc_other", "1", "2021-01-01", series="autre politique")


class FakeSearch:
    def __init__(
        self, ranked: list[SearchHit], listed: list[SearchHit]
    ) -> None:
        self.ranked = ranked
        self.listed = listed

    def hybrid_search(
        self, query: str, filters: SearchFilters | None, k: int
    ) -> list[SearchHit]:
        return self.ranked

    def list_by_filter(
        self, filters: SearchFilters, cap: int
    ) -> list[SearchHit]:
        return self.listed


def _run(
    as_of: str | None,
    ranked: list[SearchHit] | None = None,
) -> tuple[list[str], str | None] | None:
    plan = QuestionPlan(family=QuestionFamily.SUPERSEDED, as_of_date=as_of)
    search = FakeSearch(
        [V2, OTHER] if ranked is None else ranked, [V1, V2, V3, OTHER]
    )
    result = run_superseded(QUESTION, plan, search)
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


def test_no_date_picks_the_latest_version() -> None:
    outcome = _run(None)

    assert outcome is not None
    assert outcome[0][0] == "doc_v3"
    assert outcome[1] is not None and "today" in outcome[1]


def test_no_series_hit_returns_none() -> None:
    assert _run(None, ranked=[_hit("doc_x", series=None)]) is None
    assert _run(None, ranked=[]) is None


def test_hits_list_picked_then_newest_first_then_other_top_hits() -> None:
    outcome = _run("2021-06-01", ranked=[V2, OTHER])

    assert outcome is not None
    assert outcome[0] == ["doc_v1", "doc_v3", "doc_v2", "doc_other"]


def test_other_series_policies_are_not_listed_as_versions() -> None:
    outcome = _run("2021-06-01", ranked=[V2])

    assert outcome is not None
    assert outcome[0] == ["doc_v1", "doc_v3", "doc_v2"]


def test_note_names_the_picked_version() -> None:
    outcome = _run("2023-05-01")

    assert outcome is not None
    note = outcome[1] or ""
    for expected in ("doc_v2", "2022-01-01", "2024-01-01", "2023-05-01"):
        assert expected in note
    assert "superseded" in note


def test_version_without_effective_from_is_listed_not_picked() -> None:
    undated = _hit("doc_undated", "9")
    plan = QuestionPlan(family=QuestionFamily.SUPERSEDED)
    search = FakeSearch([V3], [V3, undated])

    result = run_superseded(QUESTION, plan, search)

    assert result is not None
    assert [hit.chunk.doc_id for hit in result.hits] == [
        "doc_v3",
        "doc_undated",
    ]
