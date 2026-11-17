import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from archive.pipeline.trace_model import QuestionTrace, RetrievedChunk
from archive.validation.answer_model import (
    AnswerStatus,
    DraftAnswer,
    Evidence,
    FinalAnswer,
)
from archive.validation.grounding.grounding_model import (
    Confidence,
    GroundingReport,
)
from archive.viewer.viewer_build_service import (
    ViewerBudget,
    ViewerRequest,
    build_viewer,
    question_view_from_trace,
)
from archive.viewer.viewer_constants import DATA_PLACEHOLDER, TEMP_SUFFIX

TEMPLATE = (
    '<script type="application/json" id="d">' + DATA_PLACEHOLDER + "</script>"
)


@dataclass(frozen=True)
class FakeRendered:
    page: int | None
    crop_path: Path | None
    full_path: Path | None
    is_located: bool


class FakeRenderer:
    def __init__(self, is_located: bool = True, fail: bool = False) -> None:
        self.calls: list[tuple[Path, str, bool, Path]] = []
        self._is_located = is_located
        self._fail = fail

    def __call__(
        self, pdf_path: Path, evidence: Evidence, is_verified: bool, stem: Path
    ) -> FakeRendered:
        self.calls.append((pdf_path, evidence.quote, is_verified, stem))
        if self._fail:
            raise RuntimeError("unreadable pdf")
        return FakeRendered(
            3,
            stem.with_name(stem.name + "_crop.png"),
            stem.with_name(stem.name + "_page.png"),
            self._is_located,
        )


def make_trace(
    question_id: str,
    quotes: list[str] | None = None,
    unverified: list[str] | None = None,
    confidence: Confidence = Confidence.HIGH,
) -> QuestionTrace:
    evidence = [Evidence(doc_id="d1", quote=q) for q in quotes or []]
    return QuestionTrace(
        run_id="run1",
        question_id=question_id,
        question="Q?",
        elapsed_s=1.0,
        plan={"family": "lookup"},
        retrieved=[
            RetrievedChunk(
                doc_id="d1",
                chunk_id="c1",
                score=0.5,
                doc_type="t",
                doc_date=None,
            ),
            RetrievedChunk(
                doc_id="d1",
                chunk_id="c2",
                score=0.9,
                doc_type="t",
                doc_date=None,
            ),
        ],
        note=None,
        draft=DraftAnswer(
            answer="a",
            status=AnswerStatus.ANSWERED,
            citations=["d1"],
            evidence=evidence,
            evidence_sufficient=False,
        ),
        validation_issues=["normalized: x", "no_valid_citation: y"],
        dropped_citations=[],
        grounding=GroundingReport(
            issues=[],
            unverified_quotes=unverified or [],
            ungrounded_values=[],
            confidence=confidence,
        ),
        final=FinalAnswer(
            id=question_id,
            answer="a",
            citations=["d1"],
            status=AnswerStatus.ANSWERED,
        ),
        error=None,
    )


def write_trace(trace_dir: Path, trace: QuestionTrace) -> None:
    trace_dir.mkdir(exist_ok=True)
    (trace_dir / f"{trace.question_id}.json").write_text(
        trace.model_dump_json(), encoding="utf-8"
    )


def build(
    tmp_path: Path,
    renderer: FakeRenderer,
    until_s: float | None = None,
    scores: Path | None = None,
    now: Callable[[], datetime] = datetime.now,
) -> dict[str, object]:
    template = tmp_path / "template.html"
    template.write_text(TEMPLATE, encoding="utf-8")
    request = ViewerRequest(
        trace_dir=tmp_path / "traces",
        corpus_dir=tmp_path / "corpus",
        out_dir=tmp_path / "out",
        budget=ViewerBudget(until_s, lambda: 100.0),
        render=renderer,
        scores_path=scores,
        template_path=template,
        now=now,
    )
    index = build_viewer(request)
    text = index.read_text(encoding="utf-8")
    payload = text.removeprefix(TEMPLATE.split(DATA_PLACEHOLDER)[0])
    payload = payload.removesuffix("</script>")
    data: dict[str, object] = json.loads(payload)
    return data


def test_happy_path_inlines_parseable_json(tmp_path: Path) -> None:
    write_trace(tmp_path / "traces", make_trace("q2", ["x"]))
    write_trace(tmp_path / "traces", make_trace("q1", ["y"]))
    renderer = FakeRenderer()

    data = build(tmp_path, renderer)

    questions = data["questions"]
    assert isinstance(questions, list)
    assert [q["id"] for q in questions] == ["q1", "q2"]
    first = questions[0]
    assert first["family"] == "lookup"
    assert [r["score"] for r in first["retrieved"]] == [0.9]
    assert first["confidence_reasons"] == [
        "aucune citation valide",
        "brouillon jugé insuffisant par le modèle",
    ]
    assert first["evidence"][0]["state"] == "verified"
    assert first["evidence"][0]["crop_image"] == "pages/q1_0_crop.png"
    assert renderer.calls[0][0] == tmp_path / "corpus" / "d1.pdf"


def test_doc_id_with_pdf_suffix_renders_that_corpus_file(
    tmp_path: Path,
) -> None:
    trace = make_trace("q1", ["x"])
    assert trace.draft is not None
    trace.draft.evidence[0] = Evidence(doc_id="doc_0001.pdf", quote="x")
    write_trace(tmp_path / "traces", trace)
    renderer = FakeRenderer()

    build(tmp_path, renderer)

    expected = (tmp_path / "corpus").resolve() / "doc_0001.pdf"
    assert renderer.calls[0][0] == expected


@pytest.mark.parametrize(
    "doc_id", ["../../x", "..\\..\\x", "/etc/passwd", "C:/Windows/x"]
)
def test_doc_id_outside_corpus_is_not_rendered(
    tmp_path: Path, doc_id: str
) -> None:
    trace = make_trace("q1", ["x"])
    assert trace.draft is not None
    trace.draft.evidence[0] = Evidence(doc_id=doc_id, quote="x")
    write_trace(tmp_path / "traces", trace)
    renderer = FakeRenderer()

    data = build(tmp_path, renderer)

    assert renderer.calls == []
    evidence = data["questions"][0]["evidence"][0]  # type: ignore[index]
    assert evidence["state"] == "not_rendered"


def test_unverified_and_not_located_states(tmp_path: Path) -> None:
    trace = make_trace("q1", ["bad", "ok"], unverified=["bad"])
    write_trace(tmp_path / "traces", trace)

    data = build(tmp_path, FakeRenderer(is_located=False))

    states = [e["state"] for e in data["questions"][0]["evidence"]]  # type: ignore[index]
    assert states == ["unverified", "not_located"]


def test_missing_grounding_marks_quotes_unchecked(tmp_path: Path) -> None:
    trace = make_trace("q1", ["a", "b"]).model_copy(update={"grounding": None})
    write_trace(tmp_path / "traces", trace)
    renderer = FakeRenderer()

    data = build(tmp_path, renderer)

    states = [e["state"] for e in data["questions"][0]["evidence"]]  # type: ignore[index]
    assert states == ["unchecked", "unchecked"]
    assert all(call[2] for call in renderer.calls)


def test_renderer_exception_gives_not_rendered(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    write_trace(tmp_path / "traces", make_trace("q1", ["ok"]))

    with caplog.at_level(logging.WARNING):
        data = build(tmp_path, FakeRenderer(fail=True))

    evidence = data["questions"][0]["evidence"][0]  # type: ignore[index]
    assert evidence["state"] == "not_rendered"
    assert evidence["crop_image"] is None


def test_exhausted_budget_skips_rendering(tmp_path: Path) -> None:
    write_trace(tmp_path / "traces", make_trace("q1", ["ok"]))
    renderer = FakeRenderer()

    data = build(tmp_path, renderer, until_s=50.0)

    assert renderer.calls == []
    evidence = data["questions"][0]["evidence"][0]  # type: ignore[index]
    assert evidence["state"] == "not_rendered"


def test_generated_at_uses_injected_clock(tmp_path: Path) -> None:
    write_trace(tmp_path / "traces", make_trace("q1"))
    fixed = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)

    data = build(tmp_path, FakeRenderer(), now=lambda: fixed)

    assert data["generated_at"] == fixed.astimezone().isoformat(
        timespec="seconds"
    )


def test_scores_give_accuracy_by_confidence(tmp_path: Path) -> None:
    write_trace(tmp_path / "traces", make_trace("q1"))
    write_trace(
        tmp_path / "traces", make_trace("q2", confidence=Confidence.LOW)
    )
    scores = tmp_path / "scores.json"
    scores.write_text(
        json.dumps(
            {
                "rows": [
                    {"id": "q1", "ok": True, "expected_answer": "a"},
                    {"id": "q2", "ok": False, "expected_answer": ["b"]},
                ]
            }
        ),
        encoding="utf-8",
    )

    data = build(tmp_path, FakeRenderer(), scores=scores)

    assert data["is_scored"] is True
    summary = data["summary"]
    assert summary["accuracy_by_confidence"]["high"] == {  # type: ignore[index]
        "n": 1,
        "correct": 1,
        "accuracy": 1.0,
    }
    assert summary["accuracy_by_confidence"]["low"]["correct"] == 0  # type: ignore[index]
    assert data["questions"][1]["expected_answer"] == ["b"]  # type: ignore[index]


def test_invalid_scores_leave_page_unscored(tmp_path: Path) -> None:
    write_trace(tmp_path / "traces", make_trace("q1"))
    scores = tmp_path / "scores.json"
    scores.write_text("not json", encoding="utf-8")

    data = build(tmp_path, FakeRenderer(), scores=scores)

    assert data["is_scored"] is False
    assert data["summary"]["accuracy_by_confidence"] is None  # type: ignore[index]


def test_bad_trace_is_skipped(tmp_path: Path) -> None:
    write_trace(tmp_path / "traces", make_trace("q1"))
    (tmp_path / "traces" / "broken.json").write_text("{", encoding="utf-8")

    data = build(tmp_path, FakeRenderer())

    assert len(data["questions"]) == 1  # type: ignore[arg-type]


def test_script_closing_tag_in_quote_is_escaped(tmp_path: Path) -> None:
    write_trace(tmp_path / "traces", make_trace("q1", ["a </script> b"]))
    build(tmp_path, FakeRenderer())

    text = (tmp_path / "out" / "index.html").read_text(encoding="utf-8")

    assert text.count("</script>") == 1
    assert "\\u003c/script\\u003e" in text


def test_empty_trace_dir_gives_valid_page(tmp_path: Path) -> None:
    (tmp_path / "traces").mkdir()

    data = build(tmp_path, FakeRenderer())

    assert data["questions"] == []
    assert data["summary"]["total"] == 0  # type: ignore[index]


def test_template_without_placeholder_raises(tmp_path: Path) -> None:
    (tmp_path / "traces").mkdir()
    template = tmp_path / "template.html"
    template.write_text("<html></html>", encoding="utf-8")
    request = ViewerRequest(
        trace_dir=tmp_path / "traces",
        corpus_dir=tmp_path,
        out_dir=tmp_path / "out",
        budget=ViewerBudget(None, lambda: 0.0),
        render=FakeRenderer(),
        template_path=template,
    )

    with pytest.raises(ValueError, match=DATA_PLACEHOLDER):
        build_viewer(request)


def _asset_request(tmp_path: Path, template_text: str) -> ViewerRequest:
    (tmp_path / "traces").mkdir()
    template = tmp_path / "template.html"
    template.write_text(template_text, encoding="utf-8")
    return ViewerRequest(
        trace_dir=tmp_path / "traces",
        corpus_dir=tmp_path,
        out_dir=tmp_path / "out",
        budget=ViewerBudget(None, lambda: 0.0),
        render=FakeRenderer(),
        template_path=template,
    )


def test_template_inlines_sibling_assets(tmp_path: Path) -> None:
    (tmp_path / "viewer_styles.css").write_text("body{margin:0}", "utf-8")
    request = _asset_request(
        tmp_path,
        "<style>/*__VIEWER_STYLES__*/</style>" + TEMPLATE,
    )

    text = build_viewer(request).read_text(encoding="utf-8")

    assert text.startswith("<style>body{margin:0}</style>")
    assert "__VIEWER_STYLES__" not in text


def test_template_with_missing_asset_raises(tmp_path: Path) -> None:
    request = _asset_request(
        tmp_path,
        "<style>/*__VIEWER_STYLES__*/</style>" + TEMPLATE,
    )

    with pytest.raises(FileNotFoundError, match="viewer_styles.css"):
        build_viewer(request)


def _live_request(tmp_path: Path, live: bool = False) -> ViewerRequest:
    template = tmp_path / "template.html"
    template.write_text(TEMPLATE, encoding="utf-8")
    return ViewerRequest(
        trace_dir=tmp_path / "traces",
        corpus_dir=tmp_path / "corpus",
        out_dir=tmp_path / "out",
        budget=ViewerBudget(None, lambda: 0.0),
        render=FakeRenderer(),
        template_path=template,
        extra_trace_dirs=(tmp_path / "live", tmp_path / "absent"),
        live=live,
    )


def _page_data(index: Path) -> dict[str, object]:
    text = index.read_text(encoding="utf-8")
    payload = text.removeprefix(TEMPLATE.split(DATA_PLACEHOLDER)[0])
    data: dict[str, object] = json.loads(payload.removesuffix("</script>"))
    return data


def test_extra_trace_dirs_are_live_and_ordered_after_run(
    tmp_path: Path,
) -> None:
    write_trace(tmp_path / "traces", make_trace("q2"))
    write_trace(tmp_path / "traces", make_trace("q1"))
    write_trace(tmp_path / "live", make_trace("a9"))
    write_trace(tmp_path / "live", make_trace("a1"))

    data = _page_data(build_viewer(_live_request(tmp_path, live=True)))

    questions = data["questions"]
    assert isinstance(questions, list)
    assert [(q["id"], q["is_live"]) for q in questions] == [
        ("q1", False),
        ("q2", False),
        ("a1", True),
        ("a9", True),
    ]
    assert data["live"] is True


def test_live_flag_defaults_to_false_and_missing_extra_dir_is_ok(
    tmp_path: Path,
) -> None:
    write_trace(tmp_path / "traces", make_trace("q1"))

    data = _page_data(build_viewer(_live_request(tmp_path)))

    assert data["live"] is False
    questions = data["questions"]
    assert isinstance(questions, list)
    assert len(questions) == 1


def test_question_view_from_trace_matches_build_viewer_view(
    tmp_path: Path,
) -> None:
    trace = make_trace("q1", ["x"])
    write_trace(tmp_path / "traces", trace)
    request = _live_request(tmp_path)
    built = _page_data(build_viewer(request))["questions"]
    assert isinstance(built, list)

    view = question_view_from_trace(trace, request)

    expected = dict(built[0])
    assert view.model_dump() == expected
    assert view.evidence[0].crop_image == "pages/q1_0_crop.png"
    live_view = question_view_from_trace(trace, request, is_live=True)
    assert live_view.is_live is True


def test_template_inlines_live_script(tmp_path: Path) -> None:
    (tmp_path / "viewer_live.js").write_text("const live=1;", "utf-8")
    request = _asset_request(
        tmp_path,
        "<script>/*__VIEWER_LIVE__*/</script>" + TEMPLATE,
    )

    text = build_viewer(request).read_text(encoding="utf-8")

    assert text.startswith("<script>const live=1;</script>")


def test_index_is_replaced_atomically_without_leftover_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _live_request(tmp_path)
    target = build_viewer(request)
    target.write_text("old page", encoding="utf-8")
    seen: list[tuple[str, bool]] = []
    real_replace = os.replace

    def spy(source: Path, destination: Path) -> None:
        seen.append((target.read_text("utf-8"), Path(source).exists()))
        real_replace(source, destination)

    monkeypatch.setattr(os, "replace", spy)

    build_viewer(request)

    assert seen == [("old page", True)]
    assert "old page" not in target.read_text("utf-8")
    assert not target.with_name(target.name + TEMP_SUFFIX).exists()


def test_template_inlines_list_script_before_app(tmp_path: Path) -> None:
    (tmp_path / "viewer_list.js").write_text("const list=1;", "utf-8")
    (tmp_path / "viewer_app.js").write_text("const app=1;", "utf-8")
    request = _asset_request(
        tmp_path,
        "<script>/*__VIEWER_LIST__*/</script>"
        "<script>/*__VIEWER_APP__*/</script>" + TEMPLATE,
    )

    text = build_viewer(request).read_text(encoding="utf-8")

    assert text.startswith(
        "<script>const list=1;</script><script>const app=1;</script>"
    )
