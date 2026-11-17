import json
import logging
from datetime import datetime
from pathlib import Path

import pytest

from archive.pipeline.trace_gateway import (
    TraceWriter,
    new_run_id,
    trace_filename,
)
from archive.pipeline.trace_model import QuestionTrace
from archive.validation.answer_model import FinalAnswer

ACCENTED_ANSWER = "été"


def make_trace(question_id: str = "q1") -> QuestionTrace:
    final = FinalAnswer.not_found(question_id)
    final = final.model_copy(update={"answer": ACCENTED_ANSWER})
    return QuestionTrace(
        run_id="r",
        question_id=question_id,
        question="?",
        elapsed_s=0.5,
        plan=None,
        retrieved=[],
        note=None,
        draft=None,
        validation_issues=[],
        dropped_citations=[],
        grounding=None,
        final=final,
        error=None,
    )


def test_run_id_format() -> None:
    assert new_run_id(datetime(2026, 3, 4, 5, 6, 7)) == "20260304-050607"


@pytest.mark.parametrize(
    ("question_id", "expected"),
    [
        ("q-1_a.b", "q-1_a.b.json"),
        ("a/b\\c:d", "a_b_c_d.json"),
        ("../../etc", ".._.._etc.json"),
        ("..", "question.json"),
        (".", "question.json"),
        ("", "question.json"),
    ],
)
def test_filename_is_sanitized(question_id: str, expected: str) -> None:
    assert trace_filename(question_id) == expected


def test_write_creates_dir_lazily_and_keeps_unicode(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "r1"
    writer = TraceWriter(run_dir)
    assert not run_dir.exists()

    writer.write(make_trace())

    text = (run_dir / "q1.json").read_text(encoding="utf-8")
    assert ACCENTED_ANSWER in text
    assert json.loads(text)["question_id"] == "q1"
    assert [p.name for p in run_dir.iterdir()] == ["q1.json"]


def test_write_overwrites_same_question(tmp_path: Path) -> None:
    writer = TraceWriter(tmp_path)
    writer.write(make_trace())
    writer.write(make_trace())

    assert [p.name for p in tmp_path.iterdir()] == ["q1.json"]


def test_traversal_id_stays_inside_run_dir(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    TraceWriter(run_dir).write(make_trace("../escape"))

    assert not (tmp_path / "escape.json").exists()
    assert len(list(run_dir.iterdir())) == 1


def test_unwritable_dir_logs_and_does_not_raise(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        TraceWriter(blocker / "run").write(make_trace("q9"))

    assert "q9" in caplog.text
    assert "trace not written" in caplog.text
