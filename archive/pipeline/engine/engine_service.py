"""Open the answering services once and answer one question."""

import contextlib
import logging
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from archive.agent.answer_service import DraftOutcome, answer_question
from archive.common.config import AppConfig
from archive.common.constants import PDF_GLOB
from archive.common.step_model import PipelineStep, StepCallback, emit_step
from archive.ingest.build.index_sync_service import sync_index
from archive.ingest.build.manifest_gateway import ManifestError
from archive.llm.llm_gateway import LlmGateway
from archive.pipeline.pipeline_constants import (
    LOG_DENSE_UNAVAILABLE,
    LOG_DOC_IDS_DIFFER,
    LOG_DROPPED_CITATIONS,
    LOG_GROUNDING_CONFIDENCE,
    LOG_GROUNDING_FAILED,
    LOG_MODELS_ACTIVE,
    LOG_QUESTION_INVALID,
    LOG_QUESTION_ISSUE,
    LOG_SYNC_FAILED,
    LOG_SYNC_REPORT,
    MODEL_LOAD_WORKERS,
    MSG_INDEX_OPEN,
    MSG_NO_CORPUS,
)
from archive.pipeline.trace_service import AnswerParts
from archive.retrieval.models.embedding_gateway import (
    EmbeddingPort,
    load_embedder,
)
from archive.retrieval.models.model_constants import MODEL_LOAD_TIMEOUT_S
from archive.retrieval.models.rerank_gateway import (
    RerankPort,
    load_reranker,
)
from archive.retrieval.qdrant.qdrant_gateway import IndexOpenError
from archive.retrieval.search_service import SearchService
from archive.validation.answer_model import FinalAnswer
from archive.validation.answer_validator import ValidationResult, validate
from archive.validation.grounding.grounding_model import (
    GroundingReport,
    GroundingSources,
)
from archive.validation.grounding.grounding_service import check_grounding
from archive.validation.input_model import Question

logger = logging.getLogger(__name__)

# What opening the engine can raise: unusable index or manifest, or a
# file-system failure while loading or syncing them.
ENGINE_OPEN_ERRORS = (OSError, IndexOpenError, ManifestError)


@dataclass(frozen=True)
class Engine:
    """Opened services shared by every question of a process."""

    search: SearchService
    llm: LlmGateway
    valid_doc_ids: frozenset[str]
    config: AppConfig


def _valid_doc_ids(search: SearchService, corpus_dir: Path) -> frozenset[str]:
    manifest_ids = set(search.known_doc_ids())
    corpus_ids = {path.stem for path in corpus_dir.glob(PDF_GLOB)}
    valid = frozenset(manifest_ids & corpus_ids)
    if manifest_ids != corpus_ids:
        logger.warning(
            LOG_DOC_IDS_DIFFER,
            len(manifest_ids),
            len(corpus_ids),
            len(valid),
        )
    return valid


def _load_models() -> tuple[EmbeddingPort | None, RerankPort | None]:
    """Load the embedder and reranker in parallel.

    A model that cannot be loaded is None (the loader logs the cause);
    search then falls back to the remaining models, down to BM25 only.
    """
    with ThreadPoolExecutor(max_workers=MODEL_LOAD_WORKERS) as pool:
        embedder = pool.submit(load_embedder, MODEL_LOAD_TIMEOUT_S)
        reranker = pool.submit(load_reranker, MODEL_LOAD_TIMEOUT_S)
        loaded = embedder.result(), reranker.result()
    if loaded[0] is None:
        logger.warning(LOG_DENSE_UNAVAILABLE)
    logger.info(
        LOG_MODELS_ACTIVE,
        "on" if loaded[0] else "off",
        "on" if loaded[1] else "off",
    )
    return loaded


def _sync_index_or_continue(
    config: AppConfig, embedder: EmbeddingPort | None
) -> None:
    """Sync the index with the corpus; a failure is logged, not fatal.

    The full-build fallback only runs when the index is already
    unusable, so a failed sync never replaces a usable index.
    """
    try:
        report = sync_index(
            config.corpus_dir, config.index_dir, embedder=embedder
        )
    except Exception:
        # Best effort: any failure (pool, Qdrant, validation) must not
        # stop the run, the existing index is still usable. A
        # mid-sync failure may leave some docs missing for this
        # run; the next sync re-adds them.
        logger.exception(LOG_SYNC_FAILED)
        return
    logger.info(
        LOG_SYNC_REPORT,
        len(report.added),
        len(report.changed),
        len(report.removed),
        len(report.failed),
        report.sparse_only,
        report.seconds,
    )


@contextlib.contextmanager
def open_engine(config: AppConfig) -> Iterator[Engine]:
    """Load the models, sync the index and open the search services.

    The search service is closed when the context exits.

    Raises:
        IndexOpenError: the index cannot be opened.
        ManifestError: the index manifest is unusable.
        OSError: the index files cannot be read or written.
    """
    embedder, reranker = _load_models()
    _sync_index_or_continue(config, embedder)
    with SearchService.open(config.index_dir, embedder, reranker) as search:
        yield Engine(
            search,
            LlmGateway(config),
            _valid_doc_ids(search, config.corpus_dir),
            config,
        )


def has_pdfs(corpus_dir: Path) -> bool:
    """Whether ``corpus_dir`` exists and holds at least one PDF."""
    return corpus_dir.is_dir() and any(corpus_dir.glob(PDF_GLOB))


def corpus_is_ready(corpus_dir: Path) -> bool:
    """Whether the corpus has PDFs; logs the fix when it has none."""
    if has_pdfs(corpus_dir):
        return True
    logger.error(MSG_NO_CORPUS.format(path=corpus_dir))
    return False


def log_engine_open_failure(config: AppConfig, error: Exception) -> None:
    """Log that the index of ``config`` could not be opened."""
    logger.error(MSG_INDEX_OPEN.format(path=config.index_dir, reason=error))


def _log_grounding(
    question_id: str, outcome: DraftOutcome, result: ValidationResult
) -> GroundingReport:
    report = check_grounding(
        outcome.draft,
        GroundingSources.from_hits(outcome.hits, outcome.note),
        result,
    )
    for issue in report.issues:
        logger.info(LOG_QUESTION_ISSUE, question_id, issue)
    logger.info(LOG_GROUNDING_CONFIDENCE, question_id, report.confidence)
    return report


def answer_one(
    question: Question,
    engine: Engine,
    on_step: StepCallback | None = None,
) -> AnswerParts:
    """Answer one question: draft, validate and check grounding.

    An invalid question gets a not_found answer without any search.
    A failing grounding check is logged and leaves the report empty.
    ``on_step`` also hears the validate and ground stages.

    Raises:
        LlmUnavailableError: the LLM could not give a valid draft.
    """
    if not question.is_valid:
        logger.warning(LOG_QUESTION_INVALID, question.id, question.error)
        return AnswerParts(FinalAnswer.not_found(question.id))
    outcome = answer_question(question, engine.search, engine.llm, on_step)
    result = validate(
        question.id,
        outcome.draft,
        outcome.doc_ids,
        engine.valid_doc_ids,
    )
    emit_step(on_step, PipelineStep.VALIDATE, result.answer.status.value)
    for issue in result.issues:
        logger.info(LOG_QUESTION_ISSUE, question.id, issue)
    if result.dropped_citations:
        logger.warning(
            LOG_DROPPED_CITATIONS, question.id, result.dropped_citations
        )
    report = None
    try:
        report = _log_grounding(question.id, outcome, result)
        emit_step(on_step, PipelineStep.GROUND, str(report.confidence))
    except Exception:  # broad catch at a boundary: flag-only, never fatal
        logger.exception(LOG_GROUNDING_FAILED, question.id)
    return AnswerParts(result.answer, outcome, result, report)
