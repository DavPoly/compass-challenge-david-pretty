from typing import cast

import pytest

from archive.agent.recipes import aggregation_service
from archive.agent.recipes.aggregation_service import (
    ExtractedAmount,
    ExtractedAmounts,
    run_aggregation,
)
from archive.agent.recipes.recipe_model import RecipeResult
from archive.agent.route.route_model import (
    AmountMeasure,
    QuestionFamily,
    QuestionPlan,
)
from archive.common.chunk_model import Chunk, ChunkKind
from archive.llm.llm_gateway import LlmGateway, LlmUnavailableError, Messages
from archive.retrieval.search_service import SearchFilters, SearchHit
from archive.validation.answer_model import AnswerStatus, FinalAnswer
from archive.validation.answer_validator import ValidationResult
from archive.validation.grounding.grounding_model import GroundingSources
from archive.validation.grounding.grounding_service import check_grounding
from archive.validation.input_model import Question

QUESTION = Question(id="q1", question="Total facture ?")
CODE = "BRV-2021-01"
FRENCH = (
    "FACTURE N° F-1\nFacturé à : Ville de Val\n"
    "Projet : {code}\n{label} : {sub} $\nTPS : 1 $\nTOTAL : {tot} $\n"
)
ENGLISH = (
    "INVOICE No. F-2\nBill to: Wrenfield Properties Ltd.\n"
    "Project: {code}\n{label}: ${sub}\nTOTAL: ${tot}\n"
)
SHEET = (
    "Fiche de projet\nÉlément | Valeur\n"
    "Numéro de projet | {code}\nClient | X\n"
    "Chargé de projet | {manager}\n"
)
ENGLISH_SHEET = "Item | Value\nProject manager | {manager}\n"


def _hit(doc_id: str, text: str, doc_type: str, codes: list[str]) -> SearchHit:
    chunk = Chunk(
        doc_id=doc_id,
        chunk_id=f"{doc_id}#0",
        chunk_kind=ChunkKind.TEXT,
        doc_type=doc_type,
        doc_date="2023-05-01",
        identifiers=codes,
        lang="fr",
        text=text,
    )
    return SearchHit(chunk, 0.0)


def invoice(
    doc_id: str,
    code: str,
    sub: str,
    *,
    tot: str = "1",
    template: str = FRENCH,
    label: str = "Sous-total",
) -> SearchHit:
    text = template.format(code=code, sub=sub, tot=tot, label=label)
    return _hit(doc_id, text, "invoice", [code])


def typo_invoice(doc_id: str) -> SearchHit:
    return invoice(doc_id, CODE, "20,00", label="Sxxx")


def sheet(
    doc_id: str, code: str, manager: str, template: str = SHEET
) -> SearchHit:
    text = template.format(code=code, manager=manager)
    return _hit(doc_id, text, "project_sheet", [code])


class FakeSearch:
    def __init__(self, hits: list[SearchHit]) -> None:
        self.hits = hits
        self.filters: list[SearchFilters] = []

    def hybrid_search(
        self, query: str, filters: SearchFilters | None, k: int
    ) -> list[SearchHit]:
        return []

    def list_by_filter(
        self, filters: SearchFilters, cap: int
    ) -> list[SearchHit]:
        self.filters.append(filters)
        return [
            hit
            for hit in self.hits
            if hit.chunk.doc_type in filters.doc_types
            and (
                not filters.identifiers
                or set(filters.identifiers) & set(hit.chunk.identifiers)
            )
        ]


class FakeLlm:
    def __init__(
        self,
        amounts: list[ExtractedAmount] | None = None,
        fail: bool = False,
    ) -> None:
        self.amounts = amounts or []
        self.fail = fail
        self.calls: list[Messages] = []

    def complete_json(
        self, messages: Messages, schema: type[ExtractedAmounts]
    ) -> ExtractedAmounts:
        self.calls.append(messages)
        if self.fail:
            raise LlmUnavailableError("down")
        return ExtractedAmounts(amounts=self.amounts)


def _plan(**fields: object) -> QuestionPlan:
    return QuestionPlan.model_validate(
        {
            "family": QuestionFamily.AGGREGATION,
            "measure": AmountMeasure.PRE_TAX,
            **fields,
        }
    )


def _run(
    plan: QuestionPlan, hits: list[SearchHit], llm: FakeLlm | None = None
) -> RecipeResult | None:
    return run_aggregation(
        QUESTION, plan, FakeSearch(hits), cast(LlmGateway, llm or FakeLlm())
    )


def _answer(result: RecipeResult | None) -> str:
    assert result is not None and result.draft is not None
    return str(result.draft.answer)


def test_sums_client_invoices_exactly_in_both_languages() -> None:
    hits = [
        invoice("d1", CODE, "0,10"),
        invoice("d2", CODE, "47 375,20"),
        invoice("d3", CODE, "10,925.30", template=ENGLISH, label="Subtotal"),
    ]

    result = _run(_plan(client="Ville de Val"), hits)

    assert _answer(result) == "47375.30"
    assert result is not None and result.draft is not None
    assert result.draft.status is AnswerStatus.ANSWERED
    assert result.draft.citations == ["d1", "d2"]
    assert result.draft.evidence_sufficient
    assert result.draft.evidence[1].quote == "Sous-total : 47 375,20 $"
    assert result.draft.evidence[1].value == "47375.20"


def _ungrounded(
    result: RecipeResult, hits: list[SearchHit], note: str | None
) -> list[str]:
    assert result.draft is not None
    texts = {hit.chunk.doc_id: [hit.chunk.text] for hit in hits}
    validation = ValidationResult(
        answer=FinalAnswer.not_found("q"), issues=[], dropped_citations=[]
    )
    report = check_grounding(
        result.draft, GroundingSources(texts, note), validation
    )
    return report.ungrounded_values


def test_note_carries_the_sum_so_the_total_is_grounded() -> None:
    hits = [invoice("d1", CODE, "0,10"), invoice("d2", CODE, "47 375,20")]

    result = _run(_plan(client="Ville de Val"), hits)

    assert result is not None
    assert result.note == "Sum of the matching invoices: 47375.30."
    assert _ungrounded(result, hits, result.note) == []
    assert _ungrounded(result, hits, None) == ["47375.30"]


def test_decimal_sum_has_no_float_drift() -> None:
    hits = [
        invoice(f"d{n}", CODE, "0.10", template=ENGLISH, label="Subtotal")
        for n in range(3)
    ]

    result = _run(_plan(client="Wrenfield Properties"), hits)

    assert _answer(result) == "0.30"


def test_tax_included_measure_sums_the_total() -> None:
    hits = [invoice("d1", CODE, "100,00", tot="114,98")]
    plan = _plan(project_codes=[CODE], measure=AmountMeasure.TAX_INCLUDED)

    result = _run(plan, hits)

    assert _answer(result) == "114.98"
    assert result is not None and result.draft is not None
    assert result.draft.evidence[0].quote == "TOTAL : 114,98 $"


def test_missing_measure_defers_to_direct_without_listing() -> None:
    search = FakeSearch([invoice("d1", CODE, "100,00")])
    plan = _plan(project_codes=[CODE], measure=None)

    result = run_aggregation(
        QUESTION, plan, search, cast(LlmGateway, FakeLlm())
    )

    assert result is None
    assert search.filters == []


def test_no_narrowing_entity_defers_to_direct() -> None:
    hits = [invoice("d1", CODE, "100,00")]
    plan = _plan(date_from="2024-01-01", date_to="2024-12-31")

    assert _run(plan, hits) is None


def test_non_project_code_is_not_a_narrowing_entity() -> None:
    hits = [invoice("d1", CODE, "100,00")]

    assert _run(_plan(project_codes=["F-2021-1286"]), hits) is None


def test_no_matching_invoice_defers_to_direct() -> None:
    hits = [invoice("d1", CODE, "100,00")]

    assert _run(_plan(client="Nobody At All Inc."), hits) is None


def test_dates_and_codes_reach_the_search_filter() -> None:
    search = FakeSearch([invoice("d1", CODE, "1")])
    plan = _plan(
        project_codes=[CODE], date_from="2023-01-01", date_to="2023-12-31"
    )

    run_aggregation(QUESTION, plan, search, cast(LlmGateway, FakeLlm()))

    assert search.filters[0] == SearchFilters(
        doc_types=["invoice"],
        identifiers=[CODE],
        date_from="2023-01-01",
        date_to="2023-12-31",
    )


def test_duplicate_chunks_of_one_doc_count_once() -> None:
    first = invoice("d1", CODE, "100,00")

    result = _run(_plan(project_codes=[CODE]), [first, first])

    assert _answer(result) == "100.00"
    assert result is not None and len(result.hits) == 1


def test_manager_hop_collects_codes_and_cites_used_sheets() -> None:
    hits = [
        sheet("s1", "BRV-2021-01", "Olivier Gauvreau"),
        sheet("s2", "BRV-2021-02", "olivier gauvreau", ENGLISH_SHEET),
        sheet("s3", "BRV-2021-03", "Priya Lavoie"),
        sheet("s4", "BRV-2021-04", "Olivier Gauvreau"),
        invoice("d1", "BRV-2021-01", "100,00"),
        invoice("d2", "BRV-2021-02", "50,50"),
        invoice("d3", "BRV-2021-03", "999"),
    ]

    result = _run(_plan(project_manager="Olivier Gauvreau"), hits)

    assert _answer(result) == "150.50"
    assert result is not None and result.draft is not None
    assert result.draft.citations == ["d1", "d2", "s1", "s2"]
    assert {hit.chunk.doc_id for hit in result.hits} >= {"s1", "s4", "d1"}


def test_unknown_manager_defers_to_direct() -> None:
    hits = [sheet("s1", "BRV-2021-01", "Priya Lavoie")]

    assert _run(_plan(project_manager="Olivier Gauvreau"), hits) is None


def test_regex_miss_is_read_by_one_llm_call() -> None:
    hits = [invoice("d1", CODE, "100,00"), typo_invoice("d2")]
    llm = FakeLlm(
        [
            ExtractedAmount(
                doc_id="d2", amount="20 $", quote="Sxxx : 20,00 $"
            ),
            ExtractedAmount(doc_id="zz", amount="5 $", quote="x"),
        ]
    )

    result = _run(_plan(project_codes=[CODE]), hits, llm)

    assert _answer(result) == "120.00"
    assert result is not None and result.draft is not None
    assert result.draft.evidence_sufficient
    assert len(llm.calls) == 1
    prompt = llm.calls[0][1]["content"]
    assert '<document id="d2">' in prompt
    assert '<document id="d1">' not in prompt


@pytest.mark.parametrize(
    "found",
    [
        ExtractedAmount(doc_id="d2", amount="n/a", quote="Sxxx : 20,00 $"),
        ExtractedAmount(doc_id="d2", amount="20 $", quote="invented line"),
    ],
)
def test_unusable_llm_amounts_are_ignored(found: ExtractedAmount) -> None:
    hits = [invoice("d1", CODE, "100,00"), typo_invoice("d2")]

    result = _run(_plan(project_codes=[CODE]), hits, FakeLlm([found]))

    assert _answer(result) == "100.00"
    assert result is not None and result.draft is not None
    assert not result.draft.evidence_sufficient


def test_blank_quote_amount_mismatch_and_duplicates_are_rejected() -> None:
    hits = [invoice("d1", CODE, "100,00"), typo_invoice("d2")]
    llm = FakeLlm(
        [
            ExtractedAmount(doc_id="d2", amount="20 $", quote="  "),
            ExtractedAmount(
                doc_id="d2", amount="99 $", quote="Sxxx : 20,00 $"
            ),
        ]
    )

    result = _run(_plan(project_codes=[CODE]), hits, llm)

    assert _answer(result) == "100.00"


def test_cad_marked_llm_amount_is_read() -> None:
    hits = [invoice("d1", CODE, "100,00"), typo_invoice("d2")]
    hits[1].chunk.text = hits[1].chunk.text.replace("20,00 $", "20,00 CAD")
    llm = FakeLlm(
        [
            ExtractedAmount(
                doc_id="d2", amount="20,00 CAD", quote="Sxxx : 20,00 CAD"
            )
        ]
    )

    result = _run(_plan(project_codes=[CODE]), hits, llm)

    assert _answer(result) == "120.00"


def test_duplicate_llm_doc_keeps_the_first_answer() -> None:
    hits = [invoice("d1", CODE, "100,00"), typo_invoice("d2")]
    quote = "Sxxx : 20,00 $"
    llm = FakeLlm(
        [
            ExtractedAmount(doc_id="d2", amount="20 $", quote=quote),
            ExtractedAmount(doc_id="d2", amount="99 $", quote=quote),
        ]
    )

    assert _answer(_run(_plan(project_codes=[CODE]), hits, llm)) == "120.00"


def test_llm_failure_gives_a_partial_answer() -> None:
    hits = [invoice("d1", CODE, "100,00"), typo_invoice("d2")]

    result = _run(_plan(project_codes=[CODE]), hits, FakeLlm(fail=True))

    assert _answer(result) == "100.00"
    assert result is not None and result.draft is not None
    assert result.draft.citations == ["d1"]
    assert not result.draft.evidence_sufficient
    assert {hit.chunk.doc_id for hit in result.hits} == {"d1", "d2"}


def test_every_invoice_unreadable_defers_to_direct() -> None:
    garbage = _hit("d2", "garbage", "invoice", [CODE])

    assert (
        _run(_plan(project_codes=[CODE]), [garbage], FakeLlm(fail=True))
        is None
    )


def test_invoice_without_client_line_is_unverified_not_matched() -> None:
    nameless = _hit("d2", "Sous-total : 50 $\nTOTAL : 1 $", "invoice", [CODE])
    hits = [invoice("d1", CODE, "100,00"), nameless]

    result = _run(_plan(client="Ville de Val"), hits)

    assert _answer(result) == "100.00"
    assert result is not None and result.draft is not None
    assert not result.draft.evidence_sufficient


def test_similar_client_names_are_not_confused() -> None:
    hits = [invoice("d1", CODE, "100,00")]

    assert _run(_plan(client="Ville de Valtrie"), hits) is None


def test_exact_manager_name_wins_over_a_fuzzy_neighbour() -> None:
    hits = [
        sheet("s1", "BRV-2021-01", "Lina Zabihi"),
        sheet("s2", "BRV-2021-02", "Lena Zabihi"),
        invoice("d1", "BRV-2021-01", "100,00"),
        invoice("d2", "BRV-2021-02", "50,00"),
    ]

    result = _run(_plan(project_manager="Lina Zabihi"), hits)

    assert _answer(result) == "100.00"


def test_typo_in_manager_name_still_matches_when_nothing_is_exact() -> None:
    hits = [
        sheet("s1", "BRV-2021-01", "Olivier Gauvreaux"),
        invoice("d1", "BRV-2021-01", "100,00"),
    ]

    assert _answer(_run(_plan(project_manager="Olivier Gauvreau"), hits)) == (
        "100.00"
    )


def test_non_brv_identifier_defers_even_with_a_brv_code() -> None:
    hits = [invoice("d1", CODE, "100,00")]

    assert _run(_plan(project_codes=[CODE, "F-2021-1286"]), hits) is None


def test_chunks_merge_in_numeric_order() -> None:
    first = _hit(
        "d1", "Facturé à : Ville de Val\nProjet : x", "invoice", [CODE]
    )
    second = _hit("d1", "Sous-total : 5 $", "invoice", [CODE])
    tenth = _hit("d1", "TOTAL : 6 $", "invoice", [CODE])
    first.chunk.chunk_id, second.chunk.chunk_id = "d1#2", "d1#3"
    tenth.chunk.chunk_id = "d1#10"

    result = _run(_plan(project_codes=[CODE]), [tenth, second, first])

    assert result is not None
    assert result.hits[0].chunk.text.splitlines()[-1] == "TOTAL : 6 $"


def test_capped_listing_flags_the_draft_insufficient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(aggregation_service, "AGG_LIST_CAP", 1)
    hits = [invoice("d1", CODE, "100,00")]

    result = _run(_plan(project_codes=[CODE]), hits)

    assert _answer(result) == "100.00"
    assert result is not None and result.draft is not None
    assert not result.draft.evidence_sufficient
