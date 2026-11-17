"""Aggregation recipe: sum invoice amounts over a filtered set."""

import logging
import re
from dataclasses import dataclass, replace
from decimal import Decimal

from pydantic import BaseModel

from archive.agent.draft_service import format_documents
from archive.agent.prompt_constants import MAX_PROMPT_CHUNKS
from archive.agent.recipes.invoice_parsing_utils import (
    InvoiceFields,
    client_matches,
    parse_amount_text,
    parse_invoice,
    read_line_amount,
)
from archive.agent.recipes.recipe_constants import (
    AGG_LIST_CAP,
    AMOUNT_FORMAT,
    CHUNK_ID_SEPARATOR,
    EXTRACT_SYSTEM_PROMPT,
    EXTRACT_USER_PROMPT,
    LOG_AGGREGATION,
    LOG_DUPLICATE_EXTRACTION,
    LOG_EXTRACT_UNAVAILABLE,
    LOG_LIST_CAPPED,
    LOG_NO_MEASURE,
    MANAGER_ROW_RE,
    MISS_INSTRUCTION,
    PROJECT_CODE_PATTERN,
)
from archive.agent.recipes.recipe_model import RecipeResult, RecipeSearchPort
from archive.agent.route.route_model import AmountMeasure, QuestionPlan
from archive.common.chunk_model import DocType
from archive.common.text.text_normalize_utils import normalize_for_match
from archive.llm.llm_gateway import LlmGateway, LlmUnavailableError
from archive.retrieval.search_service import SearchFilters, SearchHit
from archive.validation.answer_model import AnswerStatus, DraftAnswer, Evidence
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


@dataclass(frozen=True)
class _Reading:
    """The amount of an invoice and the line that proves it."""

    amount: Decimal
    quote: str


@dataclass(frozen=True)
class _Invoice:
    """An invoice document with the reading the recipe will sum."""

    hit: SearchHit
    fields: InvoiceFields
    reading: _Reading | None = None

    @property
    def doc_id(self) -> str:
        """Id of the invoice document."""
        return self.hit.chunk.doc_id


@dataclass(frozen=True)
class _Scope:
    """Project codes to list, and the manager sheets that gave them."""

    codes: list[str]
    sheets: list[SearchHit]
    is_truncated: bool


@dataclass(frozen=True)
class _Selection:
    """Invoices kept for the question, and what could not be checked."""

    invoices: list[_Invoice]
    unverified_count: int
    is_truncated: bool


def _chunk_order(hit: SearchHit) -> tuple[int, str]:
    """Sort key placing chunk "doc#10" after "doc#2"."""
    chunk_id = hit.chunk.chunk_id
    suffix = chunk_id.rpartition(CHUNK_ID_SEPARATOR)[2]
    return (int(suffix) if suffix.isdigit() else 0, chunk_id)


def _merge_chunks(hits: list[SearchHit]) -> list[SearchHit]:
    """One hit per doc id, with the chunk texts joined in order."""
    by_doc: dict[str, list[SearchHit]] = {}
    for hit in hits:
        by_doc.setdefault(hit.chunk.doc_id, []).append(hit)
    merged = []
    for parts in by_doc.values():
        parts.sort(key=_chunk_order)
        text = "\n".join(part.chunk.text for part in parts)
        chunk = parts[0].chunk.model_copy(update={"text": text})
        merged.append(SearchHit(chunk, parts[0].score))
    return merged


def _list_hits(
    search: RecipeSearchPort, filters: SearchFilters
) -> tuple[list[SearchHit], bool]:
    """List the chunks of a filter; flag a listing cut by the cap."""
    hits = search.list_by_filter(filters, AGG_LIST_CAP)
    is_capped = len(hits) >= AGG_LIST_CAP
    if is_capped:
        logger.warning(LOG_LIST_CAPPED, AGG_LIST_CAP)
    return hits, is_capped


def _project_codes(hit: SearchHit) -> list[str]:
    """BRV project codes carried by a chunk."""
    return [
        code for code in hit.chunk.identifiers if _PROJECT_CODE.fullmatch(code)
    ]


def _manager_scope(manager: str, search: RecipeSearchPort) -> _Scope:
    """Scope of the projects a manager leads, read on project sheets.

    Sheets whose manager equals the name exactly are used; the fuzzy
    match only applies when none does.
    """
    listed, is_truncated = _list_hits(
        search, SearchFilters(doc_types=[DocType.PROJECT_SHEET.value])
    )
    rows = []
    for hit in _merge_chunks(listed):
        row = _MANAGER_ROW.search(hit.chunk.text)
        if row is not None:
            rows.append((hit, row["value"]))
    wanted = normalize_for_match(manager)
    used = [hit for hit, name in rows if normalize_for_match(name) == wanted]
    if not used:
        used = [hit for hit, name in rows if client_matches(name, manager)]
    codes = {code for hit in used for code in _project_codes(hit)}
    return _Scope(sorted(codes), used, is_truncated)


def _resolve_scope(
    plan: QuestionPlan, search: RecipeSearchPort
) -> _Scope | None:
    """Project codes the question is limited to, or None to defer.

    Defers without a narrowing entity, with a non-project identifier
    (a single document question), or when the manager has no project.
    """
    if any(not _PROJECT_CODE.fullmatch(code) for code in plan.project_codes):
        return None
    codes = list(plan.project_codes)
    if plan.project_manager:
        scope = _manager_scope(plan.project_manager, search)
        kept = [code for code in scope.codes if not codes or code in codes]
        return replace(scope, codes=kept) if kept else None
    if plan.client is None and not codes:
        return None
    return _Scope(codes, [], False)


def _select_invoices(
    plan: QuestionPlan, codes: list[str], search: RecipeSearchPort
) -> _Selection:
    """List the invoices of the codes and period, filtered by client.

    With a wanted client, an invoice without a readable client line
    cannot be checked: it is left out and counted as unverified.
    """
    filters = SearchFilters(
        doc_types=[DocType.INVOICE.value],
        identifiers=codes,
        date_from=plan.date_from,
        date_to=plan.date_to,
    )
    listed, is_truncated = _list_hits(search, filters)
    invoices = [
        _Invoice(hit, parse_invoice(hit.chunk.text))
        for hit in _merge_chunks(listed)
    ]
    if plan.client is None:
        return _Selection(invoices, 0, is_truncated)
    kept = []
    unverified_count = 0
    for invoice in invoices:
        client = invoice.fields.client
        if client is None:
            unverified_count += 1
        elif client_matches(client, plan.client):
            kept.append(invoice)
    return _Selection(kept, unverified_count, is_truncated)


def _measured(invoice: _Invoice, measure: AmountMeasure) -> _Invoice:
    """The invoice with the regex reading of the measure, if any."""
    fields = invoice.fields
    if measure is AmountMeasure.TAX_INCLUDED:
        amount, line = fields.total, fields.total_line
    else:
        amount, line = fields.subtotal, fields.subtotal_line
    if amount is None or line is None:
        return invoice
    return replace(invoice, reading=_Reading(amount, line))


def _checked_reading(
    found: ExtractedAmount, invoice: _Invoice
) -> _Reading | None:
    """The LLM's amount when its quote is on the invoice and agrees."""
    quote = found.quote.strip()
    if not quote or quote not in invoice.hit.chunk.text:
        return None
    amount = parse_amount_text(found.amount)
    if amount is None or amount != read_line_amount(quote):
        return None
    return _Reading(amount, quote)


def _extract_with_llm(
    question: Question,
    misses: list[_Invoice],
    measure: AmountMeasure,
    llm: LlmGateway,
) -> dict[str, _Reading]:
    """Read the missing amounts with one LLM call, by doc id.

    Returns nothing on LLM failure. Only the first answer per doc id is
    kept, and only when its quote is on the invoice and carries the
    amount.
    """
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
        return {}
    by_doc = {invoice.doc_id: invoice for invoice in batch}
    seen: set[str] = set()
    readings: dict[str, _Reading] = {}
    for found in reply.amounts:
        if found.doc_id in seen:
            logger.warning(LOG_DUPLICATE_EXTRACTION, question.id, found.doc_id)
            continue
        seen.add(found.doc_id)
        invoice = by_doc.get(found.doc_id)
        reading = _checked_reading(found, invoice) if invoice else None
        if reading is not None:
            readings[found.doc_id] = reading
    return readings


def _fill_amounts(
    question: Question,
    invoices: list[_Invoice],
    measure: AmountMeasure,
    llm: LlmGateway,
) -> list[_Invoice]:
    """Read every invoice by regex, then the misses by LLM."""
    measured = [_measured(invoice, measure) for invoice in invoices]
    misses = [invoice for invoice in measured if invoice.reading is None]
    if not misses:
        return measured
    readings = _extract_with_llm(question, misses, measure, llm)
    return [
        replace(invoice, reading=readings.get(invoice.doc_id, invoice.reading))
        for invoice in measured
    ]


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
    """The answer draft: the exact sum and one evidence per invoice."""
    readings = [
        (invoice.doc_id, invoice.reading)
        for invoice in summed
        if invoice.reading is not None
    ]
    total = sum((reading.amount for _, reading in readings), Decimal(0))
    evidence = [
        Evidence(
            doc_id=doc_id,
            quote=reading.quote,
            value=format(reading.amount, AMOUNT_FORMAT),
        )
        for doc_id, reading in readings
    ] + sheet_evidence
    return DraftAnswer(
        answer=format(total, AMOUNT_FORMAT),
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

    Sums the pre-tax or tax-included amount of the invoices selected
    by client, BRV project codes or project manager (resolved through
    the project sheets) within the planned period. Returns None
    without a money measure, without a narrowing entity, with a
    non-project identifier, or when no invoice matches. Amounts the
    regex cannot read go to one LLM extraction call. The draft is
    flagged insufficient when an invoice is left out, cannot be
    checked against the client, or the listing hit its cap.
    """
    if plan.measure is None:
        logger.info(LOG_NO_MEASURE, question.id)
        return None
    scope = _resolve_scope(plan, search)
    if scope is None:
        return None
    selection = _select_invoices(plan, scope.codes, search)
    invoices = _fill_amounts(question, selection.invoices, plan.measure, llm)
    summed = [invoice for invoice in invoices if invoice.reading is not None]
    logger.info(
        LOG_AGGREGATION,
        question.id,
        len(invoices),
        len(summed),
        selection.unverified_count,
    )
    if not summed:
        return None
    is_complete = (
        len(summed) == len(invoices)
        and selection.unverified_count == 0
        and not (selection.is_truncated or scope.is_truncated)
    )
    sheet_evidence = _sheet_evidence(
        summed, scope.sheets, plan.project_manager
    )
    draft = _build_draft(summed, sheet_evidence, is_complete)
    hits = [invoice.hit for invoice in invoices] + scope.sheets
    return RecipeResult(hits=hits, draft=draft)
