"""Shape of the per-question trace written next to the answers."""

from pydantic import BaseModel

from archive.pipeline.pipeline_constants import TRACE_VERSION
from archive.validation.answer_model import DraftAnswer, FinalAnswer
from archive.validation.grounding.grounding_model import GroundingReport


class RetrievedChunk(BaseModel):
    """One chunk the draft relied on, with its retrieval score."""

    doc_id: str
    chunk_id: str
    score: float
    doc_type: str
    doc_date: str | None


class QuestionTrace(BaseModel):
    """Everything the pipeline did for one question."""

    trace_version: int = TRACE_VERSION
    run_id: str
    question_id: str
    question: str
    elapsed_s: float
    plan: dict[str, object] | None
    retrieved: list[RetrievedChunk]
    note: str | None
    draft: DraftAnswer | None
    validation_issues: list[str]
    dropped_citations: list[str]
    grounding: GroundingReport | None
    final: FinalAnswer
    error: str | None
