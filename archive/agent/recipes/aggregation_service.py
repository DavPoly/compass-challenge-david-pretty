"""Aggregation recipe: sum invoice amounts over a filtered set."""

import logging
import re
from dataclasses import dataclass
from decimal import Decimal

from pydantic import BaseModel

from archive.agent.draft_service import format_documents
from archive.agent.prompt_constants import MAX_PROMPT_CHUNKS
from archive.agent.recipes.invoice_parsing_utils import (
    InvoiceFields,
    client_matches,
    parse_invoice,
)
from archive.agent.recipes.recipe_constants import (
    AGG_LIST_CAP,
    EXTRACT_SYSTEM_PROMPT,
    EXTRACT_USER_PROMPT,
    LOG_AGGREGATION,
    LOG_EXTRACT_UNAVAILABLE,
    MANAGER_ROW_RE,
    MISS_INSTRUCTION,
    PROJECT_CODE_PATTERN,
)
from archive.agent.recipes.recipe_model import RecipeResult, RecipeSearchPort
from archive.agent.route.route_model import AmountMeasure, QuestionPlan
from archive.common.chunk_model import DocType
from archive.llm.llm_gateway import LlmGateway, LlmUnavailableError
from archive.retrieval.search_service import SearchFilters, SearchHit
from archive.validation.answer_model import AnswerStatus, DraftAnswer, Evidence
from archive.validation.answer_validator import normalize_amount
from archive.validation.input_model import Question

logger = logging.getLogger(__name__)

_MANAGER_ROW = re.compile(MANAGER_ROW_RE, re.IGNORECASE | re.MULTILINE)
_PROJECT_CODE = re.compile(PROJECT_CODE_PATTERN)


class ExtractedAmount(BaseModel):
    """One amount read by the LLM from an invoice."""

    doc_id: str
    amount: str
    quote: str


class ExtractedAmounts(BaseModel):
    """The LLM's reading of the invoices the regex could not parse."""

    amounts: list[ExtractedAmount]


@dataclass
class _Invoice:
    """An invoice document with the amount the recipe will sum."""

    hit: SearchHit
    fields: InvoiceFields
    amount: Decimal | None = None
    quote: str | None = None

    @property
    def doc_id(self) -> str:
        return self.hit.chunk.doc_id


def _merge_chunks(hits: list[SearchHit]) -> list[SearchHit]:
    """One hit per doc id, with the chunk texts joined in order."""
    by_doc: dict[str, list[SearchHit]] = {}
    for hit in hits:
        by_doc.setdefault(hit.chunk.doc_id, []).append(hit)
    merged = []
    for parts in by_doc.values():
        parts.sort(key=lambda part: part.chunk.chunk_id)
        text = "\n".join(part.chunk.text for part in parts)
        chunk = parts[0].chunk.model_copy(update={"text": text})
        merged.append(SearchHit(chunk, parts[0].score))
    return merged


def _plan_codes(plan: QuestionPlan) -> list[str]:
    return [
        code for code in plan.project_codes if _PROJECT_CODE.fullmatch(code)
    ]


def _manager_codes(
    manager: str, search: RecipeSearchPort
) -> tuple[list[str], list[SearchHit]]:
    """BRV codes of the projects a manager leads, and their sheets."""
    sheets = search.list_by_filter(
        SearchFilters(doc_types=[DocType.PROJECT_SHEET.value]), AGG_LIST_CAP
    )
    used: list[SearchHit] = []
    codes: set[str] = set()
    for hit in _merge_chunks(sheets):
        row = _MANAGER_ROW.search(hit.chunk.text)
        if row is None or not client_matches(row["value"], manager):
            continue
        used.append(hit)
        codes.update(
            code
            for code in hit.chunk.identifiers
            if _PROJECT_CODE.fullmatch(code)
        )
    return sorted(codes), used


def _is_client_invoice(invoice: _Invoice, wanted: str) -> bool:
    if invoice.fields.client is not None:
        return client_matches(invoice.fields.client, wanted)
    return client_matches(invoice.hit.chunk.text, wanted)


def _select_invoices(
    plan: QuestionPlan, codes: list[str], search: RecipeSearchPort
) -> list[_Invoice]:
    """List the invoices of the codes and period, filtered by client."""
    filters = SearchFilters(
        doc_types=[DocType.INVOICE.value],
        identifiers=codes,
        date_from=plan.date_from,
        date_to=plan.date_to,
    )
    hits = _merge_chunks(search.list_by_filter(filters, AGG_LIST_CAP))
    invoices = [_Invoice(hit, parse_invoice(hit.chunk.text)) for hit in hits]
    if plan.client is None:
        return invoices
    return [
        invoice
        for invoice in invoices
        if _is_client_invoice(invoice, plan.client)
    ]


def _read_amount(invoice: _Invoice, measure: AmountMeasure) -> None:
    fields = invoice.fields
    if measure is AmountMeasure.TAX_INCLUDED:
        invoice.amount, invoice.quote = fields.total, fields.total_line
    else:
        invoice.amount, invoice.quote = fields.subtotal, fields.subtotal_line


def _extract_with_llm(
    question: Question,
    misses: list[_Invoice],
    measure: AmountMeasure,
    llm: LlmGateway,
) -> None:
    """Fill the missing amounts with one LLM call; skip on failure."""
    batch = misses[:MAX_PROMPT_CHUNKS]
    system = EXTRACT_SYSTEM_PROMPT.format(measure=MISS_INSTRUCTION[measure])
    user = EXTRACT_USER_PROMPT.format(
        documents=format_documents([invoice.hit for invoice in batch])
    )
    try:
        reply = llm.complete_json(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            ExtractedAmounts,
        )
    except LlmUnavailableError:
        logger.warning(LOG_EXTRACT_UNAVAILABLE, question.id, len(misses))
        return
    by_doc = {invoice.doc_id: invoice for invoice in batch}
    for found in reply.amounts:
        invoice = by_doc.get(found.doc_id)
        normalized = normalize_amount(found.amount)
        if invoice is None or normalized is None:
            continue
        if found.quote not in invoice.hit.chunk.text:
            continue
        invoice.amount = Decimal(normalized)
        invoice.quote = found.quote


def _sheet_evidence(
    summed: list[_Invoice], sheets: list[SearchHit], manager: str | None
) -> list[Evidence]:
    """Manager rows of the sheets whose project has a summed invoice."""
    summed_codes = {
        code for invoice in summed for code in invoice.hit.chunk.identifiers
    }
    evidence = []
    for sheet in sheets:
        row = _MANAGER_ROW.search(sheet.chunk.text)
        if row and summed_codes.intersection(sheet.chunk.identifiers):
            evidence.append(
                Evidence(
                    doc_id=sheet.chunk.doc_id,
                    quote=row.group(0).strip(),
                    value=manager,
                )
            )
    return evidence


def _build_draft(
    summed: list[_Invoice],
    sheet_evidence: list[Evidence],
    is_complete: bool,
) -> DraftAnswer:
    total = sum(
        (invoice.amount or Decimal(0) for invoice in summed), Decimal(0)
    )
    evidence = [
        Evidence(
            doc_id=invoice.doc_id,
            quote=invoice.quote or "",
            value=f"{invoice.amount:.2f}",
        )
        for invoice in summed
    ] + sheet_evidence
    return DraftAnswer(
        answer=f"{total:.2f}",
        status=AnswerStatus.ANSWERED,
        citations=[item.doc_id for item in evidence],
        evidence=evidence,
        evidence_sufficient=is_complete,
    )


def run_aggregation(
    question: Question,
    plan: QuestionPlan,
    search: RecipeSearchPort,
    llm: LlmGateway,
) -> RecipeResult | None:
    """Answer an aggregation question, or None to use the direct path.

    Sums the pre-tax or tax-included amount of the invoices selected by
    client, project codes or project manager (resolved through the
    project sheets) within the planned period. Returns None without a
    narrowing entity or when no invoice matches. Amounts the regex
    cannot read go to one LLM extraction call; docs it cannot resolve
    are left out and the draft is flagged insufficient.
    """
    codes = _plan_codes(plan)
    sheets: list[SearchHit] = []
    if plan.project_manager:
        manager_codes, sheets = _manager_codes(plan.project_manager, search)
        codes = [c for c in manager_codes if not codes or c in codes]
        if not codes:
            return None
    elif plan.client is None and not codes:
        return None
    measure = plan.measure or AmountMeasure.PRE_TAX
    invoices = _select_invoices(plan, codes, search)
    for invoice in invoices:
        _read_amount(invoice, measure)
    misses = [invoice for invoice in invoices if invoice.amount is None]
    if misses:
        _extract_with_llm(question, misses, measure, llm)
    summed = [invoice for invoice in invoices if invoice.amount is not None]
    logger.info(
        LOG_AGGREGATION, question.id, len(invoices), len(summed), len(misses)
    )
    if not summed:
        return None
    sheet_evidence = _sheet_evidence(summed, sheets, plan.project_manager)
    draft = _build_draft(summed, sheet_evidence, len(summed) == len(invoices))
    hits = [invoice.hit for invoice in invoices] + sheets
    return RecipeResult(hits=hits, draft=draft)
