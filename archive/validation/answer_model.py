"""Shapes of a model draft and of a final answers.jsonl line."""

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field

from archive.validation.validation_constants import (
    ANSWER_FIELD_DESCRIPTION,
    CITATIONS_FIELD_DESCRIPTION,
    EVIDENCE_FIELD_DESCRIPTION,
    MISSING_FIELD_DESCRIPTION,
    NOT_FOUND_ANSWER,
    STATUS_FIELD_DESCRIPTION,
    SUFFICIENT_FIELD_DESCRIPTION,
)


class AnswerStatus(StrEnum):
    """Outcome of a question, as the scorer defines it."""

    ANSWERED = "answered"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"


class Evidence(BaseModel):
    """A verbatim quote from one document and the value it supports."""

    doc_id: str
    quote: str
    value: str | None = None


class DraftAnswer(BaseModel):
    """Structured answer returned by the model, before validation."""

    answer: str | list[str] = Field(description=ANSWER_FIELD_DESCRIPTION)
    status: AnswerStatus = Field(description=STATUS_FIELD_DESCRIPTION)
    citations: list[str] = Field(description=CITATIONS_FIELD_DESCRIPTION)
    evidence: list[Evidence] = Field(
        default_factory=list, description=EVIDENCE_FIELD_DESCRIPTION
    )
    evidence_sufficient: bool = Field(description=SUFFICIENT_FIELD_DESCRIPTION)
    missing: str | None = Field(
        default=None, description=MISSING_FIELD_DESCRIPTION
    )


class FinalAnswer(BaseModel):
    """One line of answers.jsonl: exactly four keys."""

    model_config = ConfigDict(extra="forbid")

    id: str
    answer: str | list[str]
    citations: list[str]
    status: AnswerStatus

    @classmethod
    def not_found(cls, question_id: str) -> Self:
        """Build the abstention line for a question."""
        return cls(
            id=question_id,
            answer=NOT_FOUND_ANSWER,
            citations=[],
            status=AnswerStatus.NOT_FOUND,
        )

    def to_jsonl_line(self) -> str:
        """Serialize to one JSON line, without trailing newline."""
        return self.model_dump_json()
