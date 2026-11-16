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
from archive.common.config import AppConfig
from archive.ingest.index_builder_service import ManifestError
from archive.llm.llm_gateway import LlmGateway, LlmUnavailableError
from archive.pipeline.pipeline_constants import (
    ANSWERS_ENCODING,
    EXIT_ERROR,
    EXIT_OK,
    GLOBAL_DEADLINE_S,
    MSG_CANNOT_WRITE,
    MSG_INDEX_OPEN,
    MSG_NO_CORPUS,
    POLL_INTERVAL_S,
    QUESTION_BUDGET_S,
    SEARCH_TOP_K,
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
    clock: Callable[[], float]
    sleep: Callable[[float], None]


class AnswerWriter:
    """Thread-safe answers.jsonl writer: one flushed line per id."""

    def __init__(self, out: TextIO) -> None:
        self._out = out
        self._lock = threading.Lock()
        self._written_ids: set[str] = set()
        self._started_at: dict[str, float] = {}

    def write(self, answer: FinalAnswer) -> bool:
        """Write the line unless the id has one; return if written."""
        with self._lock:
            if answer.id in self._written_ids:
                return False
            self._out.write(answer.to_jsonl_line() + "\n")
            self._out.flush()
            self._written_ids.add(answer.id)
            return True

    def mark_started(self, question_id: str, now_s: float) -> None:
        """Record when a worker began the question."""
        with self._lock:
            self._started_at[question_id] = now_s

    def is_written(self, question_id: str) -> bool:
        """Whether the question already has its line."""
        with self._lock:
            return question_id in self._written_ids

    def started_at(self, question_id: str) -> float | None:
        """Start time of the question, None while it is still queued."""
        with self._lock:
            return self._started_at.get(question_id)


def _answer_question(
    question: Question, search: SearchService, llm: LlmGateway
) -> FinalAnswer:
    if not question.is_valid:
        logger.warning(
            "question %s invalid (%s): not_found",
            question.id,
            question.error,
        )
        return FinalAnswer.not_found(question.id)
    hits = search.hybrid_search(question.question, None, SEARCH_TOP_K)
    retrieved_ids = {hit.chunk.doc_id for hit in hits}
    result = validate(
        question.id,
        draft(question, hits, llm),
        retrieved_ids,
        search.known_doc_ids(),
    )
    for issue in result.issues:
        logger.info("question %s: %s", question.id, issue)
    if result.dropped_citations:
        logger.warning(
            "question %s: dropped citations %s",
            question.id,
            result.dropped_citations,
        )
    return result.answer


def _work(
    question: Question,
    writer: AnswerWriter,
    context: RunContext,
    deadline_s: float,
) -> None:
    if context.clock() >= deadline_s:
        return
    writer.mark_started(question.id, context.clock())
    try:
        answer = _answer_question(question, context.search, context.llm)
    except LlmUnavailableError as error:
        logger.error("question %s: LLM unavailable: %s", question.id, error)
        answer = FinalAnswer.not_found(question.id)
    except Exception:
        # A single question must never kill the run: any unexpected
        # failure degrades to not_found and keeps the traceback in logs.
        logger.exception("question %s: unexpected error", question.id)
        answer = FinalAnswer.not_found(question.id)
    if not writer.write(answer):
        logger.warning("question %s: late result discarded", question.id)


def _expire_overdue(
    questions: list[Question], writer: AnswerWriter, now_s: float
) -> None:
    for question in questions:
        started = writer.started_at(question.id)
        if started is None or now_s - started < QUESTION_BUDGET_S:
            continue
        if writer.write(FinalAnswer.not_found(question.id)):
            logger.error(
                "question %s: over %.0f s budget, not_found",
                question.id,
                QUESTION_BUDGET_S,
            )


def _fill_unanswered(questions: list[Question], writer: AnswerWriter) -> None:
    for question in questions:
        if writer.write(FinalAnswer.not_found(question.id)):
            logger.error(
                "question %s: global deadline reached, not_found",
                question.id,
            )


def _process_all(
    questions: list[Question], writer: AnswerWriter, context: RunContext
) -> None:
    deadline_s = context.clock() + GLOBAL_DEADLINE_S
    pool = ThreadPoolExecutor(max_workers=WORKER_COUNT)
    try:
        for question in questions:
            pool.submit(_work, question, writer, context, deadline_s)
        while not all(writer.is_written(q.id) for q in questions):
            now_s = context.clock()
            if now_s >= deadline_s:
                break
            _expire_overdue(questions, writer, now_s)
            context.sleep(POLL_INTERVAL_S)
        _fill_unanswered(questions, writer)
    finally:
        # Stuck worker threads cannot be killed: do not wait for them.
        pool.shutdown(wait=False, cancel_futures=True)


def _unique(questions: list[Question]) -> list[Question]:
    seen: set[str] = set()
    unique = []
    for question in questions:
        if question.id in seen:
            logger.warning("duplicate question id %s ignored", question.id)
            continue
        seen.add(question.id)
        unique.append(question)
    return unique


def _has_pdfs(corpus_dir: Path) -> bool:
    return corpus_dir.is_dir() and any(corpus_dir.glob("*.pdf"))


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
    if not _has_pdfs(config.corpus_dir):
        logger.error(MSG_NO_CORPUS.format(path=config.corpus_dir))
        return EXIT_ERROR
    try:
        questions = _unique(load_questions(questions_path))
    except QuestionsFileError as error:
        logger.error("%s", error)
        return EXIT_ERROR
    try:
        search = SearchService.open(config.index_dir)
    except (IndexOpenError, ManifestError) as error:
        logger.error(
            MSG_INDEX_OPEN.format(path=config.index_dir, reason=error)
        )
        return EXIT_ERROR
    with search:
        try:
            context = RunContext(search, LlmGateway(config), clock, sleep)
            with answers_path.open(
                "w", encoding=ANSWERS_ENCODING, newline="\n"
            ) as out:
                _process_all(questions, AnswerWriter(out), context)
        except OSError as error:
            logger.error(
                MSG_CANNOT_WRITE.format(path=answers_path, reason=error)
            )
            return EXIT_ERROR
    return EXIT_OK
