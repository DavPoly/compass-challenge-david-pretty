"""Questions file model and tolerant loader."""

import json
import logging
from collections import Counter
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from archive.validation.validation_constants import LINE_ID_PREFIX

logger = logging.getLogger(__name__)


class QuestionsFileError(Exception):
    """Raised when the questions file cannot be read."""


class QuestionLine(BaseModel):
    """Raw shape of one valid questions.jsonl line."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    id: str
    question: str


class Question(BaseModel):
    """A question to answer, or a flagged invalid line."""

    id: str
    question: str
    is_valid: bool = True
    error: str | None = None


def _recover_id(payload: object, line_number: int) -> str:
    if isinstance(payload, dict):
        raw_id = payload.get("id")
        if isinstance(raw_id, str | int) and str(raw_id).strip():
            return str(raw_id).strip()
    return f"{LINE_ID_PREFIX}{line_number}"


def _invalid(payload: object, line_number: int, reason: str) -> Question:
    logger.warning("questions line %d skipped: %s", line_number, reason)
    return Question(
        id=_recover_id(payload, line_number),
        question="",
        is_valid=False,
        error=reason,
    )


def _parse_line(text: str, line_number: int) -> Question:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        return _invalid(None, line_number, f"invalid JSON: {error.msg}")
    try:
        parsed = QuestionLine.model_validate(payload)
    except ValidationError as error:
        problems = ", ".join(
            ".".join(map(str, item["loc"])) or "line"
            for item in error.errors()
        )
        return _invalid(payload, line_number, f"bad fields: {problems}")
    if not parsed.id or not parsed.question:
        return _invalid(payload, line_number, "empty id or question")
    return Question(id=parsed.id, question=parsed.question)


def _warn_duplicates(questions: list[Question]) -> None:
    counts = Counter(question.id for question in questions)
    for question_id, count in counts.items():
        if count > 1:
            logger.warning(
                "question id %r appears %d times", question_id, count
            )


def load_questions(path: Path) -> list[Question]:
    """Read questions.jsonl, flagging bad lines instead of failing.

    Blank lines are skipped. A bad line (invalid JSON, missing or empty
    id or question) becomes an invalid Question with a best-effort id,
    or ``line-<n>`` when none is recoverable, and a logged warning.
    Duplicate ids are kept and warned about.

    Raises:
        QuestionsFileError: the file is missing or unreadable.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise QuestionsFileError(
            f"Cannot read questions file {path}: {error.strerror}. "
            "Pass the path of an existing questions.jsonl."
        ) from error
    questions = [
        _parse_line(line, number)
        for number, line in enumerate(text.splitlines(), start=1)
        if line.strip()
    ]
    _warn_duplicates(questions)
    return questions
