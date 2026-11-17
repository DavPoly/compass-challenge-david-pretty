"""Build the trace of one question from what the pipeline produced."""

import time
from collections.abc import Callable
from dataclasses import dataclass

from archive.agent.answer_service import DraftOutcome
from archive.common.step_model import (
    StepCallback,
    StepEvent,
    emit_step,
)
from archive.pipeline.trace_model import (
    QuestionTrace,
    RetrievedChunk,
    StepRecord,
)
from archive.retrieval.search_service import SearchHit
from archive.validation.answer_model import FinalAnswer
from archive.validation.answer_validator import ValidationResult
from archive.validation.grounding.grounding_model import GroundingReport
from archive.validation.input_model import Question


@dataclass(frozen=True)
class AnswerParts:
    """The final answer and the intermediate results behind it."""

    answer: FinalAnswer
    outcome: DraftOutcome | None = None
    result: ValidationResult | None = None
    report: GroundingReport | None = None
    steps: tuple[StepRecord, ...] = ()


class StepRecorder:
    """Step callback that records each event, then forwards it.

    ``elapsed_s`` of a record is the time since the recorder was
    created. A failing ``on_step`` never breaks answering.
    """

    def __init__(
        self,
        on_step: StepCallback | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._on_step = on_step
        self._clock = clock
        self._started_s = clock()
        self._records: list[StepRecord] = []

    def __call__(self, event: StepEvent) -> None:
        self._records.append(
            StepRecord(
                step=event.step,
                detail=event.detail,
                elapsed_s=self._clock() - self._started_s,
            )
        )
        emit_step(self._on_step, event.step, event.detail)

    @property
    def records(self) -> tuple[StepRecord, ...]:
        """The steps heard so far, in order."""
        return tuple(self._records)


def _retrieved(hits: list[SearchHit]) -> list[RetrievedChunk]:
    """One entry per distinct chunk, in hit order."""
    seen: set[str] = set()
    chunks = []
    for hit in hits:
        chunk = hit.chunk
        if chunk.chunk_id in seen:
            continue
        seen.add(chunk.chunk_id)
        chunks.append(
            RetrievedChunk(
                doc_id=chunk.doc_id,
                chunk_id=chunk.chunk_id,
                score=hit.score,
                doc_type=chunk.doc_type,
                doc_date=chunk.doc_date,
            )
        )
    return chunks


def build_trace(
    run_id: str,
    question: Question,
    parts: AnswerParts,
    elapsed_s: float,
    error: str | None,
) -> QuestionTrace:
    """Assemble the trace; missing stages stay empty or None."""
    outcome, result = parts.outcome, parts.result
    plan = outcome.plan if outcome is not None else None
    return QuestionTrace(
        run_id=run_id,
        question_id=question.id,
        question=question.question,
        elapsed_s=elapsed_s,
        plan=plan.model_dump(mode="json") if plan is not None else None,
        retrieved=_retrieved(outcome.hits) if outcome else [],
        note=outcome.note if outcome is not None else None,
        draft=outcome.draft if outcome is not None else None,
        validation_issues=(
            [str(issue) for issue in result.issues] if result else []
        ),
        dropped_citations=result.dropped_citations if result else [],
        grounding=parts.report,
        final=parts.answer,
        error=error,
        steps=list(parts.steps),
    )
