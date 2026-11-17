"""Run every question through retrieval, drafting and validation."""

import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import TextIO

from archive.common.config import AppConfig
from archive.llm.llm_gateway import LlmUnavailableError
from archive.pipeline.engine.engine_service import (
    ENGINE_OPEN_ERRORS,
    Engine,
    answer_one,
    corpus_is_ready,
    log_engine_open_failure,
    open_engine,
)
from archive.pipeline.pipeline_constants import (
    ANSWERS_ENCODING,
    EXIT_ERROR,
    EXIT_OK,
    GLOBAL_DEADLINE_S,
    LOG_DEADLINE_REACHED,
    LOG_LATE_RESULT,
    LOG_LLM_UNAVAILABLE,
    LOG_OVER_BUDGET,
    LOG_TRACE_WRITE_FAILED,
    LOG_UNEXPECTED_ERROR,
    LOG_VIEWER_FAILED,
    LOG_VIEWER_READY,
    MSG_DEADLINE_TRACE,
    MSG_IO_ERROR,
    MSG_LATE_TRACE,
    MSG_OVER_BUDGET_TRACE,
    POLL_INTERVAL_S,
    QUESTION_BUDGET_S,
    WORKER_COUNT,
)
from archive.pipeline.trace_gateway import TraceWriter, new_run_id
from archive.pipeline.trace_service import AnswerParts, build_trace
from archive.validation.answer_model import FinalAnswer
from archive.validation.input_model import (
    Question,
    QuestionsFileError,
    load_questions,
)
from archive.viewer.page_render_gateway import render_evidence
from archive.viewer.viewer_build_service import (
    ViewerBudget,
    ViewerRequest,
    build_viewer,
)
from archive.viewer.viewer_constants import VIEWER_GRACE_S

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RunContext:
    """Shared services and injectable time sources of one run."""

    engine: Engine
    deadline_s: float
    clock: Callable[[], float]
    sleep: Callable[[float], None]
    run_id: str = ""
    traces: TraceWriter | None = None


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


def _record_trace(
    question: Question,
    parts: AnswerParts,
    context: RunContext,
    started_s: float | None,
    error: str | None,
) -> None:
    """Write the question trace; never raises, never alters answers.

    ``started_s`` is None for a question that never started (elapsed 0).
    """
    if context.traces is None:
        return
    try:
        elapsed_s = 0.0 if started_s is None else context.clock() - started_s
        trace = build_trace(context.run_id, question, parts, elapsed_s, error)
        context.traces.write(trace)
    except Exception:  # broad catch at a boundary: traces are optional
        logger.warning(LOG_TRACE_WRITE_FAILED, question.id, exc_info=True)


def _record_not_found_trace(
    question: Question,
    context: RunContext,
    started_s: float | None,
    error: str,
) -> None:
    """Minimal trace for a not_found line written by the run loop."""
    parts = AnswerParts(FinalAnswer.not_found(question.id))
    _record_trace(question, parts, context, started_s, error)


def _store_answer(
    question: Question, parts: AnswerParts, writer: AnswerWriter
) -> bool:
    """Write the answer line; False when it was not this answer."""
    try:
        written = writer.write(parts.answer)
    except Exception:
        # Late results are discarded by design: the run may already be
        # tearing down, so a closed answers file must not kill the
        # worker thread silently.
        logger.debug(LOG_LATE_RESULT, question.id, exc_info=True)
        return False
    if not written:
        logger.warning(LOG_LATE_RESULT, question.id)
    return written


def _work(
    question: Question,
    writer: AnswerWriter,
    starts: StartTimes,
    context: RunContext,
) -> None:
    if context.clock() >= context.deadline_s:
        return
    started_s = context.clock()
    starts.mark(question.id, started_s)
    error = question.error
    try:
        parts = answer_one(question, context.engine)
    except LlmUnavailableError as llm_error:
        logger.error(LOG_LLM_UNAVAILABLE, question.id, llm_error)
        parts = AnswerParts(FinalAnswer.not_found(question.id))
        error = str(llm_error)
    except Exception as unexpected:
        # A single question must never kill the run: any unexpected
        # failure degrades to not_found and keeps the traceback in logs.
        logger.exception(LOG_UNEXPECTED_ERROR, question.id)
        parts = AnswerParts(FinalAnswer.not_found(question.id))
        error = f"{type(unexpected).__name__}: {unexpected}"
    _record_trace(question, parts, context, started_s, error)
    if not _store_answer(question, parts, writer):
        # The line on disk is not_found: keep the trace consistent.
        late = replace(parts, answer=FinalAnswer.not_found(question.id))
        _record_trace(question, late, context, started_s, MSG_LATE_TRACE)


def _expire_overdue(
    questions: list[Question],
    writer: AnswerWriter,
    starts: StartTimes,
    context: RunContext,
) -> None:
    now_s = context.clock()
    for question in questions:
        started = starts.get(question.id)
        if started is None or now_s - started < QUESTION_BUDGET_S:
            continue
        if writer.write(FinalAnswer.not_found(question.id)):
            logger.error(LOG_OVER_BUDGET, question.id, QUESTION_BUDGET_S)
            _record_not_found_trace(
                question, context, started, MSG_OVER_BUDGET_TRACE
            )


def _fill_unanswered(
    questions: list[Question],
    writer: AnswerWriter,
    starts: StartTimes,
    context: RunContext,
) -> None:
    for question in questions:
        if writer.write(FinalAnswer.not_found(question.id)):
            logger.error(LOG_DEADLINE_REACHED, question.id)
            _record_not_found_trace(
                question,
                context,
                starts.get(question.id),
                MSG_DEADLINE_TRACE,
            )


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
            _expire_overdue(questions, writer, starts, context)
            context.sleep(POLL_INTERVAL_S)
        _fill_unanswered(questions, writer, starts, context)
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


def _build_viewer(
    config: AppConfig,
    run_id: str,
    deadline_s: float,
    clock: Callable[[], float],
) -> None:
    """Build the run viewer; never raise, it is a best-effort extra."""
    request = ViewerRequest(
        trace_dir=config.traces_dir / run_id,
        corpus_dir=config.corpus_dir,
        out_dir=config.viewer_dir / run_id,
        budget=ViewerBudget(deadline_s + VIEWER_GRACE_S, clock),
        render=render_evidence,
    )
    try:
        index_path = build_viewer(request)
    except Exception:  # noqa: BLE001 - the viewer must not fail the run
        logger.exception(LOG_VIEWER_FAILED)
        return
    logger.info(LOG_VIEWER_READY, index_path)


def _answer_all(
    questions: list[Question], answers_path: Path, context: RunContext
) -> int:
    """Answer into ``answers_path``; 1 when that file is unusable."""
    try:
        with answers_path.open(
            "w", encoding=ANSWERS_ENCODING, newline="\n"
        ) as out:
            _process_all(questions, AnswerWriter(out), context)
    except OSError as error:
        logger.error(MSG_IO_ERROR.format(path=answers_path, reason=error))
        return EXIT_ERROR
    return EXIT_OK


def run(  # noqa: PLR0913, PLR0917 - injectable time sources
    questions_path: Path,
    answers_path: Path,
    config: AppConfig,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] = datetime.now,
) -> int:
    """Answer every question and write answers.jsonl.

    One line is written per question as soon as it is ready; a question
    that fails, exceeds its time budget or is cut by the global deadline
    gets a not_found line. A JSON trace per question is written to
    ``config.traces_dir/<run_id>/`` on a best-effort basis.

    Returns:
        0 on a completed run (even with not_found answers), 1 when the
        corpus, questions file, index or output file is unusable. The
        reason is logged as an error.
    """
    deadline_s = clock() + GLOBAL_DEADLINE_S
    run_id = new_run_id(now())
    if not corpus_is_ready(config.corpus_dir):
        return EXIT_ERROR
    try:
        questions = _unique(load_questions(questions_path))
    except QuestionsFileError as error:
        logger.error("%s", error)
        return EXIT_ERROR
    try:
        with open_engine(config) as engine:
            context = RunContext(
                engine,
                deadline_s,
                clock,
                sleep,
                run_id,
                TraceWriter(config.traces_dir / run_id),
            )
            if _answer_all(questions, answers_path, context) != EXIT_OK:
                return EXIT_ERROR
    except ENGINE_OPEN_ERRORS as error:
        log_engine_open_failure(config, error)
        return EXIT_ERROR
    _build_viewer(config, run_id, deadline_s, clock)
    return EXIT_OK
