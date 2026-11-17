from archive.agent.hops.expand_service import expand_by_identifiers
from archive.agent.hops.hop_constants import (
    EXPAND_CAP,
    EXPAND_MAX_CODES,
    EXPAND_PER_CODE_CAP,
)
from archive.common.chunk_model import Chunk, ChunkKind, DocType
from archive.retrieval.search_service import SearchFilters, SearchHit
from archive.validation.input_model import Question

QUESTION = Question(id="q1", question="Qui pilote le projet ?")


def _hit(
    doc_id: str, identifiers: list[str], doc_type: str = "invoice"
) -> SearchHit:
    chunk = Chunk(
        doc_id=doc_id,
        chunk_id=f"{doc_id}#0",
        chunk_kind=ChunkKind.TEXT,
        doc_type=doc_type,
        doc_date=None,
        identifiers=identifiers,
        lang="fr",
        text=doc_id,
    )
    return SearchHit(chunk, 1.0)


class FakeSearch:
    def __init__(self, listed: list[SearchHit]) -> None:
        self.listed = listed
        self.calls: list[tuple[SearchFilters, int]] = []

    def hybrid_search(
        self, query: str, filters: SearchFilters | None, k: int
    ) -> list[SearchHit]:
        return []

    def list_by_filter(
        self, filters: SearchFilters, cap: int
    ) -> list[SearchHit]:
        self.calls.append((filters, cap))
        codes = filters.identifiers or []
        matching = [
            hit
            for hit in self.listed
            if any(code in hit.chunk.identifiers for code in codes)
        ]
        return matching[:cap]

    def codes_searched(self) -> list[str]:
        return [call[0].identifiers[0] for call in self.calls]


INVOICE = _hit("doc_2003", ["BRV-2019-22", "F-2021-1413"])
SHEET = _hit("doc_1387", ["BRV-2019-22"], "project_sheet")


def test_invoice_pivots_to_project_sheet() -> None:
    search = FakeSearch([SHEET])

    result = expand_by_identifiers(QUESTION, [INVOICE], search)

    assert [hit.chunk.doc_id for hit in result] == ["doc_1387"]
    assert search.codes_searched() == ["BRV-2019-22", "F-2021-1413"]


def test_question_codes_come_first() -> None:
    contract = _hit("doc_1382", ["C-2023-15"], "contract")
    question = Question(id="q1", question="Que dit C-2023-15 ?")
    search = FakeSearch([SHEET, contract])

    result = expand_by_identifiers(question, [INVOICE], search)

    assert [hit.chunk.doc_id for hit in result] == ["doc_1382", "doc_1387"]
    assert search.codes_searched()[0] == "C-2023-15"


def test_email_identifiers_are_ignored() -> None:
    mail = _hit("doc_9", ["a.b@example.com", "BRV-2019-22"])
    search = FakeSearch([])

    expand_by_identifiers(QUESTION, [mail], search)

    assert search.codes_searched() == ["BRV-2019-22"]


def test_only_emails_means_no_search() -> None:
    mail = _hit("doc_9", ["a.b@example.com"])
    search = FakeSearch([SHEET])

    assert expand_by_identifiers(QUESTION, [mail], search) == []
    assert search.calls == []


def test_no_codes_returns_empty_without_search() -> None:
    search = FakeSearch([SHEET])

    assert expand_by_identifiers(QUESTION, [], search) == []
    assert search.calls == []


def test_chunks_already_in_hits_are_dropped() -> None:
    search = FakeSearch([SHEET, INVOICE])

    result = expand_by_identifiers(QUESTION, [INVOICE], search)

    assert [hit.chunk.chunk_id for hit in result] == ["doc_1387#0"]


def test_per_code_listing_stops_at_expand_cap() -> None:
    codes = [f"BRV-2020-{n}" for n in range(EXPAND_MAX_CODES)]
    listed = [
        _hit(f"doc_{code}_{n}", [code], "contract")
        for code in codes
        for n in range(EXPAND_PER_CODE_CAP)
    ]
    hits = [_hit(f"inv_{n}", [code]) for n, code in enumerate(codes)]
    search = FakeSearch(listed)

    result = expand_by_identifiers(QUESTION, hits, search)

    assert len(result) == EXPAND_CAP
    assert len(search.calls) == EXPAND_CAP // EXPAND_PER_CODE_CAP
    assert all(call[1] == EXPAND_PER_CODE_CAP for call in search.calls)


def test_shared_code_from_low_ranks_precedes_top_hit_codes() -> None:
    hits = [
        _hit("c1", ["BRV-2020-1"], "contract"),
        _hit("c2", ["BRV-2020-2"], "contract"),
        _hit("c3", ["BRV-2020-3"], "contract"),
        _hit("charter", ["BRV-2023-14"], "project_sheet"),
        _hit("annex", ["BRV-2023-14"], "project_sheet"),
    ]
    target = _hit("doc_1382", ["BRV-2023-14"], "contract")
    search = FakeSearch([target])

    result = expand_by_identifiers(QUESTION, hits, search)

    assert search.codes_searched()[0] == "BRV-2023-14"
    assert [hit.chunk.doc_id for hit in result] == ["doc_1382"]


def test_question_codes_precede_shared_codes() -> None:
    hits = [
        _hit("a", ["BRV-2023-14"]),
        _hit("b", ["BRV-2023-14"]),
    ]
    question = Question(id="q1", question="Que dit C-2023-15 ?")
    search = FakeSearch([])

    expand_by_identifiers(question, hits, search)

    assert search.codes_searched() == ["C-2023-15", "BRV-2023-14"]


def test_code_count_is_capped() -> None:
    hits = [
        _hit(f"d{n}", [f"BRV-2020-{n}"]) for n in range(EXPAND_MAX_CODES + 3)
    ]
    hits[0] = _hit("d0", [f"BRV-2020-{n}" for n in range(20)])
    search = FakeSearch([])

    expand_by_identifiers(QUESTION, hits, search)

    assert len(search.calls) == EXPAND_MAX_CODES


def test_filters_carry_project_sheet_and_contract_types() -> None:
    search = FakeSearch([])

    expand_by_identifiers(QUESTION, [INVOICE], search)

    assert search.calls[0][0].doc_types == [
        DocType.PROJECT_SHEET.value,
        DocType.CONTRACT.value,
    ]
