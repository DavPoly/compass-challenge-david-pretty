"""Shapes of the grounding input and report."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel

from archive.retrieval.search_service import SearchHit
from archive.validation.issue_model import ValidationIssue


class Confidence(StrEnum):
    """Rule-based trust level of an answer."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True)
class GroundingSources:
    """Texts a draft may rely on.

    ``texts_by_doc`` maps a doc id to the chunk texts that reached the
    draft; ``note`` is the recipe note (aggregation total, superseded
    notes) computed outside the model.
    """

    texts_by_doc: Mapping[str, Sequence[str]]
    note: str | None

    @classmethod
    def from_hits(
        cls, hits: Sequence[SearchHit], note: str | None
    ) -> "GroundingSources":
        """Group the chunk texts of ``hits`` by their doc id."""
        texts_by_doc: dict[str, list[str]] = {}
        for hit in hits:
            texts_by_doc.setdefault(hit.chunk.doc_id, []).append(
                hit.chunk.text
            )
        return cls(texts_by_doc, note)


class GroundingReport(BaseModel):
    """Grounding issues, the flagged strings and the confidence."""

    issues: list[ValidationIssue]
    unverified_quotes: list[str]
    ungrounded_values: list[str]
    confidence: Confidence
