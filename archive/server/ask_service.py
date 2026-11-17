"""Answer one live question at a time and save its trace."""

import logging
import re
import threading
import time
from collections.abc import Callable
from pathlib import Path

from archive.common.step_model import PipelineStep, StepEvent, emit_step
from archive.pipeline.engine.engine_service import Engine, answer_one
from archive.pipeline.trace_gateway import TraceWriter
from archive.pipeline.trace_service import build_trace
from archive.server.server_constants import (
    LIVE_ID_FORMAT,
    LIVE_ID_PATTERN,
    LIVE_ID_PREFIX,
    LIVE_RUN_ID,
    LIVE_TRACE_SUFFIX,
    LOG_QUESTION_SAVED,
    MSG_BUSY,
)
from archive.validation.input_model import Question
from archive.viewer.viewer_build_service import (
    ViewerRequest,
    question_view_from_trace,
)
from archive.viewer.viewer_model import QuestionView

logger = logging.getLogger(__name__)

_LIVE_ID = re.compile(LIVE_ID_PATTERN)


class BusyError(Exception):
    """Raised when a question is already being answered."""


def highest_live_number(live_dir: Path) -> int:
    """Highest ``live-NNN`` number among the saved traces, else 0."""
    numbers = []
    for path in live_dir.glob(f"{LIVE_ID_PREFIX}*{LIVE_TRACE_SUFFIX}"):
        match = _LIVE_ID.fullmatch(path.stem)
        if match:
            numbers.append(int(match.group(1)))
    return max(numbers, default=0)


def next_live_id(live_dir: Path) -> str:
    """Next ``live-NNN`` id: one more than the highest saved trace."""
    return LIVE_ID_FORMAT.format(number=highest_live_number(live_dir) + 1)


class AskService:
    """Answers questions typed in the viewer, one at a time."""

    def __init__(
        self,
        engine: Engine,
        viewer: ViewerRequest,
        live_dir: Path,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._engine = engine
        self._viewer = viewer
        self._writer = TraceWriter(live_dir)
        self._live_dir = live_dir
        self._clock = clock
        self._lock = threading.Lock()
        self._last_issued = 0

    @property
    def is_busy(self) -> bool:
        """Whether a question is being answered right now."""
        return self._lock.locked()

    def ask(
        self, text: str, emit: Callable[[StepEvent], None]
    ) -> QuestionView:
        """Answer ``text``, save its trace and return its view.

        ``emit`` hears every pipeline step, then the render step.
        Side effects: writes ``<live_dir>/live-NNN.json`` and the
        evidence images under the viewer folder.

        Raises:
            BusyError: another question is being answered.
            LlmUnavailableError: the LLM gave no valid draft; nothing
                is saved.
        """
        if not self._lock.acquire(blocking=False):
            raise BusyError(MSG_BUSY)
        try:
            return self._answer(text.strip(), emit)
        finally:
            self._lock.release()

    def _answer(
        self, text: str, emit: Callable[[StepEvent], None]
    ) -> QuestionView:
        question = Question(id=self._issue_id(), question=text)
        started_s = self._clock()
        parts = answer_one(question, self._engine, on_step=emit)
        elapsed_s = self._clock() - started_s
        trace = build_trace(LIVE_RUN_ID, question, parts, elapsed_s, None)
        self._writer.write(trace)
        logger.info(LOG_QUESTION_SAVED, question.id, elapsed_s)
        emit_step(emit, PipelineStep.RENDER)
        return question_view_from_trace(trace, self._viewer, is_live=True)

    def _issue_id(self) -> str:
        """Next id, never one already given out, even if unsaved."""
        number = max(highest_live_number(self._live_dir), self._last_issued)
        self._last_issued = number + 1
        return LIVE_ID_FORMAT.format(number=self._last_issued)
