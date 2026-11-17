import threading
from pathlib import Path
from typing import Any, cast

import pytest

from archive.common.step_model import PipelineStep, StepEvent
from archive.pipeline.engine.engine_service import Engine
from archive.pipeline.trace_service import AnswerParts
from archive.server import ask_service
from archive.server.ask_service import AskService, BusyError, next_live_id
from archive.validation.answer_model import FinalAnswer
from archive.validation.input_model import Question
from archive.viewer.viewer_build_service import ViewerBudget, ViewerRequest

ENGINE = cast(Engine, object())


def make_viewer(tmp_path: Path) -> ViewerRequest:
    def no_render(*args: Any) -> Any:
        raise AssertionError("no evidence to render")

    return ViewerRequest(
        trace_dir=tmp_path / "run",
        corpus_dir=tmp_path / "corpus",
        out_dir=tmp_path / "out",
        budget=ViewerBudget(None, lambda: 0.0),
        render=no_render,
    )


def make_service(tmp_path: Path, times: list[float]) -> AskService:
    clock = iter(times)
    return AskService(
        ENGINE,
        make_viewer(tmp_path),
        tmp_path / "live",
        clock=lambda: next(clock),
    )


def fake_answer(
    question: Question, engine: Engine, on_step: Any = None
) -> AnswerParts:
    on_step(StepEvent(PipelineStep.ROUTE, "factual"))
    return AnswerParts(FinalAnswer.not_found(question.id))


@pytest.fixture(autouse=True)
def patched_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ask_service, "answer_one", fake_answer)


def test_first_question_gets_id_001(tmp_path: Path) -> None:
    assert next_live_id(tmp_path / "missing") == "live-001"


def test_next_id_follows_the_highest_saved_trace(tmp_path: Path) -> None:
    for name in ("live-001.json", "live-007.json", "other.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")

    assert next_live_id(tmp_path) == "live-008"


def test_ask_saves_the_trace_and_returns_a_live_view(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path, [10.0, 12.5])

    view = service.ask("  Quelle date ?  ", lambda event: None)

    assert view.id == "live-001"
    assert view.question == "Quelle date ?"
    assert view.is_live is True
    assert view.elapsed_s == 2.5
    assert (tmp_path / "live" / "live-001.json").is_file()


def test_ask_reports_pipeline_steps_then_render(tmp_path: Path) -> None:
    events: list[StepEvent] = []

    make_service(tmp_path, [0.0, 1.0]).ask("Quelle date ?", events.append)

    assert [event.step for event in events] == [
        PipelineStep.ROUTE,
        PipelineStep.RENDER,
    ]


def test_consecutive_questions_get_increasing_ids(tmp_path: Path) -> None:
    service = make_service(tmp_path, [0.0, 1.0, 2.0, 3.0])

    first = service.ask("Q1 ?", lambda event: None)
    second = service.ask("Q2 ?", lambda event: None)

    assert (first.id, second.id) == ("live-001", "live-002")


def test_second_ask_while_running_is_busy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started, release = threading.Event(), threading.Event()

    def slow_answer(
        question: Question, engine: Engine, on_step: Any = None
    ) -> AnswerParts:
        started.set()
        release.wait(timeout=5)
        return AnswerParts(FinalAnswer.not_found(question.id))

    monkeypatch.setattr(ask_service, "answer_one", slow_answer)
    service = make_service(tmp_path, [0.0, 1.0])
    worker = threading.Thread(
        target=service.ask, args=("Q1 ?", lambda event: None)
    )
    worker.start()
    assert started.wait(timeout=5)

    assert service.is_busy
    with pytest.raises(BusyError):
        service.ask("Q2 ?", lambda event: None)
    release.set()
    worker.join(timeout=5)
    assert not service.is_busy


def test_failed_answer_saves_nothing_and_frees_the_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing(*args: Any, **kwargs: Any) -> AnswerParts:
        raise RuntimeError("boom")

    monkeypatch.setattr(ask_service, "answer_one", failing)
    service = make_service(tmp_path, [0.0])

    with pytest.raises(RuntimeError):
        service.ask("Q ?", lambda event: None)

    assert not service.is_busy
    assert not (tmp_path / "live").exists()
