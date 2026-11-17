"""Typed issues recorded by validation."""

from enum import StrEnum

from pydantic import BaseModel


class IssueCode(StrEnum):
    """Kind of problem validation found or fixed."""

    NORMALIZED = "normalized"
    ANSWER_TOO_LONG = "answer_too_long"
    CITATIONS_DROPPED = "citations_dropped"
    NO_VALID_CITATION = "no_valid_citation"
    CONFLICT_CITATIONS = "conflict_citations"
    NOT_FOUND_CLEARED = "not_found_cleared"


class ValidationIssue(BaseModel):
    """One issue: a stable code and a human-readable detail."""

    code: IssueCode
    detail: str

    def __str__(self) -> str:
        return f"{self.code}: {self.detail}"
