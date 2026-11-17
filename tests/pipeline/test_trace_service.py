from archive.agent.answer_service import DraftOutcome
from archive.agent.route.route_model import QuestionFamily, QuestionPlan
from archive.common.chunk_model import Chunk, ChunkKind
from archive.pipeline.trace_service import AnswerParts, build_trace
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
