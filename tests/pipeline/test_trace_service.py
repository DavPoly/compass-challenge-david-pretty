from archive.agent.answer_service import DraftOutcome
from archive.agent.route.route_model import QuestionFamily, QuestionPlan
from archive.common.chunk_model import Chunk, ChunkKind
from archive.common.step_model import PipelineStep, StepEvent
from archive.pipeline.trace_model import QuestionTrace, StepRecord
from archive.pipeline.trace_service import (
    AnswerParts,
    StepRecorder,
    build_trace,
)
from archive.retrieval.search_service import SearchHit
from archive.validation.answer_model import (
    AnswerStatus,
    DraftAnswer,
    FinalAnswer,
)
from archive.validation.answer_validator import ValidationResult
from archive.validation.input_model import Question
from archive.validation.issue_model import IssueCode, ValidationIssue

QUESTION = Question(id="q1", question="what?")


def make_hit(chunk_id: str, score: float) -> SearchHit:
    chunk = Chunk(
        doc_id="doc_a",
        chunk_id=chunk_id,
        chunk_kind=next(iter(ChunkKind)),
        doc_type="memo",
        doc_date="2024-01-02",
        identifiers=[],
        lang="fr",
        text="t",
    )
    return SearchHit(chunk, score)


def test_trace_without_outcome_is_minimal() -> None:
    final = FinalAnswer.not_found("q1")

    trace = build_trace("r", QUESTION, AnswerParts(final), 1.5, "boom")

    assert trace.final == final
    assert trace.error == "boom"
    assert trace.plan is None
    assert trace.retrieved == []
    assert trace.draft is None
    assert trace.grounding is None


def test_trace_carries_stages_and_dedupes_chunks() -> None:
    draft = DraftAnswer(
        answer="a",
        status=AnswerStatus.ANSWERED,
        citations=["doc_a"],
        evidence_sufficient=True,
    )
    plan = QuestionPlan(family=QuestionFamily.DIRECT)
    hits = [make_hit("c1", 0.9), make_hit("c1", 0.8), make_hit("c2", 0.7)]
    outcome = DraftOutcome(draft, hits, "note", plan)
    issue = ValidationIssue(code=IssueCode.NORMALIZED, detail="d")
    final = FinalAnswer(
        id="q1", answer="a", citations=["doc_a"], status=AnswerStatus.ANSWERED
    )
    result = ValidationResult(
        answer=final, issues=[issue], dropped_citations=["x"]
    )

    trace = build_trace(
        "r", QUESTION, AnswerParts(final, outcome, result), 2.0, None
    )

    assert [c.chunk_id for c in trace.retrieved] == ["c1", "c2"]
    assert trace.retrieved[0].score == 0.9
    assert trace.plan == plan.model_dump(mode="json")
    assert trace.note == "note"
    assert trace.draft == draft
    assert trace.validation_issues == [str(issue)]
    assert trace.dropped_citations == ["x"]
    assert trace.elapsed_s == 2.0


def test_trace_carries_the_recorded_steps() -> None:
    steps = (
        StepRecord(step=PipelineStep.ROUTE, detail="x", elapsed_s=0.1),
        StepRecord(step=PipelineStep.GROUND, elapsed_s=0.4),
    )
    parts = AnswerParts(FinalAnswer.not_found("q1"), steps=steps)

    trace = build_trace("run", QUESTION, parts, 1.0, None)

    assert trace.steps == list(steps)


def test_old_trace_json_without_steps_still_loads() -> None:
    trace = build_trace(
        "run", QUESTION, AnswerParts(FinalAnswer.not_found("q1")), 1.0, None
    )
    payload = trace.model_dump(mode="json")
    del payload["steps"]

    assert QuestionTrace.model_validate(payload).steps == []


def test_recorder_forwards_events_and_times_them() -> None:
    ticks = iter([5.0, 6.0, 8.5])
    heard: list[StepEvent] = []
    recorder = StepRecorder(heard.append, lambda: next(ticks))

    recorder(StepEvent(PipelineStep.ROUTE))
    recorder(StepEvent(PipelineStep.DRAFT, "brouillon 1"))

    assert heard == [
        StepEvent(PipelineStep.ROUTE),
        StepEvent(PipelineStep.DRAFT, "brouillon 1"),
    ]
    assert [(r.step, r.elapsed_s) for r in recorder.records] == [
        (PipelineStep.ROUTE, 1.0),
        (PipelineStep.DRAFT, 3.5),
    ]
