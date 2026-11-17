from archive.agent.hops.expand_service import expand_by_identifiers
from archive.agent.hops.hop_constants import EXPAND_CAP
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
        return self.listed


INVOICE = _hit("doc_2003", ["BRV-2019-22", "F-2021-1413"])
SHEET = _hit("doc_1387", ["BRV-2019-22"], "project_sheet")


def test_invoice_pivots_to_project_sheet() -> None:
    search = FakeSearch([SHEET])

    result = expand_by_identifiers(QUESTION, [INVOICE], search)

    assert [hit.chunk.doc_id for hit in result] == ["doc_1387"]
    assert search.calls[0][0].identifiers == ["BRV-2019-22", "F-2021-1413"]


def test_question_codes_come_first() -> None:
    contract = _hit("doc_1382", ["C-2023-15"], "contract")
    question = Question(id="q1", question="Que dit C-2023-15 ?")
    search = FakeSearch([SHEET, contract])

    result = expand_by_identifiers(question, [INVOICE], search)

    assert [hit.chunk.doc_id for hit in result] == ["doc_1382", "doc_1387"]
    assert search.calls[0][0].identifiers[0] == "C-2023-15"


def test_email_identifiers_are_ignored() -> None:
    mail = _hit("doc_9", ["a.b@example.com", "BRV-2019-22"])
    search = FakeSearch([])

    expand_by_identifiers(QUESTION, [mail], search)

    assert search.calls[0][0].identifiers == ["BRV-2019-22"]


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


def test_cap_is_respected() -> None:
    many = [_hit(f"doc_{n}", ["BRV-2019-22"]) for n in range(20)]
    search = FakeSearch(many)

    result = expand_by_identifiers(QUESTION, [INVOICE], search)

    assert len(result) == EXPAND_CAP
    assert search.calls[0][1] == EXPAND_CAP


def test_filters_carry_project_sheet_and_contract_types() -> None:
    search = FakeSearch([])

    expand_by_identifiers(QUESTION, [INVOICE], search)

    assert search.calls[0][0].doc_types == [
        DocType.PROJECT_SHEET.value,
        DocType.CONTRACT.value,
    ]
