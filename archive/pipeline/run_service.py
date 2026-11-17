"""Run every question through retrieval, drafting and validation."""

import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from archive.agent.draft_service import draft
from archive.agent.retrieve_constants import SEARCH_TOP_K
from archive.agent.retrieve_service import retrieve
from archive.common.config import AppConfig
from archive.common.constants import PDF_GLOB
from archive.ingest.build.index_builder_service import IndexBuildError
from archive.ingest.build.index_sync_service import sync_index
from archive.ingest.build.manifest_gateway import ManifestError
from archive.llm.llm_gateway import LlmGateway, LlmUnavailableError
from archive.pipeline.pipeline_constants import (
    ANSWERS_ENCODING,
    EXIT_ERROR,
    EXIT_OK,
    GLOBAL_DEADLINE_S,
    LOG_DEADLINE_REACHED,
    LOG_DOC_IDS_DIFFER,
    LOG_DROPPED_CITATIONS,
    LOG_LATE_RESULT,
    LOG_LLM_UNAVAILABLE,
    LOG_OVER_BUDGET,
    LOG_QUESTION_INVALID,
    LOG_QUESTION_ISSUE,
    LOG_SYNC_FAILED,
    LOG_SYNC_REPORT,
    LOG_UNEXPECTED_ERROR,
    MSG_INDEX_OPEN,
    MSG_IO_ERROR,
    MSG_NO_CORPUS,
    POLL_INTERVAL_S,
    QUESTION_BUDGET_S,
    WORKER_COUNT,
)
from archive.retrieval.qdrant_gateway import IndexOpenError
from archive.retrieval.search_service import SearchService
from archive.validation.answer_model import FinalAnswer
from archive.validation.answer_validator import validate
from archive.validation.input_model import (
    Question,
    QuestionsFileError,
    load_questions,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RunContext:
    """Shared services and injectable time sources of one run."""

    search: SearchService
    llm: LlmGateway
    valid_doc_ids: frozenset[str]
    deadline_s: float
    clock: Callable[[], float]
    sleep: Callable[[float], None]


class StartTimes:
    """Thread-safe record of when workers began each question."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._started_at: dict[str, float] = {}

    def mark(self, question_id: str, now_s: float) -> None:
        """Record when a worker began the question."""
        with self._lock:
            self._started_at[question_id] = now_s

    def get(self, question_id: str) -> float | None:
        """Start time of the question, None while it is still queued."""
        with self._lock:
            return self._started_at.get(question_id)


class AnswerWriter:
    """Thread-safe answers.jsonl writer: one flushed line per id."""

    def __init__(self, out: TextIO) -> None:
        self._out = out
        self._lock = threading.Lock()
        self._written_ids: set[str] = set()

    def write(self, answer: FinalAnswer) -> bool:
        """Write the line unless the id has one; return if written."""
        with self._lock:
            if answer.id in self._written_ids:
                return False
            self._out.write(answer.to_jsonl_line() + "\n")
            self._out.flush()
            self._written_ids.add(answer.id)
            return True

    def is_written(self, question_id: str) -> bool:
        """Whether the question already has its line."""
        with self._lock:
            return question_id in self._written_ids


def _answer_question(question: Question, context: RunContext) -> FinalAnswer:
    if not question.is_valid:
        logger.warning(LOG_QUESTION_INVALID, question.id, question.error)
        return FinalAnswer.not_found(question.id)
    hits = retrieve(question.question, context.search, SEARCH_TOP_K)
    retrieved_ids = {hit.chunk.doc_id for hit in hits}
    result = validate(
        question.id,
        draft(question, hits, context.llm),
        retrieved_ids,
        context.valid_doc_ids,
    )
    for issue in result.issues:
        logger.info(LOG_QUESTION_ISSUE, question.id, issue)
    if result.dropped_citations:
        logger.warning(
            LOG_DROPPED_CITATIONS, question.id, result.dropped_citations
        )
    return result.answer


def _work(
    question: Question,
    writer: AnswerWriter,
    starts: StartTimes,
    context: RunContext,
) -> None:
    if context.clock() >= context.deadline_s:
        return
    starts.mark(question.id, context.clock())
    try:
        answer = _answer_question(question, context)
    except LlmUnavailableError as error:
        logger.error(LOG_LLM_UNAVAILABLE, question.id, error)
        answer = FinalAnswer.not_found(question.id)
    except Exception:
        # A single question must never kill the run: any unexpected
        # failure degrades to not_found and keeps the traceback in logs.
        logger.exception(LOG_UNEXPECTED_ERROR, question.id)
        answer = FinalAnswer.not_found(question.id)
    try:
        written = writer.write(answer)
    except Exception:
        # Late results are discarded by design: the run may already be
        # tearing down, so a closed answers file must not kill the
        # worker thread silently.
        logger.debug(LOG_LATE_RESULT, question.id, exc_info=True)
        return
    if not written:
        logger.warning(LOG_LATE_RESULT, question.id)


def _expire_overdue(
    questions: list[Question],
    writer: AnswerWriter,
    starts: StartTimes,
    now_s: float,
) -> None:
    for question in questions:
        started = starts.get(question.id)
        if started is None or now_s - started < QUESTION_BUDGET_S:
            continue
        if writer.write(FinalAnswer.not_found(question.id)):
            logger.error(LOG_OVER_BUDGET, question.id, QUESTION_BUDGET_S)


def _fill_unanswered(questions: list[Question], writer: AnswerWriter) -> None:
    for question in questions:
        if writer.write(FinalAnswer.not_found(question.id)):
            logger.error(LOG_DEADLINE_REACHED, question.id)


def _process_all(
    questions: list[Question], writer: AnswerWriter, context: RunContext
) -> None:
    starts = StartTimes()
    pool = ThreadPoolExecutor(max_workers=WORKER_COUNT)
    try:
        for question in questions:
            pool.submit(_work, question, writer, starts, context)
        while not all(writer.is_written(q.id) for q in questions):
            now_s = context.clock()
            if now_s >= context.deadline_s:
                break
            _expire_overdue(questions, writer, starts, now_s)
            context.sleep(POLL_INTERVAL_S)
        _fill_unanswered(questions, writer)
    finally:
        # Stuck worker threads cannot be killed: do not wait for them.
        pool.shutdown(wait=False, cancel_futures=True)


def _unique(questions: list[Question]) -> list[Question]:
    """Keep the first question of each id; the loader warned duplicates."""
    seen: set[str] = set()
    unique = []
    for question in questions:
        if question.id in seen:
            continue
        seen.add(question.id)
        unique.append(question)
    return unique


def _has_pdfs(corpus_dir: Path) -> bool:
    return corpus_dir.is_dir() and any(corpus_dir.glob(PDF_GLOB))


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


def _sync_index_or_continue(config: AppConfig) -> None:
    """Sync the index with the corpus; a failure keeps the old index."""
    try:
        report = sync_index(config.corpus_dir, config.index_dir)
    except (IndexBuildError, IndexOpenError, ManifestError, OSError) as error:
        logger.warning(LOG_SYNC_FAILED, error)
        return
    logger.info(
        LOG_SYNC_REPORT,
        len(report.added),
        len(report.changed),
        len(report.removed),
        len(report.failed),
        report.seconds,
    )


def run(
    questions_path: Path,
    answers_path: Path,
    config: AppConfig,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Answer every question and write answers.jsonl.

    One line is written per question as soon as it is ready; a question
    that fails, exceeds its time budget or is cut by the global deadline
    gets a not_found line.

    Returns:
        0 on a completed run (even with not_found answers), 1 when the
        corpus, questions file, index or output file is unusable. The
        reason is logged as an error.
    """
    deadline_s = clock() + GLOBAL_DEADLINE_S
    if not _has_pdfs(config.corpus_dir):
        logger.error(MSG_NO_CORPUS.format(path=config.corpus_dir))
        return EXIT_ERROR
    try:
        questions = _unique(load_questions(questions_path))
    except QuestionsFileError as error:
        logger.error("%s", error)
        return EXIT_ERROR
    _sync_index_or_continue(config)
    try:
        search = SearchService.open(config.index_dir)
    except (IndexOpenError, ManifestError) as error:
        logger.error(
            MSG_INDEX_OPEN.format(path=config.index_dir, reason=error)
        )
        return EXIT_ERROR
    with search:
        try:
            context = RunContext(
                search,
                LlmGateway(config),
                _valid_doc_ids(search, config.corpus_dir),
                deadline_s,
                clock,
                sleep,
            )
            with answers_path.open(
                "w", encoding=ANSWERS_ENCODING, newline="\n"
            ) as out:
                _process_all(questions, AnswerWriter(out), context)
        except OSError as error:
            logger.error(MSG_IO_ERROR.format(path=answers_path, reason=error))
            return EXIT_ERROR
    return EXIT_OK
