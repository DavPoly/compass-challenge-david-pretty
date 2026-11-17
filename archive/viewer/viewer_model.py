"""Shape of the data embedded in the generated viewer page."""

from typing import Literal

from pydantic import BaseModel

EvidenceState = Literal[
    "verified", "unverified", "unchecked", "not_located", "not_rendered"
]


class ConfidenceAccuracy(BaseModel):
    """Scored accuracy of the questions sharing one confidence label."""

    n: int
    correct: int
    accuracy: float


class RunSummary(BaseModel):
    """Counts over the whole run."""

    total: int
    by_status: dict[str, int]
    by_confidence: dict[str, int]
    accuracy_by_confidence: dict[str, ConfidenceAccuracy] | None


class RetrievedView(BaseModel):
    """One retrieved document with its best chunk score."""

    doc_id: str
    score: float
    doc_type: str
    doc_date: str | None


class EvidenceView(BaseModel):
    """One evidence quote and where it was found in its PDF.

    Image paths are relative to ``index.html`` and use forward slashes.
    State "unchecked" means grounding did not run for the question, so
    the quote was neither confirmed nor refuted.
    """

    doc_id: str
    quote: str
    value: str | None
    state: EvidenceState
    page: int | None
    crop_image: str | None
    full_image: str | None


class StepView(BaseModel):
    """One pipeline step that ran, with its French label."""

    step: str
    label: str
    detail: str | None = None
    elapsed_s: float


class QuestionView(BaseModel):
    """Everything the page shows for one question."""

    id: str
    question: str
    family: str | None
    status: str
    answer: str | list[str]
    citations: list[str]
    confidence: str | None
    confidence_reasons: list[str]
    ungrounded_values: list[str]
    missing_values: list[str] = []
    dropped_citations: list[str]
    note: str | None
    error: str | None
    elapsed_s: float
    is_correct: bool | None
    expected_answer: str | list[str] | None
    retrieved: list[RetrievedView]
    evidence: list[EvidenceView]
    is_live: bool = False
    steps: list[StepView] = []


class ViewerData(BaseModel):
    """Root object serialized into the page."""

    run_id: str
    generated_at: str
    is_scored: bool
    summary: RunSummary
    questions: list[QuestionView]
    live: bool = False
