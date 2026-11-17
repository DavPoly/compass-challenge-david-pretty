import json
from pathlib import Path

import pytest

from archive.pipeline.pipeline_constants import (
    EXIT_ERROR,
    EXIT_OK,
    EXIT_USAGE,
)
from archive.pipeline.trace_model import QuestionTrace
from archive.validation.answer_model import (
    AnswerStatus,
    DraftAnswer,
    Evidence,
    FinalAnswer,
)
from scripts import build_viewer

RUN_NAME = "run1"


def write_trace(trace_dir: Path, question_id: str) -> None:
    trace = QuestionTrace(
        run_id=RUN_NAME,
        question_id=question_id,
        question="Q?",
        elapsed_s=1.0,
        plan=None,
        retrieved=[],
        note=None,
        draft=DraftAnswer(
            answer="a",
            status=AnswerStatus.ANSWERED,
            citations=["doc_missing"],
            evidence=[Evidence(doc_id="doc_missing", quote="une phrase")],
            evidence_sufficient=True,
        ),
        validation_issues=[],
        dropped_citations=[],
        grounding=None,
        final=FinalAnswer(
            id=question_id,
            answer="a",
            citations=["doc_missing"],
            status=AnswerStatus.ANSWERED,
        ),
        error=None,
    )
    trace_dir.mkdir(parents=True, exist_ok=True)
    (trace_dir / f"{question_id}.json").write_text(
        trace.model_dump_json(), encoding="utf-8"
    )


@pytest.fixture
def trace_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "traces" / RUN_NAME
    write_trace(directory, "q1")
    return directory


def run_main(trace_dir: Path, tmp_path: Path, *extra: str) -> int:
    return build_viewer.main(
        [
            str(trace_dir),
            "--out",
            str(tmp_path / "out"),
            "--corpus",
            str(tmp_path / "corpus"),
            *extra,
        ]
    )


def test_builds_the_page_and_prints_its_path(
    trace_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = run_main(trace_dir, tmp_path)

    index_page = tmp_path / "out" / "index.html"
    assert code == EXIT_OK
    assert index_page.is_file()
    assert str(index_page) in capsys.readouterr().out
    assert '"q1"' in index_page.read_text(encoding="utf-8")


def test_missing_trace_dir_exits_one_with_a_fix(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    code = run_main(tmp_path / "nope", tmp_path)

    assert code == EXIT_ERROR
    assert "Run answer.py first" in caplog.text
    assert not (tmp_path / "out").exists()


def test_missing_argument_is_a_usage_error() -> None:
    with pytest.raises(SystemExit) as raised:
        build_viewer.main([])

    assert raised.value.code == EXIT_USAGE


def test_scores_option_scores_the_page(
    trace_dir: Path, tmp_path: Path
) -> None:
    scores = tmp_path / "scores.json"
    scores.write_text(
        json.dumps({"rows": [{"id": "q1", "ok": True}]}), encoding="utf-8"
    )

    code = run_main(trace_dir, tmp_path, "--scores", str(scores))

    page = (tmp_path / "out" / "index.html").read_text(encoding="utf-8")
    assert code == EXIT_OK
    assert '"is_scored":true' in page.replace(" ", "")


def test_default_output_is_under_the_repo_viewer_dir(
    trace_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(build_viewer, "REPO_ROOT", tmp_path / "repo")

    code = build_viewer.main([str(trace_dir)])

    assert code == EXIT_OK
    default_page = tmp_path / "repo" / "viewer" / RUN_NAME / "index.html"
    assert default_page.is_file()
