"""Write question traces to disk; a failure is logged, never raised."""

import logging
import os
import re
import threading
from datetime import datetime
from pathlib import Path

from archive.pipeline.pipeline_constants import (
    LOG_TRACE_WRITE_FAILED,
    RUN_ID_FORMAT,
    TRACE_ENCODING,
    TRACE_FALLBACK_NAME,
    TRACE_JSON_INDENT,
    TRACE_SAFE_NAME_PATTERN,
    TRACE_SUFFIX,
    TRACE_TEMP_SUFFIX,
    TRACE_UNSAFE_REPLACEMENT,
)
from archive.pipeline.trace_model import QuestionTrace

logger = logging.getLogger(__name__)

_DOTS_ONLY = re.compile(r"\.+")


def new_run_id(now: datetime) -> str:
    """Run identifier ``YYYYMMDD-HHMMSS`` for the given time."""
    return now.strftime(RUN_ID_FORMAT)


def trace_filename(question_id: str) -> str:
    """File name of a question trace.

    Characters outside ``[A-Za-z0-9_.-]`` become ``_``; a name made of
    dots only (``.``, ``..``) or empty is replaced, so the result can
    never leave the run directory.
    """
    safe = re.sub(
        TRACE_SAFE_NAME_PATTERN, TRACE_UNSAFE_REPLACEMENT, question_id
    )
    if not safe or _DOTS_ONLY.fullmatch(safe):
        safe = TRACE_FALLBACK_NAME
    return safe + TRACE_SUFFIX


class TraceWriter:
    """Thread-safe writer of one JSON trace per question."""

    def __init__(self, run_dir: Path) -> None:
        self._run_dir = run_dir
        self._lock = threading.Lock()

    def write(self, trace: QuestionTrace) -> None:
        """Atomically write ``<question_id>.json`` in the run directory.

        Never raises: an I/O or serialization failure is logged as a
        warning and the trace is dropped.
        """
        try:
            text = trace.model_dump_json(indent=TRACE_JSON_INDENT)
            self._write_text(trace_filename(trace.question_id), text)
        except (OSError, ValueError):
            logger.warning(
                LOG_TRACE_WRITE_FAILED, trace.question_id, exc_info=True
            )

    def _write_text(self, filename: str, text: str) -> None:
        target = self._run_dir / filename
        temp = target.with_name(target.name + TRACE_TEMP_SUFFIX)
        with self._lock:
            self._run_dir.mkdir(parents=True, exist_ok=True)
            temp.write_text(text, encoding=TRACE_ENCODING)
            os.replace(temp, target)
