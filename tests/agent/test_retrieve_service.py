import pytest

from archive.agent.retrieve_service import detect_doc_type_hints, retrieve
from archive.common.chunk_model import Chunk, ChunkKind, DocType
from archive.retrieval.search_service import SearchFilters, SearchHit


def _hit(name: str) -> SearchHit:
    chunk = Chunk(
        doc_id=name,
        chunk_id=f"{name}#0",
        chunk_kind=ChunkKind.TEXT,
        doc_type="unknown",
        doc_date=None,
        identifiers=[],
        lang="fr",
        text=name,
    )
    return SearchHit(chunk, 1.0)


class FakeSearch:
    def __init__(self, typed: list[str], plain: list[str]) -> None:
        self.typed = typed
        self.plain = plain
        self.calls: list[tuple[SearchFilters | None, int]] = []

    def hybrid_search(
        self, query: str, filters: SearchFilters | None, k: int
    ) -> list[SearchHit]:
        self.calls.append((filters, k))
        names = self.typed if filters else self.plain
        return [_hit(name) for name in names[:k]]


def _doc_ids(hits: list[SearchHit]) -> list[str]:
    return [hit.chunk.doc_id for hit in hits]


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Quel est le total de la facture F-1 ?", [DocType.INVOICE]),
        ("Was the invoice billed twice?", [DocType.INVOICE]),
        ("La politique de télétravail", [DocType.POLICY]),
        ("Which policy applies?", [DocType.POLICY]),
        ("Le contrat de Marie", [DocType.CONTRACT]),
        ("Compte rendu de la RÉUNION", [DocType.MINUTES]),
        ("Le procès-verbal du comité", [DocType.MINUTES]),
        ("Le rapport mensuel d'août", [DocType.MONTHLY_REPORT]),
        ("Dans le bottin du personnel", [DocType.DIRECTORY]),
        ("Facture et contrat", [DocType.INVOICE, DocType.CONTRACT]),
    ],
)
def test_detect_hints_fr_en_accents(
    question: str, expected: list[DocType]
) -> None:
    assert detect_doc_type_hints(question) == expected


@pytest.mark.parametrize(
    "question",
    [
        "Quelle est l'adresse courriel de Marie ?",
        "What is her email address?",
        "Quel est le salaire du poste ?",
        "Combien de projets ?",
    ],
)
def test_detect_no_hint_for_ambiguous_words(question: str) -> None:
    assert detect_doc_type_hints(question) == []


def test_no_hints_returns_plain_top_k() -> None:
    search = FakeSearch(typed=[], plain=["a", "b", "c"])

    hits = retrieve("combien ?", search, 2)

    assert _doc_ids(hits) == ["a", "b"]
    assert search.calls == [(None, 2)]


def test_typed_hits_come_first_then_unfiltered() -> None:
    search = FakeSearch(typed=["t1", "t2"], plain=["a", "b", "c", "d"])

    hits = retrieve("la facture", search, 4)

    assert _doc_ids(hits) == ["t1", "t2", "a", "b"]
    assert search.calls[0] == (SearchFilters(doc_types=["invoice"]), 2)


def test_typed_empty_falls_back_to_unfiltered() -> None:
    search = FakeSearch(typed=[], plain=["a", "b", "c"])

    hits = retrieve("la facture", search, 3)

    assert _doc_ids(hits) == ["a", "b", "c"]


def test_duplicates_across_searches_are_dropped() -> None:
    search = FakeSearch(typed=["a", "b"], plain=["a", "b", "c", "d"])

    hits = retrieve("la facture", search, 4)

    assert _doc_ids(hits) == ["a", "b", "c", "d"]


def test_never_returns_more_than_k() -> None:
    search = FakeSearch(typed=["t", "u", "v"], plain=list("abcdef"))

    assert len(retrieve("la facture", search, 5)) == 5


def test_k_smaller_than_typed_slots() -> None:
    search = FakeSearch(typed=["t1", "t2"], plain=["a", "b"])

    hits = retrieve("la facture", search, 1)

    assert _doc_ids(hits) == ["t1"]
    assert search.calls == [(SearchFilters(doc_types=["invoice"]), 1)]


def test_non_positive_k_returns_nothing() -> None:
    search = FakeSearch(typed=["t"], plain=["a"])

    assert retrieve("la facture", search, 0) == []
    assert search.calls == []
