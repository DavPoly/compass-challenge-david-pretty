import pytest

from archive.common.config import AppConfig
from archive.common.step_model import PipelineStep, StepEvent
from archive.pipeline.engine import engine_service
from archive.pipeline.engine.engine_service import (
    Engine,
    answer_one,
    open_engine,
)
from archive.retrieval.search_service import SearchService
from archive.validation.answer_model import AnswerStatus
from archive.validation.input_model import Question
from tests.pipeline.test_run_service import FakeLlm, indexed  # noqa: F401


@pytest.fixture
def engine_llm(monkeypatch: pytest.MonkeyPatch) -> FakeLlm:
    llm = FakeLlm()
    monkeypatch.setattr(engine_service, "LlmGateway", lambda config: llm)
    return llm


def test_answer_one_emits_validate_then_ground(
    indexed: tuple[AppConfig, str],  # noqa: F811
    engine_llm: FakeLlm,
) -> None:
    config, query = indexed
    events: list[StepEvent] = []

    with open_engine(config) as engine:
        parts = answer_one(
            Question(id="q", question=query), engine, events.append
        )

    steps = [event.step for event in events]
    assert steps[:2] == [PipelineStep.ROUTE, PipelineStep.RETRIEVE]
    assert steps[-2:] == [PipelineStep.VALIDATE, PipelineStep.GROUND]
    assert events[-2].detail == AnswerStatus.ANSWERED.value
    assert parts.report is not None
    assert events[-1].detail == parts.report.confidence.value


def test_invalid_question_emits_no_step(
    indexed: tuple[AppConfig, str],  # noqa: F811
    engine_llm: FakeLlm,
) -> None:
    config, _ = indexed
    events: list[StepEvent] = []
    invalid = Question(id="q", question="", is_valid=False, error="empty")

    with open_engine(config) as engine:
        parts = answer_one(invalid, engine, events.append)

    assert events == []
    assert parts.answer.status is AnswerStatus.NOT_FOUND


def test_open_engine_closes_search_on_exit(
    indexed: tuple[AppConfig, str],  # noqa: F811
    engine_llm: FakeLlm,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, _ = indexed
    closed: list[bool] = []
    real_close = SearchService.close

    def spy_close(self: SearchService) -> None:
        closed.append(True)
        real_close(self)

    monkeypatch.setattr(SearchService, "close", spy_close)

    with open_engine(config) as engine:
        assert isinstance(engine, Engine)
        assert engine.valid_doc_ids
        assert closed == []

    assert closed == [True]

